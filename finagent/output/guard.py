"""解读数字护栏（Skill 版本）：按单位与展示精度核对文字中的每个数字。

“58.62 亿元”只与真值 ÷1e8 后四舍五入到 2 位小数比较，“14.49%”只与百分数值比较，
因此不会因为中间计算结果数量多而“碰巧”放行编造的数字。
真值只取结论性产物：财报真值表与分析、业绩分析、DCF 结果、可比公司结果、核查结论中的正确值（truth_display）；
不含研报断言原文（研报里的错误数字不能成为出处），也不含三表/敏感性等中间网格。
只核对“有出处”，不核对数字与指标的对应关系。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCALE = {"亿元": 1e8, "亿": 1e8, "万元": 1e4, "万": 1e4}
NUM_UNIT_RE = re.compile(r"(-?\d[\d,]*(?:\.\d+)?)\s*(万元/吨|元/吨|亿元|万元|亿|万|元/股|元|%|个百分点|倍|x|X)?")
TRUTH_FILES = ("financials/analysis.json", "financials/earnings.json", "financials/facts.json",
               "financials/extras.json", "valuation/valuation.json", "valuation/comps.json",
               "valuation/non_operating_assets.json", "valuation/forecast_summary.json",
               "valuation/segment_forecast.json")


def _numbers(obj: Any, out: list[float]) -> None:
    """递归收集 JSON 中的数值；字符串中的“58.62亿元”这类写法换算为基本单位。"""
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, str):
        for num, unit in NUM_UNIT_RE.findall(obj):
            try:
                out.append(float(num.replace(",", "")) * SCALE.get(unit, 1.0))
            except ValueError:
                pass
    elif isinstance(obj, dict):
        for v in obj.values():
            _numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _numbers(v, out)


def truth_values(run: Path) -> list[float]:
    vals: list[float] = []
    for rel in TRUTH_FILES:
        p = run / rel
        if p.exists():
            _numbers(json.loads(p.read_text(encoding="utf-8")), vals)
    findings = run / "check" / "findings.json"
    if findings.exists():
        for f in json.loads(findings.read_text(encoding="utf-8"))["findings"]:
            _numbers(f.get("truth_display", ""), vals)  # 只取正确值；suggestion 会引用研报的错误数字
    return vals


def _decimals(s: str) -> int:
    return len(s.split(".", 1)[1]) if "." in s else 0


def check_text(text: str, values: list[float]) -> list[str]:
    """返回找不到出处的数字（带单位原样）。年份、一位整数序号、页码不检查。"""
    absv = sorted({abs(v) for v in values})
    bad: list[str] = []
    for m in NUM_UNIT_RE.finditer(text):
        raw, unit = m.group(1), m.group(2) or ""
        if not unit and re.fullmatch(r"(19|20)\d{2}|\d", raw):
            continue
        before, after = text[:m.start()].rstrip()[-1:], text[m.end():].lstrip()[:1]
        if not unit and (before == "第" or after in ("页", "年", "月", "日", "节")):
            continue
        x = abs(float(raw.replace(",", "")))
        tol = 0.5 * 10 ** -_decimals(raw) * (1 + 1e-9) + 1e-12
        # 金额按 亿/万 换算；百分数也可来自以小数存储的比例（如 1.28 → 128%）
        factors = [1 / SCALE[unit]] if unit in SCALE else ([1.0, 100.0] if unit in ("%", "个百分点") else [1.0])
        if not any(abs(v * f - x) <= tol for v in absv for f in factors):
            bad.append(raw + unit)
    return sorted(set(bad))


def check_binding(text: str, run: Path, source: str = "commentary.md") -> list[dict[str, Any]]:
    """把解读当作一份研报，用研报核查引擎按“指标 + 期间”逐条核对（能识别的表述才核对）。
    返回判定不是“正确/无法核实”的断言：指标口径、期间、单位或数值与真值表不符。"""
    from ..parsing.document import Document, _parse_markdown
    from ..tasks.report_check.claims import extract_claims
    from ..tasks.report_check.verify import verify_claims

    analysis = json.loads((run / "financials" / "analysis.json").read_text(encoding="utf-8"))
    year = int(str(analysis["period"])[:4])
    doc = Document(source, "", _parse_markdown(text, source))
    claims = extract_claims(doc, default_year=year, llm=None)
    findings = verify_claims(claims, analysis["truth_table"])["findings"]
    segment = _segment_values(run)
    return [{"quote": f["quote"], "verdict": f["verdict"], "truth": f["truth_display"], "explanation": f["explanation"]}
            for f in findings
            if f["verdict"] not in ("正确", "无法核实") and not _is_segment_claim(_context(text, f["quote"]), segment)
            and not _is_forecast(_sentence(text, f["quote"]), year)]


def _sentence(text: str, quote: str) -> str:
    """断言所在的整句（到上一个句号或换行为止；分号连接的分句共享“预计”等上下文）。"""
    i = text.find(quote)
    if i < 0:
        return quote
    start = max(text.rfind(ch, 0, i) for ch in "。\n") + 1
    return text[start:i + len(quote)]


def _is_forecast(sentence: str, year: int) -> bool:
    """预测表述（“预计”“预测”或出现晚于报告期的年份）：数字只核对出处（check_text），不与历史真值表比对。"""
    if any(k in sentence for k in ("预计", "预测")):
        return True
    return any(int(y) > year for y in re.findall(r"(20\d{2})", sentence))


def _context(text: str, quote: str, before: int = 24) -> str:
    """断言所在的上下文：向前取若干字（分部名称常在指标之前），向后补全单位（如“万元/吨”）。"""
    i = text.find(quote)
    if i < 0:
        return quote
    j = i + len(quote)
    tail = re.match(r"\s*(?:/吨|/股)?", text[j:])
    return text[max(0, i - before):j + (tail.end() if tail else 0)]


def _segment_values(run: Path) -> dict[str, list[float]]:
    """补充表格（financials/extras.json）：行名 → 该行全部已核对数值（含程序算出的比率，按比率标签归属到行名）。"""
    p = run / "financials" / "extras.json"
    if not p.exists():
        return {}
    ex = json.loads(p.read_text(encoding="utf-8"))
    out: dict[str, list[float]] = {}
    for t in ex.get("tables", []):
        for r in t["rows"]:
            out.setdefault(r["label"], []).extend(v for v in r["values"] if v is not None)
    for r in ex.get("ratios", []):
        out.setdefault(r["label"], []).append(r["value"])
    return out


def _is_segment_claim(quote: str, segment: dict[str, list[float]]) -> bool:
    """“茅台酒毛利率 93.53%”这类分部表述：句中点名了补充表格的行（茅台酒、系列酒、直销……），
    且数字按展示精度等于该行某个已核对的值，则按分部数据核对通过，不再与公司整体指标比较。"""
    m = list(NUM_UNIT_RE.finditer(quote))
    if not m or not segment:
        return False
    raw, unit = m[-1].group(1), m[-1].group(2) or ""
    x = abs(float(raw.replace(",", "")))
    tol = 0.5 * 10 ** -_decimals(raw) * (1 + 1e-9) + 1e-12
    scale = SCALE.get(unit, 1.0)
    head = quote[:m[-1].start()]
    for label, vals in segment.items():
        key = re.sub(r"^其他|（上期）$", "", label)  # “其他系列酒”在正文里常写作“系列酒”
        hit = key in head or (key.endswith("吨价") and key[:-2] in head)
        if key and hit and any(abs(abs(v) / scale - x) <= tol for v in vals):
            return True
    return False
