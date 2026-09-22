"""断言核查：把研报断言与财报“真值表”逐条比对，给出结论、错误类型、来源定位与修改建议。

结论类型：
  正确 / 数值错误 / 单位错误 / 期间错配 / 口径错误 / 方向错误 / 无法核实
误报控制：
  - 容差按研报展示精度计算（如 58.62 亿元 → ±0.005 亿元），避免把四舍五入当错误；
  - 预测值、缺少真值的断言一律判“无法核实”，不计为错误；
  - 错误类型诊断（单位/期间/口径）只有在找到精确匹配的替代解释时才下结论，否则归为“数值错误”。
"""

from __future__ import annotations

from typing import Any

from ...core import tracing
from ...core.numbers import UNIT_FACTORS, half_ulp, pct_change
from ..financials.analyze import FactTable, prior_periods
from ..financials.schema import BY_ID

ERROR_VERDICTS = {"数值错误", "单位错误", "期间错配", "口径错误", "方向错误"}
# 口径诊断只在“容易混用”的相关指标之间进行，避免跨指标的巧合匹配造成误判
CALIBER_GROUPS = [
    {"net_profit", "np_parent", "np_parent_deducted", "total_profit", "operating_profit"},
    {"revenue", "operating_cost"},
    {"gross_margin", "net_margin"},
    {"total_assets", "total_liabilities", "total_equity", "equity_parent"},
    {"depreciation", "amortization", "da"},
    {"ocf", "capex"},
]
UNIT_ALTS = {"亿元": ["万元", "元", "百万元"], "万元": ["亿元", "元", "千元"], "元": ["万元", "亿元"],
             "百万元": ["亿元", "万元"], "千元": ["万元", "元"]}


class Truth:
    def __init__(self, truth_table: list[dict[str, Any]]):
        self.t = FactTable(truth_table)

    def level(self, mid: str, period: str) -> float | None:
        return self.t.v(mid, period)

    def yoy(self, mid: str, period: str) -> float | None:
        base, _ = prior_periods(period)
        return pct_change(self.t.v(mid, period), self.t.v(mid, base)) if base else None

    def pp(self, mid: str, period: str) -> float | None:
        base, _ = prior_periods(period)
        a, b = self.t.v(mid, period), self.t.v(mid, base) if base else None
        return None if a is None or b is None else a - b

    def value(self, ctype: str, mid: str, period: str) -> float | None:
        if ctype in ("level", "ratio"):
            return self.level(mid, period)
        if ctype == "yoy":
            return self.yoy(mid, period)
        if ctype == "pp_change":
            return self.pp(mid, period)
        return None

    def evidence(self, ctype: str, mid: str, period: str) -> list[dict[str, Any]]:
        refs = [self.t.src(mid, period)]
        if ctype in ("yoy", "pp_change"):
            base, _ = prior_periods(period)
            refs.append(self.t.src(mid, base))
        cell = self.t.cells.get((mid, period))
        if cell and cell.get("method") == "derived":
            refs = [{"metric": mid, "period": period, "formula": cell.get("formula"),
                     "derived_from": cell["source"].get("derived_from")}]
        return [r for r in refs if r]

    def metrics(self) -> list[str]:
        return sorted({m for (m, _) in self.t.cells if "." not in m})

    def periods(self, mid: str) -> list[str]:
        return sorted(p for (m, p) in self.t.cells if m == mid)


def _factor(mid: str, unit: str) -> float:
    kind = BY_ID[mid].kind
    if kind in ("amount", "shares"):
        return UNIT_FACTORS.get(unit, 1.0)
    return 1.0


def _fmt(value: float, unit: str, raw: str, ctype: str, mid: str) -> str:
    dec = max(2, len(raw.split(".")[1]) if "." in raw else 0)
    if ctype == "level":
        return f"{value / _factor(mid, unit):,.{dec}f}{unit}"
    if ctype == "pp_change":
        return f"{value:+.{dec}f}个百分点"
    return f"{value:.{dec}f}%"


def verify_claim(c: dict[str, Any], truth: Truth) -> dict[str, Any]:
    mid, period, ctype, unit, raw = c["metric_id"], c["period"], c["claim_type"], c["unit"], c["raw_value"]
    out = {**c, "verdict": "无法核实", "truth_value": None, "truth_display": None, "evidence": [],
           "explanation": "", "suggestion": ""}
    if c.get("is_forecast"):
        out["explanation"] = "预测性表述，历史财报无法核验，需核对盈利预测模型。"
        return out
    t = truth.value(ctype, mid, period)
    if t is None:
        out["explanation"] = f"真值表中缺少 {BY_ID[mid].name} {period} 的{'同比' if ctype == 'yoy' else ''}数据。"
        return out

    factor = _factor(mid, unit) if ctype == "level" else 1.0
    claimed = c["value"] * factor
    tol = half_ulp(raw, factor) + (0.005 if ctype != "level" else abs(t) * 1e-6)
    out["truth_value"] = t
    out["truth_display"] = _fmt(t, unit, raw, ctype, mid)
    out["evidence"] = truth.evidence(ctype, mid, period)

    def hit(x: float | None, v: float = claimed, tl: float = tol) -> bool:
        return x is not None and abs(v - x) <= tl

    if hit(t):
        out["verdict"] = "正确"
        out["explanation"] = f"与财报一致（真值 {out['truth_display']}，差异在展示精度内）。"
        return out

    # ---- 错误类型诊断 ----
    diag = None
    if ctype == "level":
        for alt in UNIT_ALTS.get(unit, []):
            f2 = _factor(mid, alt)
            if hit(t, c["value"] * f2, half_ulp(raw, f2) + abs(t) * 1e-6):
                out["truth_display"] = _fmt(t, alt, raw, ctype, mid)
                diag = ("单位错误", f"数值与财报一致，但单位应为“{alt}”而非“{unit}”。",
                        f"将“{raw}{unit}”改为“{out['truth_display']}”。")
                break
    if diag is None and ctype in ("yoy", "pp_change") and hit(t, -claimed):
        diag = ("方向错误", "增减方向与财报相反。", f"将增减方向及数值改为 {out['truth_display']}。")
    if diag is None:
        for p2 in truth.periods(mid):
            if p2 != period and hit(truth.value(ctype, mid, p2)):
                diag = ("期间错配", f"该数值对应 {p2} 期而非 {period} 期。",
                        f"将数值改为 {period} 期的 {out['truth_display']}，或更正期间为 {p2}。")
                break
    if diag is None:
        related = set().union(*(g for g in CALIBER_GROUPS if mid in g))
        for m2 in sorted(related):
            if m2 == mid or BY_ID.get(m2) is None:
                continue
            if hit(truth.value(ctype, m2, period)):
                diag = ("口径错误", f"该数值实为“{BY_ID[m2].name}”，与所述“{BY_ID[mid].name}”口径不同。",
                        f"若指{BY_ID[mid].name}，应为 {out['truth_display']}；若指{BY_ID[m2].name}，请更正指标名称。")
                break
    if diag is None:
        diff = claimed - t
        rel = f"，相对偏差 {diff / abs(t) * 100:+.2f}%" if ctype == "level" and t else ""
        diag = ("数值错误", f"与财报不符：研报 {raw}{unit if ctype != 'pp_change' else '个百分点'}，"
                            f"财报 {out['truth_display']}{rel}。",
                f"将“{c['quote']}”中的数值改为 {out['truth_display']}。")
    out["verdict"], out["explanation"], out["suggestion"] = diag
    return out


@tracing.traced("verify_claims")
def verify_claims(claims: list[dict[str, Any]], truth_table: list[dict[str, Any]]) -> dict[str, Any]:
    truth = Truth(truth_table)
    findings = [verify_claim(c, truth) for c in claims]
    counts: dict[str, int] = {}
    for f in findings:
        counts[f["verdict"]] = counts.get(f["verdict"], 0) + 1
    return {
        "findings": findings,
        "summary": {
            "claims": len(findings),
            "errors": sum(1 for f in findings if f["verdict"] in ERROR_VERDICTS),
            "verified_correct": counts.get("正确", 0),
            "unverifiable": counts.get("无法核实", 0),
            "by_verdict": counts,
        },
    }
