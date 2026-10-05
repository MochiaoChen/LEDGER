import json

import pytest

from conftest import SAMPLES
from finagent import pipelines
from finagent.core.tracing import RunTracer
from finagent.parsing.document import load_document


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    runs = tmp_path_factory.mktemp("runs")
    c = {"input": str(SAMPLES / "annual_report_2024.md"), "fiscal_year": 2024, "company": "样例",
         "assumptions": str(SAMPLES / "valuation_assumptions.json"),
         "report": str(SAMPLES / "research_draft.md")}
    with RunTracer("test", runs) as tr:
        pipelines.run("all", c)
    c["run_dir"] = tr.dir
    return c


def test_tieouts_pass(ctx):
    assert all(t["status"] == "pass" for t in ctx["analysis"]["tieouts"])


def test_signals(ctx):
    ids = {s["id"] for s in ctx["analysis"]["signals"]}
    assert {"S1", "S3", "S4", "S5", "S8"} <= ids


def test_valuation(ctx):
    v = ctx["valuation"]
    assert v["status"] == "ok" and not v["checks"]["hard_failures"]
    r = v["value_range"]
    assert r["low"] < r["base"] < r["high"]
    # 回归基准（样例公司）：DCF 由三表模型驱动、EBIT 剔除投资收益与公允价值变动后的结果；
    # DCF 引擎本身与参考实现的逐项对照见 test_parity_reference.py
    assert r["base"] == pytest.approx(11.666818880388837, rel=1e-9)
    assert r["low"] == pytest.approx(6.168577718229366, rel=1e-9)
    assert r["high"] == pytest.approx(17.72500146281172, rel=1e-9)
    assert v["sensitivity_directionality"]["passed"]
    assert v["three_statement_tie"]["status"] == "pass"


def test_report_check(ctx):
    s = ctx["check"]["summary"]
    assert s["errors"] == 7 and s["unverifiable"] == 1


def test_run_artifacts_and_manifest(ctx):
    d = ctx["run_dir"]
    m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert m["status"] == "ok"
    for name in ("financials/report.md", "valuation/model.xlsx", "check/findings.json"):
        assert name in m["artifacts"]
    kinds = {json.loads(l)["kind"] for l in (d / "events.jsonl").read_text(encoding="utf-8").splitlines()}
    assert {"file_read", "step_start", "tool_end", "artifact", "run_end"} <= kinds


def test_deterministic(ctx, tmp_path):
    c2 = {k: ctx[k] for k in ("input", "fiscal_year", "company", "assumptions", "report")}
    with RunTracer("test2", tmp_path):
        pipelines.run("all", c2)
    assert c2["check"]["findings"] == ctx["check"]["findings"]
    assert c2["valuation"]["value_range"] == ctx["valuation"]["value_range"]
