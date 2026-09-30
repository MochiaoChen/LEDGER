"""分部驱动的经营预测：产品（销量 × 吨价）→ 收入与毛利率，费用率分项 → 经营费用率，结果喂给三表模型。

基期取经营数据（financials/extras.json，逐格核对原文）与真值表：
  分部收入 R、营业成本 C、销量 V（吨）→ 吨价 P = R / V，毛利率 = 1 − C / R；
  其他业务收入与成本 = 营业收入 / 营业成本 − 主营分部合计，预测期保持不变（金额很小）。
预测：V_t = V_{t−1} ×（1 + 销量增速），P_t = P_{t−1} ×（1 + 吨价增速），分部毛利率逐年加变动（百分点）；
  综合毛利率 = 1 −（Σ 分部成本 + 其他成本）/ 营业收入；
  经营费用率（三表口径，不含折旧摊销）= 税金及附加率 + 销售费用率 + 管理费用率 + 研发费用率 + 其他（基期轧差，保持不变）。
所有计算由程序完成；假设文件只写增速、变动与费用率（观点/假设）。单位：金额百万元，吨价万元/吨，比率存小数。
"""

from __future__ import annotations

from typing import Any

from ..financials.analyze import FactTable
from .build_plan import EBIT_PARTS

SCENARIOS = ("base", "downside", "upside")
MM = 1e6


def _extras_row(extras: dict[str, Any], table: str, row: str) -> dict[str, float | None]:
    t = next(t for t in extras["tables"] if t["id"] == table)
    r = next(r for r in t["rows"] if r["label"] == row)
    return {c["name"]: v for c, v in zip(t["columns"], r["values"])}


def _vec(x: Any, n: int) -> list[float]:
    return [float(v) for v in x] if isinstance(x, list) else [float(x or 0.0)] * n


def build(spec: dict[str, Any], extras: dict[str, Any], truth_table: list[dict[str, Any]], period: str,
          n: int) -> dict[str, Any]:
    t = FactTable(truth_table)
    y = int(period[:4])
    v = lambda m: (t.v(m, period) or 0.0) / MM  # noqa: E731
    rev, cogs = v("revenue"), v("operating_cost")
    ebit = sum(sign * v(m) for m, sign in EBIT_PARTS)
    da = v("depreciation") + v("amortization")
    opex = rev - cogs - ebit - da  # 与三表模型历史口径相同
    base_segs = []
    for s in spec["segments"]:
        p = _extras_row(extras, "product", s["product_row"])
        vol = _extras_row(extras, "volume", s.get("volume_row", s["product_row"]))["销量"]
        r, c = p["营业收入"] / MM, p["营业成本"] / MM
        base_segs.append({"id": s["id"], "name": s["name"], "revenue": r, "cogs": c, "volume": vol,
                          "price": r / vol * 100, "gross_margin": 1 - c / r})  # 百万元/吨 × 100 = 万元/吨
    other_rev = rev - sum(s["revenue"] for s in base_segs)
    other_cogs = cogs - sum(s["cogs"] for s in base_segs)
    hist_ratio = {"tax_surcharge": v("tax_surcharge") / rev, "selling": v("selling_expense") / rev,
                  "admin": v("admin_expense") / rev, "rd": v("rd_expense") / rev}
    hist_ratio["other"] = opex / rev - sum(hist_ratio.values())
    years = [f"FY{y + i + 1}" for i in range(n)]

    out: dict[str, Any] = {"period": period, "years": years, "units": "金额百万元；吨价万元/吨；比率为小数",
                           "base_year": {"revenue": rev, "cogs": cogs, "other_revenue": other_rev,
                                         "other_cogs": other_cogs, "segments": base_segs,
                                         "gross_margin": 1 - cogs / rev, "opex_pct": opex / rev,
                                         "expense_ratios": hist_ratio},
                           "scenarios": {}}
    for key in ("volume_unit", "price_label", "price_unit"):  # 可选：销量单位与单价名称（缺省为吨 / 吨价 / 万元/吨），只影响工作簿表头
        if spec.get(key):
            out[key] = spec[key]
    for k in SCENARIOS:
        segs = []
        tot_rev = [other_rev] * n
        tot_cogs = [other_cogs] * n
        for s, b in zip(spec["segments"], base_segs):
            a = s["scenarios"][k]
            vg, pg = _vec(a["volume_growth"], n), _vec(a["price_growth"], n)
            gmc = _vec(a.get("gm_change_pp", 0.0), n)
            vol, price, gm = b["volume"], b["price"], b["gross_margin"]
            rows = {"volume": [], "volume_growth": vg, "price": [], "price_growth": pg, "revenue": [],
                    "gross_margin": [], "gm_change_pp": gmc, "cogs": []}
            for i in range(n):
                vol *= 1 + vg[i]
                price *= 1 + pg[i]
                gm += gmc[i] / 100
                r = vol * price / 100
                rows["volume"].append(vol)
                rows["price"].append(price)
                rows["revenue"].append(r)
                rows["gross_margin"].append(gm)
                rows["cogs"].append(r * (1 - gm))
                tot_rev[i] += r
                tot_cogs[i] += r * (1 - gm)
            segs.append({"id": s["id"], "name": s["name"], **rows})
        prev = [rev] + tot_rev[:-1]
        ratios = {}
        for key in ("tax_surcharge", "selling", "admin", "rd", "other"):
            src = (spec.get("expense_ratios") or {}).get(key)
            src = src.get(k, src.get("base")) if isinstance(src, dict) else src
            ratios[key] = _vec(src, n) if src is not None else [hist_ratio[key]] * n
        out["scenarios"][k] = {
            "segments": segs, "revenue": tot_rev,
            "revenue_growth": [r / p - 1 for r, p in zip(tot_rev, prev)],
            "gross_margin": [1 - c / r for c, r in zip(tot_cogs, tot_rev)],
            "expense_ratios": ratios,
            "opex_pct": [sum(ratios[key][i] for key in ratios) for i in range(n)],
        }
    return out


def apply(assumptions: dict[str, Any], seg: dict[str, Any]) -> None:
    """把分部预测结果写入假设（收入增速、各情景毛利率与经营费用率），三表模型与 DCF 由此驱动。"""
    for k in SCENARIOS:
        assumptions["scenarios"][k]["revenue_growth"] = seg["scenarios"][k]["revenue_growth"]
    ts = assumptions.setdefault("three_statement", {})
    ts["gross_margin_by_scenario"] = {k: seg["scenarios"][k]["gross_margin"] for k in SCENARIOS}
    ts["opex_pct_by_scenario"] = {k: seg["scenarios"][k]["opex_pct"] for k in SCENARIOS}
