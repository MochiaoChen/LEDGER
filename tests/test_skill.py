"""Skill 版本：外部模型（Claude Code）读 PDF 抽取 → 程序校验 → 共用计算引擎。

用样例年报的表格内容模拟“模型抽取结果”：完美抽取时，结果必须与 Agent 版本（及原引擎快照）完全一致；
编造数字、页码错误、误取母公司报表、期间看反、漏抄核心指标都必须被校验拦下。
"""

import copy
import json
import re

import pytest

from conftest import ROOT, SAMPLES
from finagent import pipelines
from finagent.__main__ import HELPERS, main
from finagent.core.tracing import RunTracer
from finagent.parsing.document import load_document
from finagent.parsing.locate import locate
from finagent.tasks.financials.external import CORE_METRICS, ingest, metric_catalog
from finagent.tasks.financials.extract import extract_rule
from finagent.tasks.report_check.claims import extract_rule as claims_rule
from finagent.tasks.report_check.claims import ingest_claims

REPORT = SAMPLES / "annual_report_2024.md"
SKILL = ROOT / ".claude" / "skills" / "finagent-research"


@pytest.fixture(scope="module")
def doc():
    return load_document(REPORT)


@pytest.fixture(scope="module")
def extraction(doc):
    """模拟模型读页抽取：只含模型能从页面看到的信息（页码、原文数字、表内单位）。"""
    facts, _ = extract_rule(doc, 2024)
    items = []
    for f in facts:
        if "." in f.metric_id:
            continue
        ch = doc.get(f.source["chunk_id"])
        items.append({"metric_id": f.metric_id, "period": f.period, "raw_value": f.raw, "unit": ch.unit_hint or "元",
                      "page": f.source["page"], "label": f.label, "table": ch.caption, "scope": "consolidated"})
    return {"company": "星河智造", "fiscal_year": 2024, "facts": items}


@pytest.fixture(scope="module")
def claims_payload():
    rdoc = load_document(SAMPLES / "research_draft.md")
    return {"claims": [{"metric_id": c.metric_id, "period": c.period, "claim_type": c.claim_type,
                        "value": ("-" if c.value < 0 else "") + c.raw_value, "unit": c.unit,
                        "is_forecast": c.is_forecast, "quote": c.quote} for c in claims_rule(rdoc, 2024)]}


def _run(tmp_path_factory, name, **extra):
    c = {"input": str(REPORT), "fiscal_year": 2024, "company": "星河智造",
         "assumptions": str(SAMPLES / "valuation_assumptions.json"), "report": str(SAMPLES / "research_draft.md"),
         "peers": str(SAMPLES / "peers.csv"), "estimates": str(SAMPLES / "estimates.csv"),
         "guidance": str(SAMPLES / "guidance.csv"), "llm": None, **extra}
    with RunTracer(name, tmp_path_factory.mktemp(name)) as tr:
        pipelines.run("all", c)
    c["run_dir"] = tr.dir
    return c


@pytest.fixture(scope="module")
def runs(tmp_path_factory, extraction, claims_payload):
    d = tmp_path_factory.mktemp("inputs")
    (d / "facts.json").write_text(json.dumps(extraction, ensure_ascii=False), encoding="utf-8")
    (d / "claims.json").write_text(json.dumps(claims_payload, ensure_ascii=False), encoding="utf-8")
    agent = _run(tmp_path_factory, "agent")
    skill = _run(tmp_path_factory, "skill", facts_file=str(d / "facts.json"), claims_file=str(d / "claims.json"))
    return agent, skill


# ---------------------------------------------------------------- 定位

def test_locate_finds_statement_pages(doc):
    loc = locate(doc)
    assert loc["sections"]["key_data"] == [6, 7] and loc["sections"]["non_recurring"] == [8]
    assert loc["sections"]["quarterly"] == [7]
    assert loc["sections"]["balance"] == [102] and loc["sections"]["income"] == [106]
    assert "102-104" in loc["suggested_reads"] and "106-108" in loc["suggested_reads"]
    assert loc["unit_hints"]["106"] == "元"


# ---------------------------------------------------------------- 完美抽取 = Agent 版本

def test_perfect_extraction_passes_verification(doc, extraction):
    res = ingest(doc, extraction, fiscal_year=2024)
    assert res["rejected"] == [] and res["missing"] == []
    assert not [i for i in res["issues"] if i["severity"] == "high"]


@pytest.mark.parametrize("artifact", ["valuation/three_statement.json", "valuation/scenarios.json",
                                      "valuation/comps.json", "valuation/valuation.json",
                                      "financials/earnings.json", "check/findings.json"])
def test_skill_run_matches_agent_run(runs, artifact):
    agent, skill = runs
    a = json.loads((agent["run_dir"] / artifact).read_text(encoding="utf-8"))
    b = json.loads((skill["run_dir"] / artifact).read_text(encoding="utf-8"))
    assert a == b


def test_skill_run_truth_table_and_provenance(runs):
    agent, skill = runs
    val = lambda c: {(r["metric_id"], r["period"]): r["value"] for r in c["analysis"]["truth_table"]}  # noqa: E731
    assert val(agent) == val(skill)
    methods = {f["method"] for f in skill["extract"]["facts"] if "." not in f["metric_id"]}
    assert methods == {"rule+llm"}  # 模型抽取与规则通道逐项一致
    assert (skill["run_dir"] / "financials" / "skill_extraction.json").exists()
    assert (skill["run_dir"] / "check" / "skill_claims.json").exists()


# ---------------------------------------------------------------- 校验拦截

def _mutate(extraction, metric, period, **changes):
    e = copy.deepcopy(extraction)
    item = next(i for i in e["facts"] if i["metric_id"] == metric and i["period"] == period)
    item.update(changes)
    return e


def _reasons(res):
    return " | ".join(r["reason"] for r in res["rejected"])


def test_fabricated_number_rejected(doc, extraction):
    res = ingest(doc, _mutate(extraction, "revenue", "2024", raw_value="5,999,999,999.99"), fiscal_year=2024)
    assert re.search(r"revenue 2024=5,999,999,999.99 未在第 \d+ 页原文中找到", _reasons(res))


def test_wrong_page_rejected(doc, extraction):
    res = ingest(doc, _mutate(extraction, "total_assets", "2024", page=106), fiscal_year=2024)
    assert "未在第 106 页原文中找到" in _reasons(res)


def test_wrong_row_number_caught_as_conflict(doc, extraction):
    """数字确在该页（“增加1.23个百分点”），但抄错了行：证据校验放行，由多处取值与规则通道比对拦下。"""
    res = ingest(doc, _mutate(extraction, "revenue", "2024", raw_value="1.23"), fiscal_year=2024)
    types = {i["type"] for i in res["issues"] if "营业收入 2024" in i["message"]}
    assert {"同一指标多处取值不一致", "规则与LLM抽取不一致"} <= types


def test_parent_company_scope_rejected(doc, extraction):
    res = ingest(doc, _mutate(extraction, "cash", "2024", scope="parent"), fiscal_year=2024)
    assert "只接受合并报表口径" in _reasons(res)


def test_partial_number_not_accepted_as_evidence(doc, extraction):
    item = next(i for i in extraction["facts"] if i["metric_id"] == "revenue" and i["period"] == "2024")
    digits = re.sub(r"\D", "", item["raw_value"])
    res = ingest(doc, _mutate(extraction, "revenue", "2024", raw_value=digits[1:6]), fiscal_year=2024)
    assert res["rejected"], "数字片段不能冒充证据"


def test_swapped_period_is_flagged_and_model_value_kept(doc, extraction):
    prev = next(i for i in extraction["facts"] if i["metric_id"] == "revenue" and i["period"] == "2023")
    res = ingest(doc, _mutate(extraction, "revenue", "2024", raw_value=prev["raw_value"]), fiscal_year=2024)
    assert any(i["type"] == "规则与LLM抽取不一致" and "保留LLM结果" in i["message"] for i in res["issues"])
    rev = next(f for f in res["facts"] if f["metric_id"] == "revenue" and f["period"] == "2024")
    assert rev["raw"] == prev["raw_value"] and rev["method"] == "llm"


def test_missing_core_metric_blocks(doc):
    # 样例表格规整，模型漏抄时规则通道兜底，不算缺失
    assert ingest(doc, {"facts": []}, fiscal_year=2024)["missing"] == []
    # 规则通道也抽不到（真实 PDF 表格错乱的情形，这里用不含报表的研报模拟）：核心指标全部阻断
    res = ingest(load_document(SAMPLES / "research_draft.md"), {"facts": []}, fiscal_year=2024)
    assert {m["metric_id"] for m in res["missing"] if m["blocking"]} == set(CORE_METRICS)


def test_verify_cli_exit_codes(tmp_path, extraction):
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps(extraction, ensure_ascii=False), encoding="utf-8")
    bad.write_text(json.dumps(_mutate(extraction, "revenue", "2024", raw_value="7,777,777.77"), ensure_ascii=False),
                   encoding="utf-8")
    args = ["verify-facts", "--input", str(REPORT), "--year", "2024", "--facts"]
    assert main(args + [str(good)]) == 0
    assert main(args + [str(bad)]) == 1
    out = json.loads((tmp_path / "bad.verified.json").read_text(encoding="utf-8"))
    assert out["check"]["ok"] is False and out["check"]["rejected"]


# ---------------------------------------------------------------- 研报断言

def test_claims_fake_quote_rejected(claims_payload):
    rdoc = load_document(SAMPLES / "research_draft.md")
    p = copy.deepcopy(claims_payload)
    p["claims"][0]["quote"] = "公司实现营业收入99.99亿元"
    p["claims"][1]["value"] = "12345"
    _, rejected = ingest_claims(rdoc, p, 2024)
    reasons = " | ".join(r["reason"] for r in rejected)
    assert "quote 不是研报原文中的连续片段" in reasons and "不在 quote 中" in reasons


# ---------------------------------------------------------------- 解读护栏

GOOD_COMMENTARY = """## 事实
- 营业收入 58.62 亿元，同比增长 14.49%（年报第 6 页）。
- 归母净利润 6.12 亿元，同比增长 18.17%；扣非归母净利润 4.44 亿元，同比下降 5.67%。
- 经营活动现金流量净额 2.38 亿元，同比下降 58.98%。

## 推论
- 归母净利润增加 0.94 亿元，非经常性损益变动相当于其 128%，增量利润全部来自非经常性损益。

## 观点
- 盈利质量偏弱。DCF 基准情景每股价值 11.67 元，区间 6.17～17.73 元；不构成投资建议。
"""


def _guard(run_dir, tmp_path, text):
    f = tmp_path / "c.md"
    f.write_text(text, encoding="utf-8")
    code = main(["guard", "--run-dir", str(run_dir), "--text", str(f)])
    return code, json.loads((run_dir / "commentary_guard.json").read_text(encoding="utf-8"))


def test_guard_passes_correct_commentary(runs, tmp_path):
    code, res = _guard(runs[1]["run_dir"], tmp_path, GOOD_COMMENTARY)
    assert code == 0, res


def test_guard_flags_invented_number(runs, tmp_path):
    code, res = _guard(runs[1]["run_dir"], tmp_path, "观点：预计明年净利润 98.76 亿元。")
    assert code == 1 and res["unverified_numbers"] == ["98.76亿元"]


def test_guard_flags_every_planted_report_error(runs, tmp_path):
    """研报草稿里植入的 7 处错误，写进解读都必须被拦下（数字无出处，或指标/期间/单位对不上）。"""
    run = runs[1]["run_dir"]
    findings = json.loads((run / "check" / "findings.json").read_text(encoding="utf-8"))["findings"]
    errors = [f for f in findings if f["verdict"] not in ("正确", "无法核实")]
    assert len(errors) == 7
    for f in errors:
        code, res = _guard(run, tmp_path, f"事实：{f['quote']}")
        assert code == 1, (f["quote"], res)


# ---------------------------------------------------------------- 文档与代码同步

def test_skill_docs_in_sync_with_code():
    skill_md = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    ext_md = (SKILL / "references" / "extraction.md").read_text(encoding="utf-8")
    assert skill_md.startswith("---\nname: finagent-research\n")
    for cmd in re.findall(r"-m finagent ([a-z-]+)", skill_md):
        assert cmd in HELPERS or cmd in ("all", "financials", "valuation", "check"), cmd
    catalog = ext_md.split("## 抽取清单", 1)[1].split("## 易错点", 1)[0]
    rows = dict(re.findall(r"^\| `([a-z_]+)`( ★)? \|", catalog, flags=re.M))
    assert set(rows) == {m["metric_id"] for m in metric_catalog()}
    assert {k for k, star in rows.items() if star} == set(CORE_METRICS)
    for ref in re.findall(r"\]\((references/[a-z]+\.md)\)", skill_md):
        assert (SKILL / ref).exists(), ref


# ---------------------------------------------------------------- PDF 路径（样例 PDF + Claude Code 实际读页写出的抽取文件）

PDF = SAMPLES / "annual_report_2024.pdf"
EXTRACTION = ROOT / "data" / "extractions" / "星河智造_2024"


@pytest.fixture(scope="module")
def pdf_doc():
    pytest.importorskip("pdfplumber")
    return load_document(PDF)


def test_pdf_locate_and_parent_statement_excluded(pdf_doc):
    loc = locate(pdf_doc, 112)
    assert loc["sections"]["balance"] == [102] and loc["parent_only_pages"] == [112]
    captions = {c.page: c.caption for c in pdf_doc.tables()}
    assert captions[102] == "合并资产负债表" and captions[112] == "母公司资产负债表"
    rule, _ = extract_rule(pdf_doc, 2024)
    assert all(f.source["page"] != 112 for f in rule)  # 规则通道不取母公司报表


def test_pdf_model_extraction_verifies_and_matches_agent(pdf_doc, runs, tmp_path_factory):
    payload = json.loads((EXTRACTION / "facts.json").read_text(encoding="utf-8"))
    res = ingest(pdf_doc, payload, fiscal_year=2024)
    assert res["rejected"] == [] and res["missing"] == []
    assert not [i for i in res["issues"] if i["type"] in ("同一指标多处取值不一致", "规则与LLM抽取不一致")]
    pdf_run = _run(tmp_path_factory, "pdf", input=str(PDF), facts_file=str(EXTRACTION / "facts.json"),
                   claims_file=str(EXTRACTION / "claims.json"))
    agent = runs[0]
    for artifact in ("valuation/three_statement.json", "valuation/scenarios.json", "valuation/comps.json",
                     "valuation/valuation.json"):
        a = json.loads((agent["run_dir"] / artifact).read_text(encoding="utf-8"))
        b = json.loads((pdf_run["run_dir"] / artifact).read_text(encoding="utf-8"))
        assert a == b, artifact
    val = lambda c: {(r["metric_id"], r["period"]): r["value"] for r in c["analysis"]["truth_table"]}  # noqa: E731
    assert val(agent) == val(pdf_run)
    verdicts = lambda c: sorted((f["metric_name"], f["claim_type"], f["raw_value"], f["verdict"])  # noqa: E731
                                for f in c["check"]["findings"])
    assert verdicts(agent) == verdicts(pdf_run)
