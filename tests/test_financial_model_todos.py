import json

import pytest

from conftest import SAMPLES
from finagent.tasks.financials.extract import Fact, split_single_quarters
from finagent.tasks.valuation.build_plan import build_plan


def _fact(metric, period, value):
    return Fact(metric, period, value, str(value), "元", {"source": "fixture"}, metric, "rule_table")


def test_single_quarter_split_and_explicit_value_wins():
    facts = [_fact("revenue", "2024Q1", 10), _fact("revenue", "2024H1", 25),
             _fact("revenue", "2024Q1-3", 48), _fact("revenue", "2024", 70),
             _fact("revenue", "2024Q3", 99)]
    out, count = split_single_quarters(facts)
    cells = {f.key: f for f in out}
    assert count == 2
    assert cells[("revenue", "2024Q2")].value == 15
    assert cells[("revenue", "2024Q3")].value == 99
    assert cells[("revenue", "2024Q4")].value == 22
    assert cells[("revenue", "2024Q4")].source["formula"] == "2024 - 2024Q1-3"


def test_ebit_excludes_investment_and_fair_value_gains():
    assumptions = json.loads((SAMPLES / "valuation_assumptions.json").read_text(encoding="utf-8"))
    facts = [_fact("revenue", "2024", 1_000_000_000), _fact("total_profit", "2024", 120_000_000),
             _fact("finance_expense", "2024", 10_000_000), _fact("investment_income", "2024", 20_000_000),
             _fact("fair_value_change", "2024", -5_000_000), _fact("total_shares", "2024", 100_000_000)]
    plan, notes = build_plan([f.to_dict() for f in facts], assumptions, company="测试", period="2024", source_name="x")
    assert plan["historicals"]["ebit"] == pytest.approx(115.0)
    assert any("投资收益" in n["detail"] and "公允价值" in n["detail"] for n in notes)
