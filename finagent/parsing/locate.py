"""年报关键页定位：告诉读 PDF 的模型该读哪几页，避免整本送入、避免误读母公司报表。

按章节标题关键词在各页文本中检索；财务报表常跨 2～3 页，建议阅读范围向后延伸 2 页。
无文本层的页（扫描件）单独列出，读取时需按图片识别。
"""

from __future__ import annotations

import re
from typing import Any

from .document import Document

SECTIONS = {
    "key_data": ("主要会计数据和财务指标", "主要会计数据", "主要财务指标"),
    "quarterly": ("分季度主要财务指标", "分季度主要财务数据", "分季度主要会计数据"),
    "non_recurring": ("非经常性损益项目及金额", "非经常性损益项目", "非经常性损益明细"),
    "balance": ("合并资产负债表",),
    "income": ("合并利润表",),
    "cashflow": ("合并现金流量表",),
    "cashflow_supplement": ("现金流量表补充资料", "补充资料"),
    "share_capital": ("股本变动情况", "股份变动情况", "普通股股份总数"),
}
PARENT_ONLY = ("母公司资产负债表", "母公司利润表", "母公司现金流量表")
SPAN = 2  # 报表跨页：命中页之后再读 2 页


def _page_texts(doc: Document) -> dict[int, str]:
    pages: dict[int, list[str]] = {}
    for c in doc.chunks:
        pages.setdefault(c.page, []).append((c.caption + "\n" if c.caption else "") + c.text)
    return {p: re.sub(r"\s+", "", "\n".join(t)) for p, t in pages.items()}


def _ranges(pages: list[int]) -> list[str]:
    out: list[list[int]] = []
    for p in sorted(set(pages)):
        if out and p <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], p)
        else:
            out.append([p, p])
    return [f"{a}" if a == b else f"{a}-{b}" for a, b in out]


def locate(doc: Document, total_pages: int | None = None) -> dict[str, Any]:
    texts = _page_texts(doc)
    last = total_pages or max(texts, default=0)
    sections = {name: sorted(p for p, t in texts.items() if any(k in t for k in keys))
                for name, keys in SECTIONS.items()}
    parent = sorted(p for p, t in texts.items() if any(k in t for k in PARENT_ONLY))
    # 延伸页可能同时含合并报表末尾与母公司报表开头，照读；口径由 parent_only_pages 提示与 scope 校验把关
    reads = [q for name, ps in sections.items() for p in ps
             for q in range(p, min(p + (SPAN if name in ("balance", "income", "cashflow") else 0), last) + 1)]
    units = {p: m.group(1) for p, t in texts.items()
             if (m := re.search(r"单位[:：](?:人民币)?(元|千元|万元|百万元|亿元)", t))}
    no_text = [p for p in range(1, last + 1) if p not in texts] if total_pages else []
    return {
        "source": doc.source,
        "pages_with_text": len(texts),
        "total_pages": last,
        "sections": sections,
        "parent_only_pages": parent,
        "suggested_reads": _ranges(reads),
        "unit_hints": {str(p): u for p, u in sorted(units.items()) if p in set(reads)},
        "no_text_layer_pages": no_text,
    }


def pdf_page_count(path: str) -> int | None:
    if not str(path).lower().endswith(".pdf"):
        return None
    import pdfplumber  # type: ignore

    with pdfplumber.open(str(path)) as pdf:
        return len(pdf.pages)
