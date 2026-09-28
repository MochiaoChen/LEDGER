"""PR #2 的两个用例，按现行实现改写：单季拆分在 analyze 中完成，DCF 计划需要三表模型输出。"""

import json

import pytest

from conftest import SAMPLES
from finagent.tasks.financials.analyze import analyze
from finagent.tasks.valuation.build_plan import DRIVER_FIELDS, build_plan


def _fact(metric, period, value):
    return {"metric_id": metric, "period": period, "value": value, "raw": str(value), "unit": "元",
            "method": "rule_table", "source": {"source": "fixture"}}


def test_single_quarter_split_and_explicit_value_wins():
    facts = [_fact("revenue", "2024Q1", 10), _fact("revenue", "2024H1", 25),
             _fact("revenue", "2024Q1-3", 48), _fact("revenue", "2024", 70),
             _fact("revenue", "2024Q3", 99)]
    a = analyze(facts)
    cells = {(c["metric_id"], c["period"]): c for c in a["truth_table"]}
    assert cells[("revenue", "2024Q2")]["value"] == 15
    assert cells[("revenue", "2024Q3")]["value"] == 99  # 财报列示的单季不被推算值覆盖
    assert cells[("revenue", "2024Q4")]["value"] == 22
    assert cells[("revenue", "2024Q4")]["formula"] == "全年 − 前三季度累计"
    # 列示值与“前三季度 − 上半年”（= 23）不符，记为勾稽失败而不是静默取舍
    q3 = next(t for t in a["tieouts"] if t["check"] == "营业收入 2024 年第三季度 = 前三季度累计 − 上半年累计")
    assert q3["status"] == "fail"


def test_ebit_excludes_investment_and_fair_value_gains():
    assumptions = json.loads((SAMPLES / "valuation_assumptions.json").read_text(encoding="utf-8"))
    facts = [_fact("revenue", "2024", 1_000_000_000), _fact("total_profit", "2024", 120_000_000),
             _fact("finance_expense", "2024", 10_000_000), _fact("investment_income", "2024", 20_000_000),
             _fact("fair_value_change", "2024", -5_000_000), _fact("total_shares", "2024", 100_000_000)]
    n = len(assumptions["scenarios"]["base"]["revenue_growth"])
    stub = {"dcf_drivers": {k: {f: [0.1] * n for f in DRIVER_FIELDS} for k in assumptions["scenarios"]}}
    plan, notes = build_plan(facts, assumptions, company="测试", period="2024", source_name="x", three_statement=stub)
    assert plan["historicals"]["ebit"] == pytest.approx(115.0)  # 120 + 10 − 20 − (−5)：公允价值变动损失加回
    assert any("投资收益" in n["detail"] and "公允价值" in n["detail"] for n in notes)
