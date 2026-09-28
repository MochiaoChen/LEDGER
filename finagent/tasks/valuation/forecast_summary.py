"""盈利预测与市场数据摘要（研报首页“盈利预测与估值”表的数据来源）。

实际年度取财报真值表；预测年度取三表模型基准情景。归母净利润预测 = 三表净利润 ×（最近实际年度归母/净利润），
即假设少数股东损益占比不变（口径简化，写入 notes）。EPS 按最近期末总股本摊薄，P/E、P/B、总市值按参考股价计算。
金额单位：元；比率存百分数值（91.18 表示 91.18%）；倍数为倍。
"""

from __future__ import annotations

from typing import Any

from ...core.numbers import pct_change, safe_div
from ..financials.analyze import FactTable
from .build_plan import EBIT_PARTS


def _pct(a: float | None, b: float | None) -> float | None:
    r = safe_div(a, b)
    return None if r is None else r * 100


# 评级规则（默认）：基准情景 DCF 每股价值相对参考股价的空间，下限含本数；假设文件 rating_rule 可覆盖
RATING_RULE = [(0.20, "买入"), (0.05, "增持"), (-0.05, "中性"), (-0.20, "减持"), (float("-inf"), "卖出")]


def rating(upside: float | None, rule: list[list[Any]] | None = None) -> dict[str, Any] | None:
    if upside is None:
        return None
    tiers = [(float(x), str(n)) for x, n in rule] if rule else RATING_RULE
    name = next(n for x, n in sorted(tiers, reverse=True) if upside >= x)
    desc = "；".join(f"{n}：{'≥' + format(x, '.0%') if x != float('-inf') else '其余'}" for x, n in sorted(tiers, reverse=True))
    return {"rating": name, "upside": upside, "basis": "基准情景 DCF 每股价值相对参考股价的空间", "rule": desc}


def build(truth_table: list[dict[str, Any]], period: str, three_statement: dict[str, Any] | None,
          assumptions: dict[str, Any], valuation: dict[str, Any] | None = None) -> dict[str, Any]:
    t = FactTable(truth_table)
    y = int(period[:4])
    price = assumptions.get("current_price")
    shares = t.v("total_shares", period)
    notes: list[str] = []

    rows: list[dict[str, Any]] = []
    for yy in (y - 1, y):
        p, pp = str(yy), str(yy - 1)
        rev, npp, eps = t.v("revenue", p), t.v("np_parent", p), t.v("eps_basic", p)
        cogs = t.v("operating_cost", p)
        parts = [t.v(m, p) for m, _ in EBIT_PARTS]
        ebit = sum(sign * (v or 0.0) for (_, sign), v in zip(EBIT_PARTS, parts)) if parts[0] is not None else None
        rows.append({
            "cogs": cogs, "gross_profit": rev - cogs if rev is not None and cogs is not None else None,
            "ebit": ebit, "net_profit": t.v("net_profit", p),
            "year": f"{yy}A", "revenue": rev, "revenue_growth": pct_change(rev, t.v("revenue", pp)),
            "np_parent": npp, "np_parent_growth": pct_change(npp, t.v("np_parent", pp)),
            "eps": eps, "pe": safe_div(price, eps), "gross_margin": t.v("gross_margin", p),
            "net_margin_parent": _pct(npp, rev), "roe": t.v("roe_weighted", p),
        })

    parent_share = safe_div(t.v("np_parent", period), t.v("net_profit", period))
    stmt = ((three_statement or {}).get("statements") or {}).get("利润表")
    if stmt and parent_share is not None and shares:
        notes.append(f"预测期归母净利润 = 三表模型净利润 × {parent_share:.4f}（{period} 年归母净利润/净利润，假设少数股东损益占比不变）")
        notes.append(f"预测期 EPS 按 {period} 年末总股本摊薄，未考虑回购注销对股本的影响")
        by = {r["key"]: r["values"] for r in stmt["rows"]}
        prev_rev, prev_np = rows[-1]["revenue"], rows[-1]["np_parent"]
        for i, per in enumerate(stmt["periods"]):
            rev = by["revenue"][i] * 1e6
            npp = by["net_income"][i] * 1e6 * parent_share
            eps = npp / shares
            rows.append({
                "cogs": by["cogs"][i] * 1e6, "gross_profit": by["gross_profit"][i] * 1e6, "ebit": by["ebit"][i] * 1e6,
                "net_profit": by["net_income"][i] * 1e6,
                "year": f"{per[2:]}E", "revenue": rev, "revenue_growth": pct_change(rev, prev_rev),
                "np_parent": npp, "np_parent_growth": pct_change(npp, prev_np), "eps": eps,
                "pe": safe_div(price, eps), "gross_margin": _pct(rev - by["cogs"][i] * 1e6, rev),
                "net_margin_parent": _pct(npp, rev), "roe": None,
            })
            prev_rev, prev_np = rev, npp
    elif stmt:
        notes.append("缺少归母净利润或总股本，未生成预测期 EPS")

    equity = t.v("equity_parent", period)
    bvps = safe_div(equity, shares)
    market = {
        "price": price, "price_date": assumptions.get("valuation_date"),
        "price_source": assumptions.get("price_source", "估值假设文件 current_price"),
        "total_shares": shares, "market_cap": price * shares if price and shares else None,
        "bvps": bvps, "pb": safe_div(price, bvps), "pe_latest": safe_div(price, t.v("eps_basic", period)),
        "equity_parent": equity, "total_assets": t.v("total_assets", period),
        "debt_ratio": t.v("debt_ratio", period),
    }
    base = next((x for x in (valuation or {}).get("scenarios", []) if x.get("scenario") == "base"), None)
    rt = rating(base.get("upside_vs_price") if base else None, assumptions.get("rating_rule"))
    return {"period": period, "scenario": "base", "market": market, "years": rows, "notes": notes, "rating": rt}
