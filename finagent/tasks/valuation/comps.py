"""可比公司估值（相对估值）。

计算规则依据原插件 comps-valuation/references（valuation-readthrough.md、comps-framework.md、peer-selection.md）：
  - 股权价值 = 股价 × 股本；EV = 股权价值 + 有息负债 + 少数股东权益 − 现金 − 非经营性资产
  - EV 倍数配 EV 口径分母（收入/EBITDA/EBIT），P/E 配归母净利润；分母 ≤ 0 记 NM
  - 统计：中位数优先；P25/P75 作为估值区间；IQR 法（Q1 − 1.5×IQR, Q3 + 1.5×IQR）标记离群值但不删除数据
  - 仅核心同业（Core）驱动估值区间；次要同业（Secondary）仅作参照；Excluded 列示剔除理由
另外：若安装了 XlsxWriter，调用原插件 create_comps_template.create_workbook 生成带公式的 Excel comps 表。

同业 CSV 列名与原插件模板一致：ticker, company, peer_tier, price, basic_shares, debt, minority_interest, cash,
other_non_op_assets, revenue_ltm, ebitda_ltm, ebit_ltm, net_income_ltm, eps_cy1, market_data_date, source_name,
inclusion_rationale, exclusion_rationale, confidence（金额单位：百万元；股本：百万股；股价：元）
"""

from __future__ import annotations

import csv
import io
import statistics
from pathlib import Path
from typing import Any

from ...core import tracing
from ..financials.analyze import FactTable

MM = 1e6
MULTIPLES = [
    ("ev_revenue", "EV/营业收入", "ev", "revenue_ltm"),
    ("ev_ebitda", "EV/EBITDA", "ev", "ebitda_ltm"),
    ("ev_ebit", "EV/EBIT", "ev", "ebit_ltm"),
    ("pe_ltm", "P/E（LTM）", "equity_value", "net_income_ltm"),
]
PRIMARY = ["ev_ebitda", "pe_ltm"]


def _f(x: Any) -> float | None:
    try:
        return float(str(x).replace(",", "")) if str(x).strip() not in ("", "None") else None
    except ValueError:
        return None


def load_peers(path: str | Path) -> list[dict[str, Any]]:
    raw = tracing.read_file(path).decode("utf-8-sig")
    return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(io.StringIO(raw))]


def target_row(facts: list[dict[str, Any]], period: str, plan: dict[str, Any], company: str,
               assumptions: dict[str, Any]) -> dict[str, Any]:
    t = FactTable(facts)
    y = period[:4]
    b = plan["ev_to_equity_bridge"]
    h = plan["historicals"]
    return {
        "ticker": assumptions.get("ticker", "TARGET"), "company": company, "peer_tier": "Target",
        "price": assumptions.get("current_price"), "basic_shares": b["diluted_shares"],
        "debt": b["debt"] + b.get("leases", 0.0), "minority_interest": b.get("minorities", 0.0), "cash": b["cash"],
        "other_non_op_assets": b.get("non_operating_assets", 0.0),
        "revenue_ltm": h["revenue"], "ebitda_ltm": h["ebitda"], "ebit_ltm": h["ebit"],
        "net_income_ltm": (t.v("np_parent", y) or 0.0) / MM,
        "market_data_date": assumptions.get("valuation_date"), "source_name": "财报抽取 + 估值假设文件",
        "confidence": "high",
    }


def _metrics(row: dict[str, Any]) -> dict[str, Any]:
    price, sh = _f(row.get("price")), _f(row.get("basic_shares"))
    eq = price * sh if price is not None and sh is not None else None
    ev = None
    if eq is not None:
        ev = (eq + (_f(row.get("debt")) or 0) + (_f(row.get("minority_interest")) or 0)
              - (_f(row.get("cash")) or 0) - (_f(row.get("other_non_op_assets")) or 0))
    out = {"equity_value": eq, "ev": ev}
    for key, _, num, den in MULTIPLES:
        n, d = out[num], _f(row.get(den))
        out[key] = None if n is None or d is None else ("NM" if d <= 0 else n / d)
    eps1 = _f(row.get("eps_cy1"))
    out["pe_ntm"] = None if price is None or eps1 is None else ("NM" if eps1 <= 0 else price / eps1)
    return out


def _quantiles(vals: list[float]) -> dict[str, float | None]:
    if not vals:
        return {"n": 0, "median": None, "mean": None, "p25": None, "p75": None, "low_fence": None, "high_fence": None}
    if len(vals) == 1:
        q1 = q3 = vals[0]
    else:
        q1, _, q3 = statistics.quantiles(vals, n=4, method="inclusive")  # 与 Excel PERCENTILE.INC 一致
    iqr = q3 - q1
    return {"n": len(vals), "median": statistics.median(vals), "mean": statistics.fmean(vals), "p25": q1, "p75": q3,
            "low_fence": q1 - 1.5 * iqr, "high_fence": q3 + 1.5 * iqr}


@tracing.traced("run_comps")
def run(peers: list[dict[str, Any]], target: dict[str, Any], dcf_range: dict[str, float] | None = None) -> dict[str, Any]:
    rows = []
    for r in [target] + peers:
        tier = (r.get("peer_tier") or "Core").strip()
        rows.append({**r, "peer_tier": tier, **_metrics(r)})
    tgt = rows[0]
    stats: dict[str, dict[str, Any]] = {}
    for key, name, _, _ in MULTIPLES + [("pe_ntm", "P/E（NTM）", "", "")]:
        core = [r[key] for r in rows[1:] if r["peer_tier"] == "Core" and isinstance(r[key], float)]
        allp = [r[key] for r in rows[1:] if r["peer_tier"] in ("Core", "Secondary") and isinstance(r[key], float)]
        qc = _quantiles(core)
        outliers = [r["ticker"] for r in rows[1:] if r["peer_tier"] == "Core" and isinstance(r[key], float)
                    and qc["n"] >= 4 and not (qc["low_fence"] <= r[key] <= qc["high_fence"])]
        core_clean = [v for r, v in ((r, r[key]) for r in rows[1:]) if r["peer_tier"] == "Core"
                      and isinstance(v, float) and r["ticker"] not in outliers]
        stats[key] = {"name": name, "core": qc, "core_ex_outliers": _quantiles(core_clean),
                      "all_peers": _quantiles(allp), "outliers": outliers,
                      "target": tgt.get(key),
                      "premium_vs_core_median": (tgt[key] / qc["median"] - 1)
                      if isinstance(tgt.get(key), float) and qc["median"] else None}

    # 隐含股价：核心同业（剔除离群值）P25 / 中位数 / P75 × 目标公司分母
    implied = []
    sh = _f(target["basic_shares"])
    bridge = (_f(target.get("debt")) or 0) + (_f(target.get("minority_interest")) or 0) \
        - (_f(target.get("cash")) or 0) - (_f(target.get("other_non_op_assets")) or 0)
    for key in PRIMARY:
        q = stats[key]["core_ex_outliers"]
        den = _f(target["ebitda_ltm"] if key == "ev_ebitda" else target["net_income_ltm"])
        row = {"multiple": stats[key]["name"], "denominator_mm": den, "n_core": q["n"]}
        for lvl in ("p25", "median", "p75"):
            m = q[lvl]
            if m is None or den is None or den <= 0 or not sh:
                row[lvl] = None
                continue
            equity = m * den - bridge if key.startswith("ev_") else m * den
            row[lvl] = equity / sh
        implied.append(row)
    lows = [r["p25"] for r in implied if r["p25"] is not None]
    highs = [r["p75"] for r in implied if r["p75"] is not None]
    mids = [r["median"] for r in implied if r["median"] is not None]
    comps_range = {"low": min(lows), "mid": statistics.median(mids), "high": max(highs)} if lows else None
    cross = None
    if comps_range and dcf_range:
        overlap = min(comps_range["high"], dcf_range["high"]) - max(comps_range["low"], dcf_range["low"])
        cross = {"dcf_base": dcf_range["base"], "comps_mid": comps_range["mid"],
                 "dcf_vs_comps_mid": dcf_range["base"] / comps_range["mid"] - 1, "ranges_overlap": overlap > 0}
    core_n = sum(1 for r in rows[1:] if r["peer_tier"] == "Core")
    status = "screen-grade" if core_n < 4 else "senior-review-ready"
    return {"rows": rows, "stats": stats, "implied": implied, "range": comps_range, "dcf_cross_check": cross,
            "status": status, "core_peer_count": core_n,
            "excluded": [{"ticker": r["ticker"], "company": r["company"], "reason": r.get("exclusion_rationale", "")}
                         for r in rows if r["peer_tier"] == "Excluded"]}


def write_formula_workbook(path: Path, target: dict[str, Any], peers: list[dict[str, Any]],
                           currency: str, valuation_date: str) -> dict[str, Any] | None:
    """若安装 XlsxWriter，用原插件模板脚本生成带公式的 comps Excel；否则跳过。"""
    try:
        import xlsxwriter  # noqa: F401
    except ImportError:
        tracing.log("comps_formula_workbook_skipped", reason="XlsxWriter 未安装")
        return None
    from ...vendor import load
    mod = load("comps-valuation", "create_comps_template")
    rows = [{k.lower(): ("" if v is None else str(v)) for k, v in r.items()} for r in [target] + peers]
    return mod.create_workbook(path, target["company"], str(target["ticker"]), currency, valuation_date, rows)
