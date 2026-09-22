"""财务分析：同比/环比、派生指标、勾稽校验、异常信号识别。全部为确定性计算，LLM 只用于文字解读。"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from ...core import tracing
from ...core.numbers import fmt_pct, fmt_yi, half_ulp, pct_change, safe_div
from ...parsing.document import Document
from .schema import BY_ID

KEY_METRICS = [
    "revenue", "operating_cost", "rd_expense", "operating_profit", "net_profit", "np_parent",
    "np_parent_deducted", "non_recurring", "ocf", "accounts_receivable", "inventory",
    "total_assets", "eps_basic",
]

CALIBER_KEYWORDS = ["会计政策变更", "会计估计变更", "追溯调整", "重述", "前期差错更正",
                    "同一控制下企业合并", "合并范围变更", "调整前", "调整后"]


@dataclass
class Signal:
    id: str
    type: str
    severity: str  # high / medium / low / info
    title: str
    fact: str
    inference: str
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FactTable:
    """(指标, 期间) → Fact 的只读视图，派生值也登记在这里并注明公式。"""

    def __init__(self, facts: list[dict[str, Any]]):
        self.cells: dict[tuple[str, str], dict[str, Any]] = {(f["metric_id"], f["period"]): f for f in facts}

    def v(self, metric: str, period: str) -> float | None:
        f = self.cells.get((metric, period))
        return None if f is None else f["value"]

    def src(self, metric: str, period: str) -> dict[str, Any] | None:
        f = self.cells.get((metric, period))
        if f is None:
            return None
        return {"metric": metric, "period": period, "raw": f.get("raw"), **(f.get("source") or {})}

    def add_derived(self, metric: str, period: str, value: float | None, formula: str,
                    inputs: list[tuple[str, str]]) -> None:
        if value is None or (metric, period) in self.cells:
            return
        self.cells[(metric, period)] = {
            "metric_id": metric, "period": period, "value": value, "raw": f"{value:.4f}",
            "unit": "%" if BY_ID.get(metric) and BY_ID[metric].kind == "pct" else "元",
            "method": "derived", "formula": formula,
            "source": {"derived_from": [self.src(m, p) for m, p in inputs]},
        }

    def periods(self) -> list[str]:
        return sorted({p for (_, p) in self.cells if p})


def prior_periods(period: str) -> tuple[str | None, str | None]:
    """返回 (同比基期, 环比基期)。"""
    m = re.fullmatch(r"(20\d{2})(.*)", period)
    if not m:
        return None, None
    year, suffix = int(m.group(1)), m.group(2)
    yoy = f"{year - 1}{suffix}"
    qoq = None
    qm = re.fullmatch(r"Q([1-4])", suffix)
    if qm:
        q = int(qm.group(1))
        qoq = f"{year}Q{q - 1}" if q > 1 else f"{year - 1}Q4"
    return yoy, qoq


def _derive(t: FactTable) -> None:
    for p in t.periods():
        rev, cost = t.v("revenue", p), t.v("operating_cost", p)
        if rev and cost is not None:
            t.add_derived("gross_margin", p, (rev - cost) / rev * 100, "(营业收入-营业成本)/营业收入",
                          [("revenue", p), ("operating_cost", p)])
        t.add_derived("net_margin", p, _pct(t.v("net_profit", p), rev), "净利润/营业收入",
                      [("net_profit", p), ("revenue", p)])
        t.add_derived("rd_ratio", p, _pct(t.v("rd_expense", p), rev), "研发费用/营业收入",
                      [("rd_expense", p), ("revenue", p)])
        t.add_derived("debt_ratio", p, _pct(t.v("total_liabilities", p), t.v("total_assets", p)),
                      "负债合计/资产总计", [("total_liabilities", p), ("total_assets", p)])
        t.add_derived("ocf_to_np", p, safe_div(t.v("ocf", p), t.v("np_parent", p)),
                      "经营活动现金流量净额/归母净利润", [("ocf", p), ("np_parent", p)])
        npp, ded = t.v("np_parent", p), t.v("np_parent_deducted", p)
        if npp is not None and ded is not None:
            t.add_derived("non_recurring", p, npp - ded, "归母净利润-扣非归母净利润",
                          [("np_parent", p), ("np_parent_deducted", p)])
        dep, amo = t.v("depreciation", p), t.v("amortization", p)
        if dep is not None:
            t.add_derived("da", p, dep + (amo or 0.0), "固定资产折旧+无形资产摊销",
                          [("depreciation", p), ("amortization", p)])


def _pct(a: float | None, b: float | None) -> float | None:
    r = safe_div(a, b)
    return None if r is None else r * 100


def _changes(t: FactTable, period: str) -> list[dict[str, Any]]:
    yoy_p, qoq_p = prior_periods(period)
    rows = []
    for mid in KEY_METRICS + ["gross_margin", "net_margin", "rd_ratio", "debt_ratio"]:
        cur = t.v(mid, period)
        if cur is None:
            continue
        kind = BY_ID[mid].kind
        prev = t.v(mid, yoy_p) if yoy_p else None
        prevq = t.v(mid, qoq_p) if qoq_p else None
        row = {"metric_id": mid, "metric": BY_ID[mid].name, "period": period, "value": cur, "kind": kind,
               "yoy_base_period": yoy_p, "yoy_base": prev, "qoq_base_period": qoq_p, "qoq_base": prevq}
        if kind == "pct":  # 比率类用百分点变动
            row["yoy_change_pp"] = None if prev is None else cur - prev
            row["qoq_change_pp"] = None if prevq is None else cur - prevq
        else:
            row["yoy_pct"] = pct_change(cur, prev)
            row["qoq_pct"] = pct_change(cur, prevq)
        rows.append(row)
    return rows


def _tieouts(t: FactTable, period: str) -> list[dict[str, Any]]:
    checks = []

    def chk(name: str, lhs: float | None, rhs: float | None, tol_rel: float, inputs: list[tuple[str, str]]) -> None:
        if lhs is None or rhs is None:
            checks.append({"check": name, "status": "not_assessable", "detail": "缺少输入数据"})
            return
        diff = lhs - rhs
        ok = abs(diff) <= max(abs(rhs) * tol_rel, 1.0)
        checks.append({"check": name, "status": "pass" if ok else "fail", "lhs": lhs, "rhs": rhs, "diff": diff,
                       "evidence": [t.src(m, p) for m, p in inputs]})

    p = period
    chk("资产总计 = 负债和所有者权益总计", t.v("total_assets", p), t.v("total_liab_equity", p), 1e-6,
        [("total_assets", p), ("total_liab_equity", p)])
    le = t.v("total_liabilities", p)
    te = t.v("total_equity", p)
    chk("负债和所有者权益总计 = 负债合计 + 所有者权益合计", t.v("total_liab_equity", p),
        None if le is None or te is None else le + te, 1e-6,
        [("total_liab_equity", p), ("total_liabilities", p), ("total_equity", p)])
    ep, mi = t.v("equity_parent", p), t.v("minority_equity", p)
    chk("所有者权益合计 = 归母权益 + 少数股东权益", te, None if ep is None or mi is None else ep + mi, 1e-6,
        [("total_equity", p), ("equity_parent", p), ("minority_equity", p)])
    rep = t.cells.get(("non_recurring", p))
    npp, ded = t.v("np_parent", p), t.v("np_parent_deducted", p)
    if rep is not None and rep.get("method") != "derived":
        chk("非经常性损益合计 = 归母净利润 - 扣非归母净利润", rep["value"],
            None if npp is None or ded is None else npp - ded, 1e-4,
            [("non_recurring", p), ("np_parent", p), ("np_parent_deducted", p)])
    # 财报列示的同比增减 vs 程序计算
    yoy_p, _ = prior_periods(p)
    for (mid, per), f in list(t.cells.items()):
        if not mid.endswith(".reported_yoy") or per != p:
            continue
        base = mid.split(".")[0]
        calc = pct_change(t.v(base, p), t.v(base, yoy_p)) if yoy_p else None
        if calc is None:
            continue
        tol = half_ulp(f["raw"]) + 0.01
        ok = abs(calc - f["value"]) <= tol
        checks.append({"check": f"{BY_ID[base].name} 财报列示同比 vs 计算同比", "status": "pass" if ok else "fail",
                       "lhs": f["value"], "rhs": round(calc, 4), "diff": f["value"] - calc,
                       "evidence": [t.src(mid, p), t.src(base, p), t.src(base, yoy_p)]})
    return checks


def _signals(t: FactTable, period: str, doc: Document | None, extract_issues: list[dict]) -> list[Signal]:
    s: list[Signal] = []
    yoy_p, _ = prior_periods(period)
    p = period
    g = lambda m, per=p: t.v(m, per)  # noqa: E731
    yoy = lambda m: pct_change(g(m), g(m, yoy_p)) if yoy_p else None  # noqa: E731

    # 1. 非经常性损益占比
    nr, npp = g("non_recurring"), g("np_parent")
    share = _pct(nr, npp)
    if share is not None and npp and npp > 0 and abs(share) >= 15:
        sev = "high" if abs(share) >= 30 else "medium"
        s.append(Signal("S1", "非经常性损益", sev, "利润对非经常性损益依赖度较高",
                        f"{p} 年非经常性损益 {fmt_yi(nr)}，占归母净利润 {fmt_pct(share)}；"
                        f"扣非归母净利润同比 {fmt_pct(yoy('np_parent_deducted'))}，归母净利润同比 {fmt_pct(yoy('np_parent'))}。",
                        "归母净利润增长中有相当部分来自非经常性项目，可持续性弱于表观增速，估值应以扣非口径为主。",
                        [t.src("non_recurring", p), t.src("np_parent", p)]))
    g_np, g_ded = yoy("np_parent"), yoy("np_parent_deducted")
    if g_np is not None and g_ded is not None and g_np - g_ded >= 10:
        s.append(Signal("S2", "利润质量", "medium", "归母净利润增速显著高于扣非增速",
                        f"归母净利润同比 {fmt_pct(g_np)}，扣非归母净利润同比 {fmt_pct(g_ded)}，差距 {g_np - g_ded:.2f} 个百分点。",
                        "表观利润增长部分由一次性收益驱动。",
                        [t.src("np_parent", p), t.src("np_parent_deducted", p)]))

    # 2. 利润与现金流背离
    ocf = g("ocf")
    ratio = safe_div(ocf, npp)
    if ratio is not None and npp and npp > 0:
        if ratio < 0.8:
            sev = "high" if ratio < 0.5 else "medium"
            s.append(Signal("S3", "利润与现金流背离", sev, "经营现金流显著低于净利润",
                            f"{p} 年经营活动现金流量净额 {fmt_yi(ocf)}，归母净利润 {fmt_yi(npp)}，净现比 {ratio:.2f}。",
                            "利润的现金含量偏低，需排查应收账款、存货占款或收入确认节奏。",
                            [t.src("ocf", p), t.src("np_parent", p)]))
        g_ocf = yoy("ocf")
        if g_np is not None and g_ocf is not None and g_np > 0 and g_ocf < 0:
            s.append(Signal("S4", "利润与现金流背离", "high", "净利润增长而经营现金流下降",
                            f"归母净利润同比 {fmt_pct(g_np)}，经营活动现金流量净额同比 {fmt_pct(g_ocf)}。",
                            "盈利增长未转化为现金，是财务质量的重要预警信号。",
                            [t.src("ocf", p), t.src("ocf", yoy_p), t.src("np_parent", p)]))

    # 3. 营运资本错配
    g_rev = yoy("revenue")
    for mid, sid, name in (("accounts_receivable", "S5", "应收账款"), ("inventory", "S6", "存货")):
        gx = yoy(mid)
        if g_rev is not None and gx is not None and gx - g_rev >= 15:
            sev = "high" if gx - g_rev >= 30 else "medium"
            s.append(Signal(sid, "营运资本", sev, f"{name}增速显著快于收入",
                            f"{name}同比 {fmt_pct(gx)}，营业收入同比 {fmt_pct(g_rev)}，差距 {gx - g_rev:.2f} 个百分点。",
                            f"{name}扩张快于收入，可能存在放宽信用政策、渠道压货或减值风险。",
                            [t.src(mid, p), t.src(mid, yoy_p), t.src("revenue", p)]))

    # 4. 毛利率大幅波动
    gm, gm0 = g("gross_margin"), g("gross_margin", yoy_p) if yoy_p else None
    if gm is not None and gm0 is not None and abs(gm - gm0) >= 3:
        s.append(Signal("S7", "盈利能力", "medium", "毛利率大幅变动",
                        f"毛利率 {fmt_pct(gm)}，上年同期 {fmt_pct(gm0)}，变动 {gm - gm0:+.2f} 个百分点。",
                        "需拆分产品结构、价格与成本因素。", [t.src("revenue", p), t.src("operating_cost", p)]))

    # 5. 会计口径变化（文本关键词 + 表格调整前/后）
    if doc is not None:
        hits = []
        for ch in doc.texts():
            kws = [k for k in CALIBER_KEYWORDS if k in ch.text]
            if kws:
                hits.append({"source": ch.source, "page": ch.page, "chunk_id": ch.chunk_id,
                             "keywords": kws, "quote": ch.text[:160]})
        for iss in extract_issues:
            if iss.get("type") == "追溯调整":
                hits += iss.get("evidence", [])
        if hits:
            s.append(Signal("S8", "会计口径", "medium", "存在会计政策/口径变化的披露",
                            f"在 {len(hits)} 处发现会计口径相关披露（关键词：" +
                            "、".join(sorted({k for h in hits for k in h.get('keywords', [])})) + "）。",
                            "同比比较需确认是否使用追溯调整后的可比数据。", hits[:5]))
    return s


@tracing.traced("analyze_financials")
def analyze(facts: list[dict[str, Any]], *, period: str | None = None, doc: Document | None = None,
            extract_issues: list[dict] | None = None) -> dict[str, Any]:
    t = FactTable(facts)
    _derive(t)
    if period is None:
        annual = [p for p in t.periods() if re.fullmatch(r"20\d{2}", p) and t.v("revenue", p) is not None]
        period = max(annual) if annual else max(t.periods())
    yoy_p, _ = prior_periods(period)
    if yoy_p:
        _derive(t)
    result = {
        "period": period,
        "changes": _changes(t, period),
        "tieouts": _tieouts(t, period),
        "signals": [x.to_dict() for x in _signals(t, period, doc, extract_issues or [])],
        "truth_table": [dict(v) for v in t.cells.values()],
    }
    result["summary"] = {
        "tieout_fail": sum(1 for c in result["tieouts"] if c["status"] == "fail"),
        "signals_high": sum(1 for x in result["signals"] if x["severity"] == "high"),
        "signals_total": len(result["signals"]),
    }
    return result
