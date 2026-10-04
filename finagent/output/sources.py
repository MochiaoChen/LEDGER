"""外部资料登记（research/sources.json）：联网检索得到的事实必须登记在这里，正文才能引用。

模型容易用记忆里的行业数据、排名和事件“补全”研报。规则是：年报之外的事实只能来自本文件，
每条来源有检索词、网址、发布与访问日期和原文摘句；数字必须出现在摘句里（与 LLM 抽取的
“数字须在原文 chunk 中找到”同一原则）。guard 把这里的数字当作出处，并要求引用它们的句子带 [S编号]。

格式：
{
  "questions": [{"id": "Q1", "question": "全球油轮运力供给增速", "status": "found|not_found",
                 "queries": ["2025 全球油轮 运力 增速", "..."], "sources": ["S1"]}],
  "sources": [{"id": "S1", "title": "...", "publisher": "...", "url": "https://...",
               "published": "2026-01-15", "accessed": "2026-10-02",
               "facts": [{"quote": "原文摘句（≤ 120 字）", "value": 2.1, "unit": "%", "label": "2026 年油轮运力增速"}]}]
}
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

from .guard import _numbers

DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
MARK = re.compile(r"\[(S\d+)\]")


def _digits(x: float) -> list[str]:
    """数值可能的原文写法：整数、去尾零的小数、千分位。"""
    s = f"{x:.6f}".rstrip("0").rstrip(".")
    out = {s, s.replace("-", "")}
    if abs(x) >= 1000:
        out.add(f"{abs(x):,.6f}".rstrip("0").rstrip("."))
    return sorted(out)


def verify_sources(data: dict[str, Any]) -> dict[str, Any]:
    """结构与可追溯性检查。返回 {ok, problems, n_sources, n_facts, n_queries}。"""
    problems: list[str] = []
    sources = data.get("sources") or []
    ids = [s.get("id") for s in sources]
    if len(set(ids)) != len(ids):
        problems.append("来源 id 重复")
    n_facts = 0
    for s in sources:
        sid = s.get("id") or "?"
        if not re.fullmatch(r"S\d+", str(sid)):
            problems.append(f"{sid}: id 须为 S + 数字")
        if not str(s.get("url", "")).startswith(("http://", "https://")):
            problems.append(f"{sid}: 缺网址（只接受实际打开过的网页）")
        for k in ("title", "publisher"):
            if not s.get(k):
                problems.append(f"{sid}: 缺 {k}")
        if not DATE.match(str(s.get("accessed", ""))):
            problems.append(f"{sid}: accessed 须为访问日期 YYYY-MM-DD")
        if s.get("published") and not DATE.match(str(s["published"])):
            problems.append(f"{sid}: published 格式应为 YYYY-MM-DD 或 YYYY-MM")
        for i, f in enumerate(s.get("facts") or []):
            n_facts += 1
            q = str(f.get("quote", ""))
            if not q:
                problems.append(f"{sid} 第 {i + 1} 条：缺原文摘句")
            elif len(q) > 160:
                problems.append(f"{sid} 第 {i + 1} 条：摘句超过 160 字，只摘支撑数字的一句")
            v = f.get("value")
            if v is not None:
                plain = q.replace(",", "").replace("，", "")
                if not any(d.replace(",", "") in plain for d in _digits(float(v))):
                    problems.append(f"{sid} 第 {i + 1} 条：数值 {v} 不在摘句里（数字须原样出现在来源原文中）")
    questions = data.get("questions") or []
    known = set(ids)
    n_queries = 0
    if not questions:
        problems.append("缺 questions：先在 framework.md 列外部调研清单，再逐题检索")
    for q in questions:
        qid = q.get("id") or "?"
        n_queries += len(q.get("queries") or [])
        if not q.get("queries"):
            problems.append(f"{qid}: 没有检索记录（每个问题都要实际搜索，不能凭记忆作答）")
        if q.get("status") not in ("found", "not_found"):
            problems.append(f"{qid}: status 须为 found 或 not_found")
        if q.get("status") == "found" and not q.get("sources"):
            problems.append(f"{qid}: 标为 found 但没有关联来源")
        for sid in q.get("sources") or []:
            if sid not in known:
                problems.append(f"{qid}: 引用了不存在的来源 {sid}")
    return {"ok": not problems, "problems": problems, "n_sources": len(sources), "n_facts": n_facts,
            "n_queries": n_queries, "n_questions": len(questions)}


def load(path: str | Path | None) -> dict[str, Any]:
    if not path or not Path(path).is_file():
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def fact_values(data: dict[str, Any]) -> dict[str, list[float]]:
    """{来源 id: [数值（基本单位）]}，单位换算与 guard 一致（亿 / 万）。"""
    out: dict[str, list[float]] = {}
    for s in data.get("sources") or []:
        vals: list[float] = []
        for f in s.get("facts") or []:
            if f.get("value") is not None:
                _numbers(f"{f['value']}{f.get('unit', '')}", vals)
        out[s["id"]] = vals
    return out


def check_citations(text: str, data: dict[str, Any], truth: list[float], check_text) -> list[dict[str, Any]]:
    """只能从外部来源找到出处的数字，所在句子必须带对应来源的 [S编号]；引用的编号必须存在。"""
    by_id = fact_values(data)
    problems: list[dict[str, Any]] = []
    for sent in re.split(r"(?<=[。！？\n])", text):
        cited = MARK.findall(sent)
        for sid in cited:
            if sid not in by_id:
                problems.append({"sentence": sent.strip()[:120], "problem": f"引用了不存在的来源 {sid}"})
        plain = MARK.sub("", sent)
        external_only = check_text(plain, truth)  # 年报与运行产物里找不到出处的数字
        if not external_only:
            continue
        allowed = [v for sid in cited for v in by_id.get(sid, [])]
        still = check_text(plain, truth + allowed) if allowed else external_only
        for raw in external_only:
            if raw in still and any(raw not in check_text(plain, truth + vs) for vs in by_id.values()):
                problems.append({"sentence": sent.strip()[:120],
                                 "problem": f"{raw} 来自外部资料，句中须标注对应的 [S编号]"})
    return problems


def run_guard(run: Path, text: str, sources: str | Path | None = None) -> dict[str, Any]:
    """完整的解读护栏（guard 命令与评测共用）：数字出处、指标期间绑定、外部数字的 [S编号]。只返回结果，不落盘。"""
    from .guard import check_binding, check_text, truth_values

    plain = MARK.sub("", text)
    truth = truth_values(run)
    ext = load(sources)
    external = [v for vs in fact_values(ext).values() for v in vs]
    unverified = check_text(plain, truth + external)
    mismatched = check_binding(plain, run)
    citations = check_citations(text, ext, truth, check_text) if ext else []
    contradictions = _contradictions(run, plain)
    return {"ok": not (unverified or mismatched or citations or contradictions),
            "unverified_numbers": unverified, "mismatched_claims": mismatched, "uncited_external": citations,
            "contradictions": contradictions}


def _contradictions(run: Path, text: str) -> list[str]:
    """文稿内部前后矛盾：评级、各情景每股价值、预测年度的公司整体收入与利润（report_check/consistency.py）。"""
    from ..tasks.report_check.consistency import check, describe

    a = run / "financials" / "analysis.json"
    if not a.is_file():
        return []
    year = int(str(json.loads(a.read_text(encoding="utf-8"))["period"])[:4])
    return [describe(f) for f in check(text, year)["findings"]]


# 资料搜集阶段（先搜集、后分析）必须覆盖的方面：每个公司都适用的通用类别，不预设行业内容
CATEGORIES = {
    "latest": "年报（或招股书）之后的最新定期报告、业绩预告、经营数据",
    "market": "最新股价、市值与近期走势",
    "consensus": "卖方一致预期、评级与目标价",
    "peers": "可比公司及其估值倍数",
    "industry": "行业规模、增速、价格与景气指标",
    "competition": "竞争格局、份额与主要对手动态",
    "events": "近三个月公司重大事件、公告与新闻",
}


def _date(s: Any) -> date | None:
    m = re.match(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$", str(s or ""))
    return date(int(m[1]), int(m[2]), int(m[3] or 1)) if m else None


def coverage(data: dict[str, Any], as_of: str | None = None, recent_days: int = 90) -> dict[str, Any]:
    """资料搜集的覆盖与时效。questions 的 phase 为 collect（资料搜集）或 followup（框架之后的补充调研，缺省视为此类）。
    每个类别至少一个 collect 问题：found，或 not_found 但换过两个以上检索词。时效按 as_of 往前 recent_days 天计。"""
    qs = data.get("questions") or []
    collect = [q for q in qs if q.get("phase") == "collect"]
    covered = {q.get("category") for q in collect
               if q.get("status") == "found" or (q.get("status") == "not_found" and len(q.get("queries") or []) >= 2)}
    ref = _date(as_of) or date.today()
    recent = [s["id"] for s in data.get("sources") or []
              if (d := _date(s.get("published"))) and 0 <= (ref - d).days <= recent_days]
    return {"missing": [c for c in CATEGORIES if c not in covered],
            "unknown": sorted({str(q.get("category")) for q in collect} - set(CATEGORIES)),
            "n_collect": len(collect), "n_collect_queries": sum(len(q.get("queries") or []) for q in collect),
            "n_followup": sum(q.get("phase") != "collect" for q in qs), "recent": recent}
