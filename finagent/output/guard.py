"""文稿数字护栏：按单位与展示精度核对文字中的每个数字。

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
               "valuation/segment_forecast.json", "valuation/reverse_dcf.json")


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


MM_BLOCKS = {"forecast_base", "pv_base", "bridge_base"}  # valuation.json 中以百万元计的块


def _mm_numbers(obj: Any, out: list[float], inside: bool = False) -> None:
    """估值产物以百万元计：MM_BLOCKS 内与键名以 _mm 结尾的数值另按 ×1e6 换算为元，供“17,483.72 亿元”这类表述核对。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if inside or k in MM_BLOCKS or str(k).endswith("_mm"):
                vs: list[float] = []
                _numbers(v, vs)
                out.extend(x * 1e6 for x in vs)
            else:
                _mm_numbers(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _mm_numbers(v, out, inside)


# 数字出处的类型：报告披露、外部来源是事实；程序计算是由事实推出的推论；模型预测与估值假设依赖我们的判断，属观点。
# 同一个数能在多处找到出处时，按这里的顺序取第一个（先认事实，再认推论，最后认观点）。
EVIDENCE = {"报告披露": "事实", "外部来源": "事实", "程序计算": "推论", "估值假设": "观点", "模型预测": "观点"}


def tagged_truth_values(run: Path) -> dict[str, list[float]]:
    """按出处类型分组的真值（并集即 truth_values）。财报真值表按抽取方式分披露 / 计算，其余产物按文件定类型。"""
    tags: dict[str, list[float]] = {k: [] for k in EVIDENCE}

    def j(rel: str) -> Any:
        p = run / rel
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    if (a := j("financials/analysis.json")) is not None:
        for fact in a.get("truth_table", []):
            _numbers(fact, tags["程序计算" if fact.get("method") == "derived" else "报告披露"])
        _numbers({k: v for k, v in a.items() if k != "truth_table"}, tags["程序计算"])  # 同比、勾稽、信号、单季拆分
    if (e := j("financials/earnings.json")) is not None:
        _numbers(e, tags["程序计算"])
    if (f := j("financials/facts.json")) is not None:
        _numbers(f, tags["报告披露"])
    if (x := j("financials/extras.json")) is not None:
        _numbers({k: v for k, v in x.items() if k != "ratios"}, tags["报告披露"])
        _numbers(x.get("ratios"), tags["程序计算"])
        _extras_scaled_numbers(x, tags["报告披露"])
    for rel in ("valuation/valuation.json", "valuation/forecast_summary.json", "valuation/segment_forecast.json",
                "valuation/reverse_dcf.json"):
        if (v := j(rel)) is not None:
            _numbers(v, tags["模型预测"])
            _mm_numbers(v, tags["模型预测"])
    if (c := j("valuation/comps.json")) is not None:  # 可比公司原始数据是外部输入，倍数统计与隐含价值是计算，DCF 对照是模型
        _numbers(c.get("rows"), tags["外部来源"])
        _mm_numbers({"rows": c.get("rows")}, tags["外部来源"])
        _numbers(c.get("dcf_cross_check"), tags["模型预测"])
        _mm_numbers({"dcf_cross_check": c.get("dcf_cross_check")}, tags["模型预测"])
        rest = {k: v for k, v in c.items() if k not in ("rows", "dcf_cross_check")}
        _numbers(rest, tags["程序计算"])
        _mm_numbers(rest, tags["程序计算"])
    if (n := j("valuation/non_operating_assets.json")) is not None:  # 逐项核对过原文的非经营性资产
        _numbers(n, tags["报告披露"])
        _mm_numbers(n, tags["报告披露"])
    if (sf := j("valuation/segment_forecast.json")) is not None:  # 分部预测金额以百万元计
        for block in [sf.get("base_year", {})] + list(sf.get("scenarios", {}).values()):
            for key in ("revenue", "cogs"):
                _mm_numbers({"x_mm": block.get(key)}, tags["模型预测"])
            for sg in block.get("segments", []):
                _mm_numbers({"x_mm": [sg.get("revenue"), sg.get("cogs")]}, tags["模型预测"])
    if (pl := j("valuation/plan.json")) is not None:  # 估值输入假设（WACC 各参数、终值参数）也是出处
        _numbers({k: pl.get(k) for k in ("wacc", "terminal_value")}, tags["估值假设"])
        _mm_numbers({"bridge_mm": pl.get("ev_to_equity_bridge")}, tags["报告披露"])  # 股权价值桥各项（百万元）
    if (fd := j("check/findings.json")) is not None:
        for item in fd["findings"]:
            _numbers(item.get("truth_display", ""), tags["报告披露"])  # 只取正确值；suggestion 会引用研报的错误数字
    return tags


def truth_values(run: Path) -> list[float]:
    return [v for vs in tagged_truth_values(run).values() for v in vs]


def _extras_scaled_numbers(extras: dict[str, Any], out: list[float]) -> None:
    """经营数据表按列单位存数（如 8,162 万吨存成 8162），这里按“亿/万”换算回基本单位，供带单位的正文数字比对。"""
    for table in extras.get("tables", []):
        columns = table.get("columns", [])
        for row in table.get("rows", []):
            for column, value in zip(columns, row.get("values", [])):
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    continue
                unit = str(column.get("unit") or "")
                if unit.startswith("亿"):
                    out.append(float(value) * 1e8)
                elif unit.startswith("万"):
                    out.append(float(value) * 1e4)


def _decimals(s: str) -> int:
    return len(s.split(".", 1)[1]) if "." in s else 0


def _text_numbers(text: str):
    """正文里要核对的数字：(原文, 单位)。年份、一位整数序号、页码不检查。"""
    for m in NUM_UNIT_RE.finditer(text):
        raw, unit = m.group(1), m.group(2) or ""
        if not unit and re.fullmatch(r"(19|20)\d{2}|\d", raw):
            continue
        before, after = text[:m.start()].rstrip()[-1:], text[m.end():].lstrip()[:1]
        if not unit and (before == "第" or after in ("页", "年", "月", "日", "节")):
            continue
        yield raw, unit


def _found(raw: str, unit: str, absv: list[float]) -> bool:
    x = abs(float(raw.replace(",", "")))
    tol = 0.5 * 10 ** -_decimals(raw) * (1 + 1e-9) + 1e-12
    # 金额按 亿/万 换算；百分数也可来自以小数存储的比例（如 1.28 → 128%）
    factors = [1 / SCALE[unit]] if unit in SCALE else ([1.0, 100.0] if unit in ("%", "个百分点") else [1.0])
    return any(abs(v * f - x) <= tol for v in absv for f in factors)


def check_text(text: str, values: list[float]) -> list[str]:
    """返回找不到出处的数字（带单位原样）。年份、一位整数序号、页码不检查。"""
    absv = sorted({abs(v) for v in values})
    return sorted({raw + unit for raw, unit in _text_numbers(text) if not _found(raw, unit, absv)})


def classify_text(text: str, tagged: dict[str, list[float]]) -> dict[str, Any]:
    """正文每个数字的出处类型（EVIDENCE 顺序取第一个能找到出处的）与事实 / 推论 / 观点计数。找不到出处的不计。"""
    pools = [(label, sorted({abs(v) for v in tagged.get(label, [])})) for label in EVIDENCE]
    numbers, counts = [], {"事实": 0, "推论": 0, "观点": 0}
    for raw, unit in _text_numbers(text):
        label = next((lb for lb, pool in pools if _found(raw, unit, pool)), None)
        if label is None:
            continue
        numbers.append({"number": raw + unit, "evidence": label, "class": EVIDENCE[label]})
        counts[EVIDENCE[label]] += 1
    return {"counts": counts, "numbers": numbers}


def check_binding(text: str, run: Path, source: str = "commentary.md") -> list[dict[str, Any]]:
    """把解读当作一份研报，用研报核查引擎按“指标 + 期间”逐条核对（能识别的表述才核对）。
    返回判定不是“正确/无法核实”的断言：指标口径、期间、单位或数值与真值表不符。"""
    from ..parsing.document import Document, _parse_markdown
    from ..tasks.report_check.claims import extract_claims
    from ..tasks.report_check.verify import verify_claims

    analysis = json.loads((run / "financials" / "analysis.json").read_text(encoding="utf-8"))
    year = int(str(analysis["period"])[:4])
    doc = Document(source, "", _parse_markdown(text, source))
    claims = extract_claims(doc, default_year=year)
    segment = _segment_values(run)
    claims = [c for c in claims if _binding_candidate(c, year, segment, _sentence(text, c["quote"]))]
    findings = verify_claims(claims, analysis["truth_table"])["findings"]
    return [{"quote": f["quote"], "verdict": f["verdict"], "truth": f["truth_display"], "explanation": f["explanation"]}
            for f in findings
            if f["verdict"] not in ("正确", "无法核实") and not _is_segment_claim(_context(text, f["quote"]), segment)
            and not _is_forecast(_sentence(text, f["quote"]), year)]


def _binding_candidate(claim: dict[str, Any], year: int, segment: dict[str, list[float]],
                       paragraph: str = "") -> bool:
    """只对口径明确的断言用年度合并真值表核对：预测、季度、跨年序列、分部、现金流明细等一律不比，
    以免把分部或季度数字误判为与全年合并值不符（这些数字仍要过出处核对）。"""
    sentence = claim.get("sentence", "")
    if claim.get("is_forecast") or _is_forecast(sentence, year):
        return False
    if re.search(r"(?:Q[1-4]|[一二三四]季度|第[一二三四]季度|上半年|前三季度)", sentence):
        return False
    if len(set(re.findall(r"20\d{2}", paragraph or sentence))) > 1:
        return False
    if re.search(r"\d[\d,.]*\s*(?:亿元|万元|元|%)\s*、\s*\d", sentence):
        return False
    if any(label and len(label) >= 2 and label in sentence for label in segment):
        return False
    if re.search(r"购建|支付的现金|收回的现金|折旧|所得税影响|客户|供应商|母公司|扣非|单箱|上年|非流动性资产处置|营业外收入|分部净利润|归母净利率|假设|逐年|由\s*[\d,.]+\s*(?:亿元|万元|%)\s*(?:升)?至", sentence):
        return False
    return True


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


def _context(text: str, quote: str, before: int = 24, limit: int = 80) -> str:
    """断言所在的上下文：向前取到本句（或分句）开头，至少若干字、至多 limit 字（分部名称常在句首），
    向后补全单位（如“万元/吨”）。"""
    i = text.find(quote)
    if i < 0:
        return quote
    j = i + len(quote)
    tail = re.match(r"\s*(?:/吨|/股)?", text[j:])
    start = max(text.rfind(ch, 0, i) for ch in "。；\n") + 1
    start = max(min(start, i - before), i - limit, 0)
    return text[start:j + (tail.end() if tail else 0)]


def _segment_values(run: Path) -> dict[str, list[float]]:
    """补充表格（financials/extras.json）：行名（及别名 alias）→ 该行全部已核对数值（含程序算出的比率，按比率标签归属到行名）；
    另含利润变动归因桥各项。"""
    p = run / "financials" / "extras.json"
    if not p.exists():
        return {}
    ex = json.loads(p.read_text(encoding="utf-8"))
    out: dict[str, list[float]] = {}
    for t in ex.get("tables", []):
        for r in t["rows"]:
            for name in [r["label"], *r.get("alias", [])]:
                out.setdefault(name, []).extend(v for v in r["values"] if v is not None)
    for r in ex.get("ratios", []):
        for name in [r["label"], *r.get("alias", [])]:
            out.setdefault(name, []).append(r["value"])
    ep = run / "financials" / "earnings.json"
    if ep.exists():  # 利润变动归因桥：“销售费用增加拖累 16.14 亿元”按归因项核对
        bridge = json.loads(ep.read_text(encoding="utf-8")).get("profit_bridge") or {}
        for it in bridge.get("items", []):
            out.setdefault(it["item"], []).append(it["value"])
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
