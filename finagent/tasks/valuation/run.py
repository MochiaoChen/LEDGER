"""估值执行：调用确定性 DCF 引擎（dcf.py），输出三情景估值、敏感性矩阵与模型检查。

DCF 由三表模型驱动：plan 的情景向量取自三表模型，这里再逐期核对 DCF 还原出的收入、EBIT、折旧摊销、
资本开支、营运资本与三表模型输出一致（不一致即硬性失败）。"""

from __future__ import annotations

from typing import Any

from ...core import tracing
from . import dcf

SENS_NAMES = {
    "WACC / Terminal Growth": "WACC × 永续增长率",
    "WACC / Exit Multiple": "WACC × 退出 EV/EBITDA 倍数",
    "Revenue Growth / EBIT Margin": "收入增速 × EBIT 利润率",
}
SCEN_CN = {"base": "基准", "downside": "悲观", "upside": "乐观"}
TIE_KEYS = ["revenue", "ebit", "da", "capex", "nwc"]


def _grid(rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
    sub = [r for r in rows if r["sensitivity"] == name]
    xs = sorted({r["x_value"] for r in sub})
    ys = sorted({r["y_value"] for r in sub})
    cell = {(r["x_value"], r["y_value"]): r["value"] for r in sub}
    return {
        "name": SENS_NAMES.get(name, name),
        "x_axis": sub[0]["x_axis"] if sub else "",
        "y_axis": sub[0]["y_axis"] if sub else "",
        "x_values": xs,
        "y_values": ys,
        "matrix": [[cell.get((x, y)) for y in ys] for x in xs],
    }


def _tie_to_three_statement(scen: dict[str, dict[str, Any]], drivers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """DCF 预测行 vs 三表模型同情景输出的最大绝对偏差（百万元）。"""
    diff = max(abs(row[k] - drivers[name][k][i])
               for name, r in scen.items() for i, row in enumerate(r["forecast_rows"]) for k in TIE_KEYS)
    return {"items": TIE_KEYS, "max_abs_diff_mm": diff, "status": "pass" if diff <= 1e-6 else "fail"}


@tracing.traced("run_dcf")
def run_dcf(plan: dict[str, Any], current_price: float | None = None,
            three_statement_drivers: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    errors = dcf.validate_plan_structure(plan)
    if errors:
        return {"status": "blocked", "errors": errors}
    p = dcf.normalize_plan(plan)
    scen = {name: dcf.run_scenario(p, name) for name in dcf.SCENARIOS}
    sens = dcf.run_sensitivities(p)
    checks = dcf.compute_checks(p, scen, sens)
    tie = _tie_to_three_statement(scen, three_statement_drivers) if three_statement_drivers else None
    if tie:
        msg = f"DCF 预测与三表模型逐期核对（{'、'.join(TIE_KEYS)}），最大偏差 {tie['max_abs_diff_mm']:.2e} 百万元"
        (checks["informational"] if tie["status"] == "pass" else checks["hard_failures"]).append(msg)
    status = dcf.determine_model_status(p, checks.get("hard_failures", []), checks.get("warnings", []))

    summary = []
    for name, r in scen.items():
        vps = r["value_per_share"]
        summary.append({
            "scenario": name, "scenario_cn": SCEN_CN[name],
            "description": plan["scenarios"][name].get("description", ""),
            "wacc": r["discount_rate"], "terminal_growth": r["terminal"].get("terminal_growth_rate"),
            "enterprise_value_mm": r["enterprise_value"], "equity_value_mm": r["equity_value"],
            "value_per_share": vps, "tv_percent_ev": r["tv_percent_ev"],
            "implied_exit_ebitda": r["terminal"].get("implied_exit_ebitda_multiple"),
            "upside_vs_price": (vps / current_price - 1) if current_price and vps is not None else None,
        })
    vals = [s["value_per_share"] for s in summary if s["value_per_share"] is not None]
    return {
        "status": "ok",
        "model_status": status,
        "current_price": current_price,
        "value_range": {"low": min(vals), "base": scen["base"]["value_per_share"], "high": max(vals)} if vals else None,
        "scenarios": summary,
        "forecast_base": scen["base"]["forecast_rows"],
        "pv_base": scen["base"]["pv"],
        "bridge_base": scen["base"]["equity_bridge"],
        "wacc_base": scen["base"]["wacc"],
        "sensitivities": [_grid(sens["rows"], n) for n in SENS_NAMES],
        "sensitivity_directionality": sens.get("directionality"),
        "checks": {k: checks.get(k) for k in ("hard_failures", "warnings", "informational")},
        "three_statement_tie": tie,
        "historical_ratios": plan.get("_historical_ratios"),
    }
