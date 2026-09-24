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
        sheet = z.read("xl/worksheets/sheet5.xml").decode("utf-8")  # 隐含股价
        assert b"fullCalcOnLoad" in z.read("xl/workbook.xml")
    assert "xl/worksheets/sheet5.xml" in names
    cells = dict(re.findall(r'<c r="([A-Z]+\d+)">.*?<v>([^<]*)</v></c>', sheet))
    for ref, key in (("B9", "low"), ("C9", "mid"), ("D9", "high")):
        assert float(cells[ref]) == comps["range"][key]
