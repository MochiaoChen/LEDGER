"""（开发用）把样例年报 Markdown 渲染成 PDF，用于测试 Skill 版本的 PDF 路径（定位、表格标题、母公司报表排除、逐字证据校验）。

按 <!-- page: N --> 放到对应页，表格画成带框线表格，并在第 112 页追加一张母公司资产负债表（数字与合并报表不同）。
需要 fpdf2（仅开发时）与一款中文字体，默认用 macOS 自带的 Arial Unicode：

    pip install fpdf2
    python data/samples/build_pdf.py data/samples/annual_report_2024.md data/samples/annual_report_2024.pdf
"""
import re, sys
from fpdf import FPDF

src, out = sys.argv[1], sys.argv[2]
pages, cur = {}, None
for line in open(src, encoding="utf-8"):
    m = re.search(r"<!--\s*page:\s*(\d+)\s*-->", line)
    if m:
        cur = int(m.group(1)); pages[cur] = []; continue
    if cur is not None:
        pages[cur].append(line.rstrip("\n"))
# 母公司报表页：数字与合并报表不同，用来检验口径
pages[112] = ["### 母公司资产负债表", "单位：元", "| 项目 | 2024年12月31日 | 2023年12月31日 |", "|---|---|---|",
              "| 货币资金 | 212,345,678.90 | 198,765,432.10 |", "| 资产总计 | 4,321,098,765.43 | 3,987,654,321.09 |"]
pdf = FPDF(format="A4")
pdf.add_font("cjk", fname="/Library/Fonts/Arial Unicode.ttf"); pdf.add_font("cjk", style="B", fname="/Library/Fonts/Arial Unicode.ttf")
pdf.set_auto_page_break(False)
for p in range(1, 113):
    pdf.add_page(); pdf.set_font("cjk", size=9)
    lines = pages.get(p, [f"星河智能制造股份有限公司 2024 年年度报告 第 {p} 页（正文略）"])
    table = []
    def flush():
        if not table: return
        rows = [[c.strip() for c in r.strip().strip("|").split("|")] for r in table
                if not re.fullmatch(r"\|?\s*:?-{2,}.*", r.strip())]
        with pdf.table(text_align="LEFT", line_height=5) as t:
            for r in rows:
                row = t.row()
                for c in r: row.cell(c)
        table.clear()
    for ln in lines:
        if ln.lstrip().startswith("|"):
            table.append(ln); continue
        flush()
        if ln.strip():
            pdf.set_font("cjk", size=12 if ln.startswith("#") else 9)
            pdf.multi_cell(0, 6, ln.lstrip("# ").strip(), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("cjk", size=9)
    flush()
pdf.output(out)
print("pages:", pdf.pages_count)
