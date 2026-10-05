"""财务数据抽取的规则通道（表格科目匹配）与双通道合并。

模型通道是分析师会话按页读 PDF 写下的 facts.json，由 external.ingest 做证据校验后与本模块的规则通道合并：
两条通道对同一指标给出不同数值时，不静默取舍，而是记录为 issue 交由人工复核。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from ...core import tracing
from ...core.numbers import UNIT_FACTORS, close, parse_number
from ...parsing.document import Chunk, Document
from .schema import BY_ID, METRICS, match_label


@dataclass
class Fact:
    metric_id: str
    period: str
    value: float  # 金额类为“元”；pct 为百分数值；per_share 为元/股；shares 为股
    raw: str
    unit: str
    source: dict[str, Any]
    label: str
    method: str  # rule_table | llm | rule+llm
    confidence: str = "high"
    corroborated_by: list[dict[str, Any]] = field(default_factory=list)

    @property
    def key(self) -> tuple[str, str]:
        return (self.metric_id, self.period)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        base, _, suffix = self.metric_id.partition(".")
        d["metric_name"] = BY_ID[base].name + ("（财报列示同比%）" if suffix == "reported_yoy" else "")
        return d


@dataclass
class Issue:
    severity: str  # high / medium / low
    type: str
    message: str
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ------------------------------------------------------------------ periods
_Q = [
    (("第一季度", "1-3月", "1—3月", "一季度"), "Q1"),
    (("第二季度", "4-6月", "4—6月", "二季度"), "Q2"),
    (("第三季度", "7-9月", "7—9月", "三季度"), "Q3"),
    (("第四季度", "10-12月", "10—12月", "四季度"), "Q4"),
    (("1-6月", "1—6月", "半年度", "6月30日"), "H1"),
    (("1-9月", "1—9月", "9月30日"), "Q1-3"),
    (("3月31日",), "Q1"),
]


def parse_period(cell: str, fiscal_year: int | None = None) -> str | None:
    """表头单元格 → 期间标识：'2024' / '2024H1' / '2024Q3' / '2024Q1-3'；变动列返回 'chg'。"""
    s = re.sub(r"\s", "", cell or "")  # 表头常被 PDF 折行（“增\n减”）
    if not s:
        return None
    if any(k in s for k in ("增减", "变动", "同比", "变化")):
        return "chg"
    if any(k in s for k in ("比例", "比重", "占")):  # “本期期末数占总资产的比例”等结构比列，不是期间数值
        return None
    if "调整前" in s:
        return "skip"
    m = re.search(r"(20\d{2})", s)
    year: int | None = int(m.group(1)) if m else None
    if year is None and fiscal_year:
        if any(k in s for k in ("本期", "本年", "期末", "本报告期")):
            year = fiscal_year
        elif any(k in s for k in ("上期", "上年", "期初", "上年同期")):
            year = fiscal_year - 1
        elif any(k in s for keys, suffix in _Q[:4] for k in keys):  # 年报“分季度主要财务指标”表头只写季度
            year = fiscal_year
    if year is None:
        return None
    for keys, suffix in _Q:
        if any(k in s for k in keys):
            return f"{year}{suffix}"
    return str(year)


def _header(rows: list[list[str]], fiscal_year: int | None) -> tuple[int, list[str | None]] | None:
    for i, row in enumerate(rows[:3]):
        periods = [parse_period(c, fiscal_year) for c in row]
        if any(p not in (None, "chg", "skip") for p in periods[1:]):
            return i, periods
    return None


# ------------------------------------------------------------------ rule channel
# 规则通道只从这些表取数：主要会计数据、分季度数据、非经常性损益、三大报表及补充资料。
# 真实年报附注里大量明细表（受限资产、费用明细、关联方往来等）行名与报表科目同名但口径不同，混入会造成冲突。
SOURCE_CAPTIONS = ("主要会计数据", "主要财务指标", "分季度", "非经常性损益", "资产负债表", "利润表",
                   "现金流量表", "补充资料")


def _is_source_table(ch: Chunk) -> bool:
    if "母公司" in ch.caption:  # 只取合并报表；母公司报表科目同名，混入会造成错取
        return False
    if any("关联方" in c for c in ch.rows[0]):  # 关联方往来表：行名是科目，列是关联方
        return False
    return not ch.caption or any(k in ch.caption for k in SOURCE_CAPTIONS)


def extract_rule(doc: Document, fiscal_year: int | None = None) -> tuple[list[Fact], list[Issue]]:
    facts: list[Fact] = []
    issues: list[Issue] = []
    for ch in doc.tables():
        hdr = _header(ch.rows, fiscal_year)
        start = hdr[0] + 1 if hdr else 0
        if hdr is None and ch.header_rows:  # 跨页续表：本页无表头，沿用首页表头的期间列，从第一行起都是数据
            hdr = _header(ch.header_rows, fiscal_year)
        if hdr is None:
            continue
        periods = hdr[1]
        if "skip" in periods:
            issues.append(Issue("medium", "追溯调整",
                                "表格同时列示“调整前/调整后”数据，存在会计政策变更或追溯重述，同比口径需使用调整后数据。",
                                [_loc(ch)]))
        if not _is_source_table(ch):
            continue
        unit = ch.unit_hint or "元"
        # 同表既有“营业总收入”又有“营业收入”时（含金融子公司利息收入等），营业收入口径取后者
        has_op_rev = any(row and "营业收入" in row[0] and "营业总收入" not in row[0] for row in ch.rows)
        for r, row in enumerate(ch.rows[start:], start):
            if not row:
                continue
            metric_id = match_label(row[0], ch.caption)
            if not metric_id:
                continue
            if metric_id == "revenue" and has_op_rev and "营业总收入" in row[0]:
                continue
            if "收益以" in row[0]:  # 现金流量表补充资料的调节项（“财务费用（收益以“－”号填列）”），不是报表科目本身
                continue
            metric = BY_ID[metric_id]
            for c, period in enumerate(periods):
                if c == 0 or period in (None, "chg", "skip") or c >= len(row):
                    continue
                v = parse_number(row[c])
                if v is None:
                    continue
                facts.append(Fact(
                    metric_id=metric_id,
                    period=period,
                    value=_scale(v, metric.kind, unit),
                    raw=row[c],
                    unit=_unit_label(metric.kind, unit),
                    source=_loc(ch, row=r, col=c),
                    label=row[0],
                    method="rule_table",
                ))
            # 财报自带的“本年比上年增减”列，保留下来用于交叉核验
            for c, period in enumerate(periods):
                if period == "chg" and c < len(row) and parse_number(row[c]) is not None:
                    facts.append(Fact(metric_id + ".reported_yoy", _latest(periods), parse_number(row[c]),
                                      row[c], "%", _loc(ch, row=r, col=c), row[0], "rule_table"))
    return facts, issues


def _latest(periods: list[str | None]) -> str:
    valid = [p for p in periods if p and p not in ("chg", "skip")]
    return max(valid) if valid else ""


def _scale(v: float, kind: str, unit: str) -> float:
    if kind == "amount":
        return v * UNIT_FACTORS.get(unit, 1.0)
    return v


def _unit_label(kind: str, unit: str) -> str:
    return {"amount": unit, "per_share": "元/股", "pct": "%", "shares": "股"}.get(kind, unit)


def _loc(ch: Chunk, **extra: Any) -> dict[str, Any]:
    loc = {"source": ch.source, "page": ch.page, "chunk_id": ch.chunk_id, "caption": ch.caption, **extra}
    if ch.continued_from:
        loc["continued_from"] = ch.continued_from
    return loc


# ------------------------------------------------------------------ merge
def merge(rule_facts: list[Fact], llm_facts: list[Fact], prefer: str = "rule") -> tuple[list[Fact], list[Issue]]:
    """prefer：两通道不一致时暂时保留哪一方（流水线里为模型读原文的结果 "llm"）。不论保留哪方都记 issue，阻断估值。"""
    merged: dict[tuple[str, str], Fact] = {}
    issues: list[Issue] = []
    for f in rule_facts:
        if f.key not in merged:
            merged[f.key] = f
            continue
        base = merged[f.key]
        if close(base.value, f.value, rel=1e-6, abs_=0.01):
            base.corroborated_by.append(f.source)
        else:
            issues.append(Issue("high", "同一指标多处取值不一致",
                                f"{BY_ID.get(f.metric_id.split('.')[0]).name} {f.period}：{base.raw} vs {f.raw}",
                                [base.source, f.source]))
    for f in llm_facts:
        base = merged.get(f.key)
        if base is None:
            merged[f.key] = f
        elif close(base.value, f.value, rel=1e-6, abs_=0.01):
            base.method = "rule+llm"
            base.corroborated_by.append(f.source)
        else:
            kept = "规则" if prefer == "rule" else "LLM"
            issues.append(Issue("medium", "规则与LLM抽取不一致",
                                f"{BY_ID[f.metric_id].name} {f.period}：规则={base.raw}，LLM={f.raw}（保留{kept}结果）",
                                [base.source, f.source]))
            if prefer == "llm":
                merged[f.key] = f
    return list(merged.values()), issues


@tracing.traced("extract_financials")
def extract_financials(doc: Document, *, fiscal_year: int | None) -> dict[str, Any]:
    """只用规则通道抽取（没有模型抽取文件时，如样例回归与引擎测试）。"""
    rule_facts, issues = extract_rule(doc, fiscal_year)
    facts, merge_issues = merge(rule_facts, [])
    issues += merge_issues
    return {
        "facts": [f.to_dict() for f in sorted(facts, key=lambda x: (x.metric_id, x.period))],
        "issues": [i.to_dict() for i in issues],
        "stats": {"rule_facts": len(rule_facts), "llm_facts": 0, "merged": len(facts)},
    }
