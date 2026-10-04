"""研报内部一致性：同一指标在文中两处给出不同数值，或评级前后不一。

不需要真值表，只看研报自身；历史财务数字已由真值表核对（数字护栏、指标期间核对），这里只管真值表管不到的：
  - 本报告给出的投资评级；
  - 每股价值（基准 / 悲观 / 乐观情景）；
  - 预测年度（晚于报告期）的公司整体收入、归母净利润、扣非归母净利润、净利润、每股收益、毛利率，
    及其同比增速；支持“2026—2028 年营业收入分别为 A、B、C”的列举写法。
误报控制优先：任何一项对不上号就不进入比较，所以命中即“内部矛盾已确认”。
  - 句子（以 。；换行 断句）出现外部来源（[S编号]、卖方、一致预期等）不比：那是别人的数字；
  - 句子出现条件、敏感性、区间字样不比：情景对不上号；
  - 情景按句中“悲观 / 乐观 / 基准”判定，都没有算基准，多个同现不比（每股价值先看所在分句）；
  - 指标前除年份、期间与“我们预计”等虚词外还有别的字（如“其中光模块收入”），说明不是公司整体口径，不比；
  - 数值按展示精度比较：|a − b| 超过两者舍入容差之和才算不同（58.6 与 58.62 不算矛盾）。
"""

from __future__ import annotations

import re
from typing import Any

from ...core.numbers import half_ulp

UNIT_SCALE = {"亿元": 1e8, "百万元": 1e6, "万元": 1e4, "千元": 1e3, "元": 1.0}
SENT_RE = re.compile(r"[^。；;\n]+[。；;]?")
YEAR_RE = re.compile(r"20\d{2}")
NUM = r"(-?\d+(?:,\d{3})*(?:\.\d+)?)"
EXTERNAL = re.compile(r"\[S\d+\]|卖方|一致预期|一致评级|市场预期|机构|外资|券商|同行|可比公司|行业平均|研报")
CONDITIONAL = re.compile(r"敏感|浮动|上调|下调|上下|若|如果|假如|倘若|一旦|即便|即使|退出|矩阵|最高|最低|区间|"
                         r"不考虑|剔除|模拟|比如|例如|时[，,]|时每股|改用|计算")
RANGE_NEAR = re.compile(r"^\s*(?:至|到|—|–|～|~)")
HEAD_DROP = re.compile(r"20\d{2}\s*(?:[—–\-~～至到]\s*20\d{2})?\s*(?:年度?|E)?|"
                       r"我们|预计|预测|公司|全年|实现|的|为|将|分别|基准情景|基准|情景|下|DCF|\*+|[，,：:\s]")
METRICS = {
    "revenue": ("营业总收入", "营业收入", "营收", "收入"),
    "np_parent": ("归属于上市公司股东的净利润", "归属于母公司股东的净利润", "归母净利润"),
    "np_parent_deducted": ("扣除非经常性损益后的净利润", "扣非归母净利润", "扣非净利润"),
    "net_profit": ("净利润",),
    "eps": ("基本每股收益", "每股收益", "EPS"),
    "gross_margin": ("综合毛利率", "毛利率"),
}
METRIC_NAME = {"revenue": "营业收入", "np_parent": "归母净利润", "np_parent_deducted": "扣非归母净利润",
               "net_profit": "净利润", "eps": "每股收益", "gross_margin": "毛利率", "value_per_share": "每股价值"}
ALIAS = sorted(((a, m) for m, al in METRICS.items() for a in al), key=lambda x: -len(x[0]))
ALIAS_RE = "|".join(re.escape(a) for a, _ in ALIAS)
UNIT_RE = r"(亿元|百万元|万元|元|%)"
VALS = rf"{NUM}\s*{UNIT_RE}(?:\s*、\s*{NUM}\s*{UNIT_RE})*"
LIST_RE = re.compile(rf"(20\d{{2}})\s*[—–\-~～至到]\s*(20\d{{2}})\s*年(?:度)?\s*(?:的)?\s*({ALIAS_RE})\s*"
                     rf"(?:分别)?\s*(?:为|达到?|是|预计为)?\s*({VALS})")
SINGLE_RE = re.compile(rf"(20\d{{2}})\s*年(?:度)?\s*(?:的)?\s*({ALIAS_RE})\s*(?:为|达到?|是|预计为|将达)?\s*{NUM}\s*{UNIT_RE}")
YOY_LIST_RE = re.compile(rf"^\s*[，,]\s*(?:同比)?(?:分别)?(?:增长|增速|增速分别为|同比增长)?\s*(?:分别为)?\s*"
                         rf"({NUM}\s*%(?:\s*、\s*{NUM}\s*%)*)")
VPS_RE = re.compile(r"(每股价值|目标价|合理价值|每股内在价值)\s*(?:为|约|是)?\s*(-?\d+(?:,\d{3})*(?:\.\d+)?)\s*元(?!/)")
RATING_WORDS = "买入|增持|中性|减持|卖出"
RATING_RE = re.compile(rf"(?:给予|维持|首次覆盖[^，。；]{{0,12}}?|上调至|下调至|调整为|评级为|投资评级[:：]?)\s*"
                       rf"[“\"「『]?({RATING_WORDS})[”\"」』]?|[“\"「『]({RATING_WORDS})[”\"」』]\s*评级")


def _sentences(text: str) -> list[tuple[int, str]]:
    """(行号, 句子)；跳过表格、代码块、HTML 注释、图表指令行。"""
    out: list[tuple[int, str]] = []
    fence = False
    for ln, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s.startswith("```"):
            fence = not fence
            continue
        if fence or not s or s.startswith(("|", "<!--", "<", "{{")):
            continue
        out.extend((ln, m.group(0).strip()) for m in SENT_RE.finditer(s) if m.group(0).strip())
    return out


def _scenario(text: str) -> str | None:
    """情景：只出现悲观、乐观、基准之一即为该情景，都没有为基准，多个同现返回 None（不比）。"""
    found = [w for w in ("悲观", "乐观", "基准") if w in text]
    if len(found) > 1:
        return None
    return found[0] if found else "基准"


def _whole_company(head: str) -> bool:
    """指标前的文字去掉年份、期间与虚词后为空 → 公司整体口径。只看本句最后一个数字之后的部分。"""
    head = re.sub(r"^\s*(?:[-*]\s+)?\*\*[^*]{1,30}?[：:]\s*\*\*", "", head)  # 行首粗体小标题（“**投资建议：**”）
    head = re.split(r"\d[\d,.]*\s*(?:亿元|万元|元|%|倍)\s*[、，,]?", head)[-1]
    return HEAD_DROP.sub("", head) == ""


def _own_part(sentence: str) -> str | None:
    """去掉外部来源后本报告自己的部分；整句是别人的数字返回 None。
    带 [S编号] 的句子（常因引用收盘价）只在写明“我们”或 DCF 时保留，并删去带编号的分句。"""
    cited = re.search(r"\[S\d+\]", sentence)
    if EXTERNAL.search(re.sub(r"\[S\d+\]", "", sentence)):
        return None
    if not cited:
        return sentence
    if not re.search(r"我们|DCF", sentence):
        return None
    return "，".join(c for c in re.split(r"[，,]", sentence) if not re.search(r"\[S\d+\]", c))


def _mention(line: int, sentence: str, raw: str, unit: str, quote: str, sign: int = 1) -> dict[str, Any]:
    return {"line": line, "raw": raw, "unit": unit, "quote": quote, "sentence": sentence, "sign": sign}


def _base_value(m: dict[str, Any]) -> tuple[float, float]:
    """(按基本单位的数值, 舍入容差)。"""
    f = UNIT_SCALE.get(m["unit"], 1.0)
    return float(m["raw"].replace(",", "")) * f * m.get("sign", 1), half_ulp(m["raw"], f)


def _vals(s: str) -> list[tuple[str, str]]:
    return re.findall(rf"{NUM}\s*{UNIT_RE}", s)


def collect(text: str, report_year: int) -> dict[tuple, list[dict[str, Any]]]:
    """按比较键归组的数字提及。键：(指标, 期间, 类型, 情景)。"""
    groups: dict[tuple, list[dict[str, Any]]] = {}

    def add(key: tuple, m: dict[str, Any]) -> None:
        groups.setdefault(key, []).append(m)

    for line, full in _sentences(text):
        sent = _own_part(full)
        if sent is None or CONDITIONAL.search(sent):
            continue
        scen = _scenario(sent)
        # 每股价值（不分期间）：须写明 DCF 或情景，避免把别的“目标价”算进来；情景先看所在分句
        if re.search(r"DCF|情景|基准", sent):
            for m in VPS_RE.finditer(sent):
                if RANGE_NEAR.match(sent[m.end():]) or re.search(r"(?:至|到|—|～)\s*$", sent[:m.start()]):
                    continue
                clause = re.split(r"[，,：:]", sent[:m.start()])[-1]
                local = [w for w in ("悲观", "乐观", "基准") if w in clause]
                sc = _scenario(clause) if local else scen
                if sc is not None:
                    add(("value_per_share", "", "level", sc), _mention(line, sent, m.group(2), "元", m.group(0)))
        if scen is None:
            continue
        # 预测年度列举：2026—2028 年营业收入分别为 A、B、C[，同比增长 x%、y%、z%]
        spans = []
        for m in LIST_RE.finditer(sent):
            y0, y1, alias = int(m.group(1)), int(m.group(2)), m.group(3)
            vals = _vals(m.group(4))
            if y1 <= report_year or y1 - y0 + 1 != len(vals) or not _whole_company(sent[:m.start()]):
                continue
            metric = dict(ALIAS)[alias]
            spans.append((m.start(), m.end()))
            for y, (raw, unit) in zip(range(y0, y1 + 1), vals):
                if y > report_year:
                    add((metric, str(y), "level", scen), _mention(line, sent, raw, unit, m.group(0)))
            ym = YOY_LIST_RE.match(sent[m.end():])
            if ym and metric != "gross_margin":
                yoys = re.findall(rf"{NUM}\s*%", ym.group(1))
                if len(yoys) == len(vals):
                    for y, raw in zip(range(y0, y1 + 1), yoys):
                        if y > report_year:
                            add((metric, str(y), "yoy", scen), _mention(line, sent, raw, "%", ym.group(0)))
        # 单个预测年度：2026 年营业收入 23.45 亿元（句中只有这一个年份）
        if len(set(YEAR_RE.findall(sent))) == 1:
            for m in SINGLE_RE.finditer(sent):
                if any(a <= m.start() < b for a, b in spans) or int(m.group(1)) <= report_year:
                    continue
                if not _whole_company(sent[:m.start()]) or re.match(r"^\s*、", sent[m.end():]):
                    continue
                add((dict(ALIAS)[m.group(2)], m.group(1), "level", scen),
                    _mention(line, sent, m.group(3), m.group(4), m.group(0)))
    return groups


def ratings(text: str) -> list[dict[str, Any]]:
    """本报告给出的评级（外部来源的判定见 _own_part）。"""
    out = []
    for line, full in _sentences(text):
        sent = _own_part(full)
        if sent is None:
            continue  # 卖方、机构等别人的评级
        if "≥" in sent or len(set(re.findall(RATING_WORDS, sent))) > 1:
            continue  # 评级规则说明（“买入：≥20%；增持：≥5%…”）
        for m in RATING_RE.finditer(sent):
            out.append({"line": line, "rating": m.group(1) or m.group(2), "quote": m.group(0), "sentence": sent})
    return out


def _name(key: tuple) -> str:
    metric, period, ctype, scen = key
    return "".join(x for x in (period and f"{period} 年", METRIC_NAME[metric], "同比" if ctype == "yoy" else "",
                               f"（{scen}情景）" if scen != "基准" else "") if x)


def check(text: str, report_year: int) -> dict[str, Any]:
    """返回 {findings, compared, mentions}：findings 每条是一组互相矛盾的提及（首次提及 + 与之不一致的提及）。"""
    findings: list[dict[str, Any]] = []
    groups = collect(text, report_year)
    for key, ms in groups.items():
        first, rest = ms[0], ms[1:]
        v0, t0 = _base_value(first)
        bad = [m for m in rest if abs(_base_value(m)[0] - v0) > t0 + _base_value(m)[1] + 1e-12]
        if bad:
            findings.append({"type": "number_mismatch", "item": _name(key), "key": list(key),
                             "mentions": [first] + bad, "verdict": "内部矛盾"})
    rs = ratings(text)
    if len({r["rating"] for r in rs}) > 1:
        findings.append({"type": "rating_mismatch", "item": "投资评级", "key": ["rating"],
                         "mentions": rs, "verdict": "内部矛盾"})
    return {"findings": findings, "compared": sum(len(v) > 1 for v in groups.values()) + (len(rs) > 1),
            "mentions": sum(len(v) for v in groups.values()) + len(rs)}


def describe(f: dict[str, Any]) -> str:
    if f["type"] == "rating_mismatch":
        vals = "、".join(f"第 {m['line']} 行“{m['rating']}”" for m in f["mentions"])
    else:
        vals = "、".join(f"第 {m['line']} 行 {'-' if m['sign'] < 0 else ''}{m['raw']}{m['unit']}" for m in f["mentions"])
    return f"{f['item']}：{vals}"
