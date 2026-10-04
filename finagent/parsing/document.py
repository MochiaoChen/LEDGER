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
    # 跨页续表：续页没有表头，沿用首页表格的前几行作候选表头；continued_from 指向上一页的那张表
    header_rows: list[list[str]] = field(default_factory=list)
    continued_from: str = ""

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
    caption = ""  # 表格标题：取表格上方最近一行；续页无标题时沿用上一张表的标题
    tail = ""  # 上一页末尾、最后一张表之下的标题：有它说明下一页首张表是新表，不是续表
    last: tuple[Chunk, list[list[str]]] | None = None  # 上一张表及其未合并列的候选表头（续表要和它一起合并列）
    with pdfplumber.open(str(path)) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            text = page.extract_text() or ""
            units = UNIT_RE.findall(text)
            page_unit = units[0] if units else unit
            # 同一页有多个“单位：”声明时（如上表亿元、下表元），每张表取其上方最近的声明
            marks = _unit_marks(page) if len(set(units)) > 1 else []
            bottom = 0.0
            first = True
            for table in page.find_tables():
                raw = [[(c or "").strip() for c in r] for r in table.extract() if any(r)]
                if not raw:
                    continue
                own = _caption_above(page, table.bbox[1], bottom)
                caption = own or caption
                bottom = table.bbox[3]
                above = [u for top, u in marks if top < table.bbox[1]]
                t_unit = above[-1] if above else (unit if marks else page_unit) or page_unit
                ch = Chunk(f"c{len(chunks) + 1:04d}", str(path), pno, "table", "", unit_hint=t_unit, caption=caption)
                linked = (first and not own and not tail and last is not None and last[0].page == pno - 1
                          and link_continuation(ch, raw, *last))
                if not linked:
                    ch.rows = merge_wrapped_labels(compact_columns(raw))
                ch.text = rows_to_markdown(ch.rows)
                last = (ch, last[1] if linked else raw[:3])
                first = False
                chunks.append(ch)
            # 页末标题（表格在下一页开始）：下一页表格上方没有标题时沿用它，而不是沿用更早的表格标题
            tail = _caption_above(page, page.height, bottom)
            caption = tail or caption
            for para in re.split(r"\n\s*\n", text):
                if para.strip():
                    chunks.append(Chunk(f"c{len(chunks) + 1:04d}", str(path), pno, "text",
                                        para.strip(), unit_hint=page_unit))
            if units:
                unit = units[-1]
    return chunks


def link_continuation(cur: Chunk, raw: list[list[str]], prev: Chunk, head: list[list[str]]) -> bool:
    """页首无标题的表格是否为上一页表格的续表；是则填好 cur.rows / header_rows / continued_from 并返回 True。

    续页没有表头，要让上一张表的表头（未合并列的前几行）和本页数字落在同一列：先把两者放在一起合并列
    （两页切分一致或续页只多出被劈开的列时），不行再各自合并列（两页切分完全不同时）。合并后列数须与上一张表
    一致，否则不认作续表——宁可漏取也不错配期间。续页开头若是上一页末行科目的折行尾巴（如“号填列）”），
    接回上一张表的末行。只记录关系、不合并两页的行，每行页码仍是它实际所在的页。"""
    if not head or not prev.rows:
        return False
    want = max(len(r) for r in prev.rows)
    width, hwidth = max(len(r) for r in raw), max(len(r) for r in head)
    hdr: list[list[str]] = []
    rows: list[list[str]] = []
    if hwidth <= width:
        joint = compact_columns([r + [""] * (width - len(r)) for r in head] + raw, force=hwidth != width)
        hdr, rows = joint[:len(head)], joint[len(head):]
    if not rows or max(len(r) for r in rows) != want:
        hdr, rows = compact_columns(head), compact_columns(raw)
        if max(len(r) for r in hdr) != want or max(len(r) for r in rows) != want:
            return False
    limit = _label_width(prev.rows)
    while rows and _is_fragment(rows[0], prev.rows[-1][0], limit):
        prev.rows[-1][0] += "\n" + rows.pop(0)[0]  # 保留换行：折行判断看末行长度
        prev.text = rows_to_markdown(prev.rows)
    cur.rows = merge_wrapped_labels(rows)
    cur.header_rows = hdr
    cur.continued_from = prev.chunk_id
    return True


# 折行尾巴的开头：这些字不会作为一个报表科目的开头
_FRAGMENT_START = ("的", "）", ")", "率", "号", "列", "股）", "流量", "填列", "益）", "”", "以“")


def _label_width(rows: list[list[str]]) -> int:
    """表内科目名单行最长字数，近似科目列宽。"""
    return max((len(ln) for r in rows if r for ln in r[0].split("\n")), default=0)


def _is_fragment(row: list[str], prev_label: str, limit: int) -> bool:
    """只有标签、没有数值的一行，是否为上一行科目名的折行尾巴：上一行括号没闭合、上一行写满列宽，
    或本行以不会作科目开头的字开头。小节标题（以冒号结尾）不算。"""
    label = row[0] if row else ""
    if not label or any(c for c in row[1:]) or label.endswith(("：", ":")) or not prev_label:
        return False
    unclosed = prev_label.count("（") + prev_label.count("(") > prev_label.count("）") + prev_label.count(")")
    full = limit >= 8 and len(prev_label.split("\n")[-1]) >= limit - 1
    return unclosed or full or label.startswith(_FRAGMENT_START)


def merge_wrapped_labels(rows: list[list[str]]) -> list[list[str]]:
    """把折成多行的科目名接回有数值的那一行（如“归属于上市公司股东 / 的净利润”，数字在第一行）。"""
    limit = _label_width(rows)
    out: list[list[str]] = []
    for row in rows:
        if out and out[-1] and _is_fragment(row, out[-1][0], limit):
            out[-1] = [out[-1][0] + "\n" + row[0]] + out[-1][1:]
        else:
            out.append(list(row))
    return out


def compact_columns(rows: list[list[str]], force: bool = False) -> list[list[str]]:
    """合并稀疏网格的列。

    pdfplumber 对部分年报（如宁德时代）把一个逻辑列切成几列：科目在第 2 列、表头“期末余额”与下方数字错开一列，
    其余列全空。出现全空列（或 force）时处理：从左到右把相邻列并成一组，只要组内每一行最多一个非空单元格；
    任一行两列都有值就另起一组。规整的表格没有全空列，原样返回。"""
    if not rows:
        return rows
    width = max(len(r) for r in rows)
    grid = [r + [""] * (width - len(r)) for r in rows]
    if not force and not any(all(not r[c] for r in grid) for c in range(width)):
        return grid if any(len(r) != width for r in rows) else rows
    groups: list[list[int]] = []
    for c in range(width):
        if groups and all(not (r[c] and any(r[g] for g in groups[-1])) for r in grid):
            groups[-1].append(c)
        else:
            groups.append([c])
    out = [["".join(r[c] for c in g) for g in groups] for r in grid]
    keep = [i for i in range(len(groups)) if any(r[i] for r in out)]
    return [[r[i] for i in keep] for r in out]


def _unit_marks(page: Any) -> list[tuple[float, str]]:
    """页内各“单位：”声明的纵向位置与单位，按从上到下排序。"""
    try:
        found = page.search(UNIT_RE.pattern)
    except Exception:  # noqa: BLE001  旧版 pdfplumber 无 search 时退回整页单位
        return []
    out = []
    for m in found:
        um = UNIT_RE.search(m.get("text", ""))
        if um:
            out.append((float(m["top"]), um.group(1)))
    return sorted(out)


TITLE_RE = re.compile(r"表|^[一二三四五六七八九十]+、|^（[一二三四五六七八九十]+）|^\d+[、.]|^[（(]\d+[)）]")
# 标题与表格之间常见的非标题行：报表日期、编制单位、适用勾选、币种等，跳过后继续向上找标题
SKIP_RE = re.compile(r"^编制单位|^\d{4}\s*年.{0,12}(日|月)$|^[√□]\s*适用|币种|^项目\s|^贵州|年度报告$")


def _caption_above(page: Any, top: float, floor: float = 0.0) -> str:
    """表格上方最近的标题行（含“表”字或为编号标题），跳过“单位：”、报表日期、编制单位等行；
    只在 floor（上一张表格底部）以下查找，最多向上看 6 行；找不到返回空。"""
    if top - floor <= 1:
        return ""
    above = page.crop((0, floor, page.width, top)).extract_text() or ""
    lines = [ln.strip() for ln in above.splitlines() if ln.strip()]
    for ln in list(reversed(lines))[:6]:
        if UNIT_RE.search(ln) or SKIP_RE.search(ln):
            continue
        if len(ln) <= 40 and TITLE_RE.search(ln):
            return ln
        if len(ln) > 40:
            return ""
    return ""
