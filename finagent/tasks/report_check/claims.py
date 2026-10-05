"""研报断言抽取：规则通道（中文数字模式）+ 模型会话拆出的断言（claims.json，经证据校验后合并）。

每条断言带原文引用与位置（页码/chunk/句序号），核查结论可定位到研报具体句子。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from ...core import tracing
from ...parsing.document import Document
from ..financials.schema import BY_ID, METRICS, claim_alias_list

NUM = r"(-?\d+(?:,\d{3})*(?:\.\d+)?)"
UNIT = r"(亿元|万元|千元|百万元|元/股|元|%|倍|个百分点|pct|pp)"
YOY_RE = re.compile(r"(?:同比|较上年|比上年|较去年同期)(增长|增加|上升|提升|提高|下降|减少|下滑|降低)?\s*" + NUM + r"\s*(%|个百分点|pct|pp)")
VAL_RE = re.compile(r"(?:为|达到?|实现|录得|至|约|共计|合计|是)?\s*" + NUM + r"\s*" + UNIT)
YEAR_RE = re.compile(r"(20\d{2})\s*(?:年|E|A)?(?:度)?(?:(第[一二三四]季度|[一二三四]季度|Q[1-4]|前三季度|上半年|H1))?")
FORECAST_HINTS = ("预计", "预测", "有望", "目标", "将达", "E ", "2025E", "2026E", "2027E", "指引")
DOWN_WORDS = ("下降", "减少", "下滑", "降低")
SENT_SPLIT = re.compile(r"(?<=[。；;！!？?\n])")

QUARTER_MAP = {"第一季度": "Q1", "一季度": "Q1", "第二季度": "Q2", "二季度": "Q2", "第三季度": "Q3",
               "三季度": "Q3", "第四季度": "Q4", "四季度": "Q4", "前三季度": "Q1-3", "上半年": "H1", "H1": "H1"}


@dataclass
class Claim:
    claim_id: str
    metric_id: str
    period: str
    claim_type: str  # level | yoy | ratio | pp_change
    raw_value: str
    value: float
    unit: str
    quote: str
    sentence: str
    location: dict[str, Any]
    is_forecast: bool = False
    method: str = "rule"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["metric_name"] = BY_ID[self.metric_id].name
        return d


def _period_of(prefix: str, default_year: int | None) -> str:
    years = list(YEAR_RE.finditer(prefix))
    if not years:
        return str(default_year) if default_year else ""
    m = years[-1]
    q = m.group(2)
    return m.group(1) + (QUARTER_MAP.get(q, q) if q else "")


def extract_rule(doc: Document, default_year: int | None) -> list[Claim]:
    aliases = claim_alias_list()
    claims: list[Claim] = []
    for ch in doc.texts():
        for si, sent in enumerate(s for s in SENT_SPLIT.split(ch.text) if s.strip()):
            # 找到句中所有指标提及（最长匹配、不重叠）
            spans: list[tuple[int, int, str]] = []
            taken = [False] * len(sent)
            for alias, mid in aliases:
                for m in re.finditer(re.escape(alias), sent):
                    if any(taken[m.start():m.end()]):
                        continue
                    spans.append((m.start(), m.end(), mid))
                    for i in range(m.start(), m.end()):
                        taken[i] = True
            spans.sort()
            is_fc = any(h in sent for h in FORECAST_HINTS)
            for k, (st, en, mid) in enumerate(spans):
                seg_end = spans[k + 1][0] if k + 1 < len(spans) else len(sent)
                seg = sent[en:seg_end]
                period = _period_of(sent[:en], default_year)
                loc = {"source": ch.source, "page": ch.page, "chunk_id": ch.chunk_id, "sentence_index": si}
                kind = BY_ID[mid].kind
                # 同比增速
                ym = YOY_RE.search(seg)
                # 绝对值 / 比率：取指标后第一个数字（在同比表述之前）
                vm = VAL_RE.search(seg[: ym.start()] if ym else seg)
                if vm and vm.group(2) not in ("个百分点", "pct", "pp"):
                    unit = vm.group(2)
                    between = seg[: vm.start()]
                    # “增加0.94亿元”是变动额而非本期值（“增长至/为…”仍是本期值），无法按水平值核对，不抽取
                    is_delta = not vm.group(0).lstrip().startswith(("为", "达", "至", "实现", "录得", "是")) \
                        and re.search(r"(增加|减少|增长|下降|提升|提高|降低|上升|下滑)了?\s*$", between)
                    if unit == "%":
                        # 金额类指标后的百分数：有增减字样视为增速，否则不是该指标的比率（如“占比”），不抽取
                        ctype = "ratio" if kind == "pct" else ("yoy" if re.search(r"增|降|减|升", between) else None)
                    else:
                        ctype = None if is_delta else "level"
                    if ctype and not (ctype == "level" and unit == "倍"):
                        claims.append(_mk(claims, mid, period, ctype, vm.group(1), unit,
                                          sent[st:en + vm.end()], sent, loc, is_fc))
                if ym:
                    val = ym.group(2)
                    unit = ym.group(3)
                    num = float(val.replace(",", ""))
                    if ym.group(1) in DOWN_WORDS:
                        num = -abs(num)
                    ctype = "pp_change" if unit in ("个百分点", "pct", "pp") else "yoy"
                    c = _mk(claims, mid, period, ctype, val, "%" if ctype == "yoy" else "pp",
                            sent[en + ym.start():en + ym.end()], sent, loc, is_fc)
                    c.value = num
                    claims.append(c)
    return claims


def _mk(claims: list[Claim], mid: str, period: str, ctype: str, raw: str, unit: str, quote: str,
        sent: str, loc: dict[str, Any], is_fc: bool) -> Claim:
    return Claim(f"C{len(claims) + 1:03d}", mid, period, ctype, raw, float(raw.replace(",", "")), unit,
                 quote.strip(), sent.strip(), loc, is_fc)


def merge_claims(rule: list[Claim], llm: list[Claim]) -> list[Claim]:
    """模型拆出的断言补充规则通道漏掉的部分（按 指标+期间+类型+数值 去重）。"""
    seen = {(c.metric_id, c.period, c.claim_type, round(c.value, 6)) for c in rule}
    merged = list(rule)
    for c in llm:
        key = (c.metric_id, c.period, c.claim_type, round(c.value, 6))
        if key not in seen:
            c.claim_id = f"C{len(merged) + 1:03d}"
            merged.append(c)
            seen.add(key)
    return merged


CLAIM_TYPES = ("level", "yoy", "ratio", "pp_change")


def ingest_claims(doc: Document, payload: dict[str, Any] | list[Any],
                  default_year: int | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """接入模型会话拆出的断言。引用须为原文连续片段且包含该数字，否则拒绝；与规则通道去重合并。"""
    items = payload.get("claims", []) if isinstance(payload, dict) else payload
    ext: list[Claim] = []
    rejected: list[dict[str, Any]] = []
    for i, it in enumerate(items or []):
        it = it if isinstance(it, dict) else {}
        quote, raw = str(it.get("quote", "")).strip(), str(it.get("value", "")).strip()
        ch = next((c for c in doc.chunks if quote and quote in c.text), None)
        reason = None
        if it.get("metric_id") not in BY_ID:
            reason = f"未知指标：{it.get('metric_id')}"
        elif it.get("claim_type", "level") not in CLAIM_TYPES:
            reason = f"断言类型不合法：{it.get('claim_type')}"
        elif ch is None:
            reason = "quote 不是研报原文中的连续片段"
        elif raw.lstrip("-").replace(",", "") not in quote.replace(",", ""):
            reason = f"数值 {raw} 不在 quote 中"
        else:
            try:
                val = float(raw.replace(",", ""))
            except ValueError:
                reason = f"数值无法解析：{raw}"
        if reason:
            rejected.append({"index": i, "item": it, "reason": reason})
            continue
        ext.append(Claim(f"L{len(ext) + 1:03d}", it["metric_id"], str(it.get("period") or default_year),
                         it.get("claim_type", "level"), raw.lstrip("-"), val, it.get("unit", ""), quote, quote,
                         {"source": ch.source, "page": ch.page, "chunk_id": ch.chunk_id},
                         bool(it.get("is_forecast")), "llm"))
    return [c.to_dict() for c in merge_claims(extract_rule(doc, default_year), ext)], rejected


@tracing.traced("extract_claims")
def extract_claims(doc: Document, *, default_year: int | None) -> list[dict[str, Any]]:
    """只用规则通道拆断言（没有 claims.json 时）。"""
    return [c.to_dict() for c in extract_rule(doc, default_year)]
