"""把抽取的财务数据 + 估值假设文件 → DCF 引擎的 plan（单位：百万元，人民币）。

历史数据全部来自财报抽取结果（带来源）；缺失项不会被静默补 0，而是记为 placeholder 并在报告中披露。
"""

from __future__ import annotations

from typing import Any

from ..financials.analyze import FactTable

MM = 1e6


def _v(t: FactTable, metric: str, period: str) -> float | None:
    x = t.v(metric, period)
    return None if x is None else x / MM


def build_plan(facts: list[dict[str, Any]], assumptions: dict[str, Any], *, company: str,
               period: str, source_name: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
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
    fin_exp = need("finance_expense")
    income_tax = need("income_tax")
    ebit = total_profit + fin_exp  # 近似 EBIT：利润总额 + 财务费用
    notes.append({"type": "inference", "item": "EBIT", "detail": "EBIT 按“利润总额 + 财务费用”近似，未剔除投资收益与公允价值变动"})
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
        "scenarios": assumptions["scenarios"],
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
