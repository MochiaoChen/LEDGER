"""极简 XLSX 写出（标准库 zipfile + OOXML），无需 openpyxl。数字写为数值单元格，其余为内联字符串；
Formula 写为公式单元格（附缓存值，打开即显示；含公式的工作簿设置打开时重算）。

排版（投行模型惯例）：
  - 字体中西文配对：Arial 配楷体（默认），Times New Roman 配宋体。xlsx 单元格字体只有一个名字，
    所以文字单元格写成富文本：中文字符一段用中文字体，字母数字一段用西文字体；数值单元格用西文字体。
    （不用工作簿主题的 ea 字体：中文界面的 Excel for Mac 会把它当正文字体，连数字都变成楷体。）
  - 正文与表头 12 号字，来源及计算口径 9 号灰色斜体；表头深蓝底白字加粗；正文浅灰细线分隔；
    合计行加粗、上边框；关闭网格线、冻结表头、自动列宽；
    打印横向、按页宽缩放。
  - 数字格式：金额千分位一位小数，负数加括号，零显示“-”；比率 0.0%；倍数 0.0x；变动量带正负号。
  - 颜色：硬编码输入蓝色，公式黑色，纯跨表引用绿色；关键输出浅黄底。
表格结构不因排版改变（行列位置不动），公式引用保持有效。
"""

from __future__ import annotations

import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

_CT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
{sheets}
</Types>"""
_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'

# ------------------------------------------------------------------ 主题
FONT = "Arial"
# 西文字体 → 中文字体（Office 自带 KaiTi / SimSun，Windows 与 Mac 版 Excel 都能找到）
FONT_PAIRS = {"Arial": "KaiTi", "Times New Roman": "SimSun"}
CJK_FONT = FONT_PAIRS[FONT]
BODY_FONT_SIZE, NOTE_FONT_SIZE, TITLE_FONT_SIZE = 12, 9, 14
NAVY, SECTION_FILL, KEY_FILL, RULE, GREY_TEXT = "1F3864", "DCE6F1", "FFF2CC", "BFBFBF", "595959"
INPUT_BLUE, LINK_GREEN = "0000FF", "008000"
NUMBER_FORMATS = {
    "num0": '#,##0_);(#,##0);"-"_)',
    "num1": '#,##0.0_);(#,##0.0);"-"_)',
    "num2": '#,##0.00_);(#,##0.00);"-"_)',
    "int": '#,##0_);(#,##0);"0"_)',
    "pct1": '0.0%_);(0.0%);"-"_)',
    "pct2": '0.00%_);(0.00%);"-"_)',
    "mult": '0.0"x"_);(0.0"x");"-"_)',
    "dpct": '+0.0%;-0.0%;0.0%',        # 变动（百分比）：带正负号，零也显示
    "dpct2": '+0.00%;-0.00%;0.00%',
    "dmult": '+0.0"x";-0.0"x";0.0"x"',  # 倍数变动
    "pp": '+0.0" pp";-0.0" pp";"-"',     # 百分点
    "pp2": '+0.00" pp";-0.00" pp";"-"',  # 百分点（两位小数，与年报原文精度一致）
    "factor": "0.0000",
    "year": "0",
}
ROLES = ("body", "header", "section", "total", "key", "note", "title", "axis")


def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


@dataclass
class Formula:
    """公式单元格。expr 不带前导 "="；value 为缓存值（None 表示空串）；array=True 写为数组公式（CSE）。
    fmt / role 可覆盖所在行列的数字格式与行样式。"""
    expr: str
    value: Any = None
    array: bool = False
    fmt: str | None = None
    role: str | None = None


@dataclass
class Cell:
    """带样式的普通单元格（数值或文字）。input=True 按硬编码输入标蓝。"""
    value: Any
    fmt: str | None = None
    role: str | None = None
    input: bool | None = None


@dataclass
class ChartSeries:
    """图表序列：name 为图例名称，values 为当前工作表内的单元格区域（如 B6:E6）。"""
    name: str
    values: str
    color: str = "4472C4"


@dataclass
class Chart:
    """原生 Excel 簇状柱形图；categories / series 均引用当前工作表。"""
    title: str
    categories: str
    series: list[ChartSeries]
    anchor: tuple[int, int, int, int]
    number_format: str = "0.0"


@dataclass
class Sheet:
    """一张工作表：rows 为二维数据，其余为排版参数（行列号均从 0 开始）。

    formats：列 → 数字格式名（NUMBER_FORMATS 的键）；row_formats：行 → 数字格式名（优先于列）
    roles：行 → 行样式（header / section / total / key / note / title）；header_rows：顶部表头行数
    inputs：普通数值是否为硬编码输入（蓝色）；widths：列 → 列宽，未给出的按内容自动估算
    freeze：冻结到 (行, 列)，默认冻结表头与首列；wrap_cols：需要自动换行的长文本列
    """
    rows: list[list[Any]]
    formats: dict[int, str] = field(default_factory=dict)
    row_formats: dict[int, str] = field(default_factory=dict)
    roles: dict[int, str] = field(default_factory=dict)
    header_rows: int = 1
    inputs: bool = False
    widths: dict[int, float] = field(default_factory=dict)
    freeze: tuple[int, int] | None = None
    wrap_cols: tuple[int, ...] = ()
    tab_color: str | None = None
    charts: list[Chart] = field(default_factory=list)
    notes: dict[int, str] = field(default_factory=dict)
    notes_header: str = "来源及计算口径"
    notes_width: float = 60.0


# ------------------------------------------------------------------ 样式表
class _StyleBook:
    """把 (行样式, 数字格式, 字色, 换行, 对齐) 组合成 cellXfs，按需去重编号。"""

    def __init__(self) -> None:
        self.fonts: list[str] = [f'<font><sz val="{BODY_FONT_SIZE}"/><name val="{FONT}"/><family val="2"/></font>']
        self.fills: list[str] = ['<fill><patternFill patternType="none"/></fill>',
                                 '<fill><patternFill patternType="gray125"/></fill>']
        self.borders: list[str] = ["<border><left/><right/><top/><bottom/><diagonal/></border>"]
        self.numfmts: dict[str, int] = {}
        self.xfs: list[str] = ['<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>']
        self._cache: dict[tuple, int] = {}

    @staticmethod
    def _intern(items: list[str], xml: str) -> int:
        if xml not in items:
            items.append(xml)
        return items.index(xml)

    def _font(self, spec: tuple[bool, bool, str | None, int], name: str) -> int:
        return self._intern(self.fonts, f"<font>{_font_props(spec, name, 'name')}</font>")

    def _fill(self, rgb: str | None) -> int:
        if not rgb:
            return 0
        return self._intern(self.fills, f'<fill><patternFill patternType="solid"><fgColor rgb="FF{rgb}"/>'
                                        '<bgColor indexed="64"/></patternFill></fill>')

    def _border(self, top: tuple[str, str] | None, bottom: tuple[str, str] | None) -> int:
        def side(tag, spec):
            return f'<{tag} style="{spec[0]}"><color rgb="FF{spec[1]}"/></{tag}>' if spec else f"<{tag}/>"
        return self._intern(self.borders, "<border><left/><right/>" + side("top", top) + side("bottom", bottom)
                            + "<diagonal/></border>")

    def _numfmt(self, name: str | None) -> int:
        if not name:
            return 0
        if name not in self.numfmts:
            self.numfmts[name] = 164 + len(self.numfmts)
        return self.numfmts[name]

    def xf(self, role: str, fmt: str | None, color: str | None, wrap: bool, numeric: bool, cjk: bool = False) -> int:
        key = (role, fmt, color, wrap, numeric, cjk)
        if key in self._cache:
            return self._cache[key]
        font = self._font(font_spec(role, color), CJK_FONT if cjk else FONT)
        fill = self._fill({"header": NAVY, "section": SECTION_FILL, "key": KEY_FILL, "axis": SECTION_FILL}.get(role))
        border = {
            "header": self._border(None, ("medium", NAVY)),
            "total": self._border(("thin", "000000"), ("thin", RULE)),
            "body": self._border(None, ("hair", RULE)),
            "key": self._border(("thin", RULE), ("thin", RULE)),
            "section": self._border(None, ("thin", RULE)),
            "axis": self._border(None, ("hair", RULE)),
        }.get(role, 0)
        horiz = "center" if role == "header" else ("right" if numeric else "left")
        align = f'<alignment horizontal="{horiz}" vertical="center"' + (' wrapText="1"' if wrap or role == "header" else "") + "/>"
        nf = self._numfmt(fmt)
        apply_nf = ' applyNumberFormat="1"' if nf else ""
        self.xfs.append(f'<xf numFmtId="{nf}" fontId="{font}" fillId="{fill}" borderId="{border}" xfId="0"'
                        f'{apply_nf} applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">{align}</xf>')
        self._cache[key] = len(self.xfs) - 1
        return self._cache[key]

    def xml(self) -> str:
        nf = "".join(f'<numFmt numFmtId="{i}" formatCode="{escape(NUMBER_FORMATS[n], {chr(34): "&quot;"})}"/>'
                     for n, i in self.numfmts.items())
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                f"<styleSheet {_NS}>"
                + (f'<numFmts count="{len(self.numfmts)}">{nf}</numFmts>' if self.numfmts else "")
                + f'<fonts count="{len(self.fonts)}">{"".join(self.fonts)}</fonts>'
                + f'<fills count="{len(self.fills)}">{"".join(self.fills)}</fills>'
                + f'<borders count="{len(self.borders)}">{"".join(self.borders)}</borders>'
                + '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                + f'<cellXfs count="{len(self.xfs)}">{"".join(self.xfs)}</cellXfs>'
                + '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                + "</styleSheet>")


# ------------------------------------------------------------------ 单元格
_LINK_RE = re.compile(r"^'?[^!'()]+'?!\$?[A-Z]+\$?\d+(?:&\"\")?$")  # 纯跨表引用（含 &"" 转文本）


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _text_width(v: Any) -> float:
    s = f"{v:,.2f}" if _is_num(v) else str(v)
    return sum(2.0 if unicodedata.east_asian_width(ch) in "WF" else 1.0 for ch in s)


def font_spec(role: str, color: str | None) -> tuple[bool, bool, str | None, int]:
    """行样式 → (加粗, 斜体, 字色, 字号)；单元格样式与富文本各段共用，保证观感一致。"""
    bold = role in ("header", "section", "total", "title", "axis")
    color = "FFFFFF" if role == "header" else (GREY_TEXT if role == "note" else NAVY if role == "title" else color)
    size = TITLE_FONT_SIZE if role == "title" else NOTE_FONT_SIZE if role == "note" else BODY_FONT_SIZE
    return bold, role == "note", color, size


def _font_props(spec: tuple[bool, bool, str | None, int], name: str, tag: str) -> str:
    bold, italic, color, size = spec
    return (("<b/>" if bold else "") + ("<i/>" if italic else "") + f'<sz val="{size}"/>'
            + (f'<color rgb="FF{color}"/>' if color else "") + f'<{tag} val="{name}"/><family val="2"/>')


def _is_cjk(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in "WF"


def _rich_text(text: str, spec: tuple[bool, bool, str | None, int]) -> str:
    """按字符分段：中文（含全角标点）用中文字体，其余用西文字体；空格并入前一段。"""
    runs: list[list[Any]] = []
    for ch in text:
        cjk = _is_cjk(ch) if not ch.isspace() or not runs else runs[-1][0]
        if runs and runs[-1][0] == cjk:
            runs[-1][1] += ch
        else:
            runs.append([cjk, ch])
    return "".join(f'<r><rPr>{_font_props(spec, CJK_FONT if cjk else FONT, "rFont")}</rPr>'
                   f'<t xml:space="preserve">{escape(seg)}</t></r>' for cjk, seg in runs)


def _cell_xml(ref: str, v: Any, s: int, spec: tuple[bool, bool, str | None, int]) -> str:
    st = f' s="{s}"' if s else ""
    if isinstance(v, Formula):
        attr = f' t="array" ref="{ref}"' if v.array else ""
        body = f"<f{attr}>{escape(v.expr)}</f>"
        val = "" if v.value is None else v.value
        if _is_num(val):
            return f'<c r="{ref}"{st}>{body}<v>{val!r}</v></c>'
        return f'<c r="{ref}"{st} t="str">{body}<v>{escape(str(val))}</v></c>'
    if v is None or v == "":
        return f'<c r="{ref}"{st}/>' if s else ""
    if isinstance(v, bool):
        v = str(v)
    if _is_num(v):
        return f'<c r="{ref}"{st}><v>{v!r}</v></c>'
    text = str(v)
    if any(_is_cjk(ch) for ch in text):
        return f'<c r="{ref}"{st} t="inlineStr"><is>{_rich_text(text, spec)}</is></c>'
    return f'<c r="{ref}"{st} t="inlineStr"><is><t xml:space="preserve">{escape(text)}</t></is></c>'


def _row_role(sh: Sheet, r: int) -> str:
    return sh.roles.get(r) or ("header" if r < sh.header_rows else "body")


def _auto_widths(sh: Sheet) -> dict[int, float]:
    widths: dict[int, float] = {}
    for r, row in enumerate(sh.rows):
        role = _row_role(sh, r)
        if role in ("title", "note"):
            continue
        for c, raw in enumerate(row):
            v = raw.value if isinstance(raw, Cell) else raw
            v = v.value if isinstance(v, Formula) else v
            if v in (None, "") or c in sh.wrap_cols:
                continue
            # 表头允许折成两行；单格说明文字（如小节标题）不撑宽列
            if role == "section" and len(row) == 1:
                continue
            widths[c] = max(widths.get(c, 0.0), _text_width(v) / (2.0 if role == "header" else 1.0))
    ncols = max((len(r) for r in sh.rows), default=0)
    return {c: sh.widths.get(c) or (60.0 if c in sh.wrap_cols else min(max(widths.get(c, 8.0) + 2.5, 10.0), 48.0))
            for c in range(ncols)}


def _sheet_xml(sh: Sheet, book: _StyleBook, has_drawing: bool = False) -> str:
    base_ncols = max((len(r) for r in sh.rows), default=0)
    ncols = base_ncols + 2 if sh.notes else base_ncols
    col_w = _auto_widths(sh)
    if sh.notes:
        col_w[base_ncols] = 2.5
        col_w[base_ncols + 1] = sh.notes_width
    body = []
    for r, row in enumerate(sh.rows):
        role_r = _row_role(sh, r)
        row = list(row)
        if sh.notes:
            if role_r == "header":
                row += [Cell(None, role="note"), Cell(sh.notes_header, role="header")]
            elif r in sh.notes:
                row += [Cell(None, role="note"), Cell(sh.notes[r], role="note")]
        cells = []
        # 小节标题条铺满全表宽；表头、合计、关键行只覆盖本表的列
        span = ncols if role_r == "section" and row else len(row)
        for c in range(span):
            raw = row[c] if c < len(row) else None
            v = raw.value if isinstance(raw, Cell) else raw
            role = getattr(raw, "role", None) or role_r
            cached = v.value if isinstance(v, Formula) else v
            numeric = _is_num(cached) or cached == "NM" or (isinstance(v, Formula) and cached == "")
            fmt = getattr(raw, "fmt", None) or (v.fmt if isinstance(v, Formula) else None) \
                or sh.row_formats.get(r) or (sh.formats.get(c) if role not in ("header", "title") or _is_num(cached) else None)
            if not (numeric or isinstance(v, Formula)):
                fmt = None
            if isinstance(v, Formula):
                color = LINK_GREEN if _LINK_RE.match(v.expr) else None
            elif _is_num(v):
                is_input = raw.input if isinstance(raw, Cell) and raw.input is not None else sh.inputs
                color = INPUT_BLUE if is_input and r >= sh.header_rows else None
            else:
                color = None
            # 公式返回的文字（如引用的公司名）不能分段设字体：含中文时整格用中文字体
            cjk = isinstance(v, Formula) and isinstance(cached, str) and any(_is_cjk(ch) for ch in cached)
            s = book.xf(role, fmt, color, c in sh.wrap_cols, numeric and role not in ("header",), cjk)
            cells.append(_cell_xml(f"{_col(c)}{r + 1}", v, s, font_spec(role, color)))
        body.append(f'<row r="{r + 1}"{_row_height(sh, r, role_r, col_w)}>{"".join(cells)}</row>')

    cols = [f'<col min="{c + 1}" max="{c + 1}" width="{w:.1f}" customWidth="1"/>' for c, w in col_w.items()]
    fr, fc = sh.freeze if sh.freeze is not None else (sh.header_rows, 1 if ncols > 1 else 0)
    if fr or fc:
        tl = f"{_col(fc)}{fr + 1}"
        split = (f'xSplit="{fc}" ' if fc else "") + (f'ySplit="{fr}" ' if fr else "")
        pane = "bottomRight" if fr and fc else ("bottomLeft" if fr else "topRight")
        view = (f'<sheetView showGridLines="0" zoomScale="90" workbookViewId="0"><pane {split}topLeftCell="{tl}" '
                f'activePane="{pane}" state="frozen"/><selection pane="{pane}" activeCell="{tl}" sqref="{tl}"/></sheetView>')
    else:
        view = '<sheetView showGridLines="0" zoomScale="90" workbookViewId="0"/>'
    tab = f'<tabColor rgb="FF{sh.tab_color}"/>' if sh.tab_color else ""
    drawing = '<drawing r:id="rId1"/>' if has_drawing else ""
    rns = ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"' if has_drawing else ""
    return (('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             f'<worksheet {_NS}{rns}>'
             f'<sheetPr>{tab}<pageSetUpPr fitToPage="1"/></sheetPr>'
             f'<sheetViews>{view}</sheetViews><sheetFormatPr defaultRowHeight="16"/>')
            + (f"<cols>{''.join(cols)}</cols>" if cols else "")
            + f'<sheetData>{"".join(body)}</sheetData>'
            + '<pageMargins left="0.5" right="0.5" top="0.6" bottom="0.6" header="0.3" footer="0.3"/>'
            + '<pageSetup paperSize="9" orientation="landscape" fitToWidth="1" fitToHeight="0"/>'
            + drawing + "</worksheet>")


def _row_height(sh: Sheet, r: int, role: str, col_w: dict[int, float]) -> str:
    """表头文字超出列宽时两行高，否则单行；正文 16 磅；长文本换行列留给 Excel 自动行高。"""
    row = sh.rows[r]
    texts = [(c, (x.value if isinstance(x, Cell) else x)) for c, x in enumerate(row)]
    if role == "title":
        return ' ht="24" customHeight="1"'
    if role == "note":
        return ' ht="16" customHeight="1"'
    if role == "header":
        wraps = any(v not in (None, "") and not isinstance(v, Formula) and _text_width(v) > col_w.get(c, 10) - 1
                    for c, v in texts)
        return f' ht="{36 if wraps else 24}" customHeight="1"'
    if any(c in sh.wrap_cols and v not in (None, "") for c, v in texts):
        return ""
    return ' ht="20" customHeight="1"'


def _safe_name(name: str, used: set[str]) -> str:
    base = "".join("_" if ch in '[]:*?/\\' else ch for ch in name)[:31] or "Sheet"
    out, k = base, 1
    while out in used:
        k += 1
        out = f"{base[:28]}_{k}"
    used.add(out)
    return out


_CALC = '<calcPr fullCalcOnLoad="1"/>'


def _has_formula(sheets: dict[str, Sheet]) -> bool:
    return any(isinstance(v.value if isinstance(v, Cell) else v, Formula)
               for sh in sheets.values() for row in sh.rows for v in row)


def _chart_xml(chart: Chart, sheet_name: str, chart_index: int) -> str:
    """生成最小但完整的簇状柱形图 OOXML；数据仍保留在工作表中，便于审计。"""
    sheet_ref = "'" + sheet_name.replace("'", "''") + "'!"
    absolute = lambda rg: ":".join(re.sub(r"([A-Z]+)(\d+)", r"$\1$\2", ref) for ref in rg.split(":"))  # noqa: E731
    cat = sheet_ref + absolute(chart.categories)
    series_xml = []
    for i, s in enumerate(chart.series):
        values = sheet_ref + absolute(s.values)
        series_xml.append(
            f'<c:ser><c:idx val="{i}"/><c:order val="{i}"/>'
            f'<c:tx><c:v>{escape(s.name)}</c:v></c:tx>'
            f'<c:spPr><a:solidFill><a:srgbClr val="{s.color}"/></a:solidFill>'
            '<a:ln><a:noFill/></a:ln></c:spPr>'
            f'<c:cat><c:strRef><c:f>{escape(cat)}</c:f></c:strRef></c:cat>'
            f'<c:val><c:numRef><c:f>{escape(values)}</c:f></c:numRef></c:val></c:ser>')
    ax1, ax2 = 100000 + chart_index * 2, 100001 + chart_index * 2
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
            '<c:chart><c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="zh-CN" '
            f'sz="1100" b="1"/><a:t>{escape(chart.title)}</a:t></a:r></a:p></c:rich></c:tx>'
            '<c:layout/><c:overlay val="0"/></c:title><c:autoTitleDeleted val="0"/>'
            '<c:plotArea><c:layout/><c:barChart><c:barDir val="col"/><c:grouping val="clustered"/>'
            '<c:varyColors val="0"/>' + ''.join(series_xml) +
            f'<c:axId val="{ax1}"/><c:axId val="{ax2}"/></c:barChart>'
            f'<c:catAx><c:axId val="{ax1}"/><c:scaling><c:orientation val="minMax"/></c:scaling>'
            f'<c:axPos val="b"/><c:tickLblPos val="nextTo"/><c:crossAx val="{ax2}"/>'
            '<c:crosses val="autoZero"/><c:auto val="1"/><c:lblAlgn val="ctr"/><c:lblOffset val="100"/></c:catAx>'
            f'<c:valAx><c:axId val="{ax2}"/><c:scaling><c:orientation val="minMax"/></c:scaling>'
            f'<c:axPos val="l"/><c:numFmt formatCode="{escape(chart.number_format)}" sourceLinked="0"/>'
            f'<c:majorGridlines/><c:tickLblPos val="nextTo"/><c:crossAx val="{ax1}"/>'
            '<c:crosses val="autoZero"/><c:crossBetween val="between"/></c:valAx></c:plotArea>'
            '<c:legend><c:legendPos val="b"/><c:layout/><c:overlay val="0"/></c:legend>'
            '<c:plotVisOnly val="1"/><c:dispBlanksAs val="gap"/><c:showDLblsOverMax val="0"/></c:chart>'
            '<c:printSettings><c:headerFooter/><c:pageMargins b="0.75" l="0.7" r="0.7" t="0.75" '
            'header="0.3" footer="0.3"/><c:pageSetup/></c:printSettings></c:chartSpace>')


def _drawing_xml(charts: list[Chart]) -> str:
    anchors = []
    for i, chart in enumerate(charts, 1):
        c1, r1, c2, r2 = chart.anchor
        marker = lambda c, r: f'<xdr:col>{c}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{r}</xdr:row><xdr:rowOff>0</xdr:rowOff>'
        anchors.append(
            f'<xdr:twoCellAnchor><xdr:from>{marker(c1, r1)}</xdr:from><xdr:to>{marker(c2, r2)}</xdr:to>'
            '<xdr:graphicFrame macro=""><xdr:nvGraphicFramePr>'
            f'<xdr:cNvPr id="{i + 1}" name="图表 {i}"/><xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr>'
            '<xdr:xfrm/><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart">'
            f'<c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
            f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rId{i}"/>'
            '</a:graphicData></a:graphic></xdr:graphicFrame><xdr:clientData/></xdr:twoCellAnchor>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
            'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">' + ''.join(anchors) + '</xdr:wsDr>')


def write_xlsx(path: str | Path, sheets: dict[str, Sheet | list[list[Any]]]) -> None:
    """sheets：表名 → Sheet（或二维列表，按默认排版）。"""
    specs = {k: v if isinstance(v, Sheet) else Sheet(v) for k, v in sheets.items()}
    used: set[str] = set()
    names = [_safe_name(n, used) for n in specs]
    book = _StyleBook()
    sheet_xml = [_sheet_xml(sh, book, bool(sh.charts)) for sh in specs.values()]
    n = len(names)
    chart_count = sum(len(sh.charts) for sh in specs.values())
    drawing_count = sum(bool(sh.charts) for sh in specs.values())
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        overrides = "\n".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, n + 1))
        overrides += "".join(f'<Override PartName="/xl/drawings/drawing{i}.xml" '
                             'ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>'
                             for i in range(1, drawing_count + 1))
        overrides += "".join(f'<Override PartName="/xl/charts/chart{i}.xml" '
                             'ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>'
                             for i in range(1, chart_count + 1))
        z.writestr("[Content_Types].xml", _CT.format(sheets=overrides))
        z.writestr("_rels/.rels", _RELS)
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   f'<workbook {_NS} '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(nm)}" sheetId="{i}" r:id="rId{i}"/>' for i, nm in enumerate(names, 1))
                   + "</sheets>" + (_CALC if _has_formula(specs) else "") + "</workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                             f'relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, n + 1))
                   + f'<Relationship Id="rId{n + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                     'relationships/styles" Target="styles.xml"/>'
                   + "</Relationships>")
        z.writestr("xl/styles.xml", book.xml())
        for i, xml in enumerate(sheet_xml, 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", xml)
        chart_id = drawing_id = 0
        for sheet_id, (name, sh) in enumerate(zip(names, specs.values()), 1):
            if not sh.charts:
                continue
            drawing_id += 1
            z.writestr(f"xl/worksheets/_rels/sheet{sheet_id}.xml.rels",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       f'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                       f'relationships/drawing" Target="../drawings/drawing{drawing_id}.xml"/></Relationships>')
            z.writestr(f"xl/drawings/drawing{drawing_id}.xml", _drawing_xml(sh.charts))
            rels = []
            for i, chart in enumerate(sh.charts, 1):
                chart_id += 1
                z.writestr(f"xl/charts/chart{chart_id}.xml", _chart_xml(chart, name, chart_id))
                rels.append(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/'
                            f'2006/relationships/chart" Target="../charts/chart{chart_id}.xml"/>')
            z.writestr(f"xl/drawings/_rels/drawing{drawing_id}.xml.rels",
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       + ''.join(rels) + '</Relationships>')
