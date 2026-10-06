"""模型抽取结果接入（分析师会话读 PDF 写下的 facts.json）：逐字证据校验后与规则通道合并。

外部模型交来的每条数字都要过确定性校验后才进入真值表：
  1. 指标、期间、数值格式合法；只接受合并报表口径（母公司报表直接拒绝）；
  2. 证据校验：原文数字必须在其声明的页码文本中逐字出现（按数字边界匹配），并定位到具体 chunk；
  3. 与规则通道交叉比对：一致记为 rule+llm；不一致不静默取舍，记 issue（保留外部模型结果）；
  4. 核心指标缺失与勾稽失败一并报告，供模型回到原文修正。

多份报告（年报 + 季报）：主文件之外的一季报/半年报/三季报作为补充文件传入（--supplement），
抽取条目用 source_file 指明出处，证据在该文件中核对。规则通道只跑主文件：季报表头多写“本报告期/年初至报告期末”，
规则通道无法可靠区分单季与累计，混入会污染年度数据。单季拆分（Q4 = 全年 − 前三季度等）由 analyze 完成。
"""

from __future__ import annotations

import re
import os
from pathlib import Path
from typing import Any

from ...core.numbers import UNIT_FACTORS, close, parse_number
from ...parsing.document import Chunk, Document
from .extract import Fact, Issue, _scale, _unit_label, extract_rule, merge
from .schema import BY_ID, METRICS

PERIOD_RE = re.compile(r"^20\d{2}(H1|Q[1-4]|Q1-3)?$")
# 下游估值/核查依赖的核心指标：本期缺失视为阻断，上期缺失视为警示
CORE_METRICS = ["revenue", "operating_cost", "operating_profit", "total_profit", "net_profit", "np_parent",
                "np_parent_deducted", "total_assets", "total_liabilities", "total_equity", "cash", "ocf", "capex",
                "eps_basic"]
EXTRACTOR = os.getenv("FINAGENT_EXTRACTOR", "claude-code-skill")


def metric_catalog() -> list[dict[str, str]]:
    """可抽取指标清单（派生指标由程序计算，不需要抽取）。"""
    return [{"metric_id": m.id, "name": m.name, "statement": m.statement, "kind": m.kind,
             "aliases": list(m.aliases)} for m in METRICS if m.statement != "derived"]


def _num_pattern(raw: str) -> re.Pattern[str] | None:
    """原文数字的匹配模式：去掉千分位、括号、百分号后按数字边界匹配。"""
    core = raw.strip().replace(" ", "").replace("，", ",").replace(",", "").strip("()").rstrip("%")
    core = core.replace("−", "-").replace("–", "-").lstrip("-")
    if not re.fullmatch(r"\d+(?:\.\d+)?", core):
        return None
    # 右边界同时排除“小数点 + 数字”：原文 3,884.59 不能被 3884 命中（句末句号仍允许）
    return re.compile(r"(?<![\d.])" + re.escape(core) + r"(?!\.?\d)")


def _norm(text: str) -> str:
    # Keep cell/word whitespace: deleting it can concatenate adjacent table
    # numbers ("235 3884.59" -> "2353884.59") and falsely reject both.
    return text.replace(",", "").replace("，", "")


def find_evidence(doc: Document, page: int, raw: str) -> Chunk | None:
    """在指定页的 chunk 中找到包含该数字的第一个 chunk（表格优先）。"""
    pat = _num_pattern(raw)
    if pat is None:
        return None
    on_page = [c for c in doc.chunks if c.page == page]
    for ch in sorted(on_page, key=lambda c: c.kind != "table"):
        if pat.search(_norm(ch.text)):
            return ch
    return None


def _pick_doc(item: dict[str, Any], doc: Document, supplements: dict[str, Document]) -> Document | str:
    """按 source_file 找到条目所在文件；未写时视为主文件。按文件名匹配（不要求路径一致）。"""
    name = Path(str(item.get("source_file") or "")).name
    if not name or name == Path(doc.source).name:
        return doc
    if name in supplements:
        return supplements[name]
    return f"{item.get('metric_id')} {item.get('period')} 的 source_file={name!r} 未作为主文件或补充文件（--supplement）传入"


def _to_fact(item: dict[str, Any], doc: Document) -> Fact | str:
    mid = item.get("metric_id")
    if mid not in BY_ID or BY_ID[mid].statement == "derived":
        return f"未知或不需抽取的指标：{mid}"
    period = str(item.get("period", "")).strip()
    if not PERIOD_RE.match(period):
        return f"{mid} 期间格式不合法：{period!r}（应为 2024 / 2024H1 / 2024Q3 / 2024Q1-3）"
    scope = str(item.get("scope", "consolidated")).strip().lower()
    if scope not in ("consolidated", "合并"):
        return f"{mid} {period} 取自非合并报表（scope={scope}），只接受合并报表口径"
    raw = str(item.get("raw_value", "")).strip()
    v = parse_number(raw)
    if v is None:
        return f"{mid} {period} 数值无法解析：{raw!r}"
    try:
        page = int(item.get("page"))
    except (TypeError, ValueError):
        return f"{mid} {period} 缺少页码"
    ch = find_evidence(doc, page, raw)
    if ch is None:
        return f"{mid} {period}={raw} 未在第 {page} 页原文中找到"
    metric = BY_ID[mid]
    unit = str(item.get("unit") or ch.unit_hint or "元").strip()
    if metric.kind == "amount" and unit not in UNIT_FACTORS:
        return f"{mid} {period} 单位不合法：{unit!r}"
    hint = ch.unit_hint
    if metric.kind == "amount" and hint in UNIT_FACTORS and UNIT_FACTORS[unit] != UNIT_FACTORS[hint]:
        # 证据校验只核对数字本身；单位以页面声明为准，模型写的单位与之不符时不静默取舍
        return f"{mid} {period}={raw} 声明单位 {unit} 与第 {page} 页的单位声明 {hint} 不一致"
    value = _scale(v, metric.kind, unit)
    if metric.kind == "shares":
        value = v * UNIT_FACTORS.get(unit, 1.0)
    source = {"source": ch.source, "page": ch.page, "chunk_id": ch.chunk_id, "caption": ch.caption,
              "table": item.get("table", ""), "extractor": EXTRACTOR}
    return Fact(mid, period, value, raw, _unit_label(metric.kind, unit), source,
                str(item.get("label") or metric.name), "llm", confidence="medium")


def ingest(doc: Document, payload: dict[str, Any] | list[Any], *, fiscal_year: int | None,
           supplements: list[Document] | None = None) -> dict[str, Any]:
    """校验外部抽取结果并与规则通道合并；返回结构与 extract_financials 一致，另附 rejected / missing。
    supplements：补充文件（季报等），条目以 source_file 指向其中之一。"""
    items = payload.get("facts", []) if isinstance(payload, dict) else payload
    extra = {Path(d.source).name: d for d in supplements or []}
    accepted: list[Fact] = []
    rejected: list[dict[str, Any]] = []
    issues: list[Issue] = []
    seen: dict[tuple[str, str], Fact] = {}
    for i, item in enumerate(items or []):
        item = item if isinstance(item, dict) else {}
        src = _pick_doc(item, doc, extra)
        f = src if isinstance(src, str) else _to_fact(item, src)
        if isinstance(f, str):
            rejected.append({"index": i, "item": item, "reason": f})
            continue
        prev = seen.get(f.key)
        if prev is None:
            seen[f.key] = f
            accepted.append(f)
        elif close(prev.value, f.value, rel=1e-6, abs_=0.01):
            prev.corroborated_by.append(f.source)
        else:
            issues.append(Issue("high", "同一指标多处取值不一致",
                                f"{BY_ID[f.metric_id].name} {f.period}：{prev.raw}（第{prev.source['page']}页）"
                                f" vs {f.raw}（第{f.source['page']}页）", [prev.source, f.source]))
    rule_facts, rule_issues = extract_rule(doc, fiscal_year)
    facts, merge_issues = merge(rule_facts, accepted, prefer="llm")
    issues += rule_issues + merge_issues
    if rejected:
        issues.append(Issue("medium", "外部抽取结果未通过校验", f"{len(rejected)} 条被拒绝，详见 rejected",
                            []))
    have = {(f.metric_id, f.period) for f in facts}
    years = sorted({f.period for f in facts if re.fullmatch(r"20\d{2}", f.period)})
    cur = str(fiscal_year) if fiscal_year else (years[-1] if years else "")
    prev_year = str(int(cur) - 1) if cur else ""
    missing = [{"metric_id": m, "name": BY_ID[m].name, "period": p, "blocking": p == cur}
               for p in (cur, prev_year) if p for m in CORE_METRICS if (m, p) not in have]
    return {
        "facts": [f.to_dict() for f in sorted(facts, key=lambda x: (x.metric_id, x.period))],
        "issues": [x.to_dict() for x in issues],
        "stats": {"rule_facts": len(rule_facts), "llm_facts": len(accepted), "merged": len(facts),
                  "rejected": len(rejected), "extractor": EXTRACTOR,
                  "supplements": sorted(extra)},
        "rejected": rejected,
        "missing": missing,
    }
