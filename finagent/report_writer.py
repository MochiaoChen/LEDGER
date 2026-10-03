"""Focused DeepSeek first-draft writer from one verified company run.

This only writes prose. It cannot waive guard/review gates or change valuations.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .core.config import get_settings
from .core.llm import LLMClient
from .report_evidence import annual_excerpts, compact_tables, compact_truth, qualitative_only
from .report_pipeline import _narrative_quality
from .report_review import apply_replacements
from .output.guard import check_binding, check_text, truth_values

PARTS = ("title", "subtitle", "summary", "thesis", "overview", "performance", "business",
         "profitability", "balance", "cashflow", "forecast", "valuation", "recommendation", "risks")


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def compose_sections(raw: Any) -> str:
    if not isinstance(raw, dict) or set(raw) != set(PARTS):
        raise ValueError("研报草稿必须包含固定的 14 个章节字段")
    for key in PARTS:
        if not isinstance(raw[key], str) or not raw[key].strip():
            raise ValueError(f"章节 {key} 为空或不是文本")
        if "<!-- section:" in raw[key] or "<script" in raw[key].lower():
            raise ValueError(f"章节 {key} 含模板控制标记或 HTML")
    if len(raw["summary"]) < 350 or sum(len(raw[k]) for k in PARTS[3:]) < 5500:
        raise ValueError("研报草稿过短，缺少足够的业务与预测论证")
    return "\n\n".join(f"<!-- section: {key} -->\n{raw[key].strip()}" for key in PARTS) + "\n"


def polish_style(client: LLMClient, body: str, check_path: Path) -> str:
    """Small bounded prose-only repair before handing the draft to numeric review."""
    original_numbers = re.findall(r"\d[\d,.]*%?", body)
    try:
        for attempt in range(2):
            check_path.write_text(body, encoding="utf-8")
            issues = _narrative_quality(check_path)["issues"]
            if not issues:
                return body
            raw = client.chat_json(
                "只修复所列机械文风问题，返回 JSON {\"replacements\":[{\"old\":\"原文唯一短句\",\"new\":\"新句\"}]}。"
                "不得改任何数字、评级、事实或章节标记；不要整篇改写。最多 12 处。",
                json.dumps({"issues": issues, "text": body}, ensure_ascii=False),
                purpose=f"report-style-polish:{attempt + 1}")
            changed = apply_replacements(body, raw.get("replacements") if isinstance(raw, dict) else None)
            if re.findall(r"\d[\d,.]*%?", changed) != original_numbers:
                raise ValueError("文风修订触碰数字，拒绝写入")
            body = changed
        check_path.write_text(body, encoding="utf-8")
        issues = _narrative_quality(check_path)["issues"]
        if issues:
            raise ValueError("初稿机械文风检查未通过：" + "；".join(issues[:8]))
        return body
    finally:
        check_path.unlink(missing_ok=True)


def polish_unsupported_numbers(client: LLMClient, body: str, run: Path) -> str:
    """Remove untraceable claims without inventing replacement figures."""
    values = truth_values(run)
    for attempt in range(2):
        unverified = check_text(body, values)
        mismatched = check_binding(body, run)
        if not unverified and not mismatched:
            return body
        raw = client.chat_json(
            "只做研报数字证据清理，返回 JSON {\"replacements\":[{\"old\":\"原文唯一短句\",\"new\":\"新句\"}]}。"
            "逐条删除不在核验事实或估值产物中的数字及依赖它的推论；可以保留不带该数字的有意义分析。"
            "不得添加任何新数字、改评级或改章节标记，最多 12 处。",
            json.dumps({"unverified_numbers": unverified[:20], "mismatched_claims": mismatched[:12],
                        "text": body}, ensure_ascii=False), purpose=f"report-numeric-polish:{run.name}:{attempt + 1}")
        changed = apply_replacements(body, raw.get("replacements") if isinstance(raw, dict) else None)
        if not set(re.findall(r"\d[\d,.]*%?", changed)) <= set(re.findall(r"\d[\d,.]*%?", body)):
            raise ValueError("数字清理加入新数值，拒绝写入")
        new_count = len(check_text(changed, values)) + len(check_binding(changed, run))
        if new_count >= len(unverified) + len(mismatched):
            raise ValueError("数字清理未减少未核验断言")
        body = changed
    remaining = check_text(body, values) + [x["quote"] for x in check_binding(body, run)]
    if remaining:
        raise ValueError("初稿仍有未核验数字：" + "、".join(remaining[:12]))
    return body


def draft(ws: Path, run: Path, narrative: Path) -> dict[str, Any]:
    """One bounded full draft call; later deterministic and independent gates decide usability."""
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise ValueError("缺少 DeepSeek API Key")
    meta = _load(ws / "sample.json")
    work = ws / "data/extractions" / meta["key"]
    analysis = _load(run / "financials/analysis.json")
    extras = _load(run / "financials/extras.json")
    source = {
        "company": meta["company"], "year": meta["year"],
        "market": _load(ws / "inputs/market.json"),
        "framework": qualitative_only((work / "report/framework.md").read_text(encoding="utf-8")),
        "historical_analysis": {"changes": analysis.get("changes"), "signals": analysis.get("signals"),
                                "quarterly": analysis.get("quarterly"),
                                "truth_table": compact_truth(analysis.get("truth_table", []))},
        "verified_operating_tables": compact_tables(extras.get("tables", [])),
        "analyst_assumptions": _load(work / "valuation_assumptions.json"),
        "forecast_summary": _load(run / "valuation/forecast_summary.json"),
        "valuation": _load(run / "valuation/valuation.json"),
    }
    for name in ("segment_forecast", "three_statement_detail", "non_operating_assets"):
        p = run / "valuation" / f"{name}.json"
        if p.is_file():
            source[name] = _load(p)
    original_framework = (work / "report/framework.md").read_text(encoding="utf-8")
    source["annual_report_qualitative_pages"] = {
        page: qualitative_only(content) for page, content in annual_excerpts(
            ws, meta, original_framework, extras.get("tables", [])).items()}
    writing = (ws / ".claude/skills/finagent-research/references/writing.md").read_text(encoding="utf-8")
    sections = (ws / ".claude/skills/finagent-report/references/sections.md").read_text(encoding="utf-8")
    system = (
        "你是证券研究团队的深度报告作者，使用原版 finagent-research 与 finagent-report Skill 的下述写作规范。"
        "只返回 JSON 对象，字段严格为 title、subtitle、summary、thesis、overview、performance、business、"
        "profitability、balance、cashflow、forecast、valuation、recommendation、risks，值都是纯 Markdown 文本。"
        "framework.md 是研究线索，里面含待验证判断，不能单独当作证据；定性披露先核对原年报页文本。"
        "framework 与原页的数字已遮蔽，只能从已核验历史事实、经营表和估值产物取数，不能恢复或猜测遮蔽值。"
        "只使用证据包中的数字；不得自算新数、推断未经核验的因果或把不同口径数据推出市场份额。"
        "事实、分析师假设、预测分别清楚表述；市场股价若带历史日期须称参考股价并注明日期，不能称实时。"
        "首页 summary 先列 2–3 环关键数字推导，再给 DCF 每股价值、参考股价、投资评级及风险提示；"
        "不能只列正向利润归因而漏掉负项。至少 350 字。正文每节写实质分析，合计至少 5500 字。"
        "没有证据的不重要判断删除；重要且无法确认的因素放入 risks 中作为风险，不在正文自证或解释流程。"
        "禁用‘不是…而是…’、‘而非’、‘程序认为’、‘程序评级’、‘年报佐证’、‘具体来看’、‘不过’等空泛句式。"
        "不要写任何 HTML、章节注释或代码。不要复制优秀研报措辞。\n\n"
        "[原版研究 Skill 的写作规范]\n" + writing + "\n\n[原版报告 Skill 的章节与图表规范]\n" + sections
    )
    client = LLMClient(get_settings(llm_base_url="https://api.deepseek.com", llm_model="deepseek-flash",
                                    llm_api_key=key, llm_mode="live",
                                    cache_dir=str(ws / ".pipeline/writer_cache"), llm_timeout=180))
    raw = client.chat_json(system, json.dumps(source, ensure_ascii=False), purpose=f"report-first-draft:{run.name}")
    first_call = dict(client.last_call)
    body = compose_sections(raw)
    narrative.parent.mkdir(parents=True, exist_ok=True)
    body = polish_unsupported_numbers(client, body, run)
    body = polish_style(client, body, narrative.parent / ".style_check.md")
    narrative.write_text(body, encoding="utf-8")
    return {"chars": len(body), "model": "deepseek-flash", "run_id": run.name,
            "first_draft_request_sha256": first_call.get("request_sha256"),
            "first_draft_usage": first_call.get("usage"),
            "last_repair_request_sha256": client.last_call.get("request_sha256")}
