"""终端界面：概览页取正式评测的分数；三套主题都能挂载，切换主题时语义色跟着换。"""

import asyncio
import json

import pytest

from finagent import catalog


def _score(d, total, run, when, variant=None):
    d.mkdir(parents=True)
    (d / "score.json").write_text(json.dumps({"total": total, "deliverable": total >= 75, "layers": {}, "items": []}))
    (d / "bundle.json").write_text(json.dumps({"run": run, "evaluated_at": when}))
    if variant:
        (d / "variant.json").write_text(json.dumps({"kind": variant, "desc": "注入程序口吻"}))


def test_primary_score_ignores_calibration(tmp_path, monkeypatch):
    run = str(tmp_path / "ws" / "runs" / "r1")
    results, cal = tmp_path / "results", tmp_path / "calibration"
    _score(results / "v2_甲", 90, run, "2026-10-04T10:00:00")
    _score(cal / "甲" / "clean1", 85, run, "2026-10-04T14:00:00", "clean")
    _score(cal / "甲" / "clean2", 78, run, "2026-10-04T15:00:00", "clean")
    _score(cal / "甲" / "machine_tone", 81, run, "2026-10-04T16:00:00", "machine_tone")
    monkeypatch.setattr(catalog, "RESULTS", results)
    monkeypatch.setattr(catalog, "CALIBRATION", cal)
    monkeypatch.setattr(catalog, "PROJECT_ROOT", tmp_path)
    s = catalog.Subject("run", "r1", tmp_path / "ws" / "runs" / "r1")
    scs = catalog.scores(s)
    assert [x["kind"] for x in scs] == ["result", "repeat", "repeat", "variant"]
    assert scs[-1]["total"] == 81                      # 时间上最新的是劣化版本
    assert catalog.primary_score(scs)["total"] == 90   # 代表这份研报的是正式评测
    assert catalog.repeat_totals(scs) == [85, 78]
    assert catalog.primary_score([]) is None


def test_palette_follows_theme():
    pytest.importorskip("textual")
    from finagent_tui import render as R
    from finagent_tui.themes import PALETTE
    R.use_palette("ledger-paper")
    assert R.OK == PALETTE["ledger-paper"]["ok"] and R.EVENT_STYLE["artifact"] == R.OK
    assert R._heat(1, 0, 2) == "on " + PALETTE["ledger-paper"]["heat_mid"].lower()
    R.use_palette("nord")                              # Textual 自带主题沿用原配色
    assert R.OK == PALETTE["_fallback"]["ok"]
    R.use_palette("ledger-graphite")


@pytest.mark.parametrize("theme", ["ledger-ink", "ledger-paper", "ledger-graphite"])
def test_app_mounts_with_theme(theme, tmp_path):
    pytest.importorskip("textual")
    from finagent_tui.app import FinAgentApp

    async def run():
        app = FinAgentApp(samples=tmp_path, runs_root=tmp_path, theme=theme)
        async with app.run_test(size=(120, 36)) as pilot:
            await pilot.pause(0.2)
            assert app.theme == theme
            from finagent_tui import render as R
            from finagent_tui.themes import PALETTE
            assert R.OK == PALETTE[theme]["ok"]
    asyncio.run(run())
