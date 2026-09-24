"""极简 XLSX 写出（标准库 zipfile + OOXML），无需 openpyxl。数字写为数值单元格，其余为内联字符串；
Formula 写为公式单元格（附缓存值，打开即显示；含公式的工作簿设置打开时重算）。"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

_CT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
{sheets}
</Types>"""
_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""


def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


@dataclass
class Formula:
    """公式单元格。expr 不带前导 "="；value 为缓存值（None 表示空串）；array=True 写为数组公式（CSE）。"""
    expr: str
    value: Any = None
    array: bool = False


def _formula_cell(ref: str, f: Formula) -> str:
    attr = f' t="array" ref="{ref}"' if f.array else ""
    body = f"<f{attr}>{escape(f.expr)}</f>"
    v = "" if f.value is None else f.value
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f'<c r="{ref}">{body}<v>{v!r}</v></c>'
    return f'<c r="{ref}" t="str">{body}<v>{escape(str(v))}</v></c>'


def _cell(ref: str, v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, Formula):
        return _formula_cell(ref, v)
    if isinstance(v, bool):
        v = str(v)
    if isinstance(v, (int, float)):
        return f'<c r="{ref}"><v>{v!r}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{escape(str(v))}</t></is></c>'


def _sheet_xml(rows: list[list[Any]]) -> str:
    body = []
    for r, row in enumerate(rows, 1):
        cells = "".join(_cell(f"{_col(c)}{r}", v) for c, v in enumerate(row))
        body.append(f'<row r="{r}">{cells}</row>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(body)}</sheetData></worksheet>')


def _safe_name(name: str, used: set[str]) -> str:
    base = "".join("_" if ch in '[]:*?/\\' else ch for ch in name)[:31] or "Sheet"
    out, k = base, 1
    while out in used:
        k += 1
        out = f"{base[:28]}_{k}"
    used.add(out)
    return out


_CALC = '<calcPr fullCalcOnLoad="1"/>'


def _has_formula(sheets: dict[str, list[list[Any]]]) -> bool:
    return any(isinstance(v, Formula) for rows in sheets.values() for row in rows for v in row)


def write_xlsx(path: str | Path, sheets: dict[str, list[list[Any]]]) -> None:
    used: set[str] = set()
    names = [_safe_name(n, used) for n in sheets]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CT.format(sheets="\n".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(names) + 1))))
        z.writestr("_rels/.rels", _RELS)
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                   + "".join(f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"/>' for i, n in enumerate(names, 1))
                   + "</sheets>" + (_CALC if _has_formula(sheets) else "") + "</workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                             f'relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(names) + 1))
                   + "</Relationships>")
        for i, rows in enumerate(sheets.values(), 1):
            z.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(rows))
