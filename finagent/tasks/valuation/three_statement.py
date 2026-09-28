"""三表模型：A 股财报抽取结果 → 三表联动引擎（ts_engine.py）。

本模块只负责口径映射（A 股科目 → 引擎 plan，单位百万元）与结果整理；
利润表/资产负债表/现金流量表联动、营运资本、PP&E、债务与现金归集、勾稽检查由 ts_engine 完成。
各情景的经营预测同时导出为 DCF 驱动（dcf_drivers），DCF 由三表模型驱动。

口径映射（推论/简化，写入报告）：
  EBIT 与 DCF 同口径：利润总额 + 财务费用 − 投资收益 − 公允价值变动收益（build_plan.EBIT_PARTS）
  经营费用 opex（不含折旧摊销）= 毛利 − EBIT − 折旧摊销，为轧差项：A 股折旧摊销已计入成本费用，
    税金及附加、减值、其他收益、营业外收支等未单列项也并入其中，保证历史期引擎 EBIT = 上述经营性 EBIT
  利息 = 财务费用；PP&E = 固定资产 + 在建工程；有息负债 = 短借 + 一年内到期 + 长借 + 应付债券 + 租赁负债
  其他资产 = 资产总计 − 货币资金 − 应收 − 存货 − PP&E；其他负债 = 负债合计 − 应付账款 − 有息负债
  股东权益（含少数股东）全部计入 common_equity，retained_earnings 期初置 0（仅影响列示，不影响勾稽）
"""

from __future__ import annotations

from typing import Any

from ...core import tracing
from ..financials.analyze import FactTable
from . import ts_engine as eng
from .build_plan import EBIT_PARTS

MM = 1e6


def _hist(t: FactTable, year: str) -> tuple[dict[str, float], dict[str, float], list[str]]:
    missing: list[str] = []

    def v(m: str) -> float:
        x = t.v(m, year)
        if x is None:
            missing.append(f"{m}@{year}")
            return 0.0
        return x / MM

    rev, cogs, da = v("revenue"), v("operating_cost"), v("depreciation") + v("amortization")
    ebit = sum(sign * v(m) for m, sign in EBIT_PARTS)
    is_ = {
        "revenue": rev, "cogs": cogs, "opex": rev - cogs - ebit - da,
        "da": da, "interest": v("finance_expense"),
        "taxes": v("income_tax"), "net_income": v("net_profit"),
    }
    ppe = v("fixed_assets") + v("construction_in_progress")
    debt = v("short_debt") + v("current_ltd") + v("long_debt") + v("bonds_payable") + v("lease_liab")
    cash, ar, inv, ap = v("cash"), v("accounts_receivable"), v("inventory"), v("accounts_payable")
    ta, tl, te = v("total_assets"), v("total_liabilities"), v("total_equity")
    bs = {
        "cash": cash, "ar": ar, "inventory": inv, "other_current_assets": 0.0, "ppe_net": ppe,
        "other_assets": ta - cash - ar - inv - ppe, "total_assets": ta,
        "ap": ap, "accrued_expenses": 0.0, "deferred_revenue": 0.0, "debt": debt,
        "other_liabilities": tl - ap - debt, "common_equity": te, "retained_earnings": 0.0,
        "total_liabilities_equity": tl + te,
    }
    # 引擎在 build 时对 bonds_payable 等缺失科目按 0 处理属正常（公司无该科目），不视为缺失
    optional = {"bonds_payable", "lease_liab", "current_ltd", "construction_in_progress", "amortization",
                "investment_income", "fair_value_change"}  # 后两项缺失已在 DCF 口径说明中列示
    missing = [m for m in missing if m.split("@")[0] not in optional]
    return is_, bs, missing


def build_plan(facts: list[dict[str, Any]], assumptions: dict[str, Any], *, company: str,
               period: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    t = FactTable(facts)
    y, y0 = period[:4], str(int(period[:4]) - 1)
    is1, bs1, miss1 = _hist(t, y)
    is0, bs0, _ = _hist(t, y0)
    ts = assumptions.get("three_statement", {})
    dcf_sc = assumptions["scenarios"]
    n = len(dcf_sc["base"]["revenue_growth"])
    years = [f"FY{int(y) + i + 1}" for i in range(n)]

    def vec(x: Any) -> dict[str, float]:
        vals = x if isinstance(x, list) else [x] * n
        return {k: float(v) for k, v in zip(years, vals)}

    rev, cogs = is1["revenue"], is1["cogs"]
    hist = {
        "gross_margin": 1 - cogs / rev,
        "opex_pct": is1["opex"] / rev,
        "ar_days": bs1["ar"] / rev * 365,
        "inventory_days": bs1["inventory"] / cogs * 365,
        "ap_days": bs1["ap"] / cogs * 365,
        "dep_rate": is1["da"] / (bs0["ppe_net"] + 0.5 * (t.v("capex", y) or 0) / MM) if bs0["ppe_net"] else 0.1,
        "tax_rate": is1["taxes"] / (is1["taxes"] + is1["net_income"]) if is1["net_income"] else 0.25,
        "interest_rate": is1["interest"] / ((bs0["debt"] + bs1["debt"]) / 2) if bs0["debt"] + bs1["debt"] else 0.04,
    }
    g = lambda k: ts.get(k, hist.get(k))  # noqa: E731

    notes = [
        {"type": "inference", "item": "三表口径",
         "detail": "EBIT 与 DCF 同口径（剔除投资收益与公允价值变动）；经营费用=毛利−EBIT−折旧摊销（轧差，含税金及附加、"
                   "减值、其他收益、营业外收支）；利息=财务费用；PP&E=固定资产+在建工程；其他资产/负债为轧差项；权益合并列示"},
        {"type": "inference", "item": "默认驱动",
         "detail": "未在假设文件指定的毛利率、费用率、周转天数、折旧率、税率、利率均取 {} 年实际值；"
                   "悲观/乐观情景在此基础上按 three_statement.gross_margin_shift / ar_days_shift 调整".format(y)},
    ] + [{"type": "placeholder", "item": m, "detail": "财报未抽取到，按 0 处理"} for m in miss1]

    plan = {
        "meta": {"company_name": company, "industry": assumptions.get("industry", ""), "currency": "CNY",
                 "units": "CNY_mm", "as_of_date": assumptions.get("valuation_date"),
                 "accounting_basis": "unspecified", "model_purpose": "赛题4 三表联动预测（中国企业会计准则）"},
        "source_basis": [
            {"id": "src_hist", "label": f"{y} 年报抽取数据", "source_type": "company_filing",
             "evidence_label": "public_filing", "as_of_date": assumptions.get("as_of_date"), "covers": ["historicals"],
             "notes": "由 financials 流水线抽取，逐项来源见 facts.json"},
            {"id": "src_assump", "label": "估值假设文件", "source_type": "analyst_model",
             "evidence_label": "analyst_estimate", "as_of_date": assumptions.get("valuation_date"),
             "covers": ["forecast", "revenue", "costs", "working_capital", "ppe", "debt", "tax", "equity"],
             "notes": "驱动假设"},
        ],
        "timeline": {"start_period": years[0], "start_year": int(y) + 1, "horizon_periods": n, "periodicity": "annual"},
        "historicals": {
            "income_statement": {f"FY{y0}": is0, f"FY{y}": is1},
            "balance_sheet": {f"FY{y0}": bs0, f"FY{y}": bs1},
            "working_capital": {f"FY{y}": {"ar": bs1["ar"], "inventory": bs1["inventory"], "other_current_assets": 0.0,
                                           "ap": bs1["ap"], "accrued_expenses": 0.0, "deferred_revenue": 0.0,
                                           "nwc": bs1["ar"] + bs1["inventory"] - bs1["ap"]}},
            "cash_flow": {f"FY{y}": {"net_income": is1["net_income"], "da": is1["da"],
                                     "cfo": (t.v("ocf", y) or 0.0) / MM, "capex": (t.v("capex", y) or 0.0) / MM}},
            "debt_schedule": {f"FY{y}": {"beginning_debt": bs0["debt"], "ending_debt": bs1["debt"]}},
            "ppe": {f"FY{y}": {"beginning_ppe": bs0["ppe_net"], "capex": (t.v("capex", y) or 0.0) / MM,
                               "depreciation": (t.v("depreciation", y) or 0.0) / MM, "ending_ppe": bs1["ppe_net"]}},
        },
        "revenue": {"model": "total_growth", "base_revenue": rev, "growth_rates": vec(dcf_sc["base"]["revenue_growth"]),
                    "source_id": "src_assump"},
        "costs": {"cogs": {"method": "gross_margin", "gross_margin": vec(g("gross_margin"))},
                  "opex": {"method": "pct_revenue", "pct_revenue": vec(g("opex_pct"))}},
        "working_capital": {"method": "days", "ar_days": vec(g("ar_days")), "inventory_days": vec(g("inventory_days")),
                            "ap_days": vec(g("ap_days")), "other_current_assets_pct_revenue": vec(0.0),
                            "accrued_expenses_pct_revenue": vec(0.0), "deferred_revenue_pct_revenue": vec(0.0)},
        "ppe": {"capex_method": "pct_revenue", "capex_pct_revenue": vec(dcf_sc["base"]["capex_percent_revenue"]),
                "depreciation_method": "pct_beginning_ppe", "depreciation_pct_beginning_ppe": vec(g("dep_rate"))},
        "debt": {"beginning_debt": bs1["debt"], "beginning_revolver_drawn": 0.0,
                 "revolver_commitment": float(ts.get("revolver_commitment", 0.0)),
                 "mandatory_amortization": vec(ts.get("mandatory_amortization", 0.0)),
                 "interest_rate": vec(g("interest_rate")),
                 "cash_sweep": {"enabled": bool(ts.get("cash_sweep", False)),
                                "min_cash": float(ts.get("min_cash", 0.0)), "sweep_pct": float(ts.get("sweep_pct", 0.0))},
                 "covenants": ts.get("covenants", {})},
        "tax": {"book_tax_rate": g("tax_rate"), "cash_tax_rate": g("tax_rate"), "nol_balance": 0.0},
        "equity": {"common_equity": bs1["common_equity"], "dividends": vec(ts.get("dividends", 0.0))},
        "other_balance_sheet": {"other_assets": bs1["other_assets"], "other_liabilities": bs1["other_liabilities"]},
        "scenarios": {
            "base": {"description": dcf_sc["base"].get("description", ""), "overrides": {}},
            **{k: {"description": dcf_sc[k].get("description", ""),
                   "overrides": {"revenue": {"growth_rates": vec(dcf_sc[k]["revenue_growth"])},
                                 "ppe": {"capex_pct_revenue": vec(dcf_sc[k]["capex_percent_revenue"])},
                                 "costs": {"cogs": {"gross_margin": vec(
                                     [x + ts.get("gross_margin_shift", {}).get(k, 0.0) for x in
                                      (vec(g("gross_margin")).values())])}},
                                 **({"working_capital": {"ar_days": vec(
                                     [x + ts["ar_days_shift"][k] for x in vec(g("ar_days")).values()])}}
                                    if k in ts.get("ar_days_shift", {}) else {})}}
               for k in ("downside", "upside")},
        },
        "sensitivities": ts.get("sensitivities", {
            "revenue_growth_shocks": [-0.05, 0.05], "gross_margin_shocks": [-0.02, 0.02],
            "dso_day_shocks": [15.0, -15.0], "capex_pct_revenue_shocks": [0.01, -0.01],
            "interest_rate_shocks": [0.01, -0.01]}),
        "_historical_drivers": hist,
    }
    return plan, notes


STATEMENT_ROWS = {
    "利润表": ("income_statement", [("revenue", "营业收入"), ("cogs", "营业成本"), ("gross_profit", "毛利"),
                                   ("opex", "经营费用（不含折旧摊销）"), ("ebitda", "EBITDA"), ("da", "折旧摊销"), ("ebit", "EBIT"),
                                   ("interest", "利息费用"), ("ebt", "税前利润"), ("book_taxes", "所得税"),
                                   ("net_income", "净利润")]),
    "资产负债表": ("balance_sheet", [("cash", "货币资金"), ("ar", "应收账款"), ("inventory", "存货"),
                                     ("ppe_net", "固定资产+在建工程"), ("other_assets", "其他资产"),
                                     ("total_assets", "资产总计"), ("ap", "应付账款"), ("debt", "有息负债"),
                                     ("other_liabilities", "其他负债"), ("common_equity", "股本及资本公积等"),
                                     ("retained_earnings", "留存收益（预测期累计）"),
                                     ("total_liabilities_equity", "负债和权益总计"), ("balance_check", "平衡差")]),
    "现金流量表": ("cash_flow_statement", [("net_income", "净利润"), ("da", "折旧摊销"), ("change_nwc", "营运资本增加"),
                                         ("cash_flow_from_operations", "经营活动现金流"), ("capex", "资本开支"),
                                         ("cash_flow_from_financing", "筹资活动现金流"), ("ending_cash", "期末现金")]),
}


@tracing.traced("run_three_statement")
def run(plan: dict[str, Any]) -> dict[str, Any]:
    p = eng.normalize_plan(plan)
    outputs = eng.run_scenarios(p)
    sens = eng.run_sensitivities(p)
    hard, warn, _ = eng.evaluate(p, outputs)
    status = eng.model_status(hard, warn, p)
    base = outputs["base"]
    labels = [per.label for per in base["periods"]]
    statements = {name: {"periods": labels,
                         "rows": [{"key": k, "name": cn, "values": base[sec][k]} for k, cn in rows]}
                  for name, (sec, rows) in STATEMENT_ROWS.items()}
    c = base["checks"]
    integrity = [
        {"check": "资产 = 负债 + 权益", "max_abs_error": c["max_balance_sheet_abs_error"]},
        {"check": "现金流量表期末现金 = 资产负债表现金", "max_abs_error": c["max_cash_tie_abs_error"]},
        {"check": "留存收益滚动", "max_abs_error": c["max_retained_earnings_abs_error"]},
        {"check": "债务滚动", "max_abs_error": c["max_debt_rollforward_abs_error"]},
        {"check": "PP&E 滚动", "max_abs_error": c["max_ppe_rollforward_abs_error"]},
        {"check": "营运资本滚动", "max_abs_error": c["max_nwc_rollforward_abs_error"]},
    ]
    for it in integrity:
        it["status"] = "pass" if it["max_abs_error"] <= 1e-6 else "fail"
    return {
        "model_status": status,
        "periods": labels,
        "statements": statements,
        "integrity": integrity,
        "scenario_summary": {k: eng.summarize(v) for k, v in outputs.items()},
        "covenants": {k: base["covenants_liquidity"][k] for k in ("net_debt", "net_leverage", "interest_coverage", "liquidity")},
        "sensitivities": sens,
        "hard_failures": hard,
        "warnings": warn,
        "historical_drivers": plan.get("_historical_drivers"),
        "dcf_drivers": {k: _dcf_drivers(p, v) for k, v in outputs.items()},
    }


def _dcf_drivers(plan: dict[str, Any], r: dict[str, Any]) -> dict[str, Any]:
    """三表模型单一情景 → DCF 预测向量（比率按收入折算，DCF 引擎还原后与三表逐期一致）。
    税率取现金税率：FCFF 按 EBIT 计无杠杆税负，不含利息抵税。"""
    is_ = r["income_statement"]
    rev = is_["revenue"]
    prev = [float(plan["revenue"].get("base_revenue") or eng.last_hist_is(plan)["revenue"])] + rev[:-1]
    ratio = lambda xs: [x / y if y else 0.0 for x, y in zip(xs, rev)]  # noqa: E731
    out = {
        "periods": [per.label for per in r["periods"]],
        "revenue": rev, "ebit": is_["ebit"], "da": is_["da"], "capex": r["ppe"]["capex"],
        "nwc": r["working_capital"]["nwc"],
        "revenue_growth": [x / y - 1 if y else 0.0 for x, y in zip(rev, prev)],
        "ebit_margin": ratio(is_["ebit"]),
        "tax_rate": [float(plan["tax"]["cash_tax_rate"])] * len(rev),
        "da_percent_revenue": ratio(is_["da"]),
        "capex_percent_revenue": ratio(r["ppe"]["capex"]),
        "nwc_percent_revenue": ratio(r["working_capital"]["nwc"]),
    }
    return out
