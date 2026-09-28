"""自研引擎产物 == 原插件引擎产物（tests/golden/ 下的快照，见该目录 README）。"""

import json
import re
import zipfile

import pytest

from conftest import ROOT, SAMPLES
from finagent import pipelines
from finagent.core.tracing import RunTracer

GOLDEN = ROOT / "tests" / "golden"
ARTIFACTS = {
    "three_statement.json": "valuation/three_statement.json",
    "scenarios.json": "valuation/scenarios.json",
    "comps.json": "valuation/comps.json",
    "earnings.json": "financials/earnings.json",
}


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    c = {"input": str(SAMPLES / "annual_report_2024.md"), "fiscal_year": 2024, "company": "星河智造",
         "assumptions": str(SAMPLES / "valuation_assumptions.json"), "report": str(SAMPLES / "research_draft.md"),
         "peers": str(SAMPLES / "peers.csv"), "estimates": str(SAMPLES / "estimates.csv"),
         "guidance": str(SAMPLES / "guidance.csv"), "llm": None}
    with RunTracer("golden", tmp_path_factory.mktemp("runs")) as tr:
        pipelines.run("all", c)
    return tr.dir


@pytest.mark.parametrize("golden,artifact", ARTIFACTS.items())
def test_matches_original_engine(run_dir, golden, artifact):
    expected = json.loads((GOLDEN / golden).read_text(encoding="utf-8"))
    actual = json.loads((run_dir / artifact).read_text(encoding="utf-8"))
    assert actual == expected


def test_formula_workbook_cached_values_match_comps(run_dir):
    """公式工作簿的估值区间缓存值与 comps.json 一致（公式本身的独立重算见 PR 说明）。"""
    comps = json.loads((run_dir / "valuation" / "comps.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(run_dir / "valuation" / "comps_formula_workbook.xlsx") as z:
        names = z.namelist()
        sheet = z.read("xl/worksheets/sheet6.xml").decode("utf-8")  # 隐含股价（首张为估值摘要）
        assert b"fullCalcOnLoad" in z.read("xl/workbook.xml")
    assert "xl/worksheets/sheet6.xml" in names
    cells = dict(re.findall(r'<c r="([A-Z]+\d+)"(?: [a-z]+="[^"]*")*>(?:(?!</c>).)*?<v>([^<]*)</v></c>', sheet))
    for ref, key in (("B9", "low"), ("C9", "mid"), ("D9", "high")):
        assert float(cells[ref]) == comps["range"][key]


def test_formula_workbook_sensitivity_and_ledger(run_dir):
    """敏感性表 0% 列 = 隐含股价；来源台账覆盖目标公司与全部同业。"""
    comps = json.loads((run_dir / "valuation" / "comps_formula_workbook.xlsx").parent.joinpath("comps.json")
                       .read_text(encoding="utf-8"))
    with zipfile.ZipFile(run_dir / "valuation" / "comps_formula_workbook.xlsx") as z:
        sens = z.read("xl/worksheets/sheet7.xml").decode("utf-8")
        ledger = z.read("xl/worksheets/sheet8.xml").decode("utf-8")
    cells = dict(re.findall(r'<c r="([A-Z]+\d+)"(?: [a-z]+="[^"]*")*>(?:(?!</c>).)*?<v>([^<]*)</v></c>', sens))
    implied = {r["multiple"]: r for r in comps["implied"]}
    for first_row, name in ((4, "EV/EBITDA"), (11, "P/E（LTM）")):
        for off, lvl in enumerate(("p25", "median", "p75")):
            assert float(cells[f"E{first_row + off}"]) == pytest.approx(implied[name][lvl], rel=1e-12)
    assert ledger.count("<row ") == len(comps["rows"]) + 1


def test_formula_workbook_summary_and_charts(run_dir):
    """估值摘要置于首张，含关键结论、倍数、利润率和两张原生 Excel 图表。"""
    comps = json.loads((run_dir / "valuation" / "comps.json").read_text(encoding="utf-8"))
    with zipfile.ZipFile(run_dir / "valuation" / "comps_formula_workbook.xlsx") as z:
        wb = z.read("xl/workbook.xml").decode("utf-8")
        summary = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        names = z.namelist()
    assert re.findall(r'<sheet name="([^"]+)"', wb)[0] == "估值摘要"
    assert "xl/charts/chart1.xml" in names and "xl/charts/chart2.xml" in names
    assert "xl/drawings/drawing1.xml" in names and '<drawing r:id="rId1"/>' in summary
    cells = dict(re.findall(r'<c r="([A-Z]+\d+)"(?: [a-z]+="[^"]*")*>(?:(?!</c>).)*?<v>([^<]*)</v></c>', summary))
    assert float(cells["B6"]) == comps["rows"][0]["price"]
    assert float(cells["C6"]) == comps["range"]["low"]
    assert float(cells["D6"]) == comps["range"]["mid"]
    assert float(cells["E6"]) == comps["range"]["high"]
