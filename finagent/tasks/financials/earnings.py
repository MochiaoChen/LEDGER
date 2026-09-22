"""业绩深度分析（赛题2：业绩变化原因）。

1. 预期对比：实际值 vs 一致预期/内部预期 —— 调用原插件 earnings-deep-dive/run_plan.compute_beat_miss
2. 业绩预告对比：预告区间中值 vs 一致预期 —— 调用 run_plan.compute_guidance；并判断实际值落在预告区间的位置
3. EPS 质量筛查：沿用 run_plan 的规则（失真关键词 + EPS 超预期幅度显著大于收入/营业利润超预期），中文输出
4. 利润变动归因桥（A 股口径，自研）：
   Δ归母净利润 = 收入规模效应 + 毛利率效应 − Δ销售费用 − Δ管理费用 − Δ研发费用 − Δ财务费用
                 + Δ其他经营损益 + Δ营业外收支 − Δ所得税 − Δ少数股东损益      （逐项可加总，严格闭合）
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from ...core import tracing
from ...vendor import load
from .analyze import FactTable, prior_periods

MM = 1e6
# 中文指标 → (原插件 MetricName, 我们的 metric_id, 单位换算)
METRIC_MAP = {
    "营业收入": ("Revenue", "revenue"),
    "营业利润": ("Operating Income", "operating_profit"),
    "归母净利润": ("Net Income Attributable", "np_parent"),
    "扣非归母净利润": ("Adjusted Net Income Attributable", "np_parent_deducted"),
    "基本每股收益": ("GAAP EPS (Diluted)", "eps_basic"),
    "扣非每股收益": ("Adjusted EPS", None),
}
EN2CN = {v[0]: k for k, v in METRIC_MAP.items()}
TYPE_MAP = {"一致预期": "Consensus", "内部预期": "Internal"}
DISTORTION_CN = {"non-recurring": "非经常性损益", "gain": "一次性收益", "fair value": "公允价值变动",
                 "impairment": "减值", "asset sale": "资产处置", "tax": "税率", "one-time": "一次性项目"}


def _engine():
    return load("earnings-deep-dive", "run_plan")


def _read_csv(path: str | Path | None) -> list[dict[str, str]]:
    if not path:
        return []
    raw = tracing.read_file(path).decode("utf-8-sig")
    return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(io.StringIO(raw))]


def _metrics_df(t: FactTable, p: str, nonrec_share: float | None):
    import pandas as pd

    shares = t.v("total_shares", p)
    ded = t.v("np_parent_deducted", p)
    rows = []
    for order, (cn, (en, mid)) in enumerate(METRIC_MAP.items(), 1):
        if mid:
            v = t.v(mid, p)
            src = t.src(mid, p)
        else:
            v = ded / shares if ded is not None and shares else None
            src = {"formula": "扣非归母净利润/总股本"}
        if v is None:
            continue
        per_share = cn.endswith("每股收益")
        notes = ""
        if en == "GAAP EPS (Diluted)" and nonrec_share is not None and nonrec_share >= 15:
            notes = f"non-recurring gain: 非经常性损益占归母净利润 {nonrec_share:.1f}%"
        rows.append({"MetricName": en, "Period": p, "Value": v if per_share else v / MM,
                     "Units": "元/股" if per_share else "百万元",
                     "GAAP_Flag": "Non-GAAP" if "Adjusted" in en else "GAAP", "Segment": "Total",
                     "IsTearSheet": "Y", "DisplayOrder": order, "SourceTag": _tag(src),
                     "ComparableGAAPMetricName": "GAAP EPS (Diluted)" if en == "Adjusted EPS" else "",
                     "ReconciliationSourceTag": "", "Notes": notes})
    return pd.DataFrame(rows)


def _tag(src: dict[str, Any] | None) -> str:
    if not src:
        return "source not provided"
    if "formula" in src:
        return f"计算：{src['formula']}"
    return f"{Path(src.get('source', '')).name} p.{src.get('page')} {src.get('chunk_id', '')}"


def _estimates_df(rows: list[dict[str, str]]):
    import pandas as pd

    out = []
    for r in rows:
        m = METRIC_MAP.get(r.get("指标", ""))
        if not m:
            continue
        out.append({"MetricName": m[0], "Period": r.get("期间", ""), "EstimateType": TYPE_MAP.get(r.get("预期类型", ""), ""),
                    "Value": float(r["数值"]), "Units": r.get("单位", ""), "AsOf": r.get("截至日期", ""),
                    "Source": r.get("来源", ""), "Notes": ""})
    return pd.DataFrame(out, columns=["MetricName", "Period", "EstimateType", "Value", "Units", "AsOf", "Source", "Notes"])


def _guidance_df(rows: list[dict[str, str]]):
    import pandas as pd

    out = []
    for r in rows:
        m = METRIC_MAP.get(r.get("指标", ""))
        if not m:
            continue
        out.append({"MetricName": m[0], "Period": r.get("期间", ""), "Low": float(r["下限"]), "High": float(r["上限"]),
                    "Units": r.get("单位", ""), "GAAP_Flag": "GAAP", "Assumptions": "",
                    "SourceTag": f"{r.get('来源', '')}（{r.get('公告日期', '')}）", "Notes": ""})
    return pd.DataFrame(out, columns=["MetricName", "Period", "Low", "High", "Units", "GAAP_Flag", "Assumptions",
                                      "SourceTag", "Notes"])


def profit_bridge(t: FactTable, p: str) -> dict[str, Any] | None:
    p0, _ = prior_periods(p)
    need = ["revenue", "operating_cost", "selling_expense", "admin_expense", "rd_expense", "finance_expense",
            "operating_profit", "total_profit", "income_tax", "net_profit", "np_parent"]
    cur = {m: t.v(m, p) for m in need}
    pre = {m: t.v(m, p0) for m in need} if p0 else {}
    if p0 is None or any(v is None for v in list(cur.values()) + list(pre.values())):
        return None

    def parts(d: dict[str, float]) -> dict[str, float]:
        gp = d["revenue"] - d["operating_cost"]
        exp = d["selling_expense"] + d["admin_expense"] + d["rd_expense"] + d["finance_expense"]
        return {"gp": gp, "gm": gp / d["revenue"], "other_op": d["operating_profit"] - (gp - exp),
                "non_op": d["total_profit"] - d["operating_profit"], "minority": d["net_profit"] - d["np_parent"]}

    a, b = parts(pre), parts(cur)
    items = [
        ("收入规模效应", (cur["revenue"] - pre["revenue"]) * a["gm"], "Δ营业收入 × 上年毛利率"),
        ("毛利率效应", cur["revenue"] * (b["gm"] - a["gm"]), "本年营业收入 × Δ毛利率"),
        ("销售费用", -(cur["selling_expense"] - pre["selling_expense"]), "−Δ销售费用"),
        ("管理费用", -(cur["admin_expense"] - pre["admin_expense"]), "−Δ管理费用"),
        ("研发费用", -(cur["rd_expense"] - pre["rd_expense"]), "−Δ研发费用"),
        ("财务费用", -(cur["finance_expense"] - pre["finance_expense"]), "−Δ财务费用"),
        ("其他经营损益", b["other_op"] - a["other_op"], "Δ(营业利润 − 毛利 + 四项费用)：含税金及附加、投资收益、公允价值变动、减值、其他收益"),
        ("营业外收支", b["non_op"] - a["non_op"], "Δ(利润总额 − 营业利润)"),
        ("所得税", -(cur["income_tax"] - pre["income_tax"]), "−Δ所得税费用"),
        ("少数股东损益", -(b["minority"] - a["minority"]), "−Δ(净利润 − 归母净利润)"),
    ]
    delta = cur["np_parent"] - pre["np_parent"]
    total = sum(v for _, v, _ in items)
    rows = [{"item": n, "value": v, "share_of_change": v / delta if delta else None, "formula": f} for n, v, f in items]
    nr0, nr1 = t.v("non_recurring", p0), t.v("non_recurring", p)
    return {
        "period": p, "base_period": p0, "np_parent_start": pre["np_parent"], "np_parent_end": cur["np_parent"],
        "delta": delta, "items": rows, "closure_error": total - delta,
        "non_recurring_delta": None if nr0 is None or nr1 is None else nr1 - nr0,
        "non_recurring_share_of_delta": None if nr0 is None or nr1 is None or not delta else (nr1 - nr0) / delta,
        "drivers_ranked": [r["item"] for r in sorted(rows, key=lambda r: -abs(r["value"]))][:3],
    }


def _eps_quality(eng, rows: list[Any]) -> list[dict[str, Any]]:
    """沿用原插件 render_eps_quality_screen 的判定规则，输出结构化中文结果。"""
    out = []
    for eps in [r for r in rows if "eps" in r.metric.lower() and r.gaap_flag.lower() == "gaap"]:
        rev = eng._first_row(rows, "revenue", period=eps.period)
        op = eng._first_row(rows, "operating", period=eps.period)
        adj = eng._first_row(rows, "adjusted", "eps", period=eps.period)
        flags = []
        dist = eng._distortion_text(eps)
        if dist:
            flags.append("存在失真项：" + "、".join(DISTORTION_CN.get(x.strip(), x.strip()) for x in dist.split(",")))
        for peer, label in ((rev, "营业收入"), (op, "营业利润")):
            if eng._surprise_gap_flag(eps, peer, label):
                flags.append(f"EPS 超预期幅度显著大于{label}超预期幅度")
        out.append({
            "period": eps.period, "eps": eps.reported, "adjusted_eps": adj.reported if adj else None,
            "status": "需展开 EPS 质量拆解" if flags else "未触发 EPS 质量预警",
            "flags": flags,
            "read_through": ("不应将全部 EPS 超预期视为可持续，需先剥离：" + "；".join(flags)) if flags
            else "未发现显著失真项，仍需与财报附注核对。",
        })
    return out


@tracing.traced("earnings_deep_dive")
def run(facts: list[dict[str, Any]], period: str, *, estimates_path: str | None = None,
        guidance_path: str | None = None, nonrec_share: float | None = None) -> dict[str, Any]:
    t = FactTable(facts)
    bridge = profit_bridge(t, period)
    result: dict[str, Any] = {"period": period, "profit_bridge": bridge, "beat_miss": [], "guidance": [],
                              "eps_quality": [], "limitations": []}
    est_rows, guide_rows = _read_csv(estimates_path), _read_csv(guidance_path)
    try:
        eng = _engine()
    except ImportError as exc:  # pandas 未安装
        result["limitations"].append(f"预期对比需要 pandas：{exc}")
        return result
    metrics = _metrics_df(t, period, nonrec_share)
    est = _estimates_df(est_rows)
    if not est_rows:
        result["limitations"].append("未提供一致预期数据（estimates），跳过超预期/不及预期分析")
    bm = eng.compute_beat_miss(metrics, est)
    result["beat_miss"] = [{**r.__dict__, "metric_cn": EN2CN.get(r.metric, r.metric)} for r in bm]
    result["eps_quality"] = _eps_quality(eng, bm)
    if guide_rows:
        actual = {r.metric: r.reported for r in bm}
        for g in eng.compute_guidance(_guidance_df(guide_rows), est):
            act = actual.get(g.metric)
            pos = None
            if act is not None and g.low is not None and g.high is not None:
                pos = ("高于预告上限" if act > g.high else "低于预告下限" if act < g.low else
                       ("预告区间上半部" if act >= g.midpoint else "预告区间下半部"))
            result["guidance"].append({**g.__dict__, "metric_cn": EN2CN.get(g.metric, g.metric), "actual": act,
                                       "actual_vs_mid": None if act is None or not g.midpoint else act / g.midpoint - 1,
                                       "position": pos})
    else:
        result["limitations"].append("未提供业绩预告（guidance），跳过预告对比")
    return result
