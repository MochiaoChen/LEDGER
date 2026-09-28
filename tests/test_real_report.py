"""真实年报联调（贵州茅台 2025 年报）：规则通道在真实 PDF 上不误取母公司报表、附注明细表与结构比列；
Skill 抽取通过校验；非经营性资产明细逐项核对原文；model.xlsx 含历史财务、分季度与非经营性资产页。"""

import json
import re
import zipfile

import pytest

from conftest import ROOT
from finagent.__main__ import main
from finagent.parsing.document import load_document
from finagent.tasks.financials.analyze import analyze
from finagent.tasks.financials.external import ingest
from finagent.tasks.financials.extract import extract_rule, parse_period
from finagent.tasks.financials.extras import verify_extras
from finagent.tasks.valuation.build_plan import resolve_non_operating_items

PDF = ROOT / "report" / "resources" / "贵州茅台" / "600519_贵州茅台_2025_年度报告.pdf"
WORK = ROOT / "data" / "extractions" / "贵州茅台_2025"


@pytest.fixture(scope="module")
def doc():
    return load_document(PDF)


def test_parse_period_skips_ratio_columns_and_wrapped_headers():
    assert parse_period("本期期\n末数占\n总资产\n的比例\n（%）", 2025) is None
    assert parse_period("本期比上年同期增\n减(%)", 2025) == "chg"
    assert parse_period("本期期末\n金额较上\n期期末变\n动比例\n（%）", 2025) == "chg"


def test_statement_captions_distinguish_parent_and_consolidated(doc):
    caps = {c.page: c.caption for c in doc.tables() if c.rows and c.rows[0][:1] == ["项目"]}
    assert caps[56] == "合并资产负债表" and caps[59] == "母公司资产负债表"
    assert caps[61] == "合并利润表" and caps[63] == "母公司利润表"


def test_rule_channel_on_real_pdf(doc):
    facts, _ = extract_rule(doc, 2025)
    by = {}
    for f in facts:
        by.setdefault(f.key, set()).add(round(f.value, 2))
    # 营业收入取“其中：营业收入”，不取含财务公司利息收入的营业总收入；母公司报表与附注明细不混入
    assert by[("revenue", "2025")] == {168838102514.79}
    assert by[("finance_expense", "2025")] == {-815240284.72}
    assert by[("eps_basic", "2025")] == {65.66}
    # 跨页表格续页没有表头，规则通道目前取不到（由 Skill 抽取补齐）；取到的必须是合并报表的正确值
    truth = {("operating_profit", "2025"): 114808950164.24, ("inventory", "2025"): 61427421796.18,
             ("cash", "2025"): 51690610946.50, ("total_assets", "2025"): 303834844021.44,
             ("ocf", "2025"): 61522204989.35, ("net_profit", "2025"): 85310324833.67,
             ("accounts_receivable", "2025"): 2609048.49}
    for key, v in truth.items():
        assert by.get(key, {round(v, 2)}) == {round(v, 2)}, key


def test_moutai_skill_extraction_verifies(doc):
    res = ingest(doc, json.loads((WORK / "facts.json").read_text(encoding="utf-8")), fiscal_year=2025)
    assert not res["rejected"]
    conflicts = [i for i in res["issues"] if i["type"] in ("同一指标多处取值不一致", "规则与LLM抽取不一致")]
    assert not conflicts
    assert not [m for m in res["missing"] if m["blocking"]]
    a = analyze(res["facts"], period="2025", doc=doc, extract_issues=res["issues"])
    assert all(t["status"] == "pass" for t in a["tieouts"])


def test_non_operating_items_verified_against_pdf(doc):
    items = json.loads((WORK / "valuation_assumptions.json").read_text(encoding="utf-8"))["non_operating_assets"]
    out = resolve_non_operating_items(items, doc)
    assert out["total_mm"] == pytest.approx(127224.05867687, abs=1e-6)
    assert out["items"][-1]["value_mm"] < 0  # 吸收存款为类负债项
    bad = [dict(items[0], page=58)]
    with pytest.raises(ValueError, match="未在原文"):
        resolve_non_operating_items(bad, doc)


@pytest.fixture(scope="module")
def moutai_run(tmp_path_factory):
    runs = tmp_path_factory.mktemp("runs")
    rc = main(["valuation", "--input", str(PDF), "--year", "2025", "--company", "贵州茅台",
               "--assumptions", str(WORK / "valuation_assumptions.json"), "--facts", str(WORK / "facts.json"),
               "--extras", str(WORK / "extras.json"), "--llm", "off", "--runs-dir", str(runs)])
    assert rc == 0
    return next(runs.iterdir())


def test_extras_verified_and_ratios_computed(doc):
    payload = json.loads((WORK / "extras.json").read_text(encoding="utf-8"))
    res = verify_extras(doc, payload)  # 预检：无真值表，引用真值表的比率跳过
    assert not res["rejected"]
    ratios = {r["id"]: r["value"] for r in res["ratios"]}
    assert ratios["price_moutai"] == pytest.approx(146499906480.49 / 46750.66 / 1e4)
    assert "payout" not in ratios
    bad = json.loads(json.dumps(payload))
    bad["tables"][0]["rows"][0]["values"][0] = "146,499,906,480.94"  # 抄错两位
    assert verify_extras(doc, bad)["rejected"][0]["reason"].startswith("未在所写页码")


def test_forecast_summary(moutai_run):
    fs = json.loads((moutai_run / "valuation" / "forecast_summary.json").read_text(encoding="utf-8"))
    m = fs["market"]
    assert m["market_cap"] == pytest.approx(1237.0 * 1252270215)
    y = {r["year"]: r for r in fs["years"]}
    assert y["2025A"]["np_parent"] == pytest.approx(82320067101.68)
    e = y["2026E"]
    assert e["eps"] == pytest.approx(e["np_parent"] / 1252270215)
    assert e["pe"] == pytest.approx(1237.0 / e["eps"])
    extras = json.loads((moutai_run / "financials" / "extras.json").read_text(encoding="utf-8"))
    payout = next(r for r in extras["ratios"] if r["id"] == "payout")
    assert payout["value"] == pytest.approx(650.33e8 / 82320067101.68 * 100)


def test_guard_accepts_segment_figures_and_flags_wrong_ones(moutai_run, tmp_path):
    ok = tmp_path / "ok.md"
    ok.write_text("分产品看，茅台酒毛利率 93.53%，同比下降 0.53 个百分点；茅台酒吨价 313.36 万元/吨。", encoding="utf-8")
    assert main(["guard", "--run-dir", str(moutai_run), "--text", str(ok)]) == 0
    bad = tmp_path / "bad.md"
    bad.write_text("分产品看，茅台酒毛利率 95.53%。", encoding="utf-8")
    assert main(["guard", "--run-dir", str(moutai_run), "--text", str(bad)]) == 1


def test_moutai_valuation_workbook(moutai_run):
    run = moutai_run
    val = json.loads((run / "valuation" / "valuation.json").read_text(encoding="utf-8"))
    assert val["three_statement_tie"]["status"] == "pass"
    with zipfile.ZipFile(run / "valuation" / "model.xlsx") as z:
        wb = z.read("xl/workbook.xml").decode("utf-8")
        for name in ("盈利预测", "非经营性资产", "历史财务", "分季度", "经营数据", "三表-利润表"):
            assert f'name="{name}"' in wb
        sheets = "".join(z.read(n).decode("utf-8") for n in z.namelist() if n.startswith("xl/worksheets/sheet"))
    assert "&apos;非经营性资产&apos;!$B$" in sheets or "'非经营性资产'!$B$" in sheets  # DCF 股权桥跨表引用明细合计
    assert "(C" in sheets and "/ABS(B" in sheets  # 历史财务同比公式按 (本期 − 上期) / |上期|


def test_linked_three_statement_formulas(moutai_run):
    """三表页为公式联动：利润表取假设页驱动，资产负债表取现金流量表期末现金，DCF 取三表；勾稽检查为公式。"""
    with zipfile.ZipFile(moutai_run / "valuation" / "model.xlsx") as z:
        names = re.findall(r'<sheet name="([^"]+)"', z.read("xl/workbook.xml").decode("utf-8"))
        sheet = lambda n: z.read(f"xl/worksheets/sheet{names.index(n) + 1}.xml").decode("utf-8")  # noqa: E731
        a, is_, bs, cf, dcf = (sheet(n) for n in ("三表-假设", "三表-利润表", "三表-资产负债表", "三表-现金流量表", "DCF"))
    assert "CHOOSE($B$5," in a
    assert "&apos;三表-假设&apos;!" in is_ or "'三表-假设'!" in is_
    assert re.search(r"(&apos;|')三表-现金流量表(&apos;|')!D\d+", bs)
    assert "ROUND(" in bs and "SUMPRODUCT(ABS(" in bs and "全部平衡" in bs
    assert re.search(r"(&apos;|')三表-利润表(&apos;|')!D\d+", cf)
    assert re.search(r"(&apos;|')三表-利润表(&apos;|')!D\d+", dcf)
    detail = json.loads((moutai_run / "valuation" / "three_statement_detail.json").read_text(encoding="utf-8"))
    bsd = detail["base"]["balance_sheet"]
    assert max(abs(x) for x in bsd["balance_check"]) < 1e-6
    assert detail["base"]["equity_flows"]["dividends"][0] == pytest.approx(
        detail["base"]["income_statement"]["net_income"][0]
        * json.loads((WORK / "valuation_assumptions.json").read_text(encoding="utf-8"))["three_statement"]["dividend_payout"])


def test_segment_forecast_drives_model(moutai_run):
    """分部量价预测 → 收入增速、毛利率、经营费用率 → 三表；评级由程序按规则给出。"""
    seg = json.loads((moutai_run / "valuation" / "segment_forecast.json").read_text(encoding="utf-8"))
    ts = json.loads((moutai_run / "valuation" / "three_statement.json").read_text(encoding="utf-8"))
    base = seg["scenarios"]["base"]
    rev = next(r for r in ts["statements"]["利润表"]["rows"] if r["key"] == "revenue")["values"]
    assert rev[0] == pytest.approx(base["revenue"][0])
    by = seg["base_year"]
    assert by["revenue"] == pytest.approx(168838.10251479)
    mt = base["segments"][0]
    assert mt["revenue"][0] == pytest.approx(mt["volume"][0] * mt["price"][0] / 100)
    fs = json.loads((moutai_run / "valuation" / "forecast_summary.json").read_text(encoding="utf-8"))
    assert fs["rating"]["rating"] in ("买入", "增持", "中性", "减持", "卖出")
    with zipfile.ZipFile(moutai_run / "valuation" / "model.xlsx") as z:
        names = re.findall(r'<sheet name="([^"]+)"', z.read("xl/workbook.xml").decode("utf-8"))
        a = z.read(f"xl/worksheets/sheet{names.index('三表-假设') + 1}.xml").decode("utf-8")
    assert "分部预测" in names and re.search(r"(&apos;|')分部预测(&apos;|')!D\d+", a)



def test_rating_rule_thresholds():
    from finagent.tasks.valuation.forecast_summary import rating

    assert [rating(u)["rating"] for u in (0.20, 0.199, 0.05, 0.0, -0.05, -0.2, -0.21)] == \
        ["买入", "增持", "增持", "中性", "中性", "减持", "卖出"]
    assert rating(0.3, [[0.15, "推荐"], [float("-inf"), "中性"]])["rating"] == "推荐"
    assert rating(None) is None


def test_guard_skips_forecast_sentences_but_checks_history(moutai_run, tmp_path):
    ok = tmp_path / "f.md"
    ok.write_text("我们预计公司 2026～2028 年营业收入分别为 1,725.25 亿元、1,792.31 亿元、1,885.17 亿元；"
                  "EPS 分别为 66.75 元、69.35 元、73.06 元。", encoding="utf-8")
    assert main(["guard", "--run-dir", str(moutai_run), "--text", str(ok)]) == 0
    bad = tmp_path / "h.md"
    bad.write_text("2025 年公司实现营业收入 1,725.25 亿元。", encoding="utf-8")  # 把预测数写成历史数
    assert main(["guard", "--run-dir", str(moutai_run), "--text", str(bad)]) == 1
