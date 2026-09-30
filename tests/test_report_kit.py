"""研报排版工具包 reportkit（Skill：finagent-report）：换公司时容易出问题的情形都要能渲染出 HTML。

- 模板脚本在“另一家公司”（样例星河智造：有负债、有可比公司、没有经营数据和分部预测、低价股）上可用；
- 亏损公司（利润、EPS、P/E 为负）、没有分季度数据、没有可比公司时不报错；
- 茅台脚本（经营数据最全）可用。
只生成 HTML（--no-pdf），不依赖浏览器。
"""

import json
import re
import runpy
import shutil
import sys

import pytest

from conftest import ROOT, SAMPLES
from finagent.__main__ import main

KIT = ROOT / ".claude" / "skills" / "finagent-report"
TEMPLATE = KIT / "templates"
sys.path.insert(0, str(KIT))


@pytest.fixture(scope="module")
def sample_run(tmp_path_factory):
    runs = tmp_path_factory.mktemp("runs")
    rc = main(["all", "--input", str(SAMPLES / "annual_report_2024.md"), "--year", "2024", "--company", "星河智造",
               "--assumptions", str(SAMPLES / "valuation_assumptions.json"), "--report", str(SAMPLES / "research_draft.md"),
               "--peers", str(SAMPLES / "peers.csv"), "--estimates", str(SAMPLES / "estimates.csv"),
               "--guidance", str(SAMPLES / "guidance.csv"), "--llm", "off", "--runs-dir", str(runs)])
    assert rc == 0
    return next(runs.iterdir())


def _build_template(run_dir, tmp_path, *extra, out="report"):
    """把模板复制到仓库内的临时目录（模板按 .claude/skills 所在目录定位 reportkit），只生成 HTML。"""
    work = ROOT / "data" / "extractions" / f"_kit_test_{tmp_path.name}" / "report"
    work.mkdir(parents=True)
    try:
        for f in TEMPLATE.iterdir():
            shutil.copy(f, work / f.name)
        argv = sys.argv
        sys.argv = ["build_report.py", "--run-dir", str(run_dir), "--no-pdf", *extra]
        try:
            with pytest.raises(SystemExit) as e:
                runpy.run_path(str(work / "build_report.py"), run_name="__main__")
            assert e.value.code == 0
        finally:
            sys.argv = argv
    finally:
        shutil.rmtree(work.parent)
    return (run_dir / out / "report.html").read_text(encoding="utf-8")


def _figs(html):
    return re.findall(r'<span class="fno">图表 (\d+)</span>', html)


def test_template_on_another_company(sample_run, tmp_path):
    html = _build_template(sample_run, tmp_path)
    figs = _figs(html)
    assert figs == [str(i) for i in range(1, len(figs) + 1)] and len(figs) >= 18  # 连续编号
    assert "可比公司估值倍数与利润率" in html and "免责声明" in html
    assert "&lt;公司&gt;" in html  # 首页占位符被转义显示，而不是被浏览器当成标签
    assert "__HEADER__" not in html and "__KIND__" not in html  # 页眉占位符已替换
    # 低价股：敏感性矩阵保留两位小数
    heat = re.search(r'<table class="heat">.*?</table>', html, re.S).group(0)
    assert re.search(r">\d+\.\d{2}</td>", heat)
    for svg in (sample_run / "report" / "charts").glob("*.svg"):
        assert svg.stat().st_size > 1000


def test_template_survives_loss_no_quarterly_no_comps(sample_run, tmp_path):
    run = tmp_path / "loss_run"
    shutil.copytree(sample_run, run)
    (run / "report").exists() and shutil.rmtree(run / "report")
    (run / "valuation" / "comps.json").unlink()
    a = json.loads((run / "financials" / "analysis.json").read_text(encoding="utf-8"))
    a["quarterly"] = {"year": a["period"], "rows": []}
    for c in a["truth_table"]:
        if c["metric_id"] in ("np_parent", "np_parent_deducted", "net_profit", "eps_basic"):
            c["value"] = -abs(c["value"])
    (run / "financials" / "analysis.json").write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")
    fs = json.loads((run / "valuation" / "forecast_summary.json").read_text(encoding="utf-8"))
    for y in fs["years"]:
        y["np_parent"], y["eps"] = -abs(y["np_parent"]), -abs(y["eps"])
        y["pe"] = None
    fs["market"]["pe_latest"] = -5.0
    (run / "valuation" / "forecast_summary.json").write_text(json.dumps(fs, ensure_ascii=False), encoding="utf-8")
    html = _build_template(run, tmp_path)
    assert "可比公司估值倍数" not in html and "分季度营业收入" not in html  # 缺数据的图表整块跳过
    assert len(_figs(html)) >= 14


def test_moutai_script_builds(tmp_path):
    work = ROOT / "data" / "extractions" / "贵州茅台_2025"
    runs = tmp_path / "runs"
    pdf = ROOT / "report" / "resources" / "贵州茅台" / "600519_贵州茅台_2025_年度报告.pdf"
    assert main(["valuation", "--input", str(pdf), "--year", "2025", "--company", "贵州茅台",
                 "--assumptions", str(work / "valuation_assumptions.json"), "--facts", str(work / "facts.json"),
                 "--extras", str(work / "extras.json"), "--llm", "off", "--runs-dir", str(runs)]) == 0
    run = next(runs.iterdir())
    argv = sys.argv
    sys.argv = ["build_report.py", "--run-dir", str(run), "--no-pdf"]
    try:
        with pytest.raises(SystemExit) as e:
            runpy.run_path(str(work / "report" / "build_report.py"), run_name="__main__")
        assert e.value.code == 0
    finally:
        sys.argv = argv
    html = (run / "report" / "report.html").read_text(encoding="utf-8")
    assert len(_figs(html)) == 57 and "__HEADER__" not in html  # 含股权价值桥表


def test_red_palette(sample_run, tmp_path):
    """红色配色是唯一配色：CSS 与图表都用红色，不再提供 --theme 切换，报告固定输出到 report/。"""
    from reportkit import core
    html = _build_template(sample_run, tmp_path)
    assert "#C6342C" in html and "#1B365D" not in html and "__HEADER__" not in html
    assert core.NAVY == "#A21316" and not hasattr(core, "THEMES")
    svg = (sample_run / "report" / "charts" / "history.svg").read_text(encoding="utf-8")
    assert "#a21316" in svg.lower()


def test_equity_bridge_reconciles(sample_run):
    """股权价值桥表逐项加总 = 股权价值；与估值结果、非经营性资产合计口径一致（正文描述汇总数构成前的对账依据）。"""
    from reportkit import tables as T
    from reportkit.core import Run
    run = Run(sample_run)
    html = T.equity_bridge(run)
    vals = [float(x.replace(",", "")) for x in re.findall(r"<td(?: class=\"neg\")?>(-?[\d,]+\.\d{2})</td>", html)]
    ev, *items, equity, shares = vals  # 每股价值加粗，不在匹配结果里
    assert ev + sum(items) == pytest.approx(equity, abs=0.02)
    br = run.valuation["bridge_base"]
    assert equity == pytest.approx(br["equity_value"] / 100, abs=0.01)
