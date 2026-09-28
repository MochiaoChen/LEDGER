"""DCF（FCFF）估值引擎：纯标准库、确定性计算。

输入为 build_plan 生成的 plan（百万元口径），输出三情景估值、敏感性矩阵与模型检查。

计算口径：
  收入_t = 收入_{t-1} × (1 + g_t)
  EBIT_t = 收入_t × 利润率_t；NOPAT = EBIT × (1 − 税率)
  FCFF_t = NOPAT + 折旧摊销 − 资本开支 − Δ营运资本
  WACC = E% × Ke + D% × Kd × (1 − t) + P% × Kp，Ke = Rf + β × ERP + 规模溢价 + 特定风险溢价 + 国别溢价
  终值：永续增长法 TV = FCFF_N × (1 + g) / (WACC − g)，或退出倍数法 TV = EBITDA_N × 倍数
  折现：年中折现（第 t 年折现期 t − 0.5），终值按第 N 年末折现
  股权价值 = EV + 现金 + 非经营性资产 + 联营投资 − 有息负债 − 租赁负债 − 少数股东权益 − 养老金 − 优先股 − 期权 − 其他类债务
"""

from __future__ import annotations

import copy
import math
from typing import Any

SCENARIOS = ["base", "downside", "upside"]

REQUIRED = {
    "meta": ["company", "currency", "valuation_date"],
    "timeline": ["start_year", "horizon_years"],
    "historicals": ["revenue", "ebit", "da", "capex", "net_working_capital"],
    "wacc": ["risk_free_rate", "beta", "equity_risk_premium", "pre_tax_cost_of_debt", "marginal_tax_rate",
             "target_debt_pct", "target_equity_pct"],
    "terminal_value": ["method"],
    "ev_to_equity_bridge": ["cash", "debt", "diluted_shares"],
}
VECTOR_FIELDS = ["revenue_growth", "ebit_margin", "tax_rate", "da_percent_revenue", "capex_percent_revenue",
                 "nwc_percent_revenue"]
BRIDGE_ADD = ["cash", "non_operating_assets", "associates"]
BRIDGE_SUB = ["debt", "leases", "minorities", "pensions", "preferred_stock", "options", "other_debt_like_items"]


def _num(x: Any, default: float = 0.0) -> float:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else default


def _vec(value: Any, n: int) -> list[float]:
    if isinstance(value, list):
        return [float(v) for v in value]
    return [float(value)] * n


# ------------------------------------------------------------------ 校验
def validate_plan_structure(plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for section, fields in REQUIRED.items():
        sec = plan.get(section)
        if not isinstance(sec, dict):
            errors.append(f"缺少 {section}")
            continue
        errors += [f"缺少 {section}.{f}" for f in fields if f not in sec]
    if errors:
        return errors
    n = plan["timeline"]["horizon_years"]
    if not isinstance(n, int) or not 1 <= n <= 15:
        errors.append("timeline.horizon_years 须为 1–15 的整数")
        return errors
    if _num(plan["historicals"]["revenue"]) <= 0:
        errors.append("historicals.revenue 须大于 0")
    if _num(plan["ev_to_equity_bridge"]["diluted_shares"]) <= 0:
        errors.append("ev_to_equity_bridge.diluted_shares 须大于 0")
    w = plan["wacc"]
    weights = _num(w["target_debt_pct"]) + _num(w["target_equity_pct"]) + _num(w.get("preferred_pct"))
    if not math.isclose(weights, 1.0, abs_tol=1e-6):
        errors.append(f"资本结构权重之和须为 1（当前 {weights:.4f}）")
    tv = plan["terminal_value"]
    if tv["method"] not in ("perpetual_growth", "exit_multiple"):
        errors.append("terminal_value.method 须为 perpetual_growth 或 exit_multiple")
    for name in SCENARIOS:
        sc = (plan.get("scenarios") or {}).get(name)
        if not isinstance(sc, dict):
            errors.append(f"缺少情景 scenarios.{name}")
            continue
        for f in VECTOR_FIELDS:
            if f not in sc:
                errors.append(f"缺少 scenarios.{name}.{f}")
            elif isinstance(sc[f], list) and len(sc[f]) != n:
                errors.append(f"scenarios.{name}.{f} 应有 {n} 个值，实际 {len(sc[f])}")
    if errors:
        return errors
    for name in SCENARIOS:
        rate = compute_wacc(plan, name)["wacc"]
        g = _terminal_growth(plan, name)
        if rate <= 0:
            errors.append(f"{name} 情景折现率须大于 0")
        if tv["method"] == "perpetual_growth" and rate <= g:
            errors.append(f"{name} 情景 WACC（{rate:.2%}）须高于永续增长率（{g:.2%}）")
    return errors


def normalize_plan(plan: dict[str, Any]) -> dict[str, Any]:
    p = copy.deepcopy(plan)
    for f in ("size_premium", "company_specific_premium", "country_risk_premium", "preferred_pct",
              "pre_tax_cost_of_preferred"):
        p["wacc"].setdefault(f, 0.0)
    for f in BRIDGE_ADD + BRIDGE_SUB:
        p["ev_to_equity_bridge"].setdefault(f, 0.0)
    return p


# ------------------------------------------------------------------ 计算
def compute_wacc(plan: dict[str, Any], scenario: str, delta: float = 0.0) -> dict[str, float]:
    w = plan["wacc"]
    ke = (_num(w["risk_free_rate"]) + _num(w["beta"]) * _num(w["equity_risk_premium"]) + _num(w.get("size_premium"))
          + _num(w.get("company_specific_premium")) + _num(w.get("country_risk_premium")))
    kd = _num(w["pre_tax_cost_of_debt"]) * (1 - _num(w["marginal_tax_rate"]))
    base = (_num(w["target_equity_pct"]) * ke + _num(w["target_debt_pct"]) * kd
            + _num(w.get("preferred_pct")) * _num(w.get("pre_tax_cost_of_preferred")))
    adj = _num(plan["scenarios"][scenario].get("wacc_adjustment"))
    return {"cost_of_equity": ke, "after_tax_cost_of_debt": kd, "base_wacc": base,
            "scenario_wacc_adjustment": adj, "wacc": base + adj + delta}


def _terminal_growth(plan: dict[str, Any], scenario: str) -> float:
    sc = plan["scenarios"][scenario]
    return _num(sc.get("terminal_growth_rate"), _num(plan["terminal_value"].get("perpetual_growth_rate")))


def forecast(plan: dict[str, Any], scenario: str, growth_delta: float = 0.0,
             margin_delta: float = 0.0) -> list[dict[str, float]]:
    driven = (plan.get("three_statement_forecast") or {}).get(scenario)
    if driven:
        rows = []
        rev_prev = _num(plan["historicals"]["revenue"])
        nwc_prev = _num(plan["historicals"]["net_working_capital"])
        for source in driven:
            base_rev = _num(source["revenue"])
            base_growth = base_rev / rev_prev - 1 if rev_prev else 0.0
            rev = rev_prev * (1 + base_growth + growth_delta)
            scale = rev / base_rev if base_rev else 1.0
            margin = _num(source["ebit"]) / base_rev + margin_delta if base_rev else margin_delta
            ebit = rev * margin
            tax_rate = _num(source["cash_taxes"]) / _num(source["ebit"]) if _num(source["ebit"]) else 0.0
            taxes = ebit * tax_rate
            da, capex = _num(source["da"]) * scale, _num(source["capex"]) * scale
            d_nwc = _num(source["change_nwc"]) * scale
            nwc = nwc_prev + d_nwc
            fcf = ebit - taxes + da - capex - d_nwc
            rows.append({"period": source["period"], "revenue": rev, "revenue_growth": base_growth + growth_delta,
                         "ebit": ebit, "ebit_margin": margin, "ebitda": ebit + da, "tax_rate": tax_rate,
                         "cash_taxes": taxes, "nopat": ebit - taxes, "da": da, "capex": capex,
                         "nwc": nwc, "change_nwc": d_nwc, "unlevered_fcf": fcf,
                         "source": "three_statement"})
            rev_prev, nwc_prev = rev, nwc
        return rows
    n = plan["timeline"]["horizon_years"]
    sc = plan["scenarios"][scenario]
    v = {f: _vec(sc[f], n) for f in VECTOR_FIELDS}
    rev_prev = _num(plan["historicals"]["revenue"])
    nwc_prev = _num(plan["historicals"]["net_working_capital"])
    start = int(plan["timeline"]["start_year"])
    rows = []
    for i in range(n):
        g = v["revenue_growth"][i] + growth_delta
        rev = rev_prev * (1 + g)
        margin = v["ebit_margin"][i] + margin_delta
        ebit = rev * margin
        tax_rate = v["tax_rate"][i]
        taxes = ebit * tax_rate
        da = rev * v["da_percent_revenue"][i]
        capex = rev * v["capex_percent_revenue"][i]
        nwc = rev * v["nwc_percent_revenue"][i]
        d_nwc = nwc - nwc_prev
        fcf = ebit - taxes + da - capex - d_nwc
        rows.append({"period": str(start + i + 1), "revenue": rev, "revenue_growth": g, "ebit": ebit,
                     "ebit_margin": margin, "ebitda": ebit + da, "tax_rate": tax_rate, "cash_taxes": taxes,
                     "nopat": ebit - taxes, "da": da, "capex": capex, "nwc": nwc, "change_nwc": d_nwc,
                     "unlevered_fcf": fcf})
        rev_prev, nwc_prev = rev, nwc
    return rows


def equity_bridge(plan: dict[str, Any], ev: float) -> dict[str, float]:
    b = plan["ev_to_equity_bridge"]
    add = sum(_num(b.get(k)) for k in BRIDGE_ADD)
    sub = sum(_num(b.get(k)) for k in BRIDGE_SUB)
    return {"add_backs": add, "deductions": sub, "equity_value": ev + add - sub}


def run_scenario(plan: dict[str, Any], scenario: str, *, wacc_delta: float = 0.0, growth_delta: float = 0.0,
                 margin_delta: float = 0.0, g_delta: float = 0.0, multiple_delta: float = 0.0,
                 method: str | None = None) -> dict[str, Any]:
    w = compute_wacc(plan, scenario, wacc_delta)
    rate = w["wacc"]
    rows = forecast(plan, scenario, growth_delta, margin_delta)
    mid = bool(plan.get("forecast", {}).get("mid_year_convention", True))
    pv_rows = []
    for i, r in enumerate(rows, 1):
        t = i - 0.5 if mid else float(i)
        pv_rows.append({"period": r["period"], "cash_flow": r["unlevered_fcf"], "discount_period": t,
                        "pv_cash_flow": r["unlevered_fcf"] / (1 + rate) ** t})
    n = len(rows)
    last = rows[-1]
    tv_cfg = plan["terminal_value"]
    method = method or tv_cfg["method"]
    g = _terminal_growth(plan, scenario) + g_delta
    multiple = _num(tv_cfg.get("exit_ebitda_multiple")) + multiple_delta
    if method == "perpetual_growth":
        tv = last["unlevered_fcf"] * (1 + g) / (rate - g)
    else:
        tv = last["ebitda"] * multiple
    pv_tv = tv / (1 + rate) ** n
    pv_fcf = sum(r["pv_cash_flow"] for r in pv_rows)
    ev = pv_fcf + pv_tv
    bridge = equity_bridge(plan, ev)
    shares = _num(plan["ev_to_equity_bridge"]["diluted_shares"])
    return {
        "scenario": scenario, "cash_flow_basis": "fcff", "forecast_rows": rows, "wacc": w, "discount_rate": rate,
        "terminal": {"method": method, "terminal_growth_rate": g, "terminal_value": tv,
                     "exit_ebitda_multiple": multiple,
                     "implied_exit_ebitda_multiple": tv / last["ebitda"] if last["ebitda"] else None,
                     "implied_perpetual_growth": ((tv * rate - last["unlevered_fcf"]) / (tv + last["unlevered_fcf"])
                                                  if tv + last["unlevered_fcf"] else None)},
        "pv": {"pv_rows": pv_rows, "pv_fcf": pv_fcf, "pv_terminal_value": pv_tv, "total_pv": ev},
        "enterprise_value": ev, "equity_bridge": bridge, "equity_value": bridge["equity_value"],
        "value_per_share": bridge["equity_value"] / shares, "tv_percent_ev": pv_tv / ev if ev else None,
    }


def run_sensitivities(plan: dict[str, Any]) -> dict[str, Any]:
    s = plan["sensitivities"]
    specs = [
        ("WACC / Terminal Growth", "wacc_delta", "terminal_growth_delta",
         lambda x, y: run_scenario(plan, "base", wacc_delta=x, g_delta=y, method="perpetual_growth")),
        ("WACC / Exit Multiple", "wacc_delta", "exit_multiple_delta",
         lambda x, y: run_scenario(plan, "base", wacc_delta=x, multiple_delta=y, method="exit_multiple")),
        ("Revenue Growth / EBIT Margin", "revenue_growth_delta", "ebit_margin_delta",
         lambda x, y: run_scenario(plan, "base", growth_delta=x, margin_delta=y)),
    ]
    rows = []
    for name, xa, ya, fn in specs:
        for x in s.get(xa, [0.0]):
            for y in s.get(ya, [0.0]):
                try:
                    val = fn(x, y)["value_per_share"]
                    note = ""
                except ZeroDivisionError:
                    val, note = None, "WACC ≤ g，无意义"
                if val is not None and name == "WACC / Terminal Growth":
                    w = compute_wacc(plan, "base", x)["wacc"]
                    if w <= _terminal_growth(plan, "base") + y:
                        val, note = None, "WACC ≤ g，无意义"
                rows.append({"sensitivity": name, "x_axis": xa, "x_value": x, "y_axis": ya, "y_value": y,
                             "metric": "value_per_share", "value": val, "notes": note})
    return {"rows": rows, "directionality": _directionality(rows)}


def _directionality(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """合理性检查：每股价值应随 WACC 上升而下降，随永续增长率、利润率上升而上升。"""
    details = []

    def mono(name: str, axis: str, fixed_axis: str, expect_up: bool) -> None:
        sub = [r for r in rows if r["sensitivity"] == name and r["value"] is not None]
        for fixed in sorted({r[fixed_axis] for r in sub}):
            line = sorted((r[axis], r["value"]) for r in sub if r[fixed_axis] == fixed)
            vals = [v for _, v in line]
            ok = all(b >= a for a, b in zip(vals, vals[1:])) if expect_up else all(b <= a for a, b in zip(vals, vals[1:]))
            details.append({"check": f"{name}：沿 {axis} {'递增' if expect_up else '递减'}（{fixed_axis}={fixed}）",
                            "passed": ok})

    mono("WACC / Terminal Growth", "x_value", "y_value", expect_up=False)
    mono("WACC / Terminal Growth", "y_value", "x_value", expect_up=True)
    mono("Revenue Growth / EBIT Margin", "y_value", "x_value", expect_up=True)
    return {"passed": all(d["passed"] for d in details), "details": details}


def compute_checks(plan: dict[str, Any], scenarios: dict[str, dict[str, Any]],
                   sens: dict[str, Any]) -> dict[str, Any]:
    hard, warn, info = [], [], []
    base = scenarios["base"]
    vps = {k: v["value_per_share"] for k, v in scenarios.items()}
    if not vps["downside"] <= vps["base"] <= vps["upside"]:
        warn.append(f"情景排序异常：悲观 {vps['downside']:.2f} / 基准 {vps['base']:.2f} / 乐观 {vps['upside']:.2f}")
    if base["equity_value"] <= 0:
        hard.append("基准情景股权价值为负，模型不可用于决策")
    tvp = base["tv_percent_ev"] or 0
    if tvp > 0.75:
        warn.append(f"终值占企业价值 {tvp:.1%}，结论高度依赖终值假设，需重点复核 WACC 与永续增长率")
    h = plan["historicals"]
    hist_margin = _num(h["ebit"]) / _num(h["revenue"])
    fwd_margin = base["forecast_rows"][-1]["ebit_margin"]
    if fwd_margin - hist_margin > 0.03:
        warn.append(f"预测期末 EBIT 利润率 {fwd_margin:.1%} 较历史 {hist_margin:.1%} 提升超过 3 个百分点，需有充分依据")
    impl = base["terminal"]["implied_exit_ebitda_multiple"]
    if impl is not None and impl > 20:
        warn.append(f"永续增长法隐含 EV/EBITDA {impl:.1f}x，偏高")
    labels = {s.get("topic"): s.get("label") for s in plan.get("source_basis", [])}
    est = sorted(t for t, l in labels.items() if l in ("analyst_estimate", "placeholder"))
    if est:
        warn.append("以下关键输入依赖分析师假设：" + "、".join(est))
    if any(l == "placeholder" for l in labels.values()):
        hard.append("存在占位（placeholder）输入")
    if not sens["directionality"]["passed"]:
        hard.append("敏感性方向性检查未通过")
    info.append(f"基准 WACC {base['discount_rate']:.2%}，永续增长率 {base['terminal']['terminal_growth_rate']:.2%}")
    return {"hard_failures": hard, "warnings": warn, "informational": info}


def determine_model_status(plan: dict[str, Any], hard: list[str], warnings: list[str]) -> str:
    if hard:
        return "blocked"
    labels = {s.get("label") for s in plan.get("source_basis", [])}
    if "analyst_estimate" in labels:
        return "screen-grade"
    return "decision-grade" if not warnings else "senior-review-ready"
