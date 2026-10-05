"""反向 DCF：解出的隐含值代回正向 DCF 必须等于参考股价；无解时给出可达的最高每股价值。"""

import json

import pytest

from conftest import SAMPLES
from finagent import pipelines
from finagent.core.tracing import RunTracer
from finagent.output.guard import check_text, truth_values
from finagent.tasks.valuation import dcf, reverse_dcf


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    c = {"input": str(SAMPLES / "annual_report_2024.md"), "fiscal_year": 2024, "company": "星河智造",
         "assumptions": str(SAMPLES / "valuation_assumptions.json"), "peers": str(SAMPLES / "peers.csv")}
    with RunTracer("rdcf", tmp_path_factory.mktemp("runs")) as tr:
        pipelines.run("valuation", c)
    return tr.dir


@pytest.fixture(scope="module")
def plan(run_dir):
    return dcf.normalize_plan(json.loads((run_dir / "valuation" / "plan.json").read_text(encoding="utf-8")))


def _rdcf(run_dir):
    return json.loads((run_dir / "valuation" / "reverse_dcf.json").read_text(encoding="utf-8"))


def test_implied_values_reprice_to_current_price(run_dir, plan):
    res = _rdcf(run_dir)
    assert res["status"] == "ok"
    price = res["current_price"]
    keys = {"revenue_growth": "growth_delta", "ebit_margin": "margin_delta", "wacc": "wacc_delta",
            "terminal_growth": "g_delta", "exit_multiple": "multiple_delta"}
    solved = [r for r in res["levers"] if r.get("implied") is not None]
    assert len(solved) >= 3
    for r in solved:
        vps = dcf.run_scenario(plan, "base", **{keys[r["lever"]]: r["annual_shift"]})["value_per_share"]
        assert vps == pytest.approx(price, abs=1e-5), r["lever"]


def test_grades_follow_base_and_history(run_dir):
    lv = {r["lever"]: r for r in _rdcf(run_dir)["levers"]}
    m = lv["ebit_margin"]
    # 样例参考股价高于基准每股价值，隐含利润率必然高于基准
    assert m["implied"] > m["base"]
    expect = "超出历史最好水平" if m["implied"] > m["historical_max"] else "高于基准假设，但在历史区间内"
    assert m["grade"] == expect
    assert lv["wacc"]["implied"] < lv["wacc"]["base"]


def test_unreachable_lever_reports_max_value(run_dir, plan):
    """样例中提高增速会被营运资本与资本开支吃掉，每股价值先升后降、到不了参考股价。"""
    g = {r["lever"]: r for r in _rdcf(run_dir)["levers"]}["revenue_growth"]
    assert g["implied"] is None and g["grade"] == "单独调整达不到参考股价"
    assert g["max_inside_range"] is True
    assert g["max_value_per_share"] < _rdcf(run_dir)["current_price"]
    assert g["max_value_per_share"] > dcf.run_scenario(plan, "base")["value_per_share"]


def test_low_price_solves_growth_below_base(run_dir, plan):
    val = json.loads((run_dir / "valuation" / "valuation.json").read_text(encoding="utf-8"))
    base_vps = val["value_range"]["base"]
    res = reverse_dcf.run(plan, val, base_vps * 0.8, [])
    g = {r["lever"]: r for r in res["levers"]}["revenue_growth"]
    assert g["implied"] < g["base"] and g["grade"] == "不高于基准假设"
    assert g["historical_max"] is None


def test_skipped_without_price(run_dir, plan):
    val = json.loads((run_dir / "valuation" / "valuation.json").read_text(encoding="utf-8"))
    assert reverse_dcf.run(plan, val, None, [])["status"] == "skipped"


def test_guard_accepts_reverse_dcf_numbers(run_dir):
    lv = {r["lever"]: r for r in _rdcf(run_dir)["levers"]}
    text = f"现价隐含预测期平均 EBIT 利润率 {lv['ebit_margin']['implied'] * 100:.2f}%。"
    assert check_text(text, truth_values(run_dir)) == []
    assert "## 八、股价隐含了什么" in (run_dir / "valuation" / "report.md").read_text(encoding="utf-8")
