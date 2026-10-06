"""研报内部一致性（评分标准 N-02 的程序判定，也用于研报纠错核查与 guard）：只在同口径时比较，命中即确认。"""

import json

from finagent.evaluation.checks import check_consistency, check_guard
from finagent.evaluation.rubric import Bundle, load_rubric
from finagent.output.sources import run_guard
from finagent.tasks.report_check.consistency import check, describe

BASE = """# 摘要

**盈利预测及投资建议：** 我们预计公司 2026—2028 年归母净利润分别为 5.42 亿元、7.16 亿元、9.18 亿元；DCF 基准情景每股价值 49.88 元，给予“卖出”评级。

## 估值

基准情景预测期自由现金流现值 50.60 亿元，股权价值 181.59 亿元，每股价值 49.88 元。
悲观情景企业价值 49.47 亿元，每股价值 20.62 元；乐观情景企业价值 371.40 亿元，每股价值 109.06 元。

## 盈利预测

基准情景 2026—2028 年营业收入分别为 23.45 亿元、32.83 亿元、44.32 亿元，同比增长 38%、40%、35%。

## 投资建议

我们预计 2026—2028 年归母净利润分别为 5.42 亿元、7.16 亿元、9.18 亿元，DCF 基准情景每股价值 49.88 元，均低于 9 月 30 日收盘价 450.4 元 [S4]，给予“卖出”评级。
"""


def _items(text, year=2025):
    return {f["item"] for f in check(text, year)["findings"]}


def test_clean_report_has_no_findings():
    r = check(BASE, 2025)
    assert r["findings"] == [] and r["compared"] >= 3


def test_rating_flip_detected():
    text = BASE.replace("给予“卖出”评级。\n\n## 估值", "给予“买入”评级。\n\n## 估值", 1)
    f = check(text, 2025)["findings"]
    assert [x["type"] for x in f] == ["rating_mismatch"]
    assert "“买入”" in describe(f[0]) and "“卖出”" in describe(f[0])


def test_value_per_share_and_forecast_mismatch():
    text = BASE.replace("股权价值 181.59 亿元，每股价值 49.88 元", "股权价值 181.59 亿元，每股价值 54.87 元")
    text = text.replace("分别为 5.42 亿元、7.16 亿元、9.18 亿元，DCF", "分别为 5.42 亿元、7.61 亿元、9.18 亿元，DCF")
    assert _items(text) == {"每股价值", "2027 年归母净利润"}


def test_growth_list_and_single_year_forecast():
    text = BASE + "\n2027 年营业收入 33.10 亿元。\n" + "公司 2026—2028 年营业收入分别为 23.45 亿元、32.83 亿元、44.32 亿元，同比增长 38%、43%、35%。\n"
    assert _items(text) == {"2027 年营业收入", "2027 年营业收入同比"}


def test_display_precision_tolerated():
    text = BASE.replace("股权价值 181.59 亿元，每股价值 49.88 元", "股权价值 181.59 亿元，每股价值 49.9 元")
    assert check(text, 2025)["findings"] == []


def test_not_comparable_contexts_are_skipped():
    extra = "\n".join([
        "其中光模块 2026—2028 年营业收入分别为 20.00 亿元、30.00 亿元、40.00 亿元。",   # 分部口径
        "卖方一致预期 2026—2028 年营业收入分别为 30.00 亿元、40.00 亿元、50.00 亿元 [S9]。",  # 外部来源
        "EBIT 利润率比基准高 5 个百分点时，每股价值 60.36 元。",                     # 敏感性 / 条件
        "若毛利率维持 2025 年水平，基准情景每股价值 60.36 元。",                     # 条件句
        "悲观至乐观情景区间为 20.62 元至 109.06 元。",                                # 区间
        "2025 年营业收入 16.99 亿元。2025 年营业收入 3.37 亿元。",                    # 历史期由真值表核对，这里不比
    ])
    assert check(BASE + "\n" + extra + "\n", 2025)["findings"] == []


def test_rating_rule_text_and_others_ratings_ignored():
    extra = "评级说明：买入：≥20%；增持：≥5%。\n卖方 7 家机构一致评级“买入” [S10]。\n美银证券给予“买入”评级 [S11]。\n"
    assert check(BASE + extra, 2025)["findings"] == []


def _bundle(tmp_path, text):
    run = tmp_path / "run"
    (run / "financials").mkdir(parents=True)
    (run / "financials" / "analysis.json").write_text(json.dumps({"period": "2025", "truth_table": []}), encoding="utf-8")
    work = tmp_path / "work"
    (work / "report").mkdir(parents=True)
    (work / "report" / "narrative.md").write_text(text, encoding="utf-8")
    return Bundle("测试公司", run, work)


def test_evaluation_check_marks_hit(tmp_path):
    flipped = BASE.replace("给予“卖出”评级。\n\n## 估值", "给予“买入”评级。\n\n## 估值", 1)
    hit = check_consistency(_bundle(tmp_path / "a", flipped), {})
    assert hit["passed"] is True and "投资评级" in hit["evidence"]
    assert check_consistency(_bundle(tmp_path / "b", BASE), {})["passed"] is False


def test_guard_reports_but_gate_does_not_double_count(tmp_path):
    flipped = BASE.replace("给予“卖出”评级。\n\n## 估值", "给予“买入”评级。\n\n## 估值", 1)
    b = _bundle(tmp_path, flipped)
    g = run_guard(b.run, flipped)
    assert g["contradictions"] and g["ok"] is False
    # 硬闸门只看出处类问题；这里文稿数字在空真值表里都找不到出处，所以按出处判失败，但理由里不含矛盾
    assert "矛盾" not in check_guard(b, {})["detail"]


def test_guard_keeps_citations_when_checking_contradictions(tmp_path):
    """外部机构的评级、目标价带 [S编号]，不是本报告的结论；guard 不能先去掉编号再查矛盾。"""
    # 取自中际旭创交付稿：去掉 [S10] 后，高盛目标价会被当成本报告的乐观情景每股价值
    text = BASE + "\n高盛给予 A 股目标价 2645 元、H 股目标价 3267 港元 [S10]，我们的乐观情景每股价值 109.06 元。\n"
    assert not check(text, 2025)["findings"]
    assert run_guard(_bundle(tmp_path, text).run, text)["contradictions"] == []


def test_rubric_v2_n02_is_program():
    r = load_rubric()
    items = {i["id"]: i for i in r["items"]}
    assert r["version"] == "report_v2"
    assert items["N-02"]["judge"] == "program" and items["N-02"]["check"] == "consistency"
    assert items["N-04"]["judge"] == "llm"


def test_scenario_read_from_clause_for_value_per_share():
    """同一句里“基准情景每股价值 X，乐观情景 Y”：每股价值按所在分句归入基准，不误判为乐观情景矛盾。"""
    extra = "DCF 基准情景每股价值 49.88 元，乐观情景 109.06 元，当前股价 450.4 元 [S6] 接近乐观情景。\n"
    r = check(BASE + extra, 2025)
    assert r["findings"] == []
