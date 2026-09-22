"""估值执行：调用确定性 DCF 引擎（dcf.py），输出三情景估值、敏感性矩阵与模型检查。"""

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


@tracing.traced("run_dcf")
def run_dcf(plan: dict[str, Any], current_price: float | None = None) -> dict[str, Any]:
    errors = dcf.validate_plan_structure(plan)
    if errors:
        return {"status": "blocked", "errors": errors}
    p = dcf.normalize_plan(plan)
    scen = {name: dcf.run_scenario(p, name) for name in dcf.SCENARIOS}
    sens = dcf.run_sensitivities(p)
    checks = dcf.compute_checks(p, scen, sens)
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
        "historical_ratios": plan.get("_historical_ratios"),
    }


def workbook_sheets(plan: dict[str, Any], result: dict[str, Any]) -> dict[str, list[list[Any]]]:
    """生成 xlsx 的各工作表（数值为计算结果，便于评审核对）。"""
    sheets: dict[str, list[list[Any]]] = {}
    sheets["估值汇总"] = [["情景", "WACC", "永续增长率", "企业价值(百万元)", "股权价值(百万元)", "每股价值(元)", "终值占EV", "较现价空间"]] + [
        [s["scenario_cn"], s["wacc"], s["terminal_growth"], s["enterprise_value_mm"], s["equity_value_mm"],
         s["value_per_share"], s["tv_percent_ev"], s["upside_vs_price"]] for s in result["scenarios"]]
    fr = result["forecast_base"]
    cols = ["period", "revenue", "revenue_growth", "ebit", "ebit_margin", "cash_taxes", "nopat", "da", "capex",
            "change_nwc", "unlevered_fcf"]
    sheets["基准情景预测"] = [cols] + [[r.get(c) for c in cols] for r in fr]
    sheets["历史数据"] = [["项目", "数值(百万元)"]] + [[k, v] for k, v in plan["historicals"].items() if k != "source_id"]
    sheets["股权桥"] = [["项目", "数值"]] + [[k, v] for k, v in plan["ev_to_equity_bridge"].items() if not k.endswith("source_id")]
    for g in result["sensitivities"]:
        rows = [[f"{g['x_axis']} \\ {g['y_axis']}"] + g["y_values"]]
        rows += [[x] + row for x, row in zip(g["x_values"], g["matrix"])]
        sheets[g["name"][:28]] = rows
    sheets["模型检查"] = [["类型", "内容"]] + [[k, m] for k in ("hard_failures", "warnings", "informational")
                                          for m in (result["checks"].get(k) or [])]
    return sheets
