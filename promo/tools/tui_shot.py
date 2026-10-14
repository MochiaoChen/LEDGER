#!/usr/bin/env python3
"""把真实终端界面（finagent_tui，Textual）无头运行并导出 SVG，供宣传片上镜。

    .venv/bin/python promo/tools/tui_shot.py
选中工作区 中际旭创_2025，逐个标签页导出到 promo/public/tui/<tab>.svg。界面内容由应用自己读工作区产物渲染，本脚本不改任何内容。
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from finagent import catalog  # noqa: E402
from finagent_tui.app import FinAgentApp  # noqa: E402
from textual.widgets import Tree  # noqa: E402

OUT = ROOT / "promo" / "public" / "tui"
TARGET = "中际旭创"


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    app = FinAgentApp()
    async with app.run_test(size=(124, 36)) as pilot:
        await pilot.pause(0.5)
        tree = app.query_one("#tree", Tree)
        node = next(n for g in tree.root.children for n in g.children
                    if isinstance(n.data, catalog.Subject) and n.data.workspace and n.data.workspace.name == f"{TARGET}_2025")
        tree.select_node(node)
        app._select(node.data)
        await pilot.pause(0.5)
        for tab in ("overview", "facts", "valuation", "score", "trace", "agents"):
            app.action_tab(tab)
            await pilot.pause(0.6)
            if tab == "agents":  # 光标移到最后一次会话（排版），日志区显示它的收尾信息
                from textual.widgets import DataTable
                table = app.query_one("#agent-table", DataTable)
                table.focus()
                table.move_cursor(row=table.row_count - 1)
                await pilot.pause(0.8)
            (OUT / f"{tab}.svg").write_text(app.export_screenshot(title="finagent tui"), encoding="utf-8")
            print("写出", OUT / f"{tab}.svg")


asyncio.run(main())
