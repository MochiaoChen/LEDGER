"""数字出处类型：guard 给出正文每个数字属于事实（报告披露、外部来源）、推论（程序计算）还是观点（模型预测、估值假设）。"""

import json
import sys
from types import SimpleNamespace

import pytest

from conftest import ROOT, SAMPLES
from finagent import pipelines
from finagent.core.tracing import RunTracer
from finagent.output.guard import classify_text, tagged_truth_values, truth_values
from finagent.output.sources import run_guard


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory):
    c = {"input": str(SAMPLES / "annual_report_2024.md"), "fiscal_year": 2024, "company": "星河智造",
         "assumptions": str(SAMPLES / "valuation_assumptions.json"), "peers": str(SAMPLES / "peers.csv")}
    with RunTracer("prov", tmp_path_factory.mktemp("runs")) as tr:
        pipelines.run("valuation", c)
    return tr.dir


def test_tags_partition_truth_values(run_dir):
    tagged = tagged_truth_values(run_dir)
    assert sorted(v for vs in tagged.values() for v in vs) == sorted(truth_values(run_dir))
    assert all(tagged[k] for k in ("报告披露", "程序计算", "估值假设", "模型预测", "外部来源"))


def test_classify_priority_and_classes():
    tagged = {"报告披露": [5862000000.0], "外部来源": [2.1], "程序计算": [14.49], "估值假设": [0.085, 0.0585],
              "模型预测": [11.67, 14.49]}
    r = classify_text("营业收入 58.62 亿元，毛利率 14.49%，运力增长 2.1%，WACC 8.5%，每股价值 11.67 元，编造 9.99 元。", tagged)
    got = {n["number"]: (n["evidence"], n["class"]) for n in r["numbers"]}
    assert got == {"58.62亿元": ("报告披露", "事实"), "14.49%": ("程序计算", "推论"),  # 同时是模型预测时先认推论
                   "2.1%": ("外部来源", "事实"), "8.5%": ("估值假设", "观点"), "11.67元": ("模型预测", "观点")}
    assert r["counts"] == {"事实": 2, "推论": 1, "观点": 2}  # 找不到出处的 9.99 不计


def test_guard_reports_provenance_and_appendix_note(run_dir):
    val = json.loads((run_dir / "valuation" / "valuation.json").read_text(encoding="utf-8"))
    vps = val["value_range"]["base"]
    g = run_guard(run_dir, f"DCF 基准情景每股价值 {vps:.2f} 元。")
    assert g["provenance"]["numbers"] == [{"number": f"{vps:.2f}元", "evidence": "模型预测", "class": "观点"}]
    (run_dir / "commentary_guard.json").write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    sys.path.insert(0, str(ROOT / ".claude" / "skills" / "finagent-report"))
    from reportkit.layout import provenance_note
    note = provenance_note(SimpleNamespace(dir=run_dir))
    assert "可溯源的 1 个数字" in note and "观点 1 个（模型预测 1 个）" in note
    assert provenance_note(SimpleNamespace(dir=run_dir / "无")) == ""
