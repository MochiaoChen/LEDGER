"""自研引擎 vs 原 Public Equity Investing 插件引擎：样例 + 随机输入逐项对照（要求完全相等）。

原插件不在仓库内；设置 FINAGENT_REFERENCE_PLUGIN 指向插件目录后运行，找不到时整组跳过。
"""

import copy
import json
import math
import random

import pytest

from _reference import load, reference_root
from conftest import SAMPLES
from finagent import pipelines
from finagent.core.tracing import RunTracer
from finagent.tasks.financials import earnings
from finagent.tasks.valuation import dcf, scenario_tables, scenarios, ts_engine
from finagent.tasks.valuation import three_statement as ts_mod

pytestmark = pytest.mark.skipif(reference_root() is None, reason="未找到原插件，跳过对照测试")
N_RANDOM = 60


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    c = {"input": str(SAMPLES / "annual_report_2024.md"), "fiscal_year": 2024, "company": "样例",
         "assumptions": str(SAMPLES / "valuation_assumptions.json"), "report": str(SAMPLES / "research_draft.md"),
         "peers": str(SAMPLES / "peers.csv"), "estimates": str(SAMPLES / "estimates.csv"),
         "guidance": str(SAMPLES / "guidance.csv")}
    with RunTracer("parity", tmp_path_factory.mktemp("runs")):
        pipelines.run("all", c)
    c["assumptions_data"] = json.loads((SAMPLES / "valuation_assumptions.json").read_text(encoding="utf-8"))
    return c


# ---------------------------------------------------------------- 三表

def _sample_plan(ctx):
    plan, _ = ts_mod.build_plan(ctx["extract"]["facts"], ctx["assumptions_data"], company="样例", period="2024")
    plan.pop("_historical_drivers")
    return plan


def _vec(plan, rnd, lo, hi):
    return {k: rnd.uniform(lo, hi) for k in plan["revenue"]["growth_rates"]}


def _random_plans(base, n):
    """覆盖：收入/成本/营运资本/PP&E 各口径、亏损与可抵扣亏损、循环贷与现金归集、分红回购增发、契约、来源时效。"""
    rnd = random.Random(20260924)
    out = []
    for _ in range(n):
        p = copy.deepcopy(base)
        p["revenue"]["growth_rates"] = _vec(p, rnd, -0.3, 0.4)
        if rnd.random() < 0.3:
            p["revenue"].pop("base_revenue")
        c = p["costs"]
        if rnd.random() < 0.3:
            c["cogs"] = {"method": "pct_revenue", "pct_revenue": _vec(p, rnd, 0.4, 1.1)}
        else:
            c["cogs"]["gross_margin"] = _vec(p, rnd, -0.1, 0.6)
        if rnd.random() < 0.3:
            c["opex"] = {"method": "amount", "amount": rnd.uniform(0, 3000)}
        else:
            c["opex"]["pct_revenue"] = _vec(p, rnd, 0.0, 0.5)
        wc = p["working_capital"]
        for k in ("ar_days", "inventory_days", "ap_days"):
            wc[k] = _vec(p, rnd, 0, 200)
        for k in ("other_current_assets_pct_revenue", "accrued_expenses_pct_revenue", "deferred_revenue_pct_revenue"):
            wc[k] = _vec(p, rnd, 0, 0.1)
        if rnd.random() < 0.3:
            p["historicals"]["working_capital"] = {}
        pp = p["ppe"]
        pp["capex_method"] = rnd.choice(["pct_revenue", "amount"])
        pp["capex_amount"] = _vec(p, rnd, 0, 800)
        pp["capex_pct_revenue"] = _vec(p, rnd, 0, 0.2)
        pp["depreciation_method"] = rnd.choice(["pct_beginning_ppe", "pct_revenue", "amount"])
        pp["depreciation_pct_beginning_ppe"] = _vec(p, rnd, 0, 0.3)
        pp["depreciation_pct_revenue"] = rnd.uniform(0, 0.1)
        pp["depreciation_amount"] = rnd.uniform(0, 500)
        pp["disposals"] = {"FY2026": rnd.uniform(0, 100)}  # 只给一期：其余期间走最近期/最早期回退
        d = p["debt"]
        d["interest_rate"] = _vec(p, rnd, 0, rnd.choice([0.12, 1e-6]))  # 极小利率：检验不动点迭代收敛阈值
        d["revolver_commitment"] = rnd.choice([0.0, rnd.uniform(0, 3000)])
        d["beginning_revolver_drawn"] = rnd.choice([0.0, rnd.uniform(0, 500)])
        d["optional_draws"] = _vec(p, rnd, -100, 600)
        d["mandatory_amortization"] = _vec(p, rnd, 0, 900)
        d["cash_sweep"] = {"enabled": rnd.random() < 0.6, "min_cash": rnd.uniform(0, 3000),
                           "sweep_pct": rnd.uniform(0, 1)}
        d["covenants"] = rnd.choice([{}, {"min_liquidity": rnd.uniform(0, 3000), "max_net_leverage": rnd.uniform(0, 4),
                                          "min_interest_coverage": rnd.uniform(0, 8)}])
        p["tax"] = {"book_tax_rate": rnd.uniform(0, 0.4), "cash_tax_rate": rnd.uniform(0, 0.4),
                    "nol_balance": rnd.choice([0.0, rnd.uniform(0, 2000)])}
        p["equity"]["dividends"] = _vec(p, rnd, 0, 300)
        p["equity"]["buybacks"] = rnd.uniform(0, 200)
        p["equity"]["issuance"] = {"FY2025": rnd.uniform(0, 500)}
        p["meta"]["as_of_date"] = rnd.choice([None, "2025-04-30", "2026-06-30", "2023-01-01", "bad-date"])
        for src in p["source_basis"]:
            # 相对 2025-04-30 恰为 120/121、270/271、365/366 天：检验时效阈值边界
            src["as_of_date"] = rnd.choice([None, "2024-12-31", "2024-12-30", "2024-08-03", "2024-08-02",
                                            "2024-04-30", "2024-04-29", "2025-04-30", "2023-03-01"])
            if rnd.random() < 0.15:
                src["evidence_label"] = "placeholder"
        if rnd.random() < 0.1:
            p["source_basis"] = []
        if rnd.random() < 0.1:
            p["scenarios"] = {k: {"overrides": {}} for k in ("base", "downside", "upside")}
        out.append(p)
    return out


def _boundary_plans(base):
    """随机输入难以命中的边界：来源恰好 121/271 天、迭代中出现落在 [1e-8, 1e-6) 的利息变动。"""
    out = []
    for fc, hist in (("2024-12-30", "2024-08-02"), ("2024-12-31", "2024-08-03")):  # 121/271 天 与 120/270 天
        p = copy.deepcopy(base)
        p["meta"]["as_of_date"] = "2025-04-30"
        for src in p["source_basis"]:
            src["as_of_date"] = hist if "historicals" in src["covers"] else fc
        out.append(p)
    p = copy.deepcopy(base)  # 该利率下第 4 轮迭代利息变动约 6.8e-7：检验收敛阈值 1e-8
    p["debt"]["interest_rate"] = 0.005623413251903491
    p["debt"]["cash_sweep"] = {"enabled": True, "min_cash": 500.0, "sweep_pct": 0.5}
    return out + [p]


SECTIONS = ["income_statement", "working_capital", "ppe", "debt", "cash_flow_statement", "balance_sheet",
            "covenants_liquidity", "equity_flows", "checks"]


def test_three_statement_matches_reference(ctx):
    ref = load("three-statement-model-builder", "skill_core")
    base = _sample_plan(ctx)
    for i, plan in enumerate([base] + _boundary_plans(base) + _random_plans(base, N_RANDOM)):
        rp, mp = ref.normalize_plan(plan, None), ts_engine.normalize_plan(plan)
        ro, mo = ref.run_scenarios(rp), ts_engine.run_scenarios(mp)
        assert list(ro) == list(mo)
        for s in ro:
            assert [p.label for p in ro[s]["periods"]] == [p.label for p in mo[s]["periods"]]
            for sec in SECTIONS:
                assert ro[s][sec] == mo[s][sec], (i, s, sec)
            assert ref.summarize_result(ro[s]) == ts_engine.summarize(mo[s]), (i, s)
        assert ref.run_sensitivities(rp) == ts_engine.run_sensitivities(mp), i
        rh, rw, rc = ref.evaluate_hard_failures_and_warnings(rp, ro)
        mh, mw, mc = ts_engine.evaluate(mp, mo)
        assert (rh, rw, rc) == (mh, mw, mc), i
        assert ref.model_status(rh, rw, rp) == ts_engine.model_status(mh, mw, mp), i


def test_three_statement_plan_passes_original_validator(ctx, tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(_sample_plan(ctx), ensure_ascii=False))
    assert load("three-statement-model-builder", "validate_plan").validate(str(path)) == []


# ---------------------------------------------------------------- 情景表

def _random_payloads(base, n):
    rnd = random.Random(7)
    junk = [None, "", "abc", float("nan"), float("inf"), 0, 0.0, -1.0]
    out = []
    for _ in range(n):
        p = copy.deepcopy(base)
        b = p["base"]
        for k in list(b):
            r = rnd.random()
            if r < 0.15:
                b[k] = rnd.choice(junk)
            elif r < 0.25:
                b.pop(k)
            elif r < 0.45 and isinstance(b[k], (int, float)):
                b[k] = b[k] * rnd.uniform(-1.5, 2.5)
        for k in ("upside_probability", "base_probability", "downside_probability"):
            if rnd.random() < 0.3:
                b[k] = rnd.choice([None, "", 0.2, 0.5, 1.2, -0.1, "0.3"])
        if rnd.random() < 0.3:
            b["hurdle_return"] = rnd.uniform(0, 0.3)
            b.pop("required_return", None)
        if rnd.random() < 0.2:
            b.update(incremental_margin=0.3, revolver_availability=rnd.uniform(0, 500), source_id="base_src")
        r = rnd.random()
        if r < 0.3:
            p["cases"] = []  # 回落到 base 中的三情景
        elif r < 0.5:
            for c in p["cases"]:
                c["probability"] = rnd.choice([None, "", 0.1, 0.4, 0.5, 2.0, "x"])
                c["implication"] = "测试"
                if rnd.random() < 0.3:
                    c.pop("source_id")
        for ax in list(p["axes"]):
            if rnd.random() < 0.2:
                p["axes"][ax] = rnd.choice([[], "bad", [5.0, 9.0]])
            elif rnd.random() < 0.1:
                p["axes"].pop(ax)
        if rnd.random() < 0.3:
            p["triggers"] = []
        r = rnd.random()
        if r < 0.15:
            p.pop("source")
        elif r < 0.25:
            p["source"] = "not-a-dict"
        elif r < 0.35:
            p["metadata"] = {"source_name": "样例", "as_of": "2025-04-30"}
            p.pop("source")
        if rnd.random() < 0.1:
            p["_input_was_provided"] = False
        if rnd.random() < 0.05:
            p["base"] = {}
        out.append(p)
    return out


def _boundary_payloads(base):
    """随机输入难以命中的边界：收益率恰等于门槛、下行/上行比恰为 0.75、数值溢出为 inf。"""
    edge = copy.deepcopy(base)
    edge["base"].update(share_price=4.0, required_return=0.25)
    edge["cases"] = [{"scenario": "upside", "price_target": 5.0, "probability": 0.25},  # 收益 +25% = 门槛
                     {"scenario": "base", "price_target": 4.5, "probability": 0.5},
                     {"scenario": "downside", "price_target": 3.25, "probability": 0.25}]  # 18.75/25 = 0.75
    overflow = copy.deepcopy(base)
    overflow["base"].update(ebitda=1e308, revenue=1e308, eps=1e308, fcf=1e308)
    return [edge, overflow]


def test_scenario_tables_match_reference(ctx):
    ref = load("scenario-sensitivity-generator", "materialize_public_equity_sensitivities")
    base = scenarios.build_payload(ctx["extract"]["facts"], "2024", ctx["valuation"], ctx["plan"],
                                   ctx["assumptions_data"], ctx["analysis"]["signals"])
    for i, payload in enumerate([base] + _boundary_payloads(base) + _random_payloads(base, N_RANDOM * 3)):
        rt = [ref.BUILDERS[n](copy.deepcopy(payload)) for n in scenarios.TABLES]
        mt = [scenario_tables.BUILDERS[n](copy.deepcopy(payload)) for n in scenarios.TABLES]
        assert json.dumps(rt, ensure_ascii=False) == json.dumps(mt, ensure_ascii=False), i
        assert ref.classify_readiness(rt, payload) == scenario_tables.classify_readiness(mt, payload), i


# ---------------------------------------------------------------- 业绩深度分析

def _random_earnings(rnd):
    metrics_names = ["Revenue", "Operating Income", "Net Income Attributable", "GAAP EPS (Diluted)", "Adjusted EPS",
                     "Adjusted Net Income Attributable"]
    periods = ["2024", "2025"]
    values = [None, "", "MISSING", "1,234.5", float("nan"), 0, 0.0, -3.2, 12, 0.85]
    orders = rnd.sample(["1", "2", "3", "4", "5", "6", "x", 7.0], 8)
    metrics = []
    for j, name in enumerate(rnd.sample(metrics_names, rnd.randint(1, 6))):
        metrics.append({
            "MetricName": name, "Period": rnd.choice(periods),
            "Value": rnd.choice(values) if rnd.random() < 0.3 else rnd.uniform(-50, 900),
            "Units": "百万元", "GAAP_Flag": rnd.choice(["GAAP", "Non-GAAP", "gaap"]), "Segment": "Total",
            "IsTearSheet": rnd.choice(["Y", "yes", "TRUE", "1", "N", "no"]), "DisplayOrder": orders[j],
            "SourceTag": rnd.choice(["年报 p.3", "", "MISSING"]),
            "ComparableGAAPMetricName": rnd.choice(["", "GAAP EPS (Diluted)"]), "ReconciliationSourceTag": "",
            "Notes": rnd.choice(["", "non-recurring gain", "fair value, tax", "one-time impairment"])})
    est = [{"MetricName": rnd.choice(metrics_names), "Period": rnd.choice(periods),
            "EstimateType": rnd.choice(["Consensus", "Internal", ""]),
            "Value": rnd.choice(values) if rnd.random() < 0.3 else rnd.uniform(-50, 900),
            "Units": "", "AsOf": "", "Source": "", "Notes": ""} for _ in range(rnd.randint(0, 10))]
    guide = [{"MetricName": rnd.choice(metrics_names), "Period": rnd.choice(periods),
              "Low": rnd.choice(values) if rnd.random() < 0.3 else rnd.uniform(0, 500),
              "High": rnd.choice(values) if rnd.random() < 0.3 else rnd.uniform(500, 900),
              "Units": "", "GAAP_Flag": "GAAP", "Assumptions": "", "SourceTag": rnd.choice(["公告", ""]),
              "Notes": ""} for _ in range(rnd.randint(0, 4))]
    return metrics, est, guide


def test_earnings_rules_match_reference():
    pd = pytest.importorskip("pandas")
    ref = load("earnings-deep-dive", "run_plan")
    est_cols = ["MetricName", "Period", "EstimateType", "Value", "Units", "AsOf", "Source", "Notes"]
    guide_cols = ["MetricName", "Period", "Low", "High", "Units", "GAAP_Flag", "Assumptions", "SourceTag", "Notes"]
    rnd = random.Random(11)

    def same(a, b):
        return a == b or (isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b))

    # 边界：EPS 超预期幅度恰为 15%（3/20），收入无超预期
    row = {"Period": "2024", "Units": "", "GAAP_Flag": "GAAP", "Segment": "Total", "IsTearSheet": "Y",
           "SourceTag": "", "ComparableGAAPMetricName": "", "ReconciliationSourceTag": "", "Notes": ""}
    boundary = ([{**row, "MetricName": "Revenue", "Value": 100.0, "DisplayOrder": 1},
                 {**row, "MetricName": "GAAP EPS (Diluted)", "Value": 23.0, "DisplayOrder": 2}],
                [{"MetricName": m, "Period": "2024", "EstimateType": "Consensus", "Value": v, "Units": "", "AsOf": "",
                  "Source": "", "Notes": ""} for m, v in (("Revenue", 100.0), ("GAAP EPS (Diluted)", 20.0))], [])
    cases = [boundary] + [_random_earnings(rnd) for _ in range(N_RANDOM * 5)]
    for i, (metrics, est, guide) in enumerate(cases):
        rb = ref.compute_beat_miss(pd.DataFrame(metrics), pd.DataFrame(est, columns=est_cols))
        mb = earnings.compute_beat_miss(metrics, est)
        assert len(rb) == len(mb), i
        for a, b in zip(rb, mb):
            assert all(same(a.__dict__[k], b.__dict__[k]) for k in a.__dict__), (i, a, b)
        rg = ref.compute_guidance(pd.DataFrame(guide, columns=guide_cols), pd.DataFrame(est, columns=est_cols))
        mg = earnings.compute_guidance(guide, est)
        assert [g.__dict__ for g in rg] == [g.__dict__ for g in mg], i
        for a, b in zip(rb, mb):
            assert ref._distortion_text(a) == earnings._distortion_text(b)
            for needles in (("revenue",), ("operating",), ("adjusted", "eps")):
                ra, ma = ref._first_row(rb, *needles, period=a.period), earnings._first_row(mb, *needles, period=b.period)
                assert (ra is None and ma is None) or ra.metric == ma.metric
                assert bool(ref._surprise_gap_flag(a, ra, "x")) == earnings._surprise_gap_flag(b, ma)


# ---------------------------------------------------------------- DCF

def _dcf_plans():
    tpl = json.loads((reference_root() / "skills/dcf-model-builder/assets/plan_template.json")
                     .read_text(encoding="utf-8"))
    out = [tpl]
    rnd = random.Random(7)
    for _ in range(20):
        p = copy.deepcopy(tpl)
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
    for plan in _dcf_plans():
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
