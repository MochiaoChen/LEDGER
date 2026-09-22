import json

import pytest

from conftest import SAMPLES
from finagent import pipelines
from finagent.core.tracing import RunTracer
from finagent.parsing.document import load_document
from finagent.tasks.financials.extract import extract_financials


@pytest.fixture(scope="module")
def ctx(tmp_path_factory):
    runs = tmp_path_factory.mktemp("runs")
    c = {"input": str(SAMPLES / "annual_report_2024.md"), "fiscal_year": 2024, "company": "样例",
         "assumptions": str(SAMPLES / "valuation_assumptions.json"),
         "report": str(SAMPLES / "research_draft.md"), "llm": None}
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
    # 回归基准：与参考 DCF 实现逐项对比一致时的结果（样例公司）
    assert r["base"] == pytest.approx(14.37780469668347, rel=1e-9)
    assert r["low"] == pytest.approx(7.818038481424233, rel=1e-9)
    assert r["high"] == pytest.approx(22.714096923421934, rel=1e-9)
    assert v["sensitivity_directionality"]["passed"]


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
    c2 = {k: ctx[k] for k in ("input", "fiscal_year", "company", "assumptions", "report", "llm")}
    with RunTracer("test2", tmp_path):
        pipelines.run("all", c2)
    assert c2["check"]["findings"] == ctx["check"]["findings"]
    assert c2["valuation"]["value_range"] == ctx["valuation"]["value_range"]


class FakeLLM:
    """模拟 LLM：一条真实数字 + 一条编造数字，验证证据校验能拦截编造。"""
    enabled = True

    def chat_json(self, system, user, purpose=""):
        return {"facts": [
            {"metric_id": "revenue", "period": "2024", "raw_value": "5,862,340,125.36", "unit": "元"},
            {"metric_id": "ocf", "period": "2024", "raw_value": "999,999,999.00", "unit": "元"},
        ]}


def test_llm_evidence_guard():
    doc = load_document(SAMPLES / "annual_report_2024.md")
    out = extract_financials(doc, fiscal_year=2024, llm=FakeLLM(), llm_mode="all")
    ocf = [f for f in out["facts"] if f["metric_id"] == "ocf" and f["period"] == "2024"][0]
    assert ocf["value"] == 238460000.0  # 编造的数字未进入结果
    assert any(i["type"] == "LLM结果未通过证据校验" for i in out["issues"])
    rev = [f for f in out["facts"] if f["metric_id"] == "revenue" and f["period"] == "2024"][0]
    assert rev["method"] == "rule+llm"  # 规则与 LLM 一致 → 交叉印证
