"""经营数据补充表格：分产品 / 分渠道 / 分地区收入、产销量、线上销售等经营数据。

模型按原文逐字抄录表格（带页码），程序逐个数字在该页原文中核对、按列单位换算，通过后作为运行产物
`financials/extras.json` 供研报引用（guard 也以它为出处）。这些数据不进入真值表，不参与估值计算。

文件格式见 .claude/skills/finagent-research/references/extraction.md“补充表格”。
"""

from __future__ import annotations

from typing import Any

from ...core.numbers import UNIT_FACTORS, parse_number
from ...parsing.document import Document
from .external import find_evidence

NA = {"", "-", "—", "不适用", "/"}
def _unit_ok(u: str) -> bool:
    """金额单位必须能换算为元（UNIT_FACTORS）；其余单位（%、吨、个、元/吨、各行业的计量单位……）原值保存。
    以“元”结尾却不在换算表里的（美元、千万元等）拒收：外币或少见量级要换算后另写，不能原值混入。"""
    return bool(u) and (u in UNIT_FACTORS or not u.endswith("元"))


def _column_units(table: dict[str, Any]) -> list[str]:
    cols = table.get("columns") or []
    default = table.get("unit", "元")
    return [c.get("unit", default) if isinstance(c, dict) else default for c in cols]


RATIO_UNITS = {"%": 100.0, "倍": 1.0, "元/吨": 1.0, "万元/吨": 1e-4, "元/瓶": 1.0, "pp": 1.0, "元": 1.0}
# 其他单位写 "scale"：value = 分子 / 分母 × scale（如分子为元、分母为万件，要“元/件”就写 scale = 1e-4）


def _ref_value(ref: list[str], tables: dict[str, Any], truth: dict[tuple[str, str], float] | None,
               ratios: dict[str, float] | None = None) -> float | None:
    """ref = [表 id, 行名, 列名]、["truth", 指标 ID, 期间] 或 ["ratio", 比率 id]（引用前面已算出的比率）。"""
    if len(ref) == 2 and ref[0] == "ratio":
        return (ratios or {}).get(ref[1])
    if len(ref) != 3:
        return None
    if ref[0] == "truth":
        return (truth or {}).get((ref[1], ref[2]))
    t = tables.get(ref[0])
    if not t:
        return None
    names = [c["name"] for c in t["columns"]]
    row = next((r for r in t["rows"] if r["label"] == ref[1]), None)
    return row["values"][names.index(ref[2])] if row and ref[2] in names else None


def _ratios(specs: list[dict[str, Any]], tables: list[dict[str, Any]],
            truth: dict[tuple[str, str], float] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """比率由程序计算（op 缺省为 div）：
    div    value = 分子 / 分母 × 单位系数（% ×100，万元/吨 ÷1e4；其他单位用 scale 指定）
    growth value = (分子 / 分母 − 1) × 100，单位 %（同比增速：分子为本期，分母为上期）
    diff   value = 分子 − 分母（单位 pp 或 元；如两个占比之差、本期减上期的增量）"""
    by_id = {t["id"]: t for t in tables}
    out, bad = [], []
    done: dict[str, float] = {}
    for sp in specs:
        refs = (sp.get("num", [None])[0], sp.get("den", [None])[0])
        if truth is None and ("truth" in refs or "ratio" in refs and not _ready(sp, done)):
            continue  # 预检（无真值表）时跳过引用真值表的比率，流水线中再计算
        num = _ref_value(sp.get("num", []), by_id, truth, done)
        den = _ref_value(sp.get("den", []), by_id, truth, done)
        unit, op = sp.get("unit", "%"), sp.get("op", "div")
        scale = sp.get("scale", RATIO_UNITS.get(unit))
        if num is None or den is None or (op != "diff" and not den) or not isinstance(scale, (int, float)) \
                or op not in ("div", "growth", "diff") or (op == "growth" and unit != "%"):
            bad.append({"ratio": sp.get("label"), "reason": "分子/分母找不到、运算或单位不支持"})
            continue
        value = {"div": lambda: num / den * scale, "growth": lambda: (num / den - 1) * 100,
                 "diff": lambda: num - den}[op]()
        rid = sp.get("id", sp.get("label"))
        done[rid] = value
        out.append({"id": rid, "label": sp.get("label", ""), "alias": list(sp.get("alias") or []), "unit": unit, "op": op,
                    "value": value, "num": sp["num"], "den": sp["den"]})
    return out, bad


def _ready(sp: dict[str, Any], done: dict[str, float]) -> bool:
    """引用的比率都已算出（预检时引用真值表的比率会被跳过，依赖它们的比率也一并跳过）。"""
    return all(r[1] in done for r in (sp.get("num", []), sp.get("den", [])) if len(r) == 2 and r[0] == "ratio")


def verify_extras(doc: Document, payload: dict[str, Any],
                  truth_table: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """逐表、逐格核对。金额列换算为元；%、pp、吨等按原值保存；ratios 由程序计算。返回 {tables, ratios, rejected}。"""
    tables, rejected = [], []
    for ti, t in enumerate(payload.get("tables") or []):
        units = _column_units(t)
        names = [c.get("name") if isinstance(c, dict) else str(c) for c in t.get("columns") or []]
        bad_units = [u for u in units if not _unit_ok(u)]
        if bad_units:
            rejected.append({"table": t.get("id"), "reason": f"不支持的单位：{bad_units}"})
            continue
        rows = []
        for ri, row in enumerate(t.get("rows") or []):
            page = int(row.get("page") or t.get("page") or 0)
            raws = list(row.get("values") or [])
            if len(raws) != len(names):
                rejected.append({"table": t.get("id"), "row": row.get("label"),
                                 "reason": f"列数不符：{len(raws)} 个值，表头 {len(names)} 列"})
                continue
            values, sources = [], []
            for ci, raw in enumerate(raws):
                raw = "" if raw is None else str(raw).strip()
                if raw in NA:
                    values.append(None)
                    sources.append(None)
                    continue
                v = parse_number(raw)
                ch = find_evidence(doc, page, raw) if v is not None else None
                if ch is None:
                    rejected.append({"table": t.get("id"), "row": row.get("label"), "column": names[ci],
                                     "raw": raw, "page": page, "reason": "未在所写页码的原文中找到该数字"})
                    values.append(None)
                    sources.append(None)
                    continue
                u = units[ci]
                values.append(v * UNIT_FACTORS[u] if u in UNIT_FACTORS else v)
                sources.append({"source": ch.source, "page": ch.page, "chunk_id": ch.chunk_id})
            rows.append({"label": row.get("label", ""), "alias": list(row.get("alias") or []), "raw": raws,
                         "values": values, "sources": sources})
        tables.append({"id": t.get("id") or f"t{ti + 1}", "title": t.get("title", ""), "page": t.get("page"),
                       "columns": [{"name": n, "unit": "元" if u in UNIT_FACTORS else u} for n, u in zip(names, units)],
                       "rows": rows, "note": t.get("note", "")})
    truth = None if truth_table is None else {(c["metric_id"], c["period"]): c["value"] for c in truth_table}
    ratios, bad = _ratios(payload.get("ratios") or [], tables, truth)
    return {"tables": tables, "ratios": ratios, "rejected": rejected + bad, "notes": payload.get("notes", "")}
