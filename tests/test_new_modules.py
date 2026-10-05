"""三表 / 情景敏感性 / 可比公司 / 业绩深度分析。与原插件引擎的对照见 test_parity_reference.py、test_golden.py。"""

import pytest

from conftest import SAMPLES
from finagent import pipelines
from finagent.core.tracing import RunTracer


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    c = {"input": str(SAMPLES / "annual_report_2024.md"), "fiscal_year": 2024, "company": "样例",
         "assumptions": str(SAMPLES / "valuation_assumptions.json"), "report": str(SAMPLES / "research_draft.md"),
         "peers": str(SAMPLES / "peers.csv"), "estimates": str(SAMPLES / "estimates.csv"),
         "guidance": str(SAMPLES / "guidance.csv")}
    with RunTracer("test_new", tmp_path_factory.mktemp("runs")) as tr:
        pipelines.run("all", c)
    c["run_dir"] = tr.dir
    return c


def test_three_statement_ties_out(ctx):
    ts = ctx["three_statement"]
    assert ts["hard_failures"] == []
    assert all(c["status"] == "pass" for c in ts["integrity"])
    assert ts["statements"]["利润表"]["periods"] == ["FY2025", "FY2026", "FY2027", "FY2028", "FY2029"]


def test_scenarios(ctx):
    sc = ctx["scenarios"]
    assert sc["readiness"]["model_status"] == "senior-review-ready"
    pts = next(t for t in sc["tables"] if t["name"] == "price_target_scenario")
    weighted = next(r for r in pts["rows"] if r["scenario"] == "probability_weighted")
    assert weighted["probability_check"] == "ok"
    triggers = next(t for t in sc["tables"] if t["name"] == "thesis_trigger_table")["rows"]
    assert len(triggers) == len([s for s in ctx["analysis"]["signals"] if s["id"] in ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")])


def test_comps(ctx):
    cp = ctx["comps"]
    assert cp["core_peer_count"] == 5
    assert cp["rows"][-1]["pe_ltm"] == "NM"  # 亏损公司 P/E 记 NM
    assert cp["stats"]["ev_revenue"]["outliers"] == ["示例003"]  # IQR 离群值
    r = cp["range"]
    assert r["low"] == pytest.approx(13.0999575, rel=1e-6) and r["high"] == pytest.approx(17.3567006, rel=1e-6)
    assert (ctx["run_dir"] / "valuation" / "comps_formula_workbook.xlsx").exists()


def test_earnings(ctx):
    e = ctx["earnings"]
    b = e["profit_bridge"]
    assert abs(b["closure_error"]) < 1e-3  # 归因桥严格闭合
    assert b["non_recurring_share_of_delta"] > 1  # 增量利润全部来自非经常性损益
    pos = {g["metric_cn"]: g["position"] for g in e["guidance"]}
    assert pos == {"归母净利润": "预告区间上半部", "扣非归母净利润": "预告区间下半部"}
    ded = next(r for r in e["beat_miss"] if r["metric_cn"] == "扣非归母净利润")
    assert ded["surprise_cons"] == pytest.approx(443.95 / 520 - 1)
    assert e["eps_quality"][0]["status"] == "需展开 EPS 质量拆解"

