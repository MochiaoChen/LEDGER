"""业绩深度分析（赛题2：业绩变化原因）。

1. 预期对比：实际值 vs 一致预期/内部预期（compute_beat_miss）
2. 业绩预告对比：预告区间中值 vs 一致预期（compute_guidance），并判断实际值落在预告区间的位置
3. EPS 质量筛查：失真关键词 + EPS 超预期幅度显著大于收入/营业利润超预期，中文输出
1～3 的判定规则与原 Public Equity Investing 插件 earnings-deep-dive 一致（对照见 tests/test_parity_reference.py），
自研实现、仅用标准库。
4. 利润变动归因桥（A 股口径，自研）：
   Δ归母净利润 = 收入规模效应 + 毛利率效应 − Δ销售费用 − Δ管理费用 − Δ研发费用 − Δ财务费用
                 + Δ其他经营损益 + Δ营业外收支 − Δ所得税 − Δ少数股东损益      （逐项可加总，严格闭合）
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...core import tracing
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
# EPS 失真关键词（在指标名、口径、调节来源、备注中出现即提示）
EPS_DISTORTION_TERMS = ("asset sale", "below-the-line", "equity investment", "fair value", "fx", "gain", "impairment",
                        "litigation", "loss", "mark-to-market", "non-operating", "non-recurring", "one-time",
                        "pension", "restructuring", "share count", "tax")


@dataclass
class BeatMissRow:
    metric: str
    period: str
    units: str
    reported: float | None
    consensus: float | None
    internal: float | None
    delta_cons: float | None
    surprise_cons: float | None
    delta_int: float | None
    surprise_int: float | None
    source_tag: str
    gaap_flag: str = ""
    comparable_gaap_metric: str = ""
    reconciliation_source_tag: str = ""
    notes: str = ""


@dataclass
class GuidanceRow:
    metric: str
    period: str
    units: str
    low: float | None
    high: float | None
    midpoint: float | None
    consensus: float | None
    internal: float | None
    delta_cons_mid: float | None
    delta_int_mid: float | None
    source_tag: str


def _missing(v: Any) -> bool:
    """None、NaN、空串、"MISSING" 视为缺失。"""
    if v is None:
        return True
    if isinstance(v, float):
        return v != v
    return isinstance(v, str) and v.strip().upper() in ("", "MISSING")


def _num(v: Any) -> float | None:
    if _missing(v):
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _delta(reported: float | None, expected: float | None) -> tuple[float | None, float | None]:
    """(差额, 超预期幅度)；预期为 0 时幅度为 None。"""
    if reported is None or expected is None:
        return None, None
    d = reported - expected
    return d, (None if expected == 0 else d / expected)


def _estimate(est: list[dict[str, Any]], metric: str, period: str, kind: str) -> float | None:
    """同一指标/期间/预期类型取第一条。"""
    r = next((e for e in est if e["MetricName"] == metric and e["Period"] == period and e["EstimateType"] == kind),
             None)
    return None if r is None else _num(r["Value"])


def _order(x: Any) -> int:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return 999


def compute_beat_miss(metrics: list[dict[str, Any]], est: list[dict[str, Any]]) -> list[BeatMissRow]:
    """IsTearSheet 标记的指标按 DisplayOrder 排序，逐项对比一致预期与内部预期。"""
    shown = [m for m in metrics if str(m["IsTearSheet"]).upper() in ("Y", "YES", "TRUE", "1")]
    rows = []
    for m in sorted(shown, key=lambda m: _order(m["DisplayOrder"])):
        reported = _num(m["Value"])
        cons = _estimate(est, m["MetricName"], m["Period"], "Consensus")
        internal = _estimate(est, m["MetricName"], m["Period"], "Internal")
        dc, sc = _delta(reported, cons)
        di, si = _delta(reported, internal)
        tag = m.get("SourceTag")
        rows.append(BeatMissRow(
            metric=m["MetricName"], period=m["Period"], units=m["Units"], reported=reported, consensus=cons,
            internal=internal, delta_cons=dc, surprise_cons=sc, delta_int=di, surprise_int=si,
            source_tag="source not provided" if _missing(tag) else str(tag),
            gaap_flag=str(m.get("GAAP_Flag") or ""), comparable_gaap_metric=str(m.get("ComparableGAAPMetricName") or ""),
            reconciliation_source_tag=str(m.get("ReconciliationSourceTag") or ""), notes=str(m.get("Notes") or "")))
    return rows


def compute_guidance(guidance: list[dict[str, Any]], est: list[dict[str, Any]]) -> list[GuidanceRow]:
    """预告区间中值 vs 一致预期/内部预期。"""
    rows = []
    for g in guidance:
        low, high = _num(g["Low"]), _num(g["High"])
        mid = (low + high) / 2.0 if low is not None and high is not None else None
        cons = _estimate(est, g["MetricName"], g["Period"], "Consensus")
        internal = _estimate(est, g["MetricName"], g["Period"], "Internal")
        tag = g.get("SourceTag")
        rows.append(GuidanceRow(
            metric=g["MetricName"], period=g["Period"], units=g["Units"], low=low, high=high, midpoint=mid,
            consensus=cons, internal=internal, delta_cons_mid=_delta(mid, cons)[0],
            delta_int_mid=_delta(mid, internal)[0], source_tag="source not provided" if _missing(tag) else str(tag)))
    return rows


def _first_row(rows: list[BeatMissRow], *needles: str, period: str = "") -> BeatMissRow | None:
    """指标名（不区分大小写）同时包含所有关键词的第一行。"""
    return next((r for r in rows if (not period or r.period == period)
                 and all(n.lower() in r.metric.lower() for n in needles)), None)


def _distortion_text(row: BeatMissRow) -> str:
    text = " ".join([row.metric, row.gaap_flag, row.comparable_gaap_metric, row.reconciliation_source_tag,
                     row.notes]).lower()
    return ", ".join(t for t in EPS_DISTORTION_TERMS if t in text)


def _surprise_gap_flag(eps: BeatMissRow, peer: BeatMissRow | None) -> bool:
    """EPS 超预期幅度 ≥ 15%，且大于同行指标幅度的 2 倍与（幅度 + 10 个百分点）中的较大者。"""
    if eps.surprise_cons is None or peer is None or peer.surprise_cons is None:
        return False
    e, p = abs(eps.surprise_cons), abs(peer.surprise_cons)
    return e >= 0.15 and e > max(p * 2.0, p + 0.10)


def _read_csv(path: str | Path | None) -> list[dict[str, str]]:
    if not path:
        return []
    raw = tracing.read_file(path).decode("utf-8-sig")
    return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(io.StringIO(raw))]


def _metrics(t: FactTable, p: str, nonrec_share: float | None) -> list[dict[str, Any]]:
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
    return rows


def _tag(src: dict[str, Any] | None) -> str:
    if not src:
        return "source not provided"
    if "formula" in src:
        return f"计算：{src['formula']}"
    return f"{Path(src.get('source', '')).name} p.{src.get('page')} {src.get('chunk_id', '')}"


def _estimates(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        m = METRIC_MAP.get(r.get("指标", ""))
        if not m:
            continue
        out.append({"MetricName": m[0], "Period": r.get("期间", ""), "EstimateType": TYPE_MAP.get(r.get("预期类型", ""), ""),
                    "Value": float(r["数值"]), "Units": r.get("单位", ""), "AsOf": r.get("截至日期", ""),
                    "Source": r.get("来源", ""), "Notes": ""})
    return out


def _guidance(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        m = METRIC_MAP.get(r.get("指标", ""))
        if not m:
            continue
        out.append({"MetricName": m[0], "Period": r.get("期间", ""), "Low": float(r["下限"]), "High": float(r["上限"]),
                    "Units": r.get("单位", ""), "GAAP_Flag": "GAAP", "Assumptions": "",
                    "SourceTag": f"{r.get('来源', '')}（{r.get('公告日期', '')}）", "Notes": ""})
    return out


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


def _eps_quality(rows: list[BeatMissRow]) -> list[dict[str, Any]]:
    """GAAP EPS 质量筛查：失真项 + 超预期幅度背离，输出结构化中文结果。"""
    out = []
    for eps in [r for r in rows if "eps" in r.metric.lower() and r.gaap_flag.lower() == "gaap"]:
        rev = _first_row(rows, "revenue", period=eps.period)
        op = _first_row(rows, "operating", period=eps.period)
        adj = _first_row(rows, "adjusted", "eps", period=eps.period)
        flags = []
        dist = _distortion_text(eps)
        if dist:
            flags.append("存在失真项：" + "、".join(DISTORTION_CN.get(x.strip(), x.strip()) for x in dist.split(",")))
        for peer, label in ((rev, "营业收入"), (op, "营业利润")):
            if _surprise_gap_flag(eps, peer):
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
    est = _estimates(est_rows)
    if not est_rows:
        result["limitations"].append("未提供一致预期数据（estimates），跳过超预期/不及预期分析")
    bm = compute_beat_miss(_metrics(t, period, nonrec_share), est)
    result["beat_miss"] = [{**r.__dict__, "metric_cn": EN2CN.get(r.metric, r.metric)} for r in bm]
    result["eps_quality"] = _eps_quality(bm)
    if guide_rows:
        actual = {r.metric: r.reported for r in bm}
        for g in compute_guidance(_guidance(guide_rows), est):
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
