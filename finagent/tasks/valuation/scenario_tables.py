"""情景偏度与敏感性表格（自研，标准库实现）。

表格口径、列名与判定规则与原 Public Equity Investing 插件 scenario-sensitivity-generator 保持一致
（逐项对照见 tests/test_parity_reference.py），只保留本项目用到的 6 张表：
  price_target_scenario / valuation_sensitivity / eps_revision_sensitivity /
  kpi_driver_sensitivity / equity_liquidity_downside / thesis_trigger_table
缺少输入时输出 "input required"，不臆造数值。表内文字保持英文代码值，中文表名由 scenarios.py 补充。
"""

from __future__ import annotations

import json
import math
from typing import Any

DEFAULT_AXES = {
    "valuation_multiples": [8.0, 10.0, 12.0],
    "eps_revisions": [-0.10, 0.0, 0.10],
    "multiple_changes": [-0.10, 0.0, 0.10],
    "revenue_growth_shocks": [-0.05, 0.0, 0.05],
    "margin_shock_bps": [-200, 0, 200],
}
SOURCE_COLUMNS = ["source_id", "source_posture", "as_of_date"]
PROB_TOL = 0.0001
DEFAULT_HURDLE = 0.10
MISSING = "input required"


# ---------------------------------------------------------------- 取值与格式

def axis(payload: dict[str, Any], name: str) -> list[Any]:
    v = payload.get("axes", {}).get(name, DEFAULT_AXES[name])
    return v if isinstance(v, list) and v else DEFAULT_AXES[name]


def num(x: Any) -> float | None:
    """转为有限浮点数；空值、非数字、NaN/Inf 均返回 None。"""
    if x is None or x == "":
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def field(d: dict[str, Any], key: str, default: Any = None) -> float | None:
    return num(d.get(key, default))


def prob(x: Any) -> float | None:
    v = num(x)
    return v if v is not None and 0 <= v <= 1 else None


def fmt(v: Any, digits: int = 1) -> str:
    if v is None:
        return MISSING
    if isinstance(v, str):
        return v
    try:
        x = float(v)
    except (TypeError, ValueError):
        return str(v)
    return "n/a" if math.isnan(x) or math.isinf(x) else f"{x:.{digits}f}"


def _fmt_with(v: Any, render) -> str:
    if v is None:
        return MISSING
    try:
        return render(float(v))
    except (TypeError, ValueError):
        return str(v)


def fmt_pct(v: Any, digits: int = 1) -> str:
    return _fmt_with(v, lambda x: f"{x * 100:.{digits}f}%")


def fmt_bps(v: Any) -> str:
    return _fmt_with(v, lambda x: f"{x:.0f} bps")


def fmt_multiple(v: Any, digits: int = 1) -> str:
    return _fmt_with(v, lambda x: f"{x:.{digits}f}x")


def fmt_ratio(v: float | None) -> str:
    return MISSING if v is None else f"{v:.2f}x"


def source_context(payload: dict[str, Any], item: dict[str, Any] | None = None) -> dict[str, str]:
    """来源三元组：按 行 → base → source → metadata → payload 顺序取第一个非空值。"""
    base = payload.get("base", {})
    src = payload.get("source", {}) if isinstance(payload.get("source", {}), dict) else {}
    meta = payload.get("metadata", {}) if isinstance(payload.get("metadata", {}), dict) else {}
    item = item or {}

    def pick(*vals: Any, default: str) -> str:
        return next((str(v) for v in vals if v not in (None, "")), default)

    return {
        "source_id": pick(item.get("source_id"), item.get("source"), base.get("source_id"), src.get("source_id"),
                          meta.get("source_id"), payload.get("source_id"), default="missing"),
        "source_posture": pick(item.get("source_posture"), base.get("source_posture"), src.get("source_posture"),
                               meta.get("source_posture"), payload.get("source_posture"),
                               default="user_supplied" if meta.get("source_name") and meta.get("as_of")
                               else "unsourced_or_illustrative"),
        "as_of_date": pick(item.get("as_of_date"), base.get("as_of_date"), src.get("as_of_date"), meta.get("as_of"),
                           payload.get("as_of_date"), default="missing"),
    }


def sourced(row: dict[str, Any], payload: dict[str, Any], item: dict[str, Any] | None = None) -> dict[str, Any]:
    row.update(source_context(payload, item))
    return row


def table(name: str, desc: str, columns: list[str], rows: list[dict[str, Any]],
          notes: list[str] | None = None) -> dict[str, Any]:
    return {"name": name, "description": desc, "columns": columns + SOURCE_COLUMNS, "rows": rows,
            "notes": notes or []}


# ---------------------------------------------------------------- 情景判定规则

def check_probabilities(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """情景概率必须齐全、在 [0,1] 内且合计 100%（容差 0.01 个百分点）。"""
    vals, missing, invalid = [], [], []
    for i, c in enumerate(cases):
        label = str(c.get("scenario", f"case_{i + 1}"))
        raw = c.get("probability")
        if raw in (None, ""):
            missing.append(label)
        elif (p := prob(raw)) is None:
            invalid.append(label)
        else:
            vals.append(p)
    total = sum(vals)
    partial = total if vals else None
    if missing:
        return {"ok": False, "status": "missing probabilities: " + ", ".join(missing), "sum": partial}
    if invalid:
        return {"ok": False, "status": "invalid probabilities outside 0.0-1.0: " + ", ".join(invalid), "sum": partial}
    if not vals:
        return {"ok": False, "status": "missing probabilities", "sum": None}
    if abs(total - 1.0) > PROB_TOL:
        return {"ok": False, "status": f"probabilities must sum to 100%; supplied sum is {total * 100:.1f}%",
                "sum": total}
    return {"ok": True, "status": "ok", "sum": total}


def ret(v: float | None, price: float | None) -> float | None:
    return None if v is None or price is None or price == 0 else v / price - 1


def break_even(up: float | None, down: float | None, price: float | None) -> float | None:
    """盈亏平衡概率：现价 = p × 上行目标 + (1−p) × 下行目标 时的 p；不在 [0,1] 内返回 None。"""
    if up is None or down is None or price is None or up - down == 0:
        return None
    p = (price - down) / (up - down)
    return p if 0 <= p <= 1 else None


def _passes_hurdle(r: float, hurdle: float | None, ratio: float | None) -> bool:
    return r >= (hurdle if hurdle is not None else DEFAULT_HURDLE) and (ratio is None or ratio <= 0.75)


def skew_label(r: float | None, hurdle: float | None, ratio: float | None) -> str:
    if r is None:
        return MISSING
    if _passes_hurdle(r, hurdle, ratio):
        return "underwriteable upside"
    if r > 0:
        return "optical upside / needs proof"
    return "negative skew" if r < 0 else "balanced / watchlist"


def action_rule(r: float | None, hurdle: float | None, ratio: float | None) -> str:
    if r is None:
        return MISSING
    if _passes_hurdle(r, hurdle, ratio):
        return "add / press if evidence confirms"
    if r >= 0:
        return "hold / wait for proof"
    return "trim / exit unless thesis is re-underwritten" if r <= -0.15 else "watchlist / re-underwrite"


# ---------------------------------------------------------------- 六张表

def price_target_scenario(payload: dict[str, Any]) -> dict[str, Any]:
    base = payload["base"]
    price = field(base, "share_price")
    hurdle = field(base, "required_return", field(base, "hurdle_return", DEFAULT_HURDLE))
    cases = payload.get("cases") or [
        {"scenario": s, "price_target": base.get(f"{s}_price_target"), "probability": base.get(f"{s}_probability"),
         "rationale": f"{s} case"} for s in ("upside", "base", "downside")]
    pc = check_probabilities(cases)
    prepared, weighted, complete, rets = [], 0.0, True, []
    for c in cases:
        tgt, p = field(c, "price_target"), prob(c.get("probability"))
        r = ret(tgt, price)
        complete = complete and tgt is not None
        if r is not None:
            rets.append(r)
        if tgt is not None and p is not None and pc["ok"]:
            weighted += tgt * p
        prepared.append((c, tgt, p, r))
    up = max([r for r in rets if r > 0], default=None)
    down_abs = abs(min([r for r in rets if r < 0], default=0.0)) if rets else None
    ratio = down_abs / up if up not in (None, 0) and down_abs is not None else None
    tgts = [t for _, t, _, _ in prepared if t is not None]
    be = break_even(max(tgts) if tgts else None, min(tgts) if tgts else None, price)

    def row(scenario: Any, target: float | None, r: float | None, p: str, rationale: Any, implication: Any):
        return {"scenario": scenario, "price_target": fmt(target), "return_vs_share_price": fmt_pct(r),
                "required_return": fmt_pct(hurdle),
                "expected_return_vs_hurdle": fmt_pct(r - hurdle if r is not None and hurdle is not None else None),
                "downside_upside_ratio": fmt_ratio(ratio), "break_even_probability": fmt_pct(be),
                "skew_label": skew_label(r, hurdle, ratio), "action_rule": action_rule(r, hurdle, ratio),
                "probability": p, "probability_check": pc["status"], "probability_sum": fmt_pct(pc["sum"]),
                "rationale": rationale, "implication": implication}

    rows = [sourced(row(c.get("scenario", "case"), t, r, fmt_pct(p), c.get("rationale", ""), c.get("implication", "")),
                    payload, c) for c, t, p, r in prepared]
    can_weight = pc["ok"] and complete
    wr = ret(weighted if can_weight else None, price)
    rows.append(sourced(row("probability_weighted", weighted if can_weight else None, wr, "n/a",
                            "weighted by supplied case probabilities",
                            "compare expected return to hurdle and downside/upside skew" if can_weight
                            else "input required: complete case targets and probabilities summing to 100%"), payload))
    return table("price_target_scenario",
                 "Bull/base/bear price-target, expected return, break-even probability, and skew table.",
                 ["scenario", "price_target", "return_vs_share_price", "required_return", "expected_return_vs_hurdle",
                  "downside_upside_ratio", "break_even_probability", "skew_label", "action_rule", "probability",
                  "probability_check", "probability_sum", "rationale", "implication"], rows,
                 ["Requires share_price and complete case price targets for calculated return output.",
                  "Probability-weighted output requires every case probability to be present and sum to 100%.",
                  "Skew labels distinguish underwriteable upside from merely optical upside."])


def valuation_sensitivity(payload: dict[str, Any]) -> dict[str, Any]:
    base = payload["base"]
    ebitda, eps = field(base, "ebitda"), field(base, "eps", field(base, "ntm_eps"))
    net_debt, shares = field(base, "net_debt", 0.0), field(base, "shares_outstanding")
    rows = []
    for m in axis(payload, "valuation_multiples"):
        ev_px = ((ebitda * float(m) - net_debt) / shares
                 if ebitda is not None and net_debt is not None and shares not in (None, 0) else None)
        rows.append(sourced({"multiple": fmt_multiple(m), "ev_ebitda_implied_price": fmt(ev_px),
                             "pe_implied_price": fmt(eps * float(m) if eps is not None else None),
                             "method_note": "EV/EBITDA requires ebitda, net_debt, shares; P/E requires eps"}, payload))
    return table("valuation_sensitivity", "Implied price by valuation multiple.",
                 ["multiple", "ev_ebitda_implied_price", "pe_implied_price", "method_note"], rows)


def eps_revision_sensitivity(payload: dict[str, Any]) -> dict[str, Any]:
    base = payload["base"]
    eps = field(base, "eps", field(base, "ntm_eps"))
    mult = field(base, "pe_multiple", field(base, "multiple"))
    rows = []
    for er in axis(payload, "eps_revisions"):
        for mc in axis(payload, "multiple_changes"):
            e = eps * (1 + float(er)) if eps is not None else None
            m = mult * (1 + float(mc)) if mult is not None else None
            rows.append(sourced({"eps_revision": fmt_pct(er), "multiple_change": fmt_pct(mc),
                                 "revised_eps": fmt(e, 2), "revised_multiple": fmt_multiple(m),
                                 "implied_price": fmt(e * m if e is not None and m is not None else None)}, payload))
    return table("eps_revision_sensitivity", "Price sensitivity to EPS revisions and multiple change.",
                 ["eps_revision", "multiple_change", "revised_eps", "revised_multiple", "implied_price"], rows,
                 ["Requires eps and pe_multiple or multiple."])


def kpi_driver_sensitivity(payload: dict[str, Any]) -> dict[str, Any]:
    base = payload["base"]
    rev = field(base, "revenue")
    margin = field(base, "ebit_margin", field(base, "ebitda_margin"))
    flow = field(base, "incremental_margin", margin)
    rows = []
    for rs in axis(payload, "revenue_growth_shocks"):
        for bps in axis(payload, "margin_shock_bps"):
            impact = None
            if rev is not None and margin is not None:  # 冲击后收入 × 冲击后利润率 − 基准利润
                impact = rev * (1 + float(rs)) * (margin + float(bps) / 10000.0) - rev * margin
            rows.append(sourced({"revenue_shock": fmt_pct(rs), "margin_shock": fmt_bps(bps),
                                 "revenue_delta": fmt(rev * float(rs) if rev is not None else None),
                                 "profit_impact": fmt(impact),
                                 "flowthrough_note": "uses margin shock on scenario revenue; incremental margin "
                                                     "available separately" if flow is not None else MISSING},
                                payload))
    return table("kpi_driver_sensitivity", "Operating KPI sensitivity to revenue and margin shocks.",
                 ["revenue_shock", "margin_shock", "revenue_delta", "profit_impact", "flowthrough_note"], rows,
                 ["Adapt driver names to the relevant sector KPI: NIM, ARR, NRR, NOI, production, loss ratio, "
                  "take rate, or other key KPI."])


def equity_liquidity_downside(payload: dict[str, Any]) -> dict[str, Any]:
    """流动性压力：FCF × (1 + 冲击)（FCF 为负时冲击方向相反，保持与参照口径一致）。"""
    base = payload["base"]
    cash, revolver = field(base, "cash"), field(base, "revolver_availability")
    min_liq = field(base, "minimum_liquidity")
    fcf = field(base, "fcf", field(base, "free_cash_flow"))
    mats, debt, ebitda = field(base, "maturities_12m"), field(base, "debt"), field(base, "ebitda")
    rows = []
    for s in axis(payload, "revenue_growth_shocks"):
        sf = fcf * (1 + float(s)) if fcf is not None else None
        liq = None
        if any(v is not None for v in (cash, revolver, sf, mats)):
            liq = (cash or 0.0) + (revolver or 0.0) + (sf or 0.0) - (mats or 0.0)
        head = liq - min_liq if liq is not None and min_liq is not None else None
        lev = debt / ebitda if debt is not None and ebitda not in (None, 0) else None
        rows.append(sourced({"stress_case": f"fcf shock {fmt_pct(s)}", "stressed_fcf": fmt(sf),
                             "liquidity_after_12m_maturities": fmt(liq), "minimum_liquidity": fmt(min_liq),
                             "liquidity_headroom": fmt(head), "debt_to_ebitda": fmt_multiple(lev),
                             "implication": MISSING if head is None else
                             ("liquidity breach" if head < 0 else "liquidity ok")}, payload))
    return table("equity_liquidity_downside",
                 "Common-equity liquidity downside stress; route credit-security valuation to Credit Markets.",
                 ["stress_case", "stressed_fcf", "liquidity_after_12m_maturities", "minimum_liquidity",
                  "liquidity_headroom", "debt_to_ebitda", "implication"], rows)


DEFAULT_TRIGGERS = [
    {"trigger": "estimate revision", "threshold": MISSING, "implication": "confirm or disconfirm thesis",
     "next_step": "equity-model-update"},
    {"trigger": "valuation support", "threshold": MISSING, "implication": "reassess risk/reward",
     "next_step": "memo-builder"},
    {"trigger": "downside / stop case", "threshold": MISSING, "implication": "review sizing or hedge",
     "next_step": "portfolio-risk-management"},
]


def thesis_trigger_table(payload: dict[str, Any]) -> dict[str, Any]:
    rows = [sourced({"trigger": t.get("trigger", ""), "threshold": t.get("threshold", MISSING),
                     "monitoring_cadence": t.get("monitoring_cadence", t.get("cadence", "")),
                     "implication": t.get("implication", ""), "next_step": t.get("next_step", ""),
                     "source_or_owner": t.get("source_or_owner", t.get("owner", ""))}, payload, t)
            for t in payload.get("triggers") or DEFAULT_TRIGGERS]
    return table("thesis_trigger_table", "Confirm/disconfirm triggers and next actions.",
                 ["trigger", "threshold", "monitoring_cadence", "implication", "next_step", "source_or_owner"], rows)


BUILDERS = {f.__name__: f for f in (price_target_scenario, valuation_sensitivity, eps_revision_sensitivity,
                                    kpi_driver_sensitivity, equity_liquidity_downside, thesis_trigger_table)}


# ---------------------------------------------------------------- 就绪度

def _primary_source(payload: dict[str, Any]) -> dict[str, str]:
    src = payload.get("source", {}) if isinstance(payload.get("source", {}), dict) else {}
    base = payload.get("base", {})
    meta = payload.get("metadata", {}) if isinstance(payload.get("metadata", {}), dict) else {}
    title = src.get("title") or src.get("source_name") or base.get("source_name") or meta.get("source_name")
    as_of = src.get("as_of_date") or base.get("as_of_date") or meta.get("as_of") or payload.get("as_of_date")
    status = (src.get("source_posture") or base.get("source_posture") or meta.get("source_posture")
              or payload.get("source_posture") or ("user_supplied" if title and as_of else "unsourced_or_illustrative"))
    return {"as_of": str(as_of or "Not provided"), "status": str(status)}


def classify_readiness(tables: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any]:
    """就绪度：缺必需输入 → not-decision-ready；来源/日期缺失 → screen-grade；否则 senior-review-ready。"""
    base = payload.get("base", {})
    if not isinstance(base, dict):
        base = {}
    missing, warnings = [], []
    if not payload.get("_input_was_provided"):
        missing.append("input_json")
    if not base:
        missing.append("base_case")
    if field(base, "share_price") is None:
        missing.append("base.share_price")

    pt = next((t for t in tables if t.get("name") == "price_target_scenario"), tables[0] if tables else None)
    statuses = {str(r.get("probability_check", "")) for r in (pt or {}).get("rows", [])
                if str(r.get("scenario", "")).lower() != "probability_weighted"}
    bad = [s for s in statuses if s and s != "ok"]
    if bad:
        missing.append("scenario.probabilities")
        warnings.append("Scenario probabilities are missing, invalid, or do not sum to 100%; probability-weighted "
                        "value is not decision-ready.")
    if MISSING in json.dumps(tables).lower():
        warnings.append("One or more scenario outputs contain input required placeholders.")

    src = _primary_source(payload)
    src_missing = (src["as_of"].lower() in {"not provided", "missing", ""}
                   or src["status"].lower() in {"unsourced_or_illustrative", "missing", "not provided"})
    if src_missing:
        warnings.append("Source/as-of posture is missing or illustrative; cap the output below senior-review-ready.")

    if missing:
        status, effect = "not-decision-ready", "blocked"
        impact = ("Do not use for target, rating, sizing, circulation, or PM action until required base-case and "
                  "probability inputs are supplied.")
    elif src_missing:
        status, effect = "screen-grade", "screen_grade"
        impact = "Useful for triage, but missing source/as-of support keeps it below decision-grade."
    else:
        status, effect = "senior-review-ready", "senior_review_ready"
        impact = ("Scenario math, source/as-of posture, current price, and probability checks are complete enough "
                  "for senior review.")
    return {"model_status": status, "readiness_effect": effect, "decision_impact": impact,
            "missing_required_inputs": sorted(set(missing)), "warnings": sorted(set(warnings)),
            "source_posture": src["status"],
            "probability_validation": "ok" if not bad else "; ".join(sorted(bad))}
