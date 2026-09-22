"""三表 / 情景敏感性 / 可比公司 / 业绩深度分析 + 自研 DCF 与原插件 DCF 的一致性。"""

import copy
import json
import math
import random

import pytest

from conftest import ROOT, SAMPLES
from finagent import pipelines
from finagent.core.tracing import RunTracer
from finagent.tasks.valuation import dcf
from finagent.vendor import load


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    c = {"input": str(SAMPLES / "annual_report_2024.md"), "fiscal_year": 2024, "company": "样例",
         "assumptions": str(SAMPLES / "valuation_assumptions.json"), "report": str(SAMPLES / "research_draft.md"),
         "peers": str(SAMPLES / "peers.csv"), "estimates": str(SAMPLES / "estimates.csv"),
         "guidance": str(SAMPLES / "guidance.csv"), "llm": None}
    with RunTracer("test_new", tmp_path_factory.mktemp("runs")) as tr:
        pipelines.run("all", c)
    c["run_dir"] = tr.dir
    return c


def test_three_statement_ties_out(ctx):
    ts = ctx["three_statement"]
    assert ts["hard_failures"] == []
    assert all(c["status"] == "pass" for c in ts["integrity"])
    assert ts["statements"]["利润表"]["periods"] == ["FY2025", "FY2026", "FY2027", "FY2028", "FY2029"]


def test_three_statement_plan_passes_original_validator(ctx, tmp_path):
    from finagent.tasks.valuation import three_statement as ts_mod
    plan, _ = ts_mod.build_plan(ctx["extract"]["facts"], json.loads((SAMPLES / "valuation_assumptions.json").read_text()),
                                company="样例", period="2024")
    plan.pop("_historical_drivers")
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False))
    assert load("three-statement-model-builder", "validate_plan").validate(str(path)) == []


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
    assert r["low"] == pytest.approx(13.93297, rel=1e-6) and r["high"] == pytest.approx(17.3567006, rel=1e-6)
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


def _plans():
    ref_tpl = json.loads((ROOT / "third_party/public_equity_investing/skills/dcf-model-builder/assets/plan_template.json")
                         .read_text(encoding="utf-8"))
    out = [ref_tpl]
    rnd = random.Random(7)
    for _ in range(20):
        p = copy.deepcopy(ref_tpl)
        for sc in p["scenarios"].values():
            sc["revenue_growth"] = [rnd.uniform(-0.05, 0.25) for _ in range(5)]
            sc["ebit_margin"] = [rnd.uniform(0.05, 0.3) for _ in range(5)]
            sc["nwc_percent_revenue"] = [rnd.uniform(0.0, 0.4) for _ in range(5)]
            sc["terminal_growth_rate"] = rnd.uniform(0.0, 0.03)
        p["forecast"]["mid_year_convention"] = rnd.random() < 0.7
        if rnd.random() < 0.3:
            p["terminal_value"]["method"] = "exit_multiple"
        out.append(p)
    return out


def test_dcf_matches_original_engine():
    ref = load("dcf-model-builder", "skill_core")
    for plan in _plans():
        rp, npl = ref.normalize_plan(plan), dcf.normalize_plan(plan)
        for s in dcf.SCENARIOS:
            a, b = ref.run_scenario(rp, s), dcf.run_scenario(npl, s)
            for k in ("enterprise_value", "equity_value", "value_per_share", "tv_percent_ev"):
                assert math.isclose(a[k], b[k], rel_tol=1e-9), (s, k)
        ra = {(r["sensitivity"], r["x_value"], r["y_value"]): r["value"] for r in ref.run_sensitivities(rp)["rows"]}
        rb = {(r["sensitivity"], r["x_value"], r["y_value"]): r["value"] for r in dcf.run_sensitivities(npl)["rows"]}
        assert ra.keys() == rb.keys()
        for k in ra:
            assert (ra[k] is None and rb[k] is None) or math.isclose(ra[k], rb[k], rel_tol=1e-9), k
