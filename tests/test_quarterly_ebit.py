"""季报单季拆分、经营性 EBIT、三表驱动 DCF、comps 利润率对比页。

季度拆分用两种输入检验：年报“分季度主要财务指标”单季表（Agent / Skill 共用规则通道），
以及 Skill 版本的“年报 + 三季报”（--supplement，第四季度 = 全年 − 前三季度累计）。
"""

import json
import re
import zipfile

import pytest

from conftest import SAMPLES
from finagent import pipelines
from finagent.__main__ import main
from finagent.core.tracing import RunTracer
from finagent.parsing.document import load_document
from finagent.tasks.financials.analyze import analyze
from finagent.tasks.financials.external import ingest
from finagent.tasks.financials.extract import extract_rule
from finagent.tasks.financials.schema import match_label

ANNUAL = SAMPLES / "annual_report_2024.md"
Q3 = SAMPLES / "q3_report_2024.md"


def _fact(mid, period, value, method="rule_table"):
    return {"metric_id": mid, "period": period, "value": value, "raw": f"{value:,.2f}", "unit": "元",
            "method": method, "source": {"source": "x", "page": 1}}


def _cells(a):
    return {(c["metric_id"], c["period"]): c for c in a["truth_table"]}


# ---------------------------------------------------------------- 季度拆分（纯计算）

def test_single_quarters_derived_from_cumulative_reports():
    facts = [_fact("revenue", "2024", 1000.0), _fact("revenue", "2024Q1-3", 700.0),
             _fact("revenue", "2024H1", 450.0), _fact("revenue", "2024Q1", 200.0),
             _fact("operating_cost", "2024", 600.0), _fact("operating_cost", "2024Q1-3", 430.0)]
    a = analyze(facts)
    c = _cells(a)
    assert c[("revenue", "2024Q4")]["value"] == 300.0  # 全年 − 前三季度
    assert c[("revenue", "2024Q4")]["formula"] == "全年 − 前三季度累计"
    assert c[("revenue", "2024Q3")]["value"] == 250.0  # 前三季度 − 上半年
    assert c[("revenue", "2024Q2")]["value"] == 250.0  # 上半年 − 一季度
    assert c[("operating_cost", "2024Q4")]["value"] == 170.0
    assert c[("gross_margin", "2024Q4")]["value"] == pytest.approx(130 / 300 * 100)  # 单季派生比率随之可得
    q = {r["metric_id"]: r for r in a["quarterly"]["rows"]}
    assert q["revenue"]["methods"] == {"Q1": "reported", "Q2": "derived", "Q3": "derived", "Q4": "derived"}


def test_stock_items_eps_and_ratios_not_split():
    facts = [_fact("revenue", "2024", 1000.0), _fact("revenue", "2024Q1-3", 700.0),
             _fact("total_assets", "2024", 5000.0), _fact("total_assets", "2024Q1-3", 4800.0),
             {**_fact("eps_basic", "2024", 0.8), "unit": "元/股"}, {**_fact("eps_basic", "2024Q1-3", 0.6), "unit": "元/股"}]
    c = _cells(analyze(facts))
    assert ("revenue", "2024Q4") in c
    assert ("total_assets", "2024Q4") not in c and ("eps_basic", "2024Q4") not in c


def test_reported_quarter_checked_against_cumulative_difference():
    ok = [_fact("revenue", "2024", 1000.0), _fact("revenue", "2024Q1-3", 700.0), _fact("revenue", "2024Q4", 300.0)]
    bad = ok[:2] + [_fact("revenue", "2024Q4", 320.0)]
    name = "营业收入 2024 年第四季度 = 全年 − 前三季度累计"
    for facts, status in ((ok, "pass"), (bad, "fail")):
        t = next(x for x in analyze(facts)["tieouts"] if x["check"] == name)
        assert t["status"] == status
    # 单季全部来自同一张分季度表时，由它们加总出的累计数不再反过来核对自己
    only_q = [_fact("revenue", f"2024Q{i}", v) for i, v in enumerate((200.0, 250.0, 250.0, 300.0), 1)]
    checks = [x["check"] for x in analyze(only_q + [_fact("revenue", "2024", 1000.0)])["tieouts"]]
    assert checks.count(name) == 1 and not any("第二季度" in x or "第三季度" in x for x in checks)


def test_sign_note_suffix_matches_metric():
    assert match_label("加：投资收益（损失以“－”号填列）") == "investment_income"
    assert match_label("公允价值变动收益（损失以\"-\"号填列）") == "fair_value_change"
    assert match_label("三、营业利润（亏损以“－”号填列）") == "operating_profit"
    assert match_label("其中：对联营企业和合营企业的投资收益") is None


# ---------------------------------------------------------------- 样例：年报分季度表 / 年报 + 三季报（Skill）

@pytest.fixture(scope="module")
def run(tmp_path_factory):
    c = {"input": str(ANNUAL), "fiscal_year": 2024, "company": "星河智造",
         "assumptions": str(SAMPLES / "valuation_assumptions.json"), "peers": str(SAMPLES / "peers.csv"), "llm": None}
    with RunTracer("quarterly", tmp_path_factory.mktemp("runs")) as tr:
        pipelines.run("valuation", c)
    c["run_dir"] = tr.dir
    return c


def test_annual_report_quarter_table_ties_to_full_year(run):
    rows = {r["metric_id"]: r for r in run["analysis"]["quarterly"]["rows"]}
    assert set(rows["revenue"]["methods"].values()) == {"reported"}
    q4 = [t for t in run["analysis"]["tieouts"] if "第四季度" in t["check"]]
    assert len(q4) == 4 and all(t["status"] == "pass" for t in q4)


def _skill_payload(doc, source_file=None):
    facts, _ = extract_rule(doc, 2024)
    items = []
    for f in facts:
        if "." in f.metric_id:
            continue
        ch = doc.get(f.source["chunk_id"])
        items.append({"metric_id": f.metric_id, "period": f.period, "raw_value": f.raw, "unit": ch.unit_hint or "元",
                      "page": f.source["page"], "label": f.label, "table": ch.caption, "scope": "consolidated",
                      **({"source_file": source_file} if source_file else {})})
    return items


@pytest.fixture(scope="module")
def skill_facts(tmp_path_factory):
    annual, q3 = load_document(ANNUAL), load_document(Q3)
    payload = {"company": "星河智造", "fiscal_year": 2024,
               "facts": _skill_payload(annual) + _skill_payload(q3, "q3_report_2024.md")}
    path = tmp_path_factory.mktemp("facts") / "facts.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_supplement_q4_equals_full_year_minus_q1_3(skill_facts):
    doc, q3 = load_document(ANNUAL), load_document(Q3)
    res = ingest(doc, json.loads(skill_facts.read_text(encoding="utf-8")), fiscal_year=2024, supplements=[q3])
    assert res["rejected"] == [] and res["stats"]["supplements"] == ["q3_report_2024.md"]
    q3_src = {f["source"]["source"] for f in res["facts"] if f["period"] == "2024Q1-3"}
    assert q3_src == {str(Q3)}
    a = analyze(res["facts"], doc=doc, extract_issues=res["issues"])
    c = _cells(a)
    # 利润表只有三季报有前三季度累计：第四季度营业成本 = 全年 − 前三季度
    cost = c[("operating_cost", "2024Q4")]
    assert cost["value"] == pytest.approx(4_034_118_660.40 - 2_815_640_000.00)
    assert cost["formula"] == "全年 − 前三季度累计"
    assert ("investment_income", "2024Q4") in c and ("gross_margin", "2024Q4") in c
    # 年报分季度表的第四季度 vs 全年 − 三季报前三季度累计：两份报告互相印证
    q4 = {t["check"]: t["status"] for t in a["tieouts"] if "第四季度" in t["check"]}
    assert q4["营业收入 2024 年第四季度 = 全年 − 前三季度累计"] == "pass" and set(q4.values()) == {"pass"}


def test_supplement_must_be_passed(skill_facts, tmp_path):
    res = ingest(load_document(ANNUAL), json.loads(skill_facts.read_text(encoding="utf-8")), fiscal_year=2024)
    assert res["rejected"] and all("未作为主文件或补充文件" in r["reason"] for r in res["rejected"])
    args = ["verify-facts", "--input", str(ANNUAL), "--year", "2024", "--facts", str(skill_facts),
            "--out", str(tmp_path / "v.json")]
    assert main(args) == 1
    assert main(args + ["--supplement", str(Q3)]) == 0


def test_supplement_requires_skill_facts():
    with pytest.raises(SystemExit):
        main(["financials", "--input", str(ANNUAL), "--supplement", str(Q3), "--llm", "off"])


# ---------------------------------------------------------------- EBIT 与三表驱动的 DCF

def test_ebit_excludes_investment_income_and_fair_value(run):
    h = run["plan"]["historicals"]
    assert h["ebit"] == pytest.approx(760.12 + 45.30 - 23.50 - 41.20)
    notes = {n["item"]: n["detail"] for n in run["plan_notes"]}
    assert "剔除投资与公允价值损益" in notes["EBIT"] and "non_operating_assets" in notes["非经营性资产"]
    # 三表模型历史期 EBIT 与 DCF 同口径（经营费用为轧差项）
    d = run["three_statement"]["historical_drivers"]
    rev = 5862.34012536
    assert rev * d["gross_margin"] - rev * d["opex_pct"] - 340.5 == pytest.approx(h["ebit"])  # 毛利 − 经营费用 − 折旧摊销


def test_dcf_forecast_comes_from_three_statement(run):
    v, drivers = run["valuation"], run["three_statement"]["dcf_drivers"]
    assert v["three_statement_tie"]["status"] == "pass"
    for row, rev, ebit, nwc in zip(v["forecast_base"], drivers["base"]["revenue"], drivers["base"]["ebit"],
                                   drivers["base"]["nwc"]):
        assert (row["revenue"], row["ebit"], row["nwc"]) == pytest.approx((rev, ebit, nwc), abs=1e-9)
    # 情景差异来自三表模型的毛利率/应收天数调整，而不是假设文件里另写的利润率
    margins = {k: drivers[k]["ebit_margin"][-1] for k in ("downside", "base", "upside")}
    assert margins["downside"] < margins["base"] < margins["upside"]
    assert "ebit_margin" not in json.loads((SAMPLES / "valuation_assumptions.json").read_text("utf-8"))["scenarios"]["base"]


def test_dcf_blocked_when_three_statement_disagrees(run):
    from finagent.tasks.valuation.run import run_dcf
    drivers = json.loads(json.dumps(run["three_statement"]["dcf_drivers"]))
    drivers["base"]["ebit"][0] += 1.0
    res = run_dcf(run["plan"], 12.8, drivers)
    assert res["three_statement_tie"]["status"] == "fail" and res["model_status"] == "blocked"


# ---------------------------------------------------------------- comps 利润率对比页

def test_comps_margin_sheet(run):
    m = run["comps"]["margins"]
    assert m["ebit_margin"]["target"] == pytest.approx(run["plan"]["historicals"]["ebit"] / 5862.34012536)
    assert m["ebit_margin"]["core"]["n"] == 5
    assert run["comps"]["rows"][2]["ebitda_margin"] == pytest.approx(820 / 4100)
    with zipfile.ZipFile(run["run_dir"] / "valuation" / "comps_formula_workbook.xlsx") as z:
        wb = z.read("xl/workbook.xml").decode("utf-8")
        sheet = z.read("xl/worksheets/sheet8.xml").decode("utf-8")
    assert re.findall(r'<sheet name="([^"]+)"', wb)[-1] == "利润率对比"
    cells = dict(re.findall(r'<c r="([A-Z]+\d+)"(?: [a-z]+="[^"]*")*>(?:(?!</c>).)*?<v>([^<]*)</v></c>', sheet))
    n = len(run["comps"]["rows"])
    top = n + 3  # 表头 + n 行数据 + 空行之后为统计区
    for col, key in (("H", "ebitda_margin"), ("I", "ebit_margin"), ("J", "net_margin")):
        assert float(cells[f"{col}2"]) == m[key]["target"]
        assert float(cells[f"{col}{top + 1}"]) == m[key]["core"]["n"]
        assert float(cells[f"{col}{top + 2}"]) == m[key]["core"]["median"]
        assert float(cells[f"{col}{top + 6}"]) == pytest.approx(m[key]["diff_vs_core_median"] * 100)
    assert cells[f"G{n + 1}"] == "-150.0"  # 亏损同业净利润照录，净利率为负而不是 NM


# ---------------------------------------------------------------- 工作簿排版（references/workbook.md）

def test_model_workbook_layout_and_formulas(run):
    with zipfile.ZipFile(run["run_dir"] / "valuation" / "model.xlsx") as z:
        names = re.findall(r'<sheet name="([^"]+)"', z.read("xl/workbook.xml").decode("utf-8"))
        styles = z.read("xl/styles.xml").decode("utf-8")
        dcf = z.read(f"xl/worksheets/sheet{names.index('DCF') + 1}.xml").decode("utf-8")
    assert names[:4] == ["估值汇总", "DCF", "WACC", "敏感性"]
    assert 'name val="Arial"' in styles and "FF1F3864" in styles and "FF0000FF" in styles
    # 中西文字体配对：文字单元格按字符分段，中文段楷体、西文段 Arial（数值单元格为 Arial）
    assert re.search(r'<rFont val="Arial"/>.{0,80}<t xml:space="preserve">DCF ?</t>.*?<rFont val="KaiTi"/>', dcf)
    assert 'showGridLines="0"' in dcf and 'state="frozen"' in dcf and 'orientation="landscape"' in dcf
    found = re.findall(r'<c r="([A-Z]+\d+)"(?: [a-z]+="[^"]*")*><f>([^<]*)</f><v>([^<]*)</v></c>', dcf)
    ratios = [float(v) for _, f, v in found if re.fullmatch(r"B\d+/B\d+", f)]  # 每股价值 = 股权价值 / 股本（公式）
    assert run["valuation"]["value_range"]["base"] in ratios
