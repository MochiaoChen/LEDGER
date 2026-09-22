"""文档解析：把 PDF / Markdown / TXT 切成带来源锚点的 Chunk。

每个 Chunk 带 {source, page, chunk_id}，后续每条抽取结果、每个核查结论都能回溯到原文位置。
- PDF：pdfplumber 抽取文本与表格（扫描件需先 OCR，见 README）。
- Markdown/TXT：用于样例数据与测试；`<!-- page: N -->` 标记模拟 PDF 页码，管道表格按表格解析。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..core import tracing

UNIT_RE = re.compile(r"单位[:：]\s*(?:人民币)?\s*(元|千元|万元|百万元|亿元)")
PAGE_RE = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")


@dataclass
class Chunk:
    chunk_id: str
    source: str
    page: int
    kind: str  # "text" | "table"
    text: str
    rows: list[list[str]] = field(default_factory=list)
    unit_hint: str = ""
    caption: str = ""

    def locator(self) -> str:
        return f"{Path(self.source).name} 第{self.page}页 {self.chunk_id}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Document:
    source: str
    sha256: str
    chunks: list[Chunk]

    def tables(self) -> list[Chunk]:
        return [c for c in self.chunks if c.kind == "table"]

    def texts(self) -> list[Chunk]:
        return [c for c in self.chunks if c.kind == "text"]

    def get(self, chunk_id: str) -> Chunk | None:
        return next((c for c in self.chunks if c.chunk_id == chunk_id), None)

    def summary(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "sha256": self.sha256,
            "chunks": len(self.chunks),
            "tables": len(self.tables()),
            "pages": max((c.page for c in self.chunks), default=0),
        }


def rows_to_markdown(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    norm = [[(c or "").replace("\n", " ").strip() for c in r] + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(norm[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in norm[1:]]
    return "\n".join(lines)


# --------------------------------------------------------------------- loaders
def load_document(path: str | Path) -> Document:
    p = Path(path)
    data = tracing.read_file(p)
    digest = tracing.sha256_bytes(data)
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        chunks = _parse_pdf(p)
    elif suffix in (".md", ".txt"):
        chunks = _parse_markdown(data.decode("utf-8"), str(p))
    else:
        raise ValueError(f"不支持的文件类型：{suffix}")
    doc = Document(str(p), digest, chunks)
    tracing.log("document_parsed", **doc.summary())
    return doc


def _parse_markdown(text: str, source: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    page = 1
    unit = ""
    heading = ""
    para: list[str] = []
    table: list[str] = []

    def cid() -> str:
        return f"c{len(chunks) + 1:04d}"

    def flush_para() -> None:
        if para:
            body = "\n".join(para).strip()
            if body:
                chunks.append(Chunk(cid(), source, page, "text", body, unit_hint=unit, caption=heading))
            para.clear()

    def flush_table() -> None:
        if table:
            rows = []
            for line in table:
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    continue
                rows.append(cells)
            if rows:
                chunks.append(Chunk(cid(), source, page, "table", rows_to_markdown(rows),
                                    rows=rows, unit_hint=unit, caption=heading))
            table.clear()

    for raw in text.splitlines():
        line = raw.rstrip()
        m = PAGE_RE.search(line)
        if m:
            flush_para(); flush_table()
            page = int(m.group(1))
            continue
        if line.lstrip().startswith("|"):
            flush_para()
            table.append(line)
            continue
        flush_table()
        um = UNIT_RE.search(line)
        if um:
            unit = um.group(1)
        if line.startswith("#"):
            flush_para()
            heading = line.lstrip("#").strip()
            chunks.append(Chunk(cid(), source, page, "text", heading, unit_hint=unit, caption=heading))
            continue
        if not line.strip():
            flush_para()
            continue
        para.append(line)
    flush_para(); flush_table()
    return chunks


def _parse_pdf(path: Path) -> list[Chunk]:
    try:
        import pdfplumber  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("解析 PDF 需要 pdfplumber：pip install pdfplumber") from exc

    chunks: list[Chunk] = []
    unit = ""
    with pdfplumber.open(str(path)) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            units = UNIT_RE.findall(text)
            page_unit = units[0] if units else unit
            for table in page.extract_tables() or []:
                rows = [[(c or "").strip() for c in r] for r in table if any(r)]
                if rows:
                    chunks.append(Chunk(f"c{len(chunks) + 1:04d}", str(path), pno, "table",
                                        rows_to_markdown(rows), rows=rows, unit_hint=page_unit))
            for para in re.split(r"\n\s*\n", text):
                if para.strip():
                    chunks.append(Chunk(f"c{len(chunks) + 1:04d}", str(path), pno, "text",
                                        para.strip(), unit_hint=page_unit))
            if units:
                unit = units[-1]
    return chunks
