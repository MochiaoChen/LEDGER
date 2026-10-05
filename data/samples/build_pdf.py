"""（开发用）把样例年报 Markdown 渲染成 PDF，用于测试模型读 PDF 抽取的路径。

支持 macOS、Windows 与 Linux。中文字体按 ``--font``、``FINAGENT_CJK_FONT``、
系统常见字体路径的顺序查找；找不到时给出可操作的错误信息，不再依赖 macOS 固定路径。

    python data/samples/build_pdf.py data/samples/annual_report_2024.md data/samples/annual_report_2024.pdf
"""

from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


FONT_CANDIDATES = (
    Path(r"C:\Windows\Fonts\simkai.ttf"),
    Path(r"C:\Windows\Fonts\msyh.ttc"),
    Path(r"C:\Windows\Fonts\simsun.ttc"),
    Path("/Library/Fonts/Arial Unicode.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
)


def find_cjk_font(explicit: str | Path | None = None) -> Path:
    """返回可用中文字体；显式路径优先，便于 Windows 与 CI 稳定复现。"""
    requested = explicit or os.environ.get("FINAGENT_CJK_FONT")
    if requested:
        path = Path(requested).expanduser()
        if path.is_file():
            return path
        raise FileNotFoundError(f"指定的中文字体不存在：{path}")
    for path in FONT_CANDIDATES:
        if path.is_file():
            return path
    raise FileNotFoundError(
        "找不到中文字体。请安装楷体/微软雅黑/Noto Sans CJK，或用 --font / FINAGENT_CJK_FONT 指定字体文件。"
    )


def build(src: Path, out: Path, font: Path) -> None:
    from fpdf import FPDF

    pages: dict[int, list[str]] = {}
    cur: int | None = None
    for line in src.read_text(encoding="utf-8").splitlines():
        match = re.search(r"<!--\s*page:\s*(\d+)\s*-->", line)
        if match:
            cur = int(match.group(1))
            pages[cur] = []
            continue
        if cur is not None:
            pages[cur].append(line)

    pages[112] = [
        "### 母公司资产负债表", "单位：元", "| 项目 | 2024年12月31日 | 2023年12月31日 |", "|---|---|---|",
        "| 货币资金 | 212,345,678.90 | 198,765,432.10 |", "| 资产总计 | 4,321,098,765.43 | 3,987,654,321.09 |",
    ]
    pdf = FPDF(format="A4")
    pdf.add_font("cjk", fname=str(font))
    pdf.add_font("cjk", style="B", fname=str(font))
    pdf.set_auto_page_break(False)

    for page_no in range(1, 113):
        pdf.add_page()
        pdf.set_font("cjk", size=9)
        lines = pages.get(page_no, [f"星河智能制造股份有限公司 2024 年年度报告 第 {page_no} 页（正文略）"])
        table: list[str] = []

        def flush() -> None:
            if not table:
                return
            rows = [[cell.strip() for cell in row.strip().strip("|").split("|")] for row in table
                    if not re.fullmatch(r"\|?\s*:?-{2,}.*", row.strip())]
            with pdf.table(text_align="LEFT", line_height=5) as pdf_table:
                for values in rows:
                    pdf_row = pdf_table.row()
                    for value in values:
                        pdf_row.cell(value)
            table.clear()

        for line in lines:
            if line.lstrip().startswith("|"):
                table.append(line)
                continue
            flush()
            if line.strip():
                pdf.set_font("cjk", size=12 if line.startswith("#") else 9)
                pdf.multi_cell(0, 6, line.lstrip("# ").strip(), new_x="LMARGIN", new_y="NEXT")
                pdf.set_font("cjk", size=9)
        flush()
    out.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(out)
    print(f"pages: {pdf.pages_count}; font: {font}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把带页码锚点的样例 Markdown 渲染成 PDF")
    parser.add_argument("src", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--font", type=Path, help="中文字体文件；也可设置 FINAGENT_CJK_FONT")
    args = parser.parse_args(argv)
    build(args.src, args.out, find_cjk_font(args.font))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
