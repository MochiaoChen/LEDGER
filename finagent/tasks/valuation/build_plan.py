"""把抽取的财务数据 + 估值假设文件 + 三表模型输出 → DCF 引擎的 plan（单位：百万元，人民币）。

历史数据全部来自财报抽取结果（带来源）；缺失项不会被静默补 0，而是记为 placeholder 并在报告中披露。
预测期由三表模型驱动：各情景的收入增速、EBIT 利润率、折旧摊销率、资本开支率、营运资本占收入比、税率
都取自三表模型（three_statement.run 的 dcf_drivers），DCF 只负责折现、终值与股权桥，两者口径一致。
"""

from __future__ import annotations

from typing import Any

from ...core.numbers import UNIT_FACTORS, parse_number
from ...parsing.document import Document
from ..financials.analyze import FactTable
from ..financials.external import find_evidence

MM = 1e6
# 经营性 EBIT = 利润总额 + 财务费用 − 投资收益 − 公允价值变动收益（三表模型历史基数用同一口径）
EBIT_PARTS = [("total_profit", 1.0), ("finance_expense", 1.0), ("investment_income", -1.0),
              ("fair_value_change", -1.0)]
EBIT_NOTE = ("EBIT = 利润总额 + 财务费用 − 投资收益 − 公允价值变动收益，剔除投资与公允价值损益；"
             "资产处置收益、其他收益、减值损失与营业外收支仍留在 EBIT 中（简化）")
# 由三表模型提供的 DCF 预测向量（与 dcf.VECTOR_FIELDS 一致）
DRIVER_FIELDS = ["revenue_growth", "ebit_margin", "tax_rate", "da_percent_revenue", "capex_percent_revenue",
                 "nwc_percent_revenue"]


def _v(t: FactTable, metric: str, period: str) -> float | None:
    x = t.v(metric, period)
    return None if x is None else x / MM


def resolve_non_operating_items(items: list[dict[str, Any]], doc: Document | None) -> dict[str, Any]:
    """假设文件的 non_operating_assets 可写成明细列表：[{label, raw_value, unit, page, sign}]。
    每项按原文逐字核对（与 Skill 抽取同一规则），由程序换算、加总为百万元；sign=-1 表示类负债项（如吸收存款）。
    找不到原文的条目直接报错，不静默跳过。"""
    rows, total = [], 0.0
    for it in items:
        raw = str(it.get("raw_value", ""))
        v = parse_number(raw)
        unit = it.get("unit", "元")
        if v is None or unit not in UNIT_FACTORS:
            raise ValueError(f"non_operating_assets 条目无法解析：{it}")
        ch = find_evidence(doc, int(it.get("page", 0)), raw) if doc is not None else None
        if doc is not None and ch is None:
            raise ValueError(f"non_operating_assets 条目未在原文第 {it.get('page')} 页找到：{it.get('label')} {raw}")
        sign = -1.0 if it.get("sign", 1) in (-1, "-1", "-") else 1.0
        value = sign * v * UNIT_FACTORS[unit] / MM
        total += value
        rows.append({"label": it.get("label", ""), "raw": raw, "unit": unit, "sign": int(sign), "value_mm": value,
                     "source": {"source": ch.source, "page": ch.page, "chunk_id": ch.chunk_id} if ch else None})
    return {"total_mm": total, "items": rows}


def build_plan(facts: list[dict[str, Any]], assumptions: dict[str, Any], *, company: str,
               period: str, source_name: str,
               three_statement: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    t = FactTable(facts)
    prev = str(int(period[:4]) - 1)
    notes: list[dict[str, Any]] = []

    def need(metric: str, per: str = period, default: float = 0.0) -> float:
        x = _v(t, metric, per)
        if x is None:
            notes.append({"type": "placeholder", "item": f"{metric}@{per}", "detail": f"财报中未抽取到，按 {default} 处理"})
            return default
        return x

    revenue = need("revenue")
    total_profit = need("total_profit")
    income_tax = need("income_tax")
    ebit = sum(sign * need(m) for m, sign in EBIT_PARTS)
    notes.append({"type": "inference", "item": "EBIT", "detail": EBIT_NOTE})
    non_op = (_v(t, "investment_income", period) or 0.0) + (_v(t, "fair_value_change", period) or 0.0)
    for it in assumptions.get("non_operating_items", []):
        notes.append({"type": "assumption", "item": "非经营性资产加回",
                      "detail": f"{'减' if it['sign'] < 0 else '加'}：{it['label']} {it['raw']} {it['unit']}"
                                f"（第{(it.get('source') or {}).get('page', '?')}页）= {it['value_mm']:,.1f} 百万元"})
    if non_op and not assumptions.get("non_operating_assets"):
        notes.append({"type": "inference", "item": "非经营性资产",
                      "detail": f"EBIT 已剔除投资收益与公允价值变动（本期合计 {non_op:,.1f} 百万元），但假设文件未设置 "
                                "non_operating_assets：对应的长期股权投资、交易性金融资产等未在股权桥中加回，每股价值偏保守"})
    da = need("depreciation") + need("amortization")
    capex = need("capex")
    nwc = need("accounts_receivable") + need("inventory") - need("accounts_payable")
    nwc_prev = need("accounts_receivable", prev) + need("inventory", prev) - need("accounts_payable", prev)
    notes.append({"type": "inference", "item": "营运资本", "detail": "NWC = 应收账款 + 存货 − 应付账款（简化口径）"})
    tax_rate = income_tax / total_profit if total_profit else assumptions["wacc"]["marginal_tax_rate"]
    cash_taxes = ebit * tax_rate
    change_nwc = nwc - nwc_prev
    ufcf = ebit - cash_taxes + da - capex - change_nwc

    debt = need("short_debt") + need("current_ltd") + need("long_debt") + need("bonds_payable")
    shares = need("total_shares")  # 股 → 百万股（_v 已除以 1e6）

    vdate = assumptions["valuation_date"]
    asof = assumptions.get("as_of_date", vdate)
    src_hist = {"id": "src_hist", "topic": "historicals", "label": "reported", "source_name": source_name,
                "source_type": "company_filing", "as_of_date": asof, "confidence": "high",
                "notes": "由财报抽取结果计算，逐项来源见 financials.json"}
    plan = {
        "meta": {
            "company": company, "ticker": assumptions.get("ticker", ""), "industry": assumptions.get("industry", ""),
            "currency": "CNY", "units": "百万元（每股数据为元）", "valuation_date": vdate, "as_of_date": asof,
            "accounting_basis": "中国企业会计准则", "model_type": "fcff",
        },
        "source_basis": [
            src_hist,
            {**src_hist, "id": "src_bridge", "topic": "net_debt"},
            {**src_hist, "id": "src_shares", "topic": "share_count"},
            *[{"id": f"src_{k}", "topic": k, "label": "analyst_estimate", "source_name": "估值假设文件",
               "source_type": "analyst_model", "as_of_date": vdate, "confidence": "medium",
               "notes": assumptions.get("rationale", {}).get(k, "")}
              for k in ("forecast", "wacc", "terminal_value")],
        ],
        "timeline": {"start_year": int(period[:4]), "horizon_years": len(assumptions["scenarios"]["base"]["revenue_growth"]),
                     "periodicity": "annual"},
        "historicals": {
            "latest_year": int(period[:4]), "revenue": revenue, "ebitda": ebit + da, "ebit": ebit,
            "cash_taxes": cash_taxes, "da": da, "capex": capex, "change_nwc": change_nwc,
            "net_working_capital": nwc, "unlevered_fcf": ufcf, "net_income": need("np_parent"),
            "source_id": "src_hist",
        },
        "forecast": {"cash_flow_basis": "fcff", "mid_year_convention": True, "source_id": "src_forecast"},
        "wacc": {**assumptions["wacc"], "source_id": "src_wacc"},
        "terminal_value": {**assumptions["terminal_value"], "source_id": "src_terminal_value"},
        "ev_to_equity_bridge": {
            "cash": need("cash"), "debt": debt, "leases": need("lease_liab"),
            "minorities": need("minority_equity"), "associates": 0.0, "pensions": 0.0, "preferred_stock": 0.0,
            "non_operating_assets": assumptions.get("non_operating_assets", 0.0), "options": 0.0,
            "other_debt_like_items": 0.0, "diluted_shares": shares,
            "net_debt_source_id": "src_bridge", "share_count_source_id": "src_shares",
        },
        "scenarios": _scenarios(assumptions["scenarios"], three_statement, notes),
        "sensitivities": assumptions["sensitivities"],
    }
    plan["_historical_ratios"] = {
        "ebit_margin": ebit / revenue if revenue else None,
        "da_percent_revenue": da / revenue if revenue else None,
        "capex_percent_revenue": capex / revenue if revenue else None,
        "nwc_percent_revenue": nwc / revenue if revenue else None,
        "effective_tax_rate": tax_rate,
    }
    return plan, notes


def _scenarios(assumed: dict[str, Any], three_statement: dict[str, Any],
               notes: list[dict[str, Any]]) -> dict[str, Any]:
    """情景的经营预测向量取自三表模型；假设文件只保留情景说明、永续增长率与 WACC 调整。"""
    drivers = three_statement["dcf_drivers"]
    out = {name: {**sc, **{f: drivers[name][f] for f in DRIVER_FIELDS}} for name, sc in assumed.items()}
    notes.append({"type": "inference", "item": "预测驱动",
                  "detail": "DCF 各情景的收入、EBIT、折旧摊销、资本开支、营运资本与税率取自三表模型同一情景的输出"
                            "（收入增速、资本开支率来自假设文件，其余驱动见三表模型口径）"})
    ignored = sorted({f for sc in assumed.values() for f in DRIVER_FIELDS
                      if f in sc and f not in ("revenue_growth", "capex_percent_revenue")})
    if ignored:
        notes.append({"type": "inference", "item": "假设文件字段",
                      "detail": "假设文件中的 " + "、".join(ignored) + " 已不再驱动 DCF（由三表模型输出替代）"})
    return out
