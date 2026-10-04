"""FinAgent 终端界面。

  finagent tui [--samples ~/finagent-samples] [--runs runs/]

左侧选研报工作区或运行目录，右侧七页：概览（闸门、估值区间、评级、质检分）、真值表（点数字看来源页码）、
估值（三情景、预测、敏感性热力表）、质检（逐条判定与证据）、追溯（文件读写与步骤回放）、
Agent（各会话用量与事件流）、命令（在界面里跑 finagent 任意命令）。只读产物，不改文件。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

from rich.console import Group
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (Button, DataTable, Footer, Header, Input, Label, RichLog, Select, Static, TabbedContent,
                             TabPane, Tree)

from finagent import catalog
from finagent.core.config import PROJECT_ROOT
from finagent.report_pipeline import default_dest

from . import render as R

MAX_PERIODS = 6


def _open(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


class Card(Static):
    """带标题边框的面板。"""

    def __init__(self, title: str, body: Any = "", **kw: Any) -> None:
        super().__init__(body, **kw)
        self.border_title = title


class FinAgentApp(App):
    CSS_PATH = "app.tcss"
    TITLE = "FinAgent"
    SUB_TITLE = "金融投研智能体 · 财报分析 · 估值建模 · 研报纠错"
    BINDINGS = [
        Binding("q", "quit", "退出"),
        Binding("r", "refresh", "刷新"),
        Binding("o", "open_pdf", "打开研报"),
        Binding("x", "open_xlsx", "打开模型"),
        Binding("b", "toggle_sidebar", "侧栏"),
        *[Binding(str(i + 1), f"tab('{t}')", n, show=False) for i, (t, n) in enumerate(
            [("overview", "概览"), ("facts", "真值表"), ("valuation", "估值"), ("score", "质检"), ("trace", "追溯"),
             ("agents", "Agent"), ("command", "命令")])],
    ]

    def __init__(self, samples: Path | None = None, runs_root: Path | None = None) -> None:
        super().__init__()
        self.samples = samples or default_dest()
        self.runs_root = runs_root or catalog.RUNS
        self.subject: catalog.Subject | None = None
        self._facts: dict[tuple[str, str], dict[str, Any]] = {}
        self._scores: list[dict[str, Any]] = []
        self._agent_rows: list[dict[str, Any]] = []
        self._events: list[dict[str, Any]] = []
        self._proc: asyncio.subprocess.Process | None = None

    # ------------------------------------------------------------------ 布局
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Label("对象", classes="side-title")
                yield Tree("root", id="tree")
                yield Static(id="side-hint")
            with TabbedContent(id="tabs", initial="overview"):
                with TabPane("概览", id="overview"):
                    with VerticalScroll():
                        yield Static(id="ov-head")
                        with Horizontal(classes="row"):
                            yield Card("估值区间（元/股）", id="ov-value")
                            yield Card("质检", id="ov-score")
                        with Horizontal(classes="row"):
                            yield Card("流水线闸门", id="ov-gates")
                            yield Card("财报分析", id="ov-fin")
                with TabPane("真值表", id="facts"):
                    yield Input(placeholder="筛选指标（如 营业收入 / revenue）", id="facts-filter")
                    yield DataTable(id="facts-table", zebra_stripes=True, cursor_type="cell")
                    yield Card("来源", id="facts-source")
                with TabPane("估值", id="valuation"):
                    with VerticalScroll():
                        yield Static(id="val-body")
                with TabPane("质检", id="score"):
                    yield Select([], prompt="选择评测结果", id="score-select", allow_blank=True)
                    yield Static(id="score-head")
                    yield DataTable(id="score-table", zebra_stripes=True, cursor_type="row")
                    yield Card("判定理由与证据", id="score-detail")
                with TabPane("追溯", id="trace"):
                    yield Input(placeholder="筛选事件（如 file_read / artifact / extract）", id="trace-filter")
                    yield DataTable(id="trace-table", zebra_stripes=True, cursor_type="row")
                with TabPane("Agent", id="agents"):
                    yield DataTable(id="agent-table", zebra_stripes=True, cursor_type="row")
                    yield RichLog(id="agent-log", wrap=True, markup=False, highlight=False)
                with TabPane("命令", id="command"):
                    with Horizontal(id="cmd-bar"):
                        yield Label("finagent", id="cmd-prefix")
                        yield Input(placeholder="例如：report status --workspace …  /  bench  /  doctor", id="cmd-input")
                        yield Button("运行", id="cmd-run", variant="primary")
                        yield Button("停止", id="cmd-stop", variant="error")
                    yield Static(id="cmd-presets")
                    yield RichLog(id="cmd-log", wrap=True, markup=False, highlight=True)
        yield Footer()

    def on_mount(self) -> None:
        self.theme = "tokyo-night"
        self.query_one("#score-detail").border_subtitle = "↑↓ 选条目"
        self.query_one("#facts-source").border_subtitle = "方向键移动到数字"
        self._build_tree()

    # ------------------------------------------------------------------ 侧栏
    def _build_tree(self) -> None:
        tree = self.query_one("#tree", Tree)
        tree.clear()
        tree.show_root = False
        first = None
        ws_node = tree.root.add(Text("研报工作区", style="bold"), expand=True)
        for s in catalog.workspaces(self.samples):
            g = catalog.gates(s) or {}
            st = g.get("stages", [])
            done = sum(x["ok"] for x in st)
            mark = Text("● ", style=R.OK) if g.get("done") else Text("◐ ", style=R.WARN)
            label = mark + Text(s.title) + Text(f"  {done}/{len(st)}", style=R.MUTED)
            node = ws_node.add_leaf(label, data=s)
            first = first or node
        run_node = tree.root.add(Text("仓库运行", style="bold"), expand=True)
        for s in catalog.runs(self.runs_root, limit=15):
            run_node.add_leaf(Text(s.title, style="") + Text(f"  {s.company}", style=R.MUTED), data=s)
        self.query_one("#side-hint", Static).update(Text(f"工作区目录\n{self.samples}", style=R.MUTED))
        if first is not None:
            tree.select_node(first)
            self._select(first.data)

    @on(Tree.NodeSelected, "#tree")
    def _tree_selected(self, ev: Tree.NodeSelected) -> None:
        if isinstance(ev.node.data, catalog.Subject):
            self._select(ev.node.data)

    def _select(self, s: catalog.Subject) -> None:
        self.subject = s
        self._fill_overview()
        self._fill_facts()
        self._fill_valuation()
        self._fill_scores()
        self._fill_trace()
        self._fill_agents()
        self._fill_presets()

    # ------------------------------------------------------------------ 概览
    def _fill_overview(self) -> None:
        s = self.subject
        v = catalog.valuation(s)
        a = catalog.analysis(s)
        head = Text()
        head.append(s.company or s.title, style="bold #c0caf5")
        head.append(f"   {s.run.name if s.run else '尚无估值运行'}", style=R.MUTED)
        head.append("   ")
        head.append_text(R.rating_badge(v))
        pdf = catalog.pdf(s)
        sub = Text(f"\n研报 {pdf.name}（o 打开）" if pdf else "\n尚无研报 PDF", style=R.MUTED)
        if catalog.workbook(s):
            sub.append("   估值模型 model.xlsx（x 打开）", style=R.MUTED)
        self.query_one("#ov-head", Static).update(Group(head, sub))
        self.query_one("#ov-value", Card).update(R.value_bar(v) if v else Text("无估值产物", style=R.MUTED))
        sc = catalog.scores(s)
        self.query_one("#ov-score", Card).update(R.score_header(sc[-1]) if sc else Text("尚未评测", style=R.MUTED))
        self.query_one("#ov-gates", Card).update(R.gates_table(catalog.gates(s)))
        fin = Text()
        if a:
            fin.append(f"分析期间 {a.get('period', '')}\n", style="bold")
            tie = a.get("tieouts") or []
            fails = [t for t in tie if t.get("status") == "fail"]
            fin.append(f"勾稽 {len(tie) - len(fails)}/{len(tie)} 通过\n", style=R.OK if not fails else R.BAD)
            sig = a.get("signals") or []
            fin.append(f"异常信号 {len(sig)} 条", style=R.WARN if sig else R.OK)
            for x in sig[:5]:
                fin.append(f"\n  · {x.get('title') or x.get('message') or x.get('type', '')}"[:90], style="")
        self.query_one("#ov-fin", Card).update(fin or Text("无财报分析产物", style=R.MUTED))

    # ------------------------------------------------------------------ 真值表
    def _fill_facts(self, keyword: str = "") -> None:
        a = catalog.analysis(self.subject)
        rows = a.get("truth_table") or []
        self._facts = {(f["metric_id"], f["period"]): f for f in rows}
        periods = sorted({p for _, p in self._facts}, key=lambda p: (p[:4], p[4:] == "", p), reverse=True)[:MAX_PERIODS]
        table = self.query_one("#facts-table", DataTable)
        table.clear(columns=True)
        table.add_column("指标", key="metric", width=22)
        for p in periods:
            table.add_column(p, key=p, width=14)
        kw = keyword.strip().lower()
        names = {m: f.get("metric_name") or R.metric_name(m) for (m, _), f in self._facts.items()}
        for mid in sorted(names, key=R.metric_order):
            name = names[mid]
            if kw and kw not in name.lower() and kw not in mid.lower():
                continue
            cells = []
            for p in periods:
                f = self._facts.get((mid, p))
                if f is None:
                    cells.append(Text("", style=R.MUTED))
                    continue
                style = R.ACCENT if f.get("method") == "derived" else ""
                cells.append(Text(R.fmt_fact(mid, f.get("value")), style=style, justify="right"))
            table.add_row(Text(name), *cells, key=mid)
        self.query_one("#facts-source", Card).update(Text(f"{len(self._facts)} 个数；蓝色为程序推导值", style=R.MUTED))

    @on(Input.Changed, "#facts-filter")
    def _facts_filter(self, ev: Input.Changed) -> None:
        self._fill_facts(ev.value)

    @on(DataTable.CellHighlighted, "#facts-table")
    def _fact_cell(self, ev: DataTable.CellHighlighted) -> None:
        mid, period = ev.cell_key.row_key.value, ev.cell_key.column_key.value
        f = self._facts.get((mid, period))
        card = self.query_one("#facts-source", Card)
        if not f:
            card.update(Text(R.metric_name(mid or ""), style=R.MUTED))
            return
        src = f.get("source") or {}
        t = Text()
        t.append(f"{R.metric_name(mid)} {period} = ", style="bold")
        t.append(f"{f.get('raw') or R.fmt_fact(mid, f.get('value'))} {f.get('unit', '')}", style=f"bold {R.ACCENT}")
        t.append(f"   方法 {f.get('method', '')}  置信度 {f.get('confidence', '')}\n", style=R.MUTED)
        if f.get("method") == "derived":
            t.append(f"推导：{f.get('formula') or src.get('formula') or ''}", style="")
        else:
            t.append(f"{Path(str(src.get('source', ''))).name}  第 {src.get('page', '?')} 页", style="bold")
            t.append(f"  {src.get('caption', '')}  行 {src.get('row', '—')} 列 {src.get('col', '—')}  {src.get('chunk_id', '')}")
            if src.get("continued_from"):
                t.append(f"  跨页续表（表头来自 {src['continued_from']}）", style=R.WARN)
            cor = f.get("corroborated_by") or []
            if cor:
                t.append(f"\n交叉印证 {len(cor)} 处：" + "；".join(
                    f"第 {c.get('page', '?')} 页 {c.get('extractor') or c.get('caption', '')}" for c in cor[:3]), style=R.OK)
        card.update(t)

    # ------------------------------------------------------------------ 估值
    def _fill_valuation(self) -> None:
        v = catalog.valuation(self.subject)
        body = self.query_one("#val-body", Static)
        if not v:
            body.update(Text("该对象没有估值产物（valuation/valuation.json）。", style=R.MUTED))
            return
        parts: list[Any] = [R.rating_badge(v), Text(""), R.value_bar(v), Text(""), R.scenarios_table(v), Text("")]
        bridge = v.get("bridge_base") or {}
        if bridge:
            parts.append(Text(f"股权价值桥（基准，百万元）：企业价值 + 加回 {bridge.get('add_backs', 0):,.0f} − 扣减 "
                              f"{bridge.get('deductions', 0):,.0f} = 股权价值 {bridge.get('equity_value', 0):,.0f}",
                              style=R.MUTED))
            parts.append(Text(""))
        parts += [R.forecast_table(v), Text("")]
        for t in R.sensitivity_tables(v):
            parts += [t, Text("")]
        parts.append(Text(f"模型状态 {v.get('model_status', '')}；数值均为引擎产物，界面不重算。", style=R.MUTED))
        body.update(Group(*parts))

    # ------------------------------------------------------------------ 质检
    def _fill_scores(self) -> None:
        self._scores = catalog.scores(self.subject)
        sel = self.query_one("#score-select", Select)
        sel.set_options([(f"{sc['label']} · {sc.get('total', 0):g} 分", i) for i, sc in enumerate(self._scores)])
        if self._scores:
            sel.value = len(self._scores) - 1
            self._show_score(len(self._scores) - 1)
        else:
            self.query_one("#score-head", Static).update(Text("尚未评测：finagent eval run --workspace <工作区>", style=R.MUTED))
            self.query_one("#score-table", DataTable).clear(columns=True)

    @on(Select.Changed, "#score-select")
    def _score_changed(self, ev: Select.Changed) -> None:
        if isinstance(ev.value, int):
            self._show_score(ev.value)

    def _show_score(self, i: int) -> None:
        sc = self._scores[i]
        self.query_one("#score-head", Static).update(R.score_header(sc))
        table = self.query_one("#score-table", DataTable)
        table.clear(columns=True)
        for col, w in (("层", 4), ("条目", 7), ("标题", 22), ("判定方", 7), ("结果", 8), ("分值", 6)):
            table.add_column(col, width=w)
        for r in sc.get("items", []):
            neg = r["layer"] == "N"
            bad = r["passed"] if neg else not r["passed"]
            mark = Text(("命中" if neg else "未过") if bad else ("未命中" if neg else "通过"), style=R.BAD if bad else R.OK)
            pts = r.get("got", r.get("points", 0))
            table.add_row(r["layer"], r["id"], r.get("title", ""), "程序" if r.get("judge") == "program" else "评审",
                          mark, f"{pts:g}" if isinstance(pts, (int, float)) else str(pts), key=r["id"])

    @on(DataTable.RowHighlighted, "#score-table")
    def _score_row(self, ev: DataTable.RowHighlighted) -> None:
        sel = self.query_one("#score-select", Select).value
        if not isinstance(sel, int) or not self._scores:
            return
        item = next((r for r in self._scores[sel].get("items", []) if r["id"] == ev.row_key.value), None)
        if not item:
            return
        t = Text()
        t.append(f"{item['id']} {item.get('title', '')}\n", style="bold")
        t.append(str(item.get("reason") or item.get("detail") or ""), style="")
        if item.get("evidence"):
            t.append(f"\n证据：{item['evidence']}", style=R.MUTED)
        self.query_one("#score-detail", Card).update(t)

    # ------------------------------------------------------------------ 追溯
    def _fill_trace(self, keyword: str = "") -> None:
        self._events = catalog.events(self.subject)
        table = self.query_one("#trace-table", DataTable)
        table.clear(columns=True)
        for col, w in (("#", 5), ("时间", 13), ("事件", 14), ("内容", 100)):
            table.add_column(col, width=w)
        kw = keyword.strip().lower()
        for ev in self._events:
            summary = R.event_summary(ev)
            kind = ev.get("kind", "")
            if kw and kw not in kind.lower() and kw not in summary.lower():
                continue
            table.add_row(str(ev.get("seq", "")), str(ev.get("ts", ""))[11:23],
                          Text(kind, style=R.EVENT_STYLE.get(kind, "")), summary)

    @on(Input.Changed, "#trace-filter")
    def _trace_filter(self, ev: Input.Changed) -> None:
        self._fill_trace(ev.value)

    # ------------------------------------------------------------------ Agent
    def _fill_agents(self) -> None:
        self._agent_rows = catalog.agent_runs(self.subject)
        table = self.query_one("#agent-table", DataTable)
        table.clear(columns=True)
        for col in ("角色", "模型", "开始", "用时", "轮数", "费用（美元等值）", "退出"):
            table.add_column(col)
        for i, r in enumerate(self._agent_rows):
            code = r.get("exit_code")
            table.add_row(r.get("role", ""), r.get("model", ""), str(r.get("started_at", ""))[5:16].replace("T", " "),
                          f"{(r.get('elapsed_sec') or 0) / 60:.1f} 分", str(r.get("turns", "—")),
                          f"{r['cost_usd']:.2f}" if isinstance(r.get("cost_usd"), (int, float)) else "—",
                          Text(str(code), style=R.OK if code == 0 else R.BAD), key=str(i))
        log = self.query_one("#agent-log", RichLog)
        log.clear()
        if self._agent_rows:
            total = sum(r.get("cost_usd") or 0 for r in self._agent_rows)
            mins = sum(r.get("elapsed_sec") or 0 for r in self._agent_rows) / 60
            log.write(Text(f"{len(self._agent_rows)} 个会话，合计 {mins:.0f} 分钟、{total:.2f} 美元等值。选中一行查看事件流摘要。",
                           style=R.MUTED))
        else:
            log.write(Text("该对象没有 Agent 会话记录（只有研报工作区有）。", style=R.MUTED))

    @on(DataTable.RowHighlighted, "#agent-table")
    def _agent_row(self, ev: DataTable.RowHighlighted) -> None:
        r = self._agent_rows[int(ev.row_key.value)]
        log = self.query_one("#agent-log", RichLog)
        log.clear()
        log.write(Text(f"{r.get('role', '')} · {r.get('model', '')} · {r.get('log', '')}", style="bold"))
        for line in catalog.agent_log(self.subject, r.get("log", "")):
            log.write(Text(line, style=R.OK if line.startswith("[完成]") else ""))

    # ------------------------------------------------------------------ 命令
    def _presets(self) -> list[str]:
        s = self.subject
        out = []
        if s and s.workspace:
            ws = shlex.quote(str(s.workspace))
            out += [f"report status --workspace {ws}", f"eval run --workspace {ws} --no-judge"]
        out += ["ls", "bench", "doctor", "test"]
        return out

    def _fill_presets(self) -> None:
        t = Text("常用：", style=R.MUTED)
        for i, p in enumerate(self._presets()):
            t.append(f"  [{i + 1}] ", style=R.ACCENT)
            t.append(p)
        t.append("\n在输入框里输入 #1、#2… 快速填入；命令在仓库目录下运行，输出实时显示。", style=R.MUTED)
        self.query_one("#cmd-presets", Static).update(t)

    @on(Input.Submitted, "#cmd-input")
    @on(Button.Pressed, "#cmd-run")
    def _cmd_submit(self) -> None:
        box = self.query_one("#cmd-input", Input)
        text = box.value.strip()
        if text.startswith("#") and text[1:].isdigit():
            presets = self._presets()
            k = int(text[1:]) - 1
            if 0 <= k < len(presets):
                box.value = presets[k]
            return
        if text:
            self._run_command(text)

    @on(Button.Pressed, "#cmd-stop")
    def _cmd_stop(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()

    @work(exclusive=True, group="cmd")
    async def _run_command(self, text: str) -> None:
        log = self.query_one("#cmd-log", RichLog)
        log.write(Text(f"$ finagent {text}", style=f"bold {R.ACCENT}"))
        env = {**os.environ, "PYTHONUNBUFFERED": "1", "NO_COLOR": "1"}
        self._proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "finagent", *shlex.split(text), cwd=PROJECT_ROOT, env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        assert self._proc.stdout is not None
        async for raw in self._proc.stdout:
            log.write(raw.decode("utf-8", "replace").rstrip("\n"))
        code = await self._proc.wait()
        log.write(Text(f"[退出码 {code}]", style=R.OK if code == 0 else R.BAD))

    # ------------------------------------------------------------------ 动作
    def action_tab(self, tab: str) -> None:
        self.query_one("#tabs", TabbedContent).active = tab

    def action_refresh(self) -> None:
        key = self.subject.key if self.subject else None
        self._build_tree()
        if key:
            for node in self.query_one("#tree", Tree).root.children:
                for leaf in node.children:
                    if isinstance(leaf.data, catalog.Subject) and leaf.data.key == key:
                        self.query_one("#tree", Tree).select_node(leaf)
                        self._select(leaf.data)
        self.notify("已刷新")

    def action_toggle_sidebar(self) -> None:
        side = self.query_one("#sidebar")
        side.display = not side.display

    def action_open_pdf(self) -> None:
        p = catalog.pdf(self.subject) if self.subject else None
        if p:
            _open(p)
        else:
            self.notify("该对象没有研报 PDF", severity="warning")

    def action_open_xlsx(self) -> None:
        p = catalog.workbook(self.subject) if self.subject else None
        if p:
            _open(p)
        else:
            self.notify("该对象没有估值模型", severity="warning")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="finagent tui", description="FinAgent 终端界面")
    ap.add_argument("--samples", help="研报工作区目录，默认 ~/finagent-samples（FINAGENT_SAMPLES_DIR）")
    ap.add_argument("--runs", help="运行目录，默认仓库 runs/")
    args = ap.parse_args(argv)
    FinAgentApp(Path(args.samples).expanduser() if args.samples else None,
                Path(args.runs).expanduser() if args.runs else None).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
