"""情景偏度与多维敏感性：DCF / 财报结果 → 原插件情景敏感性生成器
（scenario-sensitivity-generator/materialize_public_equity_sensitivities.py）。

本模块负责组装 payload（单位：金额百万元、每股元），表格计算由原脚本完成：
  - price_target_scenario：三情景目标价、预期收益、盈亏平衡概率、下行/上行比、偏度与行动规则
  - valuation_sensitivity：EV/EBITDA 与 P/E 倍数对应的隐含股价
  - eps_revision_sensitivity：EPS 修正 × 估值倍数变化
  - kpi_driver_sensitivity：收入增速 × 利润率冲击对 EBIT 的影响
  - equity_liquidity_downside：流动性压力测试
  - thesis_trigger_table：由财报异常信号生成的跟踪触发条件
"""

from __future__ import annotations

from typing import Any

from ...core import tracing
from ...vendor import load
from ..financials.analyze import FactTable

TABLES = ["price_target_scenario", "valuation_sensitivity", "eps_revision_sensitivity",
          "kpi_driver_sensitivity", "equity_liquidity_downside", "thesis_trigger_table"]
TABLE_CN = {
    "price_target_scenario": "三情景目标价与收益偏度",
    "valuation_sensitivity": "估值倍数 → 隐含股价",
    "eps_revision_sensitivity": "EPS 修正 × 倍数变化",
    "kpi_driver_sensitivity": "收入 × 利润率冲击",
    "equity_liquidity_downside": "流动性压力测试",
    "thesis_trigger_table": "跟踪触发条件",
}
MM = 1e6

# 财报异常信号 → 跟踪触发条件（阈值与下一步动作）
SIGNAL_TRIGGERS = {
    "S1": ("非经常性损益占归母净利润比例", "> 30%", "估值切换为扣非口径，下调利润可持续性假设"),
    "S2": ("归母与扣非净利润增速差", "> 10 个百分点", "拆分一次性收益，复核盈利预测"),
    "S3": ("净现比（经营现金流/归母净利润）", "< 0.5", "排查应收与存货，下调现金流假设"),
    "S4": ("利润增长但经营现金流同比下降", "连续 2 期", "重新评估盈利质量，考虑下调评级"),
    "S5": ("应收账款增速 − 收入增速", "> 20 个百分点", "复核信用政策与坏账计提"),
    "S6": ("存货增速 − 收入增速", "> 20 个百分点", "复核跌价准备与去库存节奏"),
    "S7": ("毛利率同比变动", "±3 个百分点", "拆分价格、成本与结构因素"),
    "S8": ("会计政策/口径变更", "出现追溯调整", "使用调整后可比数据重算同比"),
}


def _engine():
    return load("scenario-sensitivity-generator", "materialize_public_equity_sensitivities")


def build_payload(facts: list[dict[str, Any]], period: str, dcf_result: dict[str, Any], plan: dict[str, Any],
                  assumptions: dict[str, Any], signals: list[dict[str, Any]]) -> dict[str, Any]:
    t = FactTable(facts)
    y = period[:4]
    sc = {s["scenario"]: s["value_per_share"] for s in dcf_result["scenarios"]}
    probs = assumptions.get("scenario_probabilities", {"upside": 0.25, "base": 0.5, "downside": 0.25})
    bridge = plan["ev_to_equity_bridge"]
    h = plan["historicals"]
    net_debt = (bridge["debt"] + bridge.get("leases", 0.0) + bridge.get("minorities", 0.0) - bridge["cash"]
                - bridge.get("non_operating_assets", 0.0))
    ocf, capex = t.v("ocf", y), t.v("capex", y)
    eps = t.v("eps_basic", y)
    price = assumptions.get("current_price")
    src = {"source_id": "financials+dcf", "source_posture": "model_validated",
           "as_of_date": assumptions.get("valuation_date")}
    return {
        "currency": "¥",
        "source": src,
        "_input_was_provided": True,
        "base": {
            "share_price": price,
            "required_return": assumptions.get("required_return", 0.10),
            "upside_price_target": sc.get("upside"), "base_price_target": sc.get("base"),
            "downside_price_target": sc.get("downside"),
            "upside_probability": probs.get("upside"), "base_probability": probs.get("base"),
            "downside_probability": probs.get("downside"),
            "shares_outstanding": bridge["diluted_shares"], "net_debt": net_debt,
            "ebitda": h["ebitda"], "eps": eps, "pe_multiple": (price / eps) if price and eps else None,
            "revenue": h["revenue"], "ebit_margin": h["ebit"] / h["revenue"],
            "cash": bridge["cash"], "debt": bridge["debt"],
            "fcf": (ocf - capex) / MM if ocf is not None and capex is not None else None,
            "maturities_12m": ((t.v("short_debt", y) or 0.0) + (t.v("current_ltd", y) or 0.0)) / MM,
            "minimum_liquidity": assumptions.get("minimum_liquidity_mm", 0.0),
        },
        "axes": {
            "valuation_multiples": assumptions.get("ev_ebitda_axis", [6.0, 8.0, 10.0, 12.0, 14.0]),
            "eps_revisions": [-0.2, -0.1, 0.0, 0.1],
            "multiple_changes": [-0.2, -0.1, 0.0, 0.1],
            "revenue_growth_shocks": [-0.10, -0.05, 0.0, 0.05],
            "margin_shock_bps": [-300, -150, 0, 150],
        },
        "cases": [
            {"scenario": k, "price_target": sc.get(k), "probability": probs.get(k),
             "rationale": dcf_result_desc(dcf_result, k), **src}
            for k in ("upside", "base", "downside")
        ],
        "triggers": [
            {"trigger": SIGNAL_TRIGGERS[s["id"]][0], "threshold": SIGNAL_TRIGGERS[s["id"]][1],
             "monitoring_cadence": "每期定期报告", "implication": s["title"],
             "next_step": SIGNAL_TRIGGERS[s["id"]][2], "source_or_owner": f"财报异常信号 {s['id']}", **src}
            for s in signals if s["id"] in SIGNAL_TRIGGERS
        ],
    }


def dcf_result_desc(res: dict[str, Any], scenario: str) -> str:
    return next((s["description"] for s in res["scenarios"] if s["scenario"] == scenario), "")


@tracing.traced("run_scenario_tables")
def run(payload: dict[str, Any]) -> dict[str, Any]:
    eng = _engine()
    tables = [eng.BUILDERS[name](payload) for name in TABLES]
    for tb in tables:
        tb["name_cn"] = TABLE_CN.get(tb["name"], tb["name"])
    readiness = eng.classify_readiness(tables, payload)
    return {"tables": tables, "readiness": readiness}
