"""把产物渲染成 Rich 可显示的对象：数字格式、闸门、估值区间条、敏感性热力表、评分条。

只做展示，不做任何计算——数值全部来自引擎产物（设计规范 1：LLM 不做算术，界面也不重算）。
"""

from __future__ import annotations

from typing import Any

from rich.console import Group
from rich.table import Table
from rich.text import Text

from finagent.tasks.financials.schema import BY_ID, METRICS

_ORDER = {m.id: i for i, m in enumerate(METRICS)}


def metric_order(metric_id: str) -> tuple[int, str]:
    """按指标清单顺序（主要数据 → 利润表 → 资产负债表 → 现金流 → 推导比率）排，列示同比紧跟本指标。"""
    base = metric_id.split(".")[0]
    return (_ORDER.get(base, len(_ORDER)), metric_id)

OK, BAD, WARN, MUTED, ACCENT = "#9ece6a", "#f7768e", "#e0af68", "#565f89", "#7aa2f7"


def fmt_fact(metric_id: str, value: float | None) -> str:
    """真值表的数：金额（元）按亿 / 万展示，比率加 %，每股保留两位。"""
    if value is None:
        return "—"
    kind = BY_ID[metric_id.split(".")[0]].kind if metric_id.split(".")[0] in BY_ID else "amount"
    if metric_id.endswith(".reported_yoy") or kind == "pct":
        return f"{value:,.2f}%"
    if kind == "per_share":
        return f"{value:,.2f}"
    if kind == "shares":
        return f"{value / 1e8:,.2f} 亿股"
    if abs(value) >= 1e8:
        return f"{value / 1e8:,.2f} 亿"
    if abs(value) >= 1e4:
        return f"{value / 1e4:,.2f} 万"
    return f"{value:,.2f}"


def metric_name(metric_id: str) -> str:
    base, _, suffix = metric_id.partition(".")
    name = BY_ID[base].name if base in BY_ID else metric_id
    return name + ("（列示同比）" if suffix == "reported_yoy" else "")


def gates_table(g: dict[str, Any] | None) -> Table | Text:
    if not g:
        return Text("不是研报工作区，或工作区尚未开始。", style=MUTED)
    t = Table(box=None, show_header=False, expand=True, padding=(0, 1))
    t.add_column(width=2)
    t.add_column(style="bold", no_wrap=True)
    t.add_column(ratio=1)
    for st in g.get("stages", []):
        mark = Text("●", style=OK) if st["ok"] else Text("○", style=BAD)
        detail = Text(st["detail"], style="" if st["ok"] else WARN)
        if not st["ok"] and st.get("next"):
            detail.append(f"\n→ {st['next']}", style=MUTED)
        t.add_row(mark, st["stage"], detail)
    return t


def value_bar(v: dict[str, Any], width: int = 56) -> Group | Text:
    """悲观—基准—乐观每股价值与当前股价画在同一条轴上。"""
    vr, price = v.get("value_range") or {}, v.get("current_price")
    if not vr:
        return Text("无估值产物", style=MUTED)
    pts = [x for x in (vr.get("low"), vr.get("base"), vr.get("high"), price) if isinstance(x, (int, float))]
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0

    def pos(x: float) -> int:
        return round((x - lo) / span * (width - 1))

    line = [" "] * width
    styles = [MUTED] * width
    a, b = pos(vr["low"]), pos(vr["high"])
    for i in range(a, b + 1):
        line[i], styles[i] = "━", ACCENT
    marks = [(pos(vr["low"]), "▏", ACCENT), (pos(vr["base"]), "◆", "bold #c0caf5"), (pos(vr["high"]), "▕", ACCENT)]
    if isinstance(price, (int, float)):
        marks.append((pos(price), "▼", WARN))
    for i, ch, st in marks:
        line[i], styles[i] = ch, st
    bar = Text()
    for ch, st in zip(line, styles):
        bar.append(ch, style=st)
    legend = Text()
    legend.append(f"悲观 {vr['low']:,.2f}", style=ACCENT)
    legend.append("   ◆ 基准 ", style="bold #c0caf5")
    legend.append(f"{vr['base']:,.2f}", style="bold #c0caf5")
    legend.append(f"   乐观 {vr['high']:,.2f}", style=ACCENT)
    if isinstance(price, (int, float)):
        legend.append(f"   ▼ 股价 {price:,.2f}", style=WARN)
    return Group(bar, legend)


def rating_badge(v: dict[str, Any]) -> Text:
    r = (v.get("rating") or {})
    name = r.get("rating")
    if not name:
        return Text("")
    color = {"买入": OK, "增持": OK, "中性": WARN, "减持": BAD, "卖出": BAD}.get(name, ACCENT)
    t = Text(f" {name} ", style=f"bold #1a1b26 on {color}")
    up = r.get("upside")
    if isinstance(up, (int, float)):
        t.append(f"  基准空间 {up:+.1%}", style=color)
    return t


def scenarios_table(v: dict[str, Any]) -> Table:
    t = Table(title="三情景 DCF（百万元 / 元每股）", title_style="bold", header_style=f"bold {ACCENT}")
    for col in ("情景", "WACC", "永续增长", "企业价值", "股权价值", "每股价值", "终值占 EV", "相对股价"):
        t.add_column(col, justify="left" if col == "情景" else "right")
    order = {"downside": 0, "base": 1, "upside": 2}
    for s in sorted(v.get("scenarios", []), key=lambda s: order.get(s.get("scenario"), 9)):
        up = s.get("upside_vs_price")
        t.add_row(s.get("scenario_cn", s.get("scenario", "")), f"{s['wacc']:.2%}", f"{s['terminal_growth']:.2%}",
                  f"{s['enterprise_value_mm']:,.0f}", f"{s['equity_value_mm']:,.0f}",
                  Text(f"{s['value_per_share']:,.2f}", style="bold"), f"{s['tv_percent_ev']:.1%}",
                  Text(f"{up:+.1%}", style=OK if up >= 0 else BAD) if isinstance(up, (int, float)) else "—")
    return t


def forecast_table(v: dict[str, Any]) -> Table:
    t = Table(title="基准情景预测（百万元）", title_style="bold", header_style=f"bold {ACCENT}")
    rows = (v.get("forecast_base") or [])[:6]
    t.add_column("项目")
    for r in rows:
        t.add_column(str(r["period"]), justify="right")
    spec = [("营业收入", "revenue", "{:,.0f}"), ("收入增速", "revenue_growth", "{:.1%}"), ("EBIT", "ebit", "{:,.0f}"),
            ("EBIT 利润率", "ebit_margin", "{:.1%}"), ("资本开支", "capex", "{:,.0f}"),
            ("无杠杆自由现金流", "unlevered_fcf", "{:,.0f}")]
    for label, key, f in spec:
        t.add_row(label, *[f.format(r[key]) if isinstance(r.get(key), (int, float)) else "—" for r in rows])
    return t


def _heat(x: float, lo: float, hi: float) -> str:
    """红（低）→ 灰 → 绿（高）背景色。"""
    if hi == lo:
        return "on #24283b"
    k = (x - lo) / (hi - lo)
    if k < 0.5:
        a = 1 - k * 2
        r, g, b = 0x24 + int((0x8c - 0x24) * a), 0x28 + int((0x2f - 0x28) * a), 0x3b + int((0x45 - 0x3b) * a)
    else:
        a = (k - 0.5) * 2
        r, g, b = 0x24 + int((0x3d - 0x24) * a), 0x28 + int((0x6b - 0x28) * a), 0x3b + int((0x3a - 0x3b) * a)
    return f"on #{r:02x}{g:02x}{b:02x}"


AXIS_NAMES = {"wacc_delta": "WACC", "terminal_growth_delta": "永续增长", "exit_multiple_delta": "退出倍数",
              "revenue_growth_delta": "收入增速", "revenue_delta": "收入", "ebit_margin_delta": "EBIT 利润率"}


def _axis_name(name: str) -> str:
    return AXIS_NAMES.get(name, name)


def _axis(name: str, x: float) -> str:
    if "multiple" in name:
        return f"{x:+.1f}x"
    return f"{x * 100:+.1f}pp"


def sensitivity_tables(v: dict[str, Any]) -> list[Table]:
    out = []
    for s in v.get("sensitivities") or []:
        m = s.get("matrix") or []
        flat = [x for row in m for x in row if isinstance(x, (int, float))]
        if not flat:
            continue
        lo, hi = min(flat), max(flat)
        t = Table(title=f"敏感性：{s.get('name', '')}（每股价值，元）", title_style="bold", header_style=f"bold {ACCENT}")
        t.add_column(f"{_axis_name(s.get('y_axis', ''))} ↓  {_axis_name(s.get('x_axis', ''))} →", style=MUTED)
        for x in s.get("x_values", []):
            t.add_column(_axis(s.get("x_axis", ""), x), justify="right")
        for y, row in zip(s.get("y_values", []), m):
            cells = []
            for i, x in enumerate(row):
                center = y == 0 and s.get("x_values", [None])[i] == 0
                cells.append(Text(f"{x:,.2f}", style=("bold underline " if center else "") + _heat(x, lo, hi)))
            t.add_row(_axis(s.get("y_axis", ""), y), *cells)
        out.append(t)
    return out


def score_header(sc: dict[str, Any]) -> Group:
    total = sc.get("total", 0)
    ok = sc.get("deliverable")
    head = Text()
    head.append(f"{total:g}", style=f"bold {OK if ok else WARN}")
    head.append(" 分  ", style="bold")
    head.append("达到交付标准" if ok else "未达交付标准", style=OK if ok else WARN)
    head.append(f"   评分标准 {sc.get('rubric', '')}", style=MUTED)
    if sc.get("deduction"):
        head.append(f"   扣分 {sc['deduction']:g}", style=BAD)
    rows = [head]
    names = {"L1": "数据闭合", "L2": "分析质量", "L3": "表达合规"}
    for k, name in names.items():
        lay = (sc.get("layers") or {}).get(k)
        if not lay or not lay.get("possible"):
            continue
        ratio = lay["earned"] / lay["possible"]
        w = 30
        filled = round(ratio * w)
        bar = Text(f"{k} {name} ", style="bold")
        bar.append("█" * filled, style=OK if ratio >= 0.8 else ACCENT if ratio >= 0.6 else WARN)
        bar.append("░" * (w - filled), style=MUTED)
        bar.append(f" {lay['earned']:g}/{lay['possible']:g}")
        rows.append(bar)
    for p in sc.get("judge_problems") or []:
        rows.append(Text(f"⚠ {p}", style=BAD))
    return Group(*rows)


EVENT_STYLE = {"run_start": ACCENT, "run_end": ACCENT, "step_start": "bold", "step_end": MUTED, "file_read": "#7dcfff",
               "artifact": OK, "tool_start": "#bb9af7", "tool_end": MUTED, "document_parsed": "#7dcfff", "llm_call": "#bb9af7", "error": BAD, "warning": WARN}


def event_summary(ev: dict[str, Any]) -> str:
    kind = ev.get("kind", "")
    if kind in ("step_start", "step_end"):
        extra = f"（{ev['elapsed_ms'] / 1000:.1f}s）" if "elapsed_ms" in ev else f"{ev.get('index', '')}/{ev.get('total', '')}"
        return f"{ev.get('pipeline', '')} · {ev.get('step', '')} {extra}"
    if kind in ("file_read", "artifact"):
        sha = (ev.get("sha256") or "")[:12]
        return f"{ev.get('path', '')}  {ev.get('bytes', '')} B  sha256 {sha}…"
    if kind == "run_start":
        return f"任务 {ev.get('task', '')}"
    if kind in ("tool_start", "tool_end"):
        h = ((ev.get("args") or ev.get("result") or {}) if isinstance(ev.get("args") or ev.get("result"), dict) else {})
        return f"{ev.get('tool', '')}" + (f"  {'参数' if kind == 'tool_start' else '结果'} sha256 {h['sha256'][:12]}…" if h.get("sha256") else "")
    if kind == "document_parsed":
        return f"{ev.get('source', '')}  {ev.get('pages', '')} 页 · {ev.get('tables', '')} 张表 · {ev.get('chunks', '')} 个片段"
    rest = {k: v for k, v in ev.items() if k not in ("seq", "ts", "kind")}
    return ", ".join(f"{k}={v}" for k, v in list(rest.items())[:4])[:200]
