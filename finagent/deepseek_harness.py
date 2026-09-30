"""Two-company DeepSeek V4.1 Flash report benchmark.

Usage:
  python -m finagent.deepseek_harness prepare
  python -m finagent.deepseek_harness run

The annual reports are repository resources. Outputs and response caches live
under runs/ and are never treated as verified investment research.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .core.config import PROJECT_ROOT, get_settings
from .core.llm import LLMClient, LLMError, parse_json

RESOURCES = PROJECT_ROOT / "report" / "resources"
DEFAULT_OUTPUT = PROJECT_ROOT / "runs" / "deepseek-v41-flash"
COMPANIES = ("宁德时代", "招商轮船")
# The MD&A ranges were identified in the corresponding 2025 annual reports.
MANAGEMENT_PAGES = {"宁德时代": range(14, 41), "招商轮船": range(12, 41)}
CITATION = re.compile(r"【年报第(\d+)页】")
NUMBER = re.compile(r"\d")
EDITORIAL_PLACEHOLDER = re.compile(r"[？?]|TODO|TBD|待核实|待查证", re.IGNORECASE)
MODEL = "deepseek-flash"

SYSTEM = (
    "你是审慎的 A 股卖方研究员。只使用提供的 2025 年年度报告摘录，"
    "不调用记忆中的公司数字或外部行情。事实、推论和分析师观点须分开。"
    "任何数字或可核查的公司事实，在同一段末尾标注【年报第N页】；"
    "未披露的指标明确写“年报未披露”，不可编造股价、目标价、评级或收益预测。"
)


def _read_manifest(company: str) -> tuple[dict[str, Any], Path, dict[str, Any]]:
    manifest = json.loads((RESOURCES / "manifest.json").read_text(encoding="utf-8"))
    record = next((r for r in manifest["reports"] if r["short_name"] == company), None)
    if record is None:
        raise ValueError(f"资源清单中没有 {company}")
    pdf = RESOURCES / record["path"]
    if not pdf.is_file():
        raise FileNotFoundError(pdf)
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    if digest != record["sha256"]:
        raise ValueError(f"{company} 年报哈希与资源清单不符")
    locate = json.loads((pdf.parent / "locate.json").read_text(encoding="utf-8"))
    return record, pdf, locate


def page_numbers(company: str, locate: dict[str, Any]) -> list[int]:
    pages = set(MANAGEMENT_PAGES[company])
    for section in locate["sections"].values():
        pages.update(section)
    for spec in locate.get("suggested_reads", []):
        bounds = [int(part) for part in str(spec).split("-", 1)]
        pages.update(range(bounds[0], bounds[-1] + 1))
    return sorted(n for n in pages if 1 <= n <= locate["total_pages"])


def prepare_company(company: str, root: Path, *, max_chars: int = 350_000) -> dict[str, Any]:
    import pdfplumber

    record, pdf_path, locate = _read_manifest(company)
    pages = page_numbers(company, locate)
    snippets: list[str] = []
    missing: list[int] = []
    with pdfplumber.open(pdf_path) as pdf:
        if len(pdf.pages) != record["pages"]:
            raise ValueError(f"{company} 年报页数与资源清单不符")
        for number in pages:
            body = (pdf.pages[number - 1].extract_text(layout=False) or "").strip()
            if not body:
                missing.append(number)
                continue
            snippets.append(f"\n### 年报 PDF 第 {number} 页\n{body}\n")
    if missing:
        raise ValueError(f"{company} 选中页没有可提取文本：{missing}")
    source = (
        f"# {company} 2025 年年报证据包\n\n"
        f"来源：{pdf_path.relative_to(PROJECT_ROOT).as_posix()}\n"
        f"原文 SHA-256：{record['sha256']}\n"
        "页码为 PDF 物理页码，从 1 开始。\n"
        + "".join(snippets)
    )
    if len(source) > max_chars:
        raise ValueError(f"{company} 证据包 {len(source)} 字符，超过上限 {max_chars}；需要人工调整选页")
    folder = root / f"{record['ticker']}_{company}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "source_pack.md").write_text(source, encoding="utf-8")
    meta = {
        "company": company,
        "ticker": record["ticker"],
        "fiscal_year": 2025,
        "source_pdf": pdf_path.relative_to(PROJECT_ROOT).as_posix(),
        "source_sha256": record["sha256"],
        "source_url": record["source_url"],
        "selected_pages": pages,
        "source_chars": len(source),
        "model": MODEL,
        "status": "prepared",
    }
    (folder / "manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**meta, "folder": str(folder)}


def _quality_check(text: str, allowed_pages: set[int]) -> dict[str, Any]:
    cited = [int(n) for n in CITATION.findall(text)]
    invalid = sorted(set(cited) - allowed_pages)
    missing: list[str] = []
    placeholders = [line.strip()[:120] for line in text.splitlines() if EDITORIAL_PLACEHOLDER.search(line)]
    for paragraph in re.split(r"\n\s*\n", text):
        plain = paragraph.strip()
        if not plain or plain.startswith("#") or plain.startswith("|"):
            continue
        if NUMBER.search(plain) and not CITATION.search(plain):
            missing.append(plain[:100])
    return {
        "citation_count": len(cited),
        "invalid_citation_pages": invalid,
        "numeric_paragraphs_without_citation": missing,
        "editorial_placeholders": placeholders,
        "requires_human_review": True,
        "status": "needs_review" if invalid or missing or placeholders or not cited else "draft_ready_for_review",
    }


def run_company(prepared: dict[str, Any], client: LLMClient) -> dict[str, Any]:
    folder = Path(prepared["folder"])
    source = (folder / "source_pack.md").read_text(encoding="utf-8")
    outline_prompt = (
        "先从年报证据推导分析框架。返回 JSON 对象，字段为 "
        "investment_thesis（3 条可验证判断，每条含依据页码）、"
        "revenue_drivers、margin_and_cost_drivers、cash_flow_drivers、"
        "forward_indicators、disclosure_limits、report_sections。"
        "每条判断都写明证据页，不能填年报没有披露的数值。\n\n" + source
    )
    framework_msg = client.chat(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": outline_prompt}],
        json_mode=True, purpose=f"deepseek_framework:{prepared['ticker']}", reasoning_effort="high",
    )
    framework_text = framework_msg.get("content") or ""
    if not framework_text:
        raise LLMError("分析框架响应为空")
    framework = parse_json(framework_text)
    if not isinstance(framework, dict):
        raise LLMError("分析框架响应不是 JSON 对象")
    (folder / "framework.json").write_text(json.dumps(framework, ensure_ascii=False, indent=2), encoding="utf-8")
    first_call = dict(client.last_call)

    report_prompt = (
        f"请写一份 {prepared['company']} 2025 年年报深度分析的 Markdown 初稿，用于与其他模型横向比较。"
        "先给 3 条有信息量的投资要点，再按分析主线组织业绩、业务驱动、利润与现金流、"
        "前瞻指标和风险。每段首句给出具体判断或事实，后面解释数据之间的关系和推导过程。"
        "引用年报时按 PDF 物理页码标【年报第N页】。"
        "对于估值、股价、预测和评级，若输入没有提供可核验依据，写“待补充”，不自行猜测。"
        "输出约 3000 至 5000 字；宁可短，也不要堆砌重复数据。\n\n"
        "分析框架：\n" + json.dumps(framework, ensure_ascii=False) + "\n\n证据包：\n" + source
    )
    message = client.chat(
        [{"role": "system", "content": SYSTEM}, {"role": "user", "content": report_prompt}],
        purpose=f"deepseek_report:{prepared['ticker']}", reasoning_effort="high",
    )
    report = (message.get("content") or "").strip()
    if not report:
        raise LLMError("报告响应为空")
    (folder / "report_draft.md").write_text(report + "\n", encoding="utf-8")
    qa = _quality_check(report, set(prepared["selected_pages"]))
    (folder / "qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    meta = {k: v for k, v in prepared.items() if k != "folder"}
    meta.update({
        "status": qa["status"],
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "framework_call": first_call,
        "report_call": dict(client.last_call),
        "quality_check": qa,
    })
    (folder / "manifest.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"company": prepared["company"], "folder": str(folder), "status": qa["status"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DeepSeek-V4.1-Flash 两公司年报报告测试")
    parser.add_argument("action", choices=("prepare", "run"))
    parser.add_argument("--company", action="append", choices=COMPANIES,
                        help="默认处理宁德时代和招商轮船，可重复指定")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    companies = tuple(dict.fromkeys(args.company or COMPANIES))
    root = args.output_dir.resolve()
    try:
        prepared = [prepare_company(company, root) for company in companies]
        if args.action == "prepare":
            print(json.dumps(prepared, ensure_ascii=False, indent=2))
            return 0
        key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("LLM_API_KEY")
        if not key:
            raise LLMError(
                "缺少 DeepSeek API Key。请在被 .gitignore 忽略的 .env 中填写 "
                "DEEPSEEK_API_KEY，或在本机设置同名环境变量；不要把密钥发到聊天或提交到 Git。"
            )
        settings = get_settings(
            llm_base_url="https://api.deepseek.com/v1",
            llm_model=MODEL,
            llm_api_key=key,
            llm_mode="live",
            cache_dir=str(root / ".cache"),
        )
        client = LLMClient(settings)
        results = [run_company(item, client) for item in prepared]
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, FileNotFoundError, LLMError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
