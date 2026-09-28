"""三表联动预测引擎（自研，标准库实现）。

计算口径与原 Public Equity Investing 插件 three-statement-model-builder 引擎一致（逐项对照见
tests/test_parity_reference.py），只保留本项目用到的部分：年度预测、total_growth 收入模型。

流程：收入 → 利润表初算（取营业成本）→ PP&E/折旧 → 营运资本 → 利息与现金归集（不动点迭代）
      → 利润表终算 → 现金流量表 → 资产负债表 → 偿债/流动性指标 → 勾稽检查。
所有浮点运算顺序与参照引擎保持一致，保证结果逐位相同。
"""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

SCENARIOS = ("base", "downside", "upside")
TOLERANCE = 0.05  # 勾稽误差容忍度（百万元）
DECISION_LABELS = {"source_reported", "connector_sourced", "public_filing", "web_verified",
                   "management_guidance", "company_provided"}


@dataclass
class Period:
    index: int
    label: str
    year: int


# ---------------------------------------------------------------- 通用工具

def deep_merge(base: Any, override: Any) -> Any:
    """递归合并 override 到 base，不修改入参。"""
    if override is None:
        return copy.deepcopy(base)
    if isinstance(base, dict) and isinstance(override, dict):
        out = copy.deepcopy(base)
        for k, v in override.items():
            out[k] = deep_merge(out.get(k), v)
        return out
    return copy.deepcopy(override)


def is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))


def period_key(label: str) -> tuple[int, int]:
    """期间排序键：(年份, 季度)，无季度按第 4 季度。"""
    text = str(label)
    y = re.search(r"(19|20|21)\d{2}", text)
    q = re.search(r"q([1-4])", text.lower())
    return (int(y.group(0)) if y else 0, int(q.group(1)) if q else 4)


def latest_key(mapping: dict[str, Any]) -> str | None:
    if not isinstance(mapping, dict) or not mapping:
        return None
    return max(mapping.keys(), key=period_key)


def timeline(start_year: int, n: int, periodicity: str) -> list[Period]:
    if periodicity != "annual":
        raise ValueError(f"仅支持年度预测，收到 periodicity={periodicity}")
    if n <= 0:
        raise ValueError("horizon_periods 必须为正")
    return [Period(i, f"FY{start_year + i}", start_year + i) for i in range(n)]


def assume(value: Any, p: Period, default: float = 0.0) -> float:
    """取假设值：标量直接用；按期间的字典先精确匹配，否则取不晚于本期的最近一期，再否则取最早一期。"""
    if value is None:
        return float(default)
    if is_number(value):
        return float(value)
    if not isinstance(value, dict) or not value:
        return float(default)
    for k in (p.label, f"FY{p.year}", str(p.year)):
        if k in value and value[k] is not None:
            return float(value[k])
    keyed = sorted((period_key(str(k)), str(k)) for k in value)
    target = period_key(p.label)
    prior = [k for ks, k in keyed if ks <= target]
    return float(value[prior[-1]]) if prior else float(value[keyed[0][1]])


def last_bs(plan: dict[str, Any]) -> dict[str, Any]:
    bs = plan.get("historicals", {}).get("balance_sheet", {})
    k = latest_key(bs)
    return copy.deepcopy(bs.get(k, {})) if k else {}


def last_bs_value(plan: dict[str, Any], key: str, default: float = 0.0) -> float:
    return float(last_bs(plan).get(key, default) or 0.0)


def last_nwc(plan: dict[str, Any]) -> float:
    wc = plan.get("historicals", {}).get("working_capital", {})
    k = latest_key(wc)
    if k and is_number(wc[k].get("nwc")):
        return float(wc[k]["nwc"])
    bs = last_bs(plan)
    g = lambda x: float(bs.get(x, 0.0) or 0.0)  # noqa: E731
    return (g("ar") + g("inventory") + g("other_current_assets") - g("ap") - g("accrued_expenses")
            - g("deferred_revenue"))


def last_hist_is(plan: dict[str, Any]) -> dict[str, Any]:
    h = plan.get("historicals", {}).get("income_statement", {})
    k = latest_key(h)
    return copy.deepcopy(h.get(k, {})) if k else {}


def normalize_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """补齐不影响结论的默认值。"""
    p = copy.deepcopy(plan)
    p.setdefault("meta", {})
    p["meta"].setdefault("currency", "USD")
    p["meta"].setdefault("units", "USD_mm")
    p["meta"].setdefault("accounting_basis", "unspecified")
    p.setdefault("source_basis", [])
    p.setdefault("scenarios", {k: {"overrides": {}} for k in SCENARIOS})
    p.setdefault("sensitivities", {})
    p.setdefault("other_balance_sheet", {})
    p["other_balance_sheet"].setdefault("other_assets", last_bs_value(p, "other_assets", 0.0))
    p["other_balance_sheet"].setdefault("other_liabilities", last_bs_value(p, "other_liabilities", 0.0))
    return p


# ---------------------------------------------------------------- 分表计算

def _revenue(plan: dict[str, Any], periods: list[Period]) -> list[float]:
    rp = plan.get("revenue", {})
    if rp.get("model", "total_growth") != "total_growth":
        raise ValueError(f"仅支持 total_growth 收入模型，收到 {rp.get('model')}")
    base = rp.get("base_revenue")
    if base is None:
        base = last_hist_is(plan).get("revenue")
    rev = float((0.0 if base is None else base) or 0.0)
    out = []
    for p in periods:
        rev *= 1.0 + assume(rp.get("growth_rates"), p, 0.0)
        out.append(rev)
    return out


IS_KEYS = ["revenue", "cogs", "gross_profit", "opex", "ebitda", "da", "ebit", "interest", "ebt", "book_taxes",
           "cash_taxes", "net_income", "deferred_tax", "nol_used", "ending_nol"]


def _income_statement(plan: dict[str, Any], periods: list[Period], revenue: list[float], da: list[float],
                      interest: list[float]) -> dict[str, list[float]]:
    cogs_p = plan.get("costs", {}).get("cogs", {})
    opex_p = plan.get("costs", {}).get("opex", {})
    tax = plan.get("tax", {})
    nol = float(tax.get("nol_balance", 0.0) or 0.0)
    book_rate = float(tax.get("book_tax_rate", 0.0) or 0.0)
    cash_rate = float(tax.get("cash_tax_rate", book_rate) or 0.0)
    out: dict[str, list[float]] = {k: [] for k in IS_KEYS}
    for i, p in enumerate(periods):
        rev = revenue[i]
        if cogs_p.get("method", "gross_margin") == "pct_revenue":
            cogs = rev * assume(cogs_p.get("pct_revenue"), p, 0.0)
        else:
            cogs = rev * (1.0 - assume(cogs_p.get("gross_margin"), p, 0.0))
        if opex_p.get("method", "pct_revenue") == "amount":
            opex = assume(opex_p.get("amount"), p, 0.0)
        else:
            opex = rev * assume(opex_p.get("pct_revenue"), p, 0.0)
        gp = rev - cogs
        ebitda = gp - opex
        ebit = ebitda - da[i]
        ebt = ebit - interest[i]
        if ebt > 0:  # 盈利期先用可抵扣亏损，账面税按税前利润、现金税按应税所得
            nol_used = min(nol, ebt)
            taxable = max(0.0, ebt - nol_used)
            book_tax, cash_tax = ebt * book_rate, taxable * cash_rate
            nol = max(0.0, nol - nol_used)
        else:
            nol_used = book_tax = cash_tax = 0.0
            nol += abs(ebt)
        ni = ebt - book_tax
        for k, v in zip(IS_KEYS, [rev, cogs, gp, opex, ebitda, da[i], ebit, interest[i], ebt, book_tax, cash_tax,
                                  ni, book_tax - cash_tax, nol_used, nol]):
            out[k].append(v)
    return out


def _ppe(plan: dict[str, Any], periods: list[Period], revenue: list[float]) -> dict[str, list[float]]:
    pp = plan.get("ppe", {})
    begin = last_bs_value(plan, "ppe_net", 0.0)
    out: dict[str, list[float]] = {k: [] for k in ("beginning_ppe", "capex", "depreciation", "disposals", "ending_ppe")}
    for i, p in enumerate(periods):
        if pp.get("capex_method", "pct_revenue") == "amount":
            capex = assume(pp.get("capex_amount"), p, 0.0)
        else:
            capex = revenue[i] * assume(pp.get("capex_pct_revenue"), p, 0.0)
        method = pp.get("depreciation_method", "pct_beginning_ppe")
        if method == "pct_revenue":
            dep = revenue[i] * assume(pp.get("depreciation_pct_revenue"), p, 0.0)
        elif method == "amount":
            dep = assume(pp.get("depreciation_amount"), p, 0.0)
        else:  # 期初 PP&E + 半年资本开支 × 折旧率
            dep = (begin + 0.5 * capex) * assume(pp.get("depreciation_pct_beginning_ppe"), p, 0.0)
        disp = assume(pp.get("disposals"), p, 0.0)
        end = max(0.0, begin + capex - dep - disp)
        for k, v in zip(out, [begin, capex, dep, disp, end]):
            out[k].append(v)
        begin = end
    return out


WC_KEYS = ["ar_days", "inventory_days", "ap_days", "ar", "inventory", "other_current_assets", "ap",
           "accrued_expenses", "deferred_revenue", "nwc", "change_nwc"]


def _working_capital(plan: dict[str, Any], periods: list[Period], revenue: list[float],
                     cogs: list[float]) -> dict[str, list[float]]:
    wp = plan.get("working_capital", {})
    prev = last_nwc(plan)
    out: dict[str, list[float]] = {k: [] for k in WC_KEYS}
    for i, p in enumerate(periods):
        rev, cg = revenue[i], cogs[i]
        ar_d = assume(wp.get("ar_days"), p, 0.0)
        inv_d = assume(wp.get("inventory_days"), p, 0.0)
        ap_d = assume(wp.get("ap_days"), p, 0.0)
        ar = rev * ar_d / 365.0
        inv = cg * inv_d / 365.0
        oca = rev * assume(wp.get("other_current_assets_pct_revenue"), p, 0.0)
        ap = cg * ap_d / 365.0
        accrued = rev * assume(wp.get("accrued_expenses_pct_revenue"), p, 0.0)
        deferred = rev * assume(wp.get("deferred_revenue_pct_revenue"), p, 0.0)
        nwc = ar + inv + oca - ap - accrued - deferred
        for k, v in zip(WC_KEYS, [ar_d, inv_d, ap_d, ar, inv, oca, ap, accrued, deferred, nwc, nwc - prev]):
            out[k].append(v)
        prev = nwc
    return out


DEBT_KEYS = ["beginning_cash", "beginning_debt", "beginning_revolver_drawn", "scheduled_draws", "required_draws",
             "total_draws", "mandatory_repayment", "optional_repayment", "total_repayments", "interest_rate",
             "interest", "ending_debt", "ending_revolver_drawn", "revolver_availability", "cash_before_sweep",
             "cash_change", "ending_cash", "minimum_cash"]


def _debt(plan: dict[str, Any], periods: list[Period], flows: dict[str, list[float]]) -> dict[str, list[float]]:
    """债务与现金归集：计划提款 → 强制还款 → 利息（按平均余额）→ 低于最低现金时循环贷补足 → 超额现金按比例扫还。"""
    dp = plan.get("debt", {})
    sweep = dp.get("cash_sweep", {})
    beg_debt = float(dp.get("beginning_debt", last_bs_value(plan, "debt", 0.0)) or 0.0)
    beg_cash = last_bs_value(plan, "cash", 0.0)
    beg_rev = float(dp.get("beginning_revolver_drawn", 0.0) or 0.0)
    commit = float(dp.get("revolver_commitment", 0.0) or 0.0)
    min_cash = float(sweep.get("min_cash", 0.0) or 0.0)
    sweep_pct = float(sweep.get("sweep_pct", 0.0) if sweep.get("enabled", True) else 0.0)
    out: dict[str, list[float]] = {k: [] for k in DEBT_KEYS}
    for i, p in enumerate(periods):
        rate = assume(dp.get("interest_rate"), p, 0.0)
        draw = assume(dp.get("optional_draws"), p, 0.0)
        avail0 = max(0.0, commit - beg_rev)
        draw = min(max(0.0, draw), avail0) if commit > 0 else max(0.0, draw)
        mand = min(max(0.0, assume(dp.get("mandatory_amortization"), p, 0.0)), beg_debt + draw)
        interest = max(0.0, beg_debt + 0.5 * draw - 0.5 * mand) * rate
        cash = (beg_cash + flows["cash_flow_from_operations"][i] - flows["capex"][i] - flows["dividends"][i]
                - flows["buybacks"][i] + flows["issuance"][i] + draw - mand)
        req = 0.0
        revolver = beg_rev + draw
        debt = beg_debt + draw - mand
        if cash < min_cash:
            need = min_cash - cash
            avail = max(0.0, commit - revolver)
            req = min(need, avail) if commit > 0 else need
            cash += req
            revolver += req
            debt += req
        opt = 0.0
        if sweep_pct > 0.0 and cash > min_cash and debt > 0.0:
            opt = min((cash - min_cash) * sweep_pct, debt)
        end_cash = cash - opt
        end_debt = max(0.0, debt - opt)
        end_rev = max(0.0, revolver - min(opt, revolver))
        availability = max(0.0, commit - end_rev) if commit > 0 else 0.0
        for k, v in zip(DEBT_KEYS, [beg_cash, beg_debt, beg_rev, draw, req, draw + req, mand, opt, mand + opt, rate,
                                    interest, end_debt, end_rev, availability, cash, end_cash - beg_cash, end_cash,
                                    min_cash]):
            out[k].append(v)
        beg_cash, beg_debt, beg_rev = end_cash, end_debt, end_rev
    return out


def _equity_flows(plan: dict[str, Any], periods: list[Period]) -> dict[str, list[float]]:
    eq = plan.get("equity", {})
    return {k: [assume(eq.get(k), p, 0.0) for p in periods] for k in ("dividends", "buybacks", "issuance")}


CF_KEYS = ["net_income", "da", "deferred_tax", "change_nwc", "cash_flow_from_operations", "capex",
           "cash_flow_from_investing", "debt_draws", "debt_repayments", "dividends", "buybacks", "issuance",
           "cash_flow_from_financing", "cash_change", "ending_cash"]


def _cash_flow(is_: dict, wc: dict, ppe: dict, debt: dict, eq: dict) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {k: [] for k in CF_KEYS}
    for i in range(len(is_["net_income"])):
        cfo = is_["net_income"][i] + is_["da"][i] + is_["deferred_tax"][i] - wc["change_nwc"][i]
        cff = (debt["total_draws"][i] - debt["total_repayments"][i] - eq["dividends"][i] - eq["buybacks"][i]
               + eq["issuance"][i])
        for k, v in zip(CF_KEYS, [is_["net_income"][i], is_["da"][i], is_["deferred_tax"][i], wc["change_nwc"][i],
                                  cfo, ppe["capex"][i], -ppe["capex"][i], debt["total_draws"][i],
                                  debt["total_repayments"][i], eq["dividends"][i], eq["buybacks"][i],
                                  eq["issuance"][i], cff, debt["cash_change"][i], debt["ending_cash"][i]]):
            out[k].append(v)
    return out


BS_KEYS = ["cash", "ar", "inventory", "other_current_assets", "ppe_net", "other_assets", "total_assets", "ap",
           "accrued_expenses", "deferred_revenue", "debt", "other_liabilities", "common_equity", "retained_earnings",
           "total_liabilities_equity", "balance_check"]


def _balance_sheet(plan: dict, periods: list[Period], is_: dict, wc: dict, ppe: dict, debt: dict,
                   eq: dict) -> dict[str, list[float]]:
    obs = plan.get("other_balance_sheet", {})
    other_a = float(obs.get("other_assets", last_bs_value(plan, "other_assets", 0.0)) or 0.0)
    other_l = float(obs.get("other_liabilities", last_bs_value(plan, "other_liabilities", 0.0)) or 0.0)
    ce = float(plan.get("equity", {}).get("common_equity", last_bs_value(plan, "common_equity", 0.0)) or 0.0)
    re_ = last_bs_value(plan, "retained_earnings", 0.0)
    dtl = 0.0  # 累计递延所得税负债并入其他负债
    out: dict[str, list[float]] = {k: [] for k in BS_KEYS}
    for i in range(len(periods)):
        ce += eq["issuance"][i] - eq["buybacks"][i]
        re_ += is_["net_income"][i] - eq["dividends"][i]
        dtl += is_["deferred_tax"][i]
        ol = other_l + dtl
        ta = (debt["ending_cash"][i] + wc["ar"][i] + wc["inventory"][i] + wc["other_current_assets"][i]
              + ppe["ending_ppe"][i] + other_a)
        tle = (wc["ap"][i] + wc["accrued_expenses"][i] + wc["deferred_revenue"][i] + debt["ending_debt"][i] + ol
               + ce + re_)
        for k, v in zip(BS_KEYS, [debt["ending_cash"][i], wc["ar"][i], wc["inventory"][i],
                                  wc["other_current_assets"][i], ppe["ending_ppe"][i], other_a, ta, wc["ap"][i],
                                  wc["accrued_expenses"][i], wc["deferred_revenue"][i], debt["ending_debt"][i], ol, ce,
                                  re_, tle, ta - tle]):
            out[k].append(v)
    return out


COV_KEYS = ["net_debt", "liquidity", "net_leverage", "interest_coverage", "min_liquidity", "max_net_leverage",
            "min_interest_coverage", "liquidity_headroom", "net_leverage_headroom", "interest_coverage_headroom",
            "covenant_breach_flag"]


def _covenants(plan: dict, periods: list[Period], is_: dict, debt: dict) -> dict[str, list[float]]:
    cov = plan.get("debt", {}).get("covenants", {})
    out: dict[str, list[float]] = {k: [] for k in COV_KEYS}
    for i in range(len(periods)):
        cash = debt["ending_cash"][i]
        liq = cash + debt["revolver_availability"][i]
        ebitda, interest = is_["ebitda"][i], is_["interest"][i]
        nd = debt["ending_debt"][i] - cash
        lev = nd / ebitda if ebitda > 0 else float("inf")
        icr = ebitda / interest if interest > 0 else float("inf")
        min_liq = float(cov.get("min_liquidity", 0.0) or 0.0)
        max_lev = float(cov.get("max_net_leverage", 1e9) or 1e9)
        min_icr = float(cov.get("min_interest_coverage", 0.0) or 0.0)
        liq_h = liq - min_liq
        lev_h = max_lev - lev if math.isfinite(lev) else -1e9
        icr_h = icr - min_icr if math.isfinite(icr) else 1e9
        breach = 1.0 if liq_h < -TOLERANCE or lev_h < -0.01 or icr_h < -0.01 else 0.0
        for k, v in zip(COV_KEYS, [nd, liq, lev, icr, min_liq, max_lev, min_icr, liq_h, lev_h, icr_h, breach]):
            out[k].append(v)
    return out


# ---------------------------------------------------------------- 联动求解

def _cfo(is_: dict, wc: dict) -> list[float]:
    return [is_["net_income"][i] + is_["da"][i] + is_["deferred_tax"][i] - wc["change_nwc"][i]
            for i in range(len(wc["change_nwc"]))]


def run_model(plan: dict[str, Any], scenario: str = "base") -> dict[str, Any]:
    tl = plan.get("timeline", {})
    periods = timeline(int(tl["start_year"]), int(tl["horizon_periods"]), tl.get("periodicity", "annual"))
    n = len(periods)
    revenue = _revenue(plan, periods)
    first = _income_statement(plan, periods, revenue, [0.0] * n, [0.0] * n)  # 首轮只为取营业成本
    ppe = _ppe(plan, periods, revenue)
    wc = _working_capital(plan, periods, revenue, first["cogs"])
    eq = _equity_flows(plan, periods)
    flows = {"cash_flow_from_operations": [0.0] * n, "capex": ppe["capex"], **eq}

    # 利息依赖期末现金/债务、现金又依赖利息：不动点迭代求解（最多 20 轮，收敛阈值 1e-8）
    payout = plan.get("equity", {}).get("dividend_payout_ratio")  # 可选：现金分红 = 净利润 × 分红率（本项目扩展）

    def _set_dividends(is_: dict[str, list[float]]) -> None:
        if payout is not None:
            eq["dividends"] = [max(0.0, is_["net_income"][i]) * assume(payout, p, 0.0) for i, p in enumerate(periods)]
            flows["dividends"] = eq["dividends"]

    interest = [0.0] * n
    for _ in range(20):
        is_ = _income_statement(plan, periods, revenue, ppe["depreciation"], interest)
        _set_dividends(is_)
        flows["cash_flow_from_operations"] = _cfo(is_, wc)
        new = _debt(plan, periods, flows)["interest"]
        done = max(abs(new[i] - interest[i]) for i in range(n)) < 1e-8
        interest = new
        if done:
            break
    is_ = _income_statement(plan, periods, revenue, ppe["depreciation"], interest)
    _set_dividends(is_)
    flows["cash_flow_from_operations"] = _cfo(is_, wc)
    debt = _debt(plan, periods, flows)
    is_ = _income_statement(plan, periods, revenue, ppe["depreciation"], debt["interest"])
    _set_dividends(is_)
    result = {
        "scenario": scenario, "periods": periods, "income_statement": is_, "working_capital": wc, "ppe": ppe,
        "debt": debt, "cash_flow_statement": _cash_flow(is_, wc, ppe, debt, eq),
        "balance_sheet": _balance_sheet(plan, periods, is_, wc, ppe, debt, eq),
        "covenants_liquidity": _covenants(plan, periods, is_, debt), "equity_flows": eq,
    }
    result["checks"] = _checks(plan, result)
    return result


def run_scenarios(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s: run_model(deep_merge(plan, plan.get("scenarios", {}).get(s, {}).get("overrides", {})), s)
            for s in SCENARIOS}


def _shock_growth(plan: dict[str, Any], delta: float) -> dict[str, Any]:
    out = copy.deepcopy(plan)
    rates = out.get("revenue", {}).setdefault("growth_rates", {})
    for k in list(rates):
        rates[k] = float(rates[k]) + delta
    return out


def _shock(plan: dict[str, Any], path: list[str], delta: float) -> dict[str, Any]:
    out = copy.deepcopy(plan)
    node = out
    for k in path[:-1]:
        node = node.setdefault(k, {})
    leaf = node.get(path[-1], {})
    if isinstance(leaf, dict):
        for k in list(leaf):
            if is_number(leaf[k]):
                leaf[k] = float(leaf[k]) + delta
    elif is_number(leaf):
        node[path[-1]] = float(leaf) + delta
    return out


SENSITIVITY_PATHS = [
    ("revenue_growth_shocks", "revenue_growth", None),
    ("gross_margin_shocks", "gross_margin", ["costs", "cogs", "gross_margin"]),
    ("dso_day_shocks", "dso_days", ["working_capital", "ar_days"]),
    ("capex_pct_revenue_shocks", "capex_pct_revenue", ["ppe", "capex_pct_revenue"]),
    ("interest_rate_shocks", "interest_rate", ["debt", "interest_rate"]),
]


def run_sensitivities(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """单因素冲击（基准情景）：收入增速、毛利率、应收天数、资本开支率、利率。"""
    sens = plan.get("sensitivities", {})
    rows = []
    for key, driver, path in SENSITIVITY_PATHS:
        for d in sens.get(key, []):
            d = float(d)
            case = _shock_growth(plan, d) if path is None else _shock(plan, path, d)
            s = summarize(run_model(case, f"sensitivity_{driver}_{d:+.4f}"))
            rows.append({"case": f"{driver}_{d:+.4f}", "driver": driver, "shock": d,
                         **{k: s[k] for k in ("final_revenue", "final_ebitda", "final_fcf", "ending_cash",
                                              "liquidity_trough", "peak_net_leverage")}})
    return rows


# ---------------------------------------------------------------- 勾稽与判定

CHECK_KEYS = [("balance_sheet_error", "max_balance_sheet_abs_error"), ("cash_tie_error", "max_cash_tie_abs_error"),
              ("retained_earnings_error", "max_retained_earnings_abs_error"),
              ("debt_rollforward_error", "max_debt_rollforward_abs_error"),
              ("ppe_rollforward_error", "max_ppe_rollforward_abs_error"),
              ("nwc_rollforward_error", "max_nwc_rollforward_abs_error")]


def _checks(plan: dict[str, Any], r: dict[str, Any]) -> dict[str, Any]:
    bs, cf, debt, ppe, wc, is_, eq = (r[k] for k in ("balance_sheet", "cash_flow_statement", "debt", "ppe",
                                                     "working_capital", "income_statement", "equity_flows"))
    out: dict[str, Any] = {"period_checks": [], **{m: 0.0 for _, m in CHECK_KEYS}}
    prior_re, prior_nwc = last_bs_value(plan, "retained_earnings", 0.0), last_nwc(plan)
    for i, p in enumerate(r["periods"]):
        errs = [
            bs["balance_check"][i],
            cf["ending_cash"][i] - bs["cash"][i],
            prior_re + is_["net_income"][i] - eq["dividends"][i] - bs["retained_earnings"][i],
            debt["beginning_debt"][i] + debt["total_draws"][i] - debt["total_repayments"][i] - debt["ending_debt"][i],
            (ppe["beginning_ppe"][i] + ppe["capex"][i] - ppe["depreciation"][i] - ppe["disposals"][i]
             - ppe["ending_ppe"][i]),
            prior_nwc + wc["change_nwc"][i] - wc["nwc"][i],
        ]
        out["period_checks"].append({"period": p.label, **{k: e for (k, _), e in zip(CHECK_KEYS, errs)}})
        for (_, m), e in zip(CHECK_KEYS, errs):
            out[m] = max(out[m], abs(e))
        prior_re, prior_nwc = bs["retained_earnings"][i], wc["nwc"][i]
    return out


def summarize(r: dict[str, Any]) -> dict[str, Any]:
    is_, cf, cov, debt = r["income_statement"], r["cash_flow_statement"], r["covenants_liquidity"], r["debt"]
    last = len(r["periods"]) - 1
    return {
        "final_revenue": is_["revenue"][last],
        "final_ebitda": is_["ebitda"][last],
        "final_ebitda_margin": is_["ebitda"][last] / is_["revenue"][last] if is_["revenue"][last] else 0.0,
        "final_fcf": cf["cash_flow_from_operations"][last] - cf["capex"][last],
        "ending_cash": debt["ending_cash"][last],
        "ending_debt": debt["ending_debt"][last],
        "liquidity_trough": min(cov["liquidity"]),
        "peak_net_leverage": max([x for x in cov["net_leverage"] if math.isfinite(x)] or [0.0]),
        "min_interest_coverage": min([x for x in cov["interest_coverage"] if math.isfinite(x)] or [999.0]),
        "final_period": r["periods"][last].label,
    }


def _iso(x: Any) -> date | None:
    if not isinstance(x, str):
        return None
    try:
        return datetime.strptime(x, "%Y-%m-%d").date()
    except ValueError:
        return None


def _freshness(plan: dict[str, Any]) -> list[dict[str, str]]:
    """来源时效：来源晚于模型日期、预测来源超 120 天、历史来源超 270 天、来源跨度超一年。"""
    out: list[dict[str, str]] = []
    as_of = _iso(plan.get("meta", {}).get("as_of_date"))
    dates: list[date] = []
    for src in plan.get("source_basis", []):
        if not isinstance(src, dict) or not (d := _iso(src.get("as_of_date"))):
            continue
        dates.append(d)
        if not as_of:
            continue
        age = (as_of - d).days
        covers = set(src["covers"]) if isinstance(src.get("covers"), list) else set()
        sid = src.get("id", "source")
        if age < 0:
            out.append({"code": "SOURCE_DATE_AFTER_MODEL_AS_OF",
                        "message": f"{sid} is dated after meta.as_of_date; confirm the model as-of date."})
        elif covers & {"forecast", "revenue", "costs", "working_capital", "ppe", "debt"} and age > 120:
            out.append({"code": "STALE_FORECAST_SOURCE",
                        "message": f"{sid} is {age} days older than meta.as_of_date for forecast-driver support."})
        elif covers & {"historicals"} and age > 270:
            out.append({"code": "STALE_HISTORICAL_SOURCE",
                        "message": f"{sid} historical support is {age} days older than meta.as_of_date; "
                                   "refresh for decision-grade use."})
    if dates and (max(dates) - min(dates)).days > 365:
        out.append({"code": "SOURCE_DATE_SPREAD",
                    "message": "Source dates span more than one year; verify historicals, forecasts, guidance, "
                               "and market context are contemporaneous."})
    return out


CHECK_FAILURES = [
    ("max_balance_sheet_abs_error", "BALANCE_SHEET_DOES_NOT_BALANCE", "balance sheet error exceeds tolerance."),
    ("max_cash_tie_abs_error", "CASH_DOES_NOT_TIE", "ending cash does not tie to cash flow statement."),
    ("max_retained_earnings_abs_error", "RETAINED_EARNINGS_ROLLFORWARD_FAIL", "retained earnings roll-forward fails."),
    ("max_debt_rollforward_abs_error", "DEBT_ROLLFORWARD_FAIL", "debt roll-forward fails."),
    ("max_ppe_rollforward_abs_error", "PPE_ROLLFORWARD_FAIL", "PP&E roll-forward fails."),
    ("max_nwc_rollforward_abs_error", "NWC_ROLLFORWARD_FAIL", "working capital roll-forward fails."),
]


def evaluate(plan: dict[str, Any], outputs: dict[str, dict[str, Any]]
             ) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    """硬失败（勾稽不平、情景无差异、缺来源）与警示（流动性、现金为负、激进假设、来源时效）。"""
    hard: list[dict[str, str]] = []
    warn: list[dict[str, str]] = []
    summary: dict[str, Any] = {}
    for s, r in outputs.items():
        c = r["checks"]
        summary[s] = {k: v for k, v in c.items() if k != "period_checks"}
        hard += [{"code": code, "message": f"{s}: {msg}"} for key, code, msg in CHECK_FAILURES if c[key] > TOLERANCE]
        if max(r["covenants_liquidity"]["covenant_breach_flag"] or [0.0]) > 0:
            warn.append({"code": "LIQUIDITY_OR_COVENANT_ISSUE",
                         "message": f"{s}: liquidity or covenant headroom issue appears in forecast."})
        if min(r["debt"]["ending_cash"] or [0.0]) < -TOLERANCE:
            warn.append({"code": "NEGATIVE_CASH", "message": f"{s}: ending cash falls below zero."})

    base, down, up = (outputs.get(k) for k in SCENARIOS)
    if base and down and up:
        b, d, u = summarize(base), summarize(down), summarize(up)
        if (abs(b["final_revenue"] - d["final_revenue"]) < TOLERANCE
                and abs(b["final_revenue"] - u["final_revenue"]) < TOLERANCE):
            hard.append({"code": "SCENARIO_SWITCH_NO_OUTPUT_CHANGE",
                         "message": "scenario switch changes labels but not material model outputs."})

    sources = plan.get("source_basis", [])
    if not sources:
        hard.append({"code": "SOURCE_BASIS_MISSING",
                     "message": "source_basis is missing for material historicals or forecast drivers."})
    else:
        covers = {c for src in sources for c in src.get("covers", [])}
        if "historicals" not in covers:
            hard.append({"code": "HISTORICAL_SOURCE_MISSING",
                         "message": "source_basis does not cover historical financials."})
        if not ({"revenue", "forecast", "costs"} & covers):
            hard.append({"code": "FORECAST_SOURCE_MISSING",
                         "message": "source_basis does not cover material forecast drivers."})
        if any(src.get("evidence_label") == "placeholder" for src in sources):
            warn.append({"code": "PLACEHOLDER_ASSUMPTIONS_ACTIVE",
                         "message": "placeholder source basis remains active; model should be treated as "
                                    "screen-grade only."})
        warn += _freshness(plan)

    hist_rev = float(last_hist_is(plan).get("revenue", 0.0) or 0.0)
    if base and hist_rev > 0:
        rev = base["income_statement"]["revenue"]
        n = max(1, len(base["periods"]))
        cagr = (rev[-1] / hist_rev) ** (1.0 / n) - 1.0 if rev[-1] > 0 else -1.0
        if cagr > 0.20:
            warn.append({"code": "AGGRESSIVE_REVENUE_RAMP",
                         "message": "base case revenue CAGR exceeds 20%; verify capacity, market share, sales "
                                    "productivity, and demand evidence."})
        if rev[0] > hist_rev * 1.25:
            warn.append({"code": "STEP_UP_REVENUE",
                         "message": "first forecast period revenue steps up more than 25% from latest historical "
                                    "period."})
    if base:
        is_ = base["income_statement"]
        if is_["gross_profit"][-1] / is_["revenue"][-1] - is_["gross_profit"][0] / is_["revenue"][0] > 0.05:
            warn.append({"code": "UNSUPPORTED_MARGIN_EXPANSION",
                         "message": "gross margin expands by more than 500 bps; verify mix, pricing, utilization, "
                                    "input costs, and sourcing evidence."})
        growth = is_["revenue"][-1] / is_["revenue"][0] - 1.0 if is_["revenue"][0] else 0.0
        if growth > 0.10 and base["ppe"]["capex"][-1] < base["ppe"]["depreciation"][-1] * 0.75:
            warn.append({"code": "CAPEX_TOO_LOW_FOR_GROWTH",
                         "message": "capex is below 75% of D&A despite forecast revenue growth; verify maintenance "
                                    "and growth capex."})
        hist_ratio = last_nwc(plan) / hist_rev if hist_rev else 0.0
        fc_ratio = base["working_capital"]["nwc"][-1] / is_["revenue"][-1] if is_["revenue"][-1] else 0.0
        if hist_ratio - fc_ratio > 0.05:
            warn.append({"code": "WORKING_CAPITAL_RELEASE_INCONSISTENT_WITH_HISTORY",
                         "message": "forecast working capital intensity improves by more than 500 bps vs. history; "
                                    "verify DSO/DIO/DPO assumptions."})
    return hard, warn, summary


def model_status(hard: list[dict[str, str]], warn: list[dict[str, str]], plan: dict[str, Any]) -> str:
    if hard:
        return "not-decision-ready"
    if any(w.get("code") == "PLACEHOLDER_ASSUMPTIONS_ACTIVE" for w in warn):
        return "screen-grade"
    if warn:
        return "senior-review-ready"
    labels = {src.get("evidence_label") for src in plan.get("source_basis", [])}
    return "decision-grade" if labels and labels <= DECISION_LABELS else "senior-review-ready"
