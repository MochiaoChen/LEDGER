"""Bounded original annual-report excerpts for the writer and independent reviewer.

The model-authored framework is a list of leads, not proof. Both calls receive the
same source pages so a cited management statement can be checked against the PDF.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


PAGE_REF = re.compile(r"P\s*(\d{1,4})(?:\s*[–—-]\s*P?\s*(\d{1,4}))?", re.IGNORECASE)


def cited_pages(framework: str, table_pages: list[Any], *, page_count: int, limit: int = 24) -> list[int]:
    """Prioritize the investment thesis, then verified-table pages; cap API context."""
    preferred: list[int] = []
    thesis = framework.split("## 二、", 1)[0]
    for match in PAGE_REF.finditer(thesis):
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if end >= start and end - start <= 5:
            preferred.extend(range(start, end + 1))
    preferred.extend(int(x) for x in table_pages if isinstance(x, int) or str(x).isdigit())
    for match in PAGE_REF.finditer(framework):
        preferred.append(int(match.group(1)))
    return list(dict.fromkeys(p for p in preferred if 1 <= p <= page_count))[:limit]


def annual_excerpts(ws: Path, meta: dict[str, Any], framework: str, tables: list[dict[str, Any]]) -> dict[str, str]:
    import pdfplumber

    source = (ws / meta["pdf"]).resolve()
    if not source.is_relative_to(ws.resolve()) or not source.is_file() or source.suffix.lower() != ".pdf":
        raise ValueError("年报 PDF 路径无效")
    excerpts: dict[str, str] = {}
    with pdfplumber.open(source) as pdf:
        pages = cited_pages(framework, [t.get("page") for t in tables], page_count=len(pdf.pages))
        for number in pages:
            text = pdf.pages[number - 1].extract_text() or ""
            if text.strip():
                excerpts[f"PDF 物理第 {number} 页"] = text[:4000]
    return excerpts


def compact_truth(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the audited amount, period, unit and physical PDF page; omit parser metadata."""
    return [{"metric": item.get("metric_id"), "period": item.get("period"),
             "value": item.get("value"), "unit": item.get("unit"),
             "page": (item.get("source") or {}).get("page")}
            for item in facts]


def compact_tables(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep every verified cell but not duplicate raw strings, aliases, or chunk metadata."""
    return [{"id": table.get("id"), "title": table.get("title"), "page": table.get("page"),
             "columns": [{"name": c.get("name"), "unit": c.get("unit")} for c in table.get("columns", [])],
             "rows": [{"label": row.get("label"), "values": row.get("values")}
                      for row in table.get("rows", [])]}
            for table in tables]


def qualitative_only(text: str) -> str:
    """Keep management discussion but prevent unverified page numbers entering the draft."""
    return re.sub(r"(?<![A-Za-z])[-−+]?\d[\d,]*(?:\.\d+)?%?", "[数值须取核验数据]", text)
