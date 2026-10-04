"""统一命令行与终端界面：命令分发、旧入口兼容、产物目录读取、界面各页能渲染。"""

import asyncio
import json

import pytest

from finagent import catalog, cli


def test_usage_lists_every_group(capsys):
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    for name in cli.GROUPS:
        assert name in out


def test_groups_and_legacy_tasks_dispatch(monkeypatch):
    seen = []
    monkeypatch.setitem(cli.GROUPS, "report", (lambda a: seen.append(("report", a)) or 0, ""))
    monkeypatch.setattr(cli, "_research", lambda a: seen.append(("research", a)) or 0)
    monkeypatch.setitem(cli.GROUPS, "research", (cli._research, ""))
    assert cli.main(["report", "status", "--workspace", "w"]) == 0
    assert cli.main(["verify-facts", "--input", "x.pdf"]) == 0  # 旧写法：finagent <任务>
    assert seen == [("report", ["status", "--workspace", "w"]), ("research", ["verify-facts", "--input", "x.pdf"])]
    assert cli.main(["nope"]) == 2


def test_research_schema_through_unified_cli(capsys):
    assert cli.main(["research", "schema"]) == 0
    assert "revenue" in capsys.readouterr().out


def _run(tmp_path, name="20261004-000000-valuation"):
    d = tmp_path / "runs" / name
    (d / "financials").mkdir(parents=True)
    (d / "valuation").mkdir()
    facts = [{"metric_id": "revenue", "period": "2025", "value": 1.5e9, "raw": "1,500,000,000", "unit": "元",
              "metric_name": "营业收入", "method": "rule_table",
              "source": {"source": "a.pdf", "page": 12, "chunk_id": "c1", "caption": "合并利润表", "continued_from": "c0"}}]
    (d / "financials" / "analysis.json").write_text(json.dumps(
        {"period": "2025", "truth_table": facts, "tieouts": [{"status": "pass"}], "signals": [], "summary": {}}),
        encoding="utf-8")
    (d / "valuation" / "valuation.json").write_text(json.dumps({
        "current_price": 50.0, "value_range": {"low": 30.0, "base": 45.0, "high": 70.0},
        "scenarios": [{"scenario": "base", "scenario_cn": "基准", "wacc": 0.09, "terminal_growth": 0.03,
                       "enterprise_value_mm": 1000.0, "equity_value_mm": 1100.0, "value_per_share": 45.0,
                       "tv_percent_ev": 0.6, "upside_vs_price": -0.1}],
        "forecast_base": [{"period": "2026", "revenue": 1600.0, "revenue_growth": 0.07}],
        "sensitivities": [{"name": "WACC × 永续增长率", "x_axis": "wacc_delta", "y_axis": "terminal_growth_delta",
                           "x_values": [-0.01, 0.0], "y_values": [0.0, 0.01], "matrix": [[50.0, 45.0], [55.0, 48.0]]}],
        "bridge_base": {"add_backs": 100.0, "deductions": 0.0, "equity_value": 1100.0}}), encoding="utf-8")
    (d / "valuation" / "forecast_summary.json").write_text(json.dumps({"rating": {"rating": "中性", "upside": -0.1}}),
                                                            encoding="utf-8")
    (d / "events.jsonl").write_text(json.dumps({"seq": 1, "ts": "2026-10-04T00:00:00.000", "kind": "run_start",
                                                "task": "valuation"}) + "\n", encoding="utf-8")
    return d


def test_catalog_reads_run_products(tmp_path):
    d = _run(tmp_path)
    (tmp_path / "runs" / "20261004-000001-eval" / "financials").mkdir(parents=True)  # 样例评测的运行不列
    (tmp_path / "runs" / "20261004-000001-eval" / "financials" / "analysis.json").write_text("{}", encoding="utf-8")
    subjects = catalog.runs(tmp_path / "runs")
    assert [s.run for s in subjects] == [d]
    s = subjects[0]
    assert catalog.analysis(s)["truth_table"][0]["metric_id"] == "revenue"
    assert catalog.valuation(s)["rating"]["rating"] == "中性"
    assert catalog.events(s)[0]["kind"] == "run_start"
    assert catalog.gates(s) is None and catalog.agent_runs(s) == []


def test_tui_renders_every_tab(tmp_path):
    pytest.importorskip("textual")
    from textual.widgets import TabbedContent

    from finagent_tui.app import FinAgentApp

    _run(tmp_path)

    async def drive():
        app = FinAgentApp(samples=tmp_path / "none", runs_root=tmp_path / "runs")
        async with app.run_test(size=(160, 45)) as pilot:
            await pilot.pause(0.3)
            tree = app.query_one("#tree")
            leaf = next(n for top in tree.root.children for n in top.children if n.data)
            app._select(leaf.data)
            for tab in ("overview", "facts", "valuation", "score", "trace", "agents", "command"):
                app.action_tab(tab)
                await pilot.pause(0.1)
                assert app.query_one("#tabs", TabbedContent).active == tab
            assert app.query_one("#facts-table").row_count == 1
            assert app.query_one("#trace-table").row_count == 1

    asyncio.run(drive())
