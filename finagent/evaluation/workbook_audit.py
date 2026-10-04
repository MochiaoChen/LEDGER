"""只读审计与被评 PDF 同包交付的 XLSX；不改写工作簿。"""

from __future__ import annotations

import hashlib
import math
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG = "{http://schemas.openxmlformats.org/package/2006/relationships}"
SHEET_FILE = re.compile(r"xl/worksheets/sheet\d+\.xml")
TOLERANCE_MM = 1e-4  # 工作簿单位为百万元；比写入缓存的 6 位小数略宽
# 公式里允许出现的约定常数：0/1、平均余额的 0.5 与 2、年化的 4/12/365、百分数换算的 100
CONVENTION_CONSTANTS = {0.0, 0.5, 1.0, 2.0, 4.0, 12.0, 100.0, 365.0}
VOLATILE = re.compile(r"\b(NOW|TODAY|RAND|RANDBETWEEN|OFFSET|INDIRECT)\s*\(", re.I)
CELL_REF = re.compile(r"(\$?)([A-Z]{1,3})(\$?)(\d+)(?![\d(])")
QUOTED = re.compile(r'"[^"]*"|\'[^\']*\'!|[A-Za-z_\u4e00-\u9fff][\w\u4e00-\u9fff.]*!')
NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?(?:[eE]-?\d+)?)(?![\w.(])")
# 这些函数的最后一个参数是精度或分位序号，不是业务假设
INDEX_ARG_FUNCS = ("ROUND", "ROUNDUP", "ROUNDDOWN", "QUARTILE", "QUARTILE.INC", "PERCENTILE", "PERCENTILE.INC",
                   "LARGE", "SMALL", "INDEX", "CHOOSE")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def find_matching_workbook(pdf: Path, deliveries_root: Path) -> Path | None:
    """只接受同目录 report.pdf 与被评 PDF 字节完全一致的 sheet.xlsx。"""
    if not pdf.is_file() or not deliveries_root.is_dir():
        return None
    target_hash = _sha256(pdf)
    matches = []
    for report in deliveries_root.glob("*/report.pdf"):
        workbook = report.with_name("sheet.xlsx")
        if workbook.is_file() and _sha256(report) == target_hash:
            matches.append(workbook)
    return matches[0] if len(matches) == 1 else None


def _cells(z: zipfile.ZipFile) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, int]]:
    book = ET.fromstring(z.read("xl/workbook.xml"))
    relations = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    targets = {r.attrib["Id"]: r.attrib["Target"].lstrip("/") for r in relations.findall(f"{PKG}Relationship")}
    sheets: dict[str, dict[str, dict[str, Any]]] = {}
    counters = {"formula_count": 0, "missing_cache_count": 0, "error_count": 0, "broken_ref_count": 0}
    for sheet in book.findall(f"{MAIN}sheets/{MAIN}sheet"):
        target = targets[sheet.attrib[f"{REL}id"]]
        path = target if target.startswith("xl/") else f"xl/{target}"
        if not SHEET_FILE.fullmatch(path):
            raise ValueError("工作簿含无法读取的工作表路径")
        root = ET.fromstring(z.read(path))
        cells: dict[str, dict[str, Any]] = {}
        for cell in root.iter(f"{MAIN}c"):
            formula = cell.find(f"{MAIN}f")
            value = cell.find(f"{MAIN}v")
            ftext = (formula.text or "") if formula is not None else None
            raw = value.text if value is not None else None
            label = "".join(t.text or "" for t in cell.iter(f"{MAIN}t"))
            cells[cell.attrib["r"]] = {"formula": ftext, "value": raw, "label": label}
            if formula is not None:
                counters["formula_count"] += 1
                counters["missing_cache_count"] += raw is None
                counters["broken_ref_count"] += "#REF!" in ftext.upper()
            counters["error_count"] += cell.attrib.get("t") == "e"
        sheets[sheet.attrib["name"]] = cells
    return sheets, counters


def _number(sheets: dict[str, dict[str, dict[str, Any]]], sheet: str, cell: str) -> float:
    raw = sheets[sheet][cell]["value"]
    if raw is None:
        raise ValueError(f"{sheet}!{cell} 缺计算缓存")
    value = float(raw)
    if not math.isfinite(value):
        raise ValueError(f"{sheet}!{cell} 非有限数")
    return value


def _check_three_statements(sheets: dict[str, dict[str, dict[str, Any]]]) -> tuple[list[dict[str, Any]], float]:
    bs, cf, inc, assumptions = ("三表-资产负债表", "三表-现金流量表", "三表-利润表", "三表-假设")
    expected_labels = {
        (bs, "A11"): "资产总计", (bs, "A21"): "负债和所有者权益总计",
        (bs, "A23"): "勾稽检查", (bs, "A24"): "资产总计 − 负债和所有者权益总计",
        (bs, "A25"): "现金流量表期末现金 − 货币资金", (bs, "A26"): "留存收益滚动",
        (bs, "A27"): "PP&E 滚动", (bs, "A28"): "有息负债滚动",
        (cf, "A21"): "期末现金", (inc, "A17"): "净利润",
    }
    for (sheet, cell), label in expected_labels.items():
        if label not in sheets[sheet][cell]["label"]:
            raise ValueError(f"{sheet}!{cell} 标签与预期不符，不能套用现有三表核对口径")
    def find_row(label: str) -> int:
        matches = [int(ref[1:]) for ref, cell in sheets[assumptions].items()
                   if ref.startswith("A") and cell["label"] == label]
        if len(matches) != 1:
            raise ValueError(f"{assumptions} 中缺少唯一的 {label} 行")
        return matches[0]

    ppe_start = find_row("辅助计算：固定资产（固定资产 + 在建工程）")
    debt_start = find_row("辅助计算：有息负债与利息")
    dividend_row = find_row("现金分红")
    for offset, label in enumerate(("期初余额", "加：资本开支", "减：折旧摊销", "期末余额"), 1):
        if sheets[assumptions][f"A{ppe_start + offset}"]["label"] != label:
            raise ValueError("固定资产滚动行与预期不符")
    for offset, label in enumerate(("期初余额", "减：偿还", "期末余额"), 1):
        if sheets[assumptions][f"A{debt_start + offset}"]["label"] != label:
            raise ValueError("有息负债滚动行与预期不符")
    bs_cells = sheets[bs]
    forecast_cols = [col for col in "DEFGHIJKLMNOP" if f"{col}24" in bs_cells and bs_cells[f"{col}24"]["formula"]]
    if not forecast_cols:
        raise ValueError("没有找到可核对的预测期三表勾稽公式")
    checks = []
    max_residual = 0.0
    for col in forecast_cols:
        prev = chr(ord(col) - 1)
        tests = [
            (24, "资产负债平衡", _number(sheets, bs, f"{col}11") - _number(sheets, bs, f"{col}21"),
             f"ROUND({col}11-{col}21,6)"),
            (25, "现金与现金流量表衔接", _number(sheets, cf, f"{col}21") - _number(sheets, bs, f"{col}6"),
             f"ROUND('三表-现金流量表'!{col}21-{col}6,6)"),
            (26, "留存收益滚动", _number(sheets, bs, f"{prev}19") + _number(sheets, inc, f"{col}17")
             - _number(sheets, assumptions, f"{col}{dividend_row}") - _number(sheets, bs, f"{col}19"),
             f"ROUND({prev}19+'三表-利润表'!{col}17-'三表-假设'!{col}{dividend_row}-{col}19,6)"),
            (27, "固定资产滚动", _number(sheets, assumptions, f"{col}{ppe_start + 1}")
             + _number(sheets, assumptions, f"{col}{ppe_start + 2}") - _number(sheets, assumptions, f"{col}{ppe_start + 3}")
             - _number(sheets, assumptions, f"{col}{ppe_start + 4}"),
             f"ROUND('三表-假设'!{col}{ppe_start + 1}+'三表-假设'!{col}{ppe_start + 2}-'三表-假设'!{col}{ppe_start + 3}-'三表-假设'!{col}{ppe_start + 4},6)"),
            (28, "有息负债滚动", _number(sheets, assumptions, f"{col}{debt_start + 1}")
             - _number(sheets, assumptions, f"{col}{debt_start + 2}") - _number(sheets, assumptions, f"{col}{debt_start + 3}"),
             f"ROUND('三表-假设'!{col}{debt_start + 1}-'三表-假设'!{col}{debt_start + 2}-'三表-假设'!{col}{debt_start + 3},6)"),
        ]
        for row, label, residual, expected_formula in tests:
            cell = bs_cells[f"{col}{row}"]
            formula_ok = cell["formula"] == expected_formula
            cache_ok = abs(_number(sheets, bs, f"{col}{row}") - residual) <= TOLERANCE_MM
            passed = formula_ok and cache_ok and abs(residual) <= TOLERANCE_MM
            max_residual = max(max_residual, abs(residual))
            checks.append({"name": label, "cell": f"{bs}!{col}{row}", "passed": passed,
                           "formula_link_ok": formula_ok, "cache_matches_independent": cache_ok,
                           "residual_mm": round(residual, 8)})
    return checks, max_residual


def _col_num(col: str) -> int:
    n = 0
    for ch in col:
        n = n * 26 + ord(ch) - 64
    return n


def _col_name(n: int) -> str:
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _drop_index_args(body: str) -> str:
    """去掉 ROUND 精度、QUARTILE 分位序号等最后一个参数（按括号配对，支持嵌套）。"""
    out, i = [], 0
    pattern = re.compile(r"\b(" + "|".join(re.escape(f) for f in INDEX_ARG_FUNCS) + r")\(", re.I)
    while (m := pattern.search(body, i)):
        out.append(body[i:m.end()])
        depth, j, last_comma = 1, m.end(), None
        while j < len(body) and depth:
            ch = body[j]
            depth += ch == "("
            depth -= ch == ")"
            if ch == "," and depth == 1:
                last_comma = j
            j += 1
        inner = body[m.end():j - 1]
        if last_comma is not None and re.fullmatch(r"\s*-?[\d.]+\s*", body[last_comma + 1:j - 1]):
            inner = body[m.end():last_comma]
        out.append(_drop_index_args(inner) + ")")
        i = j
    out.append(body[i:])
    return "".join(out)


def hardcoded_literals(formula: str) -> list[str]:
    """公式里写死的数字（约定常数、函数精度参数、比较容差除外）。假设应放在单元格里被引用，便于追溯与情景切换。"""
    body = CELL_REF.sub(" R ", _drop_index_args(QUOTED.sub(" ", formula)))
    found = []
    for m in NUMBER.finditer(body):
        v = float(m.group(1))
        if v in CONVENTION_CONSTANTS:
            continue
        if body[:m.start()].rstrip().endswith(("<", ">", "=")) and v <= 0.01:
            continue  # 勾稽检查里的容差
        found.append(m.group(1))
    return found


def _relative(formula: str, col: int) -> str:
    """把相对列引用换成相对偏移（R1C1 思路），同一行不同期的公式写法相同时结果相同。"""
    return CELL_REF.sub(lambda m: m.group(0) if m.group(1) else f"C[{_col_num(m.group(2)) - col}]{m.group(3)}{m.group(4)}",
                        formula)


def formula_controls(sheets: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    """跨期公式一致性、公式内写死数字、易变函数。
    跨期一致性只抓“孤岛”：某一期的公式写法与左右相邻两期都不同、而左右两期彼此相同（如中间一年被手工改成数值或改了引用）。
    历史期与预测期的分界、首个预测期衔接资产负债表、末列合计或同比，都是写法的一次性切换，不算异常。"""
    rows: dict[tuple[str, str], dict[int, str]] = {}
    hardcodes, volatile = [], []
    for sheet, cells in sheets.items():
        for ref, cell in cells.items():
            formula = cell["formula"]
            if not formula:
                continue
            col, row = re.fullmatch(r"([A-Z]+)(\d+)", ref).groups()
            rows.setdefault((sheet, row), {})[_col_num(col)] = _relative(formula, _col_num(col))
            if lits := hardcoded_literals(formula):
                hardcodes.append({"cell": f"{sheet}!{ref}", "formula": formula, "literals": lits})
            if VOLATILE.search(formula):
                volatile.append({"cell": f"{sheet}!{ref}", "formula": formula})
    islands = []
    for (sheet, row), cols in rows.items():
        for c, pattern in cols.items():
            left, right = cols.get(c - 1), cols.get(c + 1)
            if left is not None and left == right != pattern:
                islands.append({"cell": f"{sheet}!{_col_name(c)}{row}",
                                "formula": sheets[sheet][f"{_col_name(c)}{row}"]["formula"],
                                "neighbor_formula": sheets[sheet][f"{_col_name(c - 1)}{row}"]["formula"]})
    return {"inconsistent_formulas": islands, "hardcoded_formulas": hardcodes, "volatile_formulas": volatile}


def audit_workbook(path: Path | None) -> dict[str, Any]:
    """静态公式结构 + 基于前置缓存值的独立勾稽复算；不宣称已重算整本 Excel。"""
    if path is None:
        return {"status": "not_run", "reason": "未找到与被评 PDF 完全匹配的配套 sheet.xlsx"}
    result: dict[str, Any] = {"status": "fail", "workbook_sha256": _sha256(path), "workbook_name": path.name,
                              "method": "只读公式结构检查；以来源单元格缓存值独立复算三表勾稽"}
    try:
        with zipfile.ZipFile(path) as z:
            sheets, counters = _cells(z)
        result.update(counters)
        controls = formula_controls(sheets)
        result.update(controls)
        checks, max_residual = _check_three_statements(sheets)
        result.update({"checks": checks, "max_abs_residual_mm": round(max_residual, 8)})
        # 跨期写法孤岛判失败；写死数字与易变函数列为警告（约定常数靠白名单识别，不宜一票否决）
        result["warnings"] = ([f"{h['cell']} 公式内写死数字 {'、'.join(h['literals'])}" for h in controls["hardcoded_formulas"]]
                              + [f"{v['cell']} 使用易变函数" for v in controls["volatile_formulas"]])
        result["status"] = "pass" if (counters["formula_count"] > 0
                                       and not any(counters[k] for k in ("missing_cache_count", "error_count", "broken_ref_count"))
                                       and not controls["inconsistent_formulas"]
                                       and all(row["passed"] for row in checks)) else "fail"
        if controls["inconsistent_formulas"] and "reason" not in result:
            result["reason"] = "跨期公式写法不一致：" + "、".join(x["cell"] for x in controls["inconsistent_formulas"][:5])
        result["limitation"] = ("未在 Excel/LibreOffice 中重算全部公式；只验证公式结构、缓存、跨期写法一致性、"
                                "公式内写死数字与五组勾稽关系")
    except (OSError, KeyError, ValueError, zipfile.BadZipFile, ET.ParseError) as exc:
        result["reason"] = str(exc)
    return result
