"""研报图表（matplotlib → SVG）。

两类函数：
- 标准图（第一个参数是 Run）：直接从运行产物取数，任何公司都能用。
- 原语（第一个参数是输出目录）：分组柱、堆叠柱、横条、环形、进度条等；数值由公司脚本从产物 JSON 取出后传入，
  这里只画图，不产生新数字。

所有函数返回 SVG 文件名，交给 layout.Doc.img() 嵌入。
"""

from __future__ import annotations

from pathlib import Path

from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from .core import (BRICK, FULL, GOLD, GRID, HALF, INK, LIGHT, LIGHT2, MUTED, NAVY, NAVY2, NEUTRAL, PALETTE, SLATE,
                   Run, clean, fig_size, fmt_of, hgrid, labels, legend_below, note_above, save, subtitle)

QS = ["Q1", "Q2", "Q3", "Q4"]
H = 45  # 半栏图默认高度（mm）


# ================================================================== 原语
def grouped(out: Path, name: str, cats: list[str], series: list[tuple[str, list[float]]], *, notes=None,
            note_color=None, title="", fmt="{:,.2f}", w=HALF, h=H, colors=None, size=6.0, ylim=1.3) -> str:
    """分组柱。series = [(图例, 各类别数值)]。
    notes 为柱顶第二行标注（如同比）：一维列表标在最后一个系列上；二维列表按系列逐个给（不标的系列写 None）。"""
    colors = colors or ([LIGHT, NAVY] if len(series) == 2 else PALETTE)
    fig, ax = fig_size(w, h)
    k = len(series)
    width = 0.72 / k
    bars = []
    for i, (lab, vals) in enumerate(series):
        xs = [x - 0.36 + width * (i + 0.5) for x in range(len(cats))]
        bars.append(ax.bar(xs, vals, width * 0.95, color=colors[i % len(colors)], label=lab))
        labels(ax, bars[-1], fmt, size=size)
    per = notes if notes and any(isinstance(n, (list, tuple)) for n in notes) else [None] * (k - 1) + [notes]
    for bs, ns in zip(bars, per):
        for b, t in zip(bs, ns or []):
            if t:
                note_above(ax, b, t, color=note_color)
    ax.set_xticks(range(len(cats)), cats, fontsize=6.4)
    clean(ax)
    top = max(v for _, vals in series for v in vals if v is not None)
    ax.set_ylim(0, top * ylim)
    if k > 1:
        legend_below(ax, ncol=min(k, 4))
    if title:
        subtitle(ax, title)
    return save(fig, out / f"{name}.svg")


def stacked(out: Path, name: str, cats: list[str], series: list[tuple[str, list[float]]], *, totals=None,
            tops=None, title="", fmt="{:,.2f}", w=HALF, h=H, colors=None, min_label=0.06, legend="below") -> str:
    """堆叠柱。totals 为柱顶合计（产物里有才传）；tops 为柱顶的文字标注（如“直销占比 50.09%”）。
    段内数值小于总高度 min_label 比例时不标。"""
    colors = colors or PALETTE
    fig, ax = fig_size(w, h)
    x = list(range(len(cats)))
    base = [0.0] * len(cats)
    height = max(sum(v for _, vals in series for v in [vals[i]]) for i in range(len(cats)))
    for (lab, vals), c in zip(series, colors):
        bars = ax.bar(x, vals, 0.5, bottom=base, color=c, label=lab)
        for b, v, b0 in zip(bars, vals, base):
            if v / height >= min_label:
                ax.text(b.get_x() + b.get_width() / 2, b0 + v / 2, fmt.format(v), ha="center", va="center",
                        fontsize=6.4, color="white" if c in (NAVY, NAVY2, SLATE, BRICK) else INK)
        base = [a + b for a, b in zip(base, vals)]
    for xi, b0, t in zip(x, base, totals or [None] * len(x)):
        if t is not None:
            ax.annotate(fmt.format(t), (xi, b0), xytext=(0, 2), textcoords="offset points", ha="center",
                        fontsize=6.6, fontweight=600)
    for xi, b0, t in zip(x, base, tops or [None] * len(x)):
        if t:
            ax.annotate(t, (xi, b0), xytext=(0, 2 if not totals else 11), textcoords="offset points", ha="center",
                        fontsize=6.6, color=NAVY, fontweight=600)
    ax.set_xticks(x, cats)
    clean(ax)
    ax.set_xlim(-0.7, len(cats) - 0.3 + (0.9 if legend == "right" else 0))
    ax.set_ylim(0, height * (1.25 if tops else 1.12))
    if legend == "right":
        ax.legend(frameon=False, loc="center right", handlelength=1, reverse=True)
    else:
        legend_below(ax, ncol=min(len(series), 4))
    if title:
        subtitle(ax, title)
    return save(fig, out / f"{name}.svg")


def hbars(out: Path, name: str, labels_: list[str], values: list[float], *, fmt="{:,.0f}", title="", w=HALF,
          h=40, highlight_first=True) -> str:
    """横向条形（排名、构成）。"""
    fig, ax = fig_size(w, h)
    y = list(range(len(labels_)))[::-1]
    ax.barh(y, values, 0.55, color=[NAVY] + [SLATE] * (len(values) - 1) if highlight_first else NAVY)
    for yi_, v in zip(y, values):
        ax.annotate(fmt.format(v), (v, yi_), xytext=(3, 0), textcoords="offset points", va="center", fontsize=6.6)
    ax.set_yticks(y, labels_)
    ax.tick_params(axis="y", length=0)
    ax.set_xticks([])
    ax.spines["bottom"].set_visible(False)
    ax.set_xlim(0, max(values) * 1.25)
    if title:
        subtitle(ax, title)
    return save(fig, out / f"{name}.svg")


def donuts(out: Path, name: str, panels: list[tuple[str, list[float]]], names: list[str], *, w=HALF, h=H) -> str:
    """环形图（每个面板一组占比，%）。圆心写第一项。"""
    fig, axes = fig_size(w, h, ncols=len(panels))
    axes = axes if len(panels) > 1 else [axes]
    for ax, (t, vals) in zip(axes, panels):
        ax.pie(vals, colors=PALETTE[:len(vals)], startangle=90, counterclock=False,
               wedgeprops={"width": 0.38, "edgecolor": "white", "linewidth": 1})
        ax.text(0, 0.08, f"{vals[0]:.2f}%", ha="center", va="center", fontsize=8, color=NAVY, fontweight=600)
        ax.text(0, -0.2, names[0], ha="center", va="center", fontsize=6.2, color=MUTED)
        ax.set_title(t, fontsize=7, color=INK)
    fig.legend(handles=[Patch(color=c, label=n) for c, n in zip(PALETTE, names)], frameon=False,
               loc="lower center", ncol=len(names), bbox_to_anchor=(0.5, -0.04))
    return save(fig, out / f"{name}.svg")


def progress(out: Path, name: str, labels_: list[str], done: list[float], total: list[float], *, fmt="{:,.2f}",
             title="", w=FULL, h=36, done_label="累计", total_label="计划") -> str:
    """进度条（累计 / 计划），如在建项目投资进度。"""
    fig, ax = fig_size(w, h)
    y = list(range(len(labels_)))[::-1]
    ax.barh(y, total, 0.5, color=LIGHT2, label=total_label)
    ax.barh(y, done, 0.5, color=NAVY, label=done_label)
    for yi_, p, d in zip(y, total, done):
        ax.annotate(f"{fmt.format(d)} / {fmt.format(p)}", (p, yi_), xytext=(4, 0), textcoords="offset points",
                    va="center", fontsize=6.6)
    ax.set_yticks(y, labels_)
    ax.tick_params(axis="y", length=0)
    ax.set_xlim(0, max(total) * 1.25)
    ax.xaxis.grid(True, color=GRID, lw=0.5)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.08), ncol=2, handlelength=1)
    if title:
        subtitle(ax, title)
    return save(fig, out / f"{name}.svg")


def panels(out: Path, name: str, items: list[tuple], *, fmt="{:,.2f}", w=HALF, h=H) -> str:
    """并排小柱图：items = [(面板标题, 类别, 数值, 柱顶第二行标注[, 数值格式])]，如“收入与同比 | 毛利率与变动”。"""
    fig, axes = fig_size(w, h, ncols=len(items))
    for ax, item in zip(axes, items):
        t, cats, vals, notes = item[:4]
        f = item[4] if len(item) > 4 else fmt
        bars = ax.bar(range(len(cats)), vals, 0.55, color=PALETTE[:len(cats)])
        for b, v, nt in zip(bars, vals, notes):
            ax.annotate(f.format(v) + (f"\n({nt})" if nt else ""), (b.get_x() + b.get_width() / 2, v),
                        xytext=(0, 1.5), textcoords="offset points", ha="center", va="bottom", fontsize=6.2,
                        color=BRICK if nt and nt.startswith("-") else INK)
        ax.set_xticks(range(len(cats)), cats)
        ax.set_ylim(0, max(vals) * 1.35)
        clean(ax)
        subtitle(ax, t)
    fig.tight_layout(w_pad=1.2)
    return save(fig, out / f"{name}.svg")


def composition(out: Path, name: str, parts: list[tuple[str, float]], *, note="", fmt="{:,.2f}", w=FULL,
                h=24) -> str:
    """单根横向堆叠条（如年度分红构成），右侧写合计说明。"""
    fig, ax = fig_size(w, h)
    left = 0.0
    for (lab, v), c in zip(parts, PALETTE):
        ax.barh(0, v, 0.5, left=left, color=c, label=f"{lab} {fmt.format(v)}")
        ax.text(left + v / 2, 0, fmt.format(v), ha="center", va="center", fontsize=6.6,
                color="white" if c in (NAVY, SLATE, NAVY2) else INK)
        left += v
    if note:
        ax.annotate(note, (left, 0), xytext=(5, 0), textcoords="offset points", va="center", fontsize=7, color=NAVY,
                    fontweight=600)
    ax.set_xlim(0, left * 1.55)
    ax.set_ylim(-0.5, 0.5)
    ax.axis("off")
    ax.legend(frameon=False, loc="upper left", bbox_to_anchor=(0, 0), ncol=len(parts), handlelength=1, fontsize=6.6)
    return save(fig, out / f"{name}.svg")


def signed(out: Path, name: str, cats: list[str], series: list[tuple[str, list[float]]], *, title="",
           fmt="{:,.2f}", w=HALF, h=H) -> str:
    """可正可负的分组柱（如三类现金流量净额）。"""
    fig, ax = fig_size(w, h)
    k = len(series)
    width = 0.72 / k
    allv = [v for _, vals in series for v in vals]
    for i, ((lab, vals), c) in enumerate(zip(series, [LIGHT, NAVY] if k == 2 else PALETTE)):
        xs = [x - 0.36 + width * (i + 0.5) for x in range(len(cats))]
        bars = ax.bar(xs, vals, width * 0.95, color=c, label=lab)
        for b, v in zip(bars, vals):
            ax.annotate(fmt.format(v), (b.get_x() + b.get_width() / 2, v), xytext=(0, 1.5 if v >= 0 else -7),
                        textcoords="offset points", ha="center", fontsize=6)
    ax.axhline(0, color="#9CA3AF", lw=0.6)
    ax.set_xticks(range(len(cats)), cats)
    ax.tick_params(axis="x", length=0)
    clean(ax)
    ax.spines["bottom"].set_visible(False)
    ax.set_ylim(min(min(allv), 0) * 1.25, max(max(allv), 0) * 1.3)
    legend_below(ax, ncol=k)
    if title:
        subtitle(ax, title)
    return save(fig, out / f"{name}.svg")


# ================================================================== 标准图（直接读产物）
def cover(run: Run, out: Path) -> str:
    """首页侧栏：营业收入与归母净利润（实际 + 预测）。"""
    ys = [y for y in run.fs["years"] if y["year"] <= f"{int(run.period) + 3}E"]
    lab = [y["year"] for y in ys]
    rev = [y["revenue"] / 1e8 for y in ys]
    npp = [y["np_parent"] / 1e8 for y in ys]
    fig, ax = fig_size(56, 33)
    x = range(len(ys))
    act = [s.endswith("A") for s in lab]
    ax.bar([i - 0.2 for i in x], rev, 0.38, color=[NAVY if a else LIGHT for a in act])
    ax.bar([i + 0.2 for i in x], npp, 0.38, color=[SLATE if a else LIGHT2 for a in act])
    ax.set_xticks(list(x), lab, fontsize=6.2)
    clean(ax)
    ax.set_ylim(0, max(rev) * 1.12)
    ax.legend(handles=[Patch(color=NAVY, label="营业收入"), Patch(color=SLATE, label="归母净利润"),
                       Patch(color=LIGHT, label="预测值")],
              frameon=False, loc="upper left", ncol=3, fontsize=5.8, handlelength=0.8, columnspacing=0.6,
              bbox_to_anchor=(0, 1.16))
    return save(fig, out / "cover.svg")


def history(run: Run, out: Path) -> str:
    """上上年 A ～ 预测末年：营业收入（柱）与归母净利润（线）。"""
    ys = run.fs["years"]
    extra = [run.prev2] if run.v("revenue", run.prev2) is not None and f"{run.prev2}A" not in run.years else []
    lab = [f"{y}A" for y in extra] + [y["year"] for y in ys]
    rev = [run.v("revenue", y) / 1e8 for y in extra] + [y["revenue"] / 1e8 for y in ys]
    npp = [run.v("np_parent", y) / 1e8 for y in extra] + [y["np_parent"] / 1e8 for y in ys]
    fig, ax = fig_size(FULL, 58)
    x = list(range(len(lab)))
    act = [s.endswith("A") for s in lab]
    f = fmt_of(*rev)
    labels(ax, ax.bar(x, rev, 0.55, color=[NAVY if a else LIGHT for a in act]), f, size=6.4)
    ax.plot(x, npp, color=BRICK, lw=1.2, marker="o", ms=3)
    for xi, v in zip(x, npp):
        ax.annotate(f.format(v), (xi, v), xytext=(0, 5), textcoords="offset points", ha="center", fontsize=6.2,
                    color=BRICK, bbox={"boxstyle": "round,pad=0.15", "fc": "white", "ec": "none"})
    ax.set_xticks(x, lab)
    clean(ax)
    ax.set_ylim(min(0, min(npp) * 1.3), max(rev) * 1.15)
    ax.legend(handles=[Patch(color=NAVY, label="营业收入（实际）"), Patch(color=LIGHT, label="营业收入（预测）"),
                       Line2D([0], [0], color=BRICK, lw=1.2, marker="o", ms=3, label="归母净利润")],
              frameon=False, loc="upper left", ncol=3, handlelength=1.2)
    subtitle(ax, "单位：亿元；预测为基准情景")
    return save(fig, out / "history.svg")


def quality(run: Run, out: Path) -> str:
    """近三年加权平均 ROE 与净现比。"""
    ys = [y for y in (run.prev2, run.prev, run.period) if run.v("roe_weighted", y) is not None]
    fig, (a1, a2) = fig_size(HALF, H, ncols=2)
    for ax, mid, fmt, t in ((a1, "roe_weighted", "{:.2f}%", "加权平均 ROE"), (a2, "ocf_to_np", "{:.2f}", "净现比（倍）")):
        vals = [run.v(mid, y) or 0 for y in ys]
        labels(ax, ax.bar(range(len(ys)), vals, 0.55, color=[SLATE] * (len(ys) - 1) + [NAVY]), fmt)
        ax.set_xticks(range(len(ys)), ys)
        ax.set_ylim(min(0, min(vals)) * 1.25, max(vals) * 1.25)
        clean(ax)
        subtitle(ax, t)
    fig.tight_layout(w_pad=1.2)
    return save(fig, out / "quality.svg")


def quarterly(run: Run, out: Path, metric: str = "np_parent", label: str = "归母净利润") -> str:
    """分季度营业收入与利润（或经营现金流），来自 analysis.quarterly。"""
    rev = [run.quarterly["revenue"]["values"][q] / 1e8 for q in QS]
    other = [run.quarterly[metric]["values"][q] / 1e8 for q in QS]
    return grouped(out, f"quarterly_{metric}", [f"{run.period}{q}" for q in QS],
                   [("营业收入", rev), (label, other)], colors=[NAVY, SLATE], title="单位：亿元")


def cash_quarterly(run: Run, out: Path) -> str:
    ocf = [run.quarterly["ocf"]["values"][q] / 1e8 for q in QS]
    npp = [run.quarterly["np_parent"]["values"][q] / 1e8 for q in QS]
    return signed(out, "cash_quarterly", [f"{run.period}{q}" for q in QS],
                  [("经营现金流净额", ocf), ("归母净利润", npp)], title="单位：亿元")


def bridge(run: Run, out: Path, span: float | None = None) -> str:
    """归母净利润变动归因瀑布（earnings.profit_bridge）。span 为纵轴截断后显示的高度（亿元），默认自动。"""
    pb = run.earnings["profit_bridge"]
    items = pb["items"]
    lab = [f"{pb['base_period']}\n归母净利润"] + [i["item"] for i in items] + [f"{pb['period']}\n归母净利润"]
    lab = [s if "\n" in s or len(s) <= 4 else s[:-2] + "\n" + s[-2:] for s in lab]
    fig, ax = fig_size(FULL, 56)
    start, end = pb["np_parent_start"] / 1e8, pb["np_parent_end"] / 1e8
    levels, level = [start], start
    for it in items:
        level += it["value"] / 1e8
        levels.append(level)
    low, high = min(levels + [end]), max(levels + [end])
    pad = span or max((high - low) * 1.6, abs(end) * 0.05)
    lo = low - pad * 0.35 if low > 0 else min(0, low * 1.1)  # 利润为正时截断纵轴，突出变动项
    ax.bar(0, start - lo, bottom=lo, color=NEUTRAL, width=0.62)
    ax.annotate(f"{start:,.2f}", (0, start), xytext=(0, 1.5), textcoords="offset points", ha="center", fontsize=6.6)
    level = start
    for k, it in enumerate(items, 1):
        d = it["value"] / 1e8
        ax.bar(k, abs(d), bottom=level if d >= 0 else level + d, color=NAVY if d >= 0 else BRICK, width=0.62)
        ax.plot([k - 1 + 0.31, k - 0.31], [level, level], color="#9CA3AF", lw=0.5)
        ax.annotate(f"{d:+,.2f}", (k, max(level, level + d)), xytext=(0, 1.5), textcoords="offset points",
                    ha="center", fontsize=6.6, color=NAVY if d >= 0 else BRICK)
        level += d
    n = len(items) + 1
    ax.plot([n - 1 + 0.31, n - 0.31], [level, level], color="#9CA3AF", lw=0.5)
    ax.bar(n, end - lo, bottom=lo, color=NEUTRAL, width=0.62)
    ax.annotate(f"{end:,.2f}", (n, end), xytext=(0, 1.5), textcoords="offset points", ha="center", fontsize=6.6)
    ax.set_xticks(range(n + 1), lab, fontsize=6.8)
    ax.set_ylim(lo, high + (high - lo) * 0.08)
    hgrid(ax)
    ax.legend(handles=[Patch(color=NAVY, label="正向贡献"), Patch(color=BRICK, label="负向贡献")], frameon=False,
              loc="upper right", ncol=2, handlelength=1)
    subtitle(ax, "单位：亿元" + ("（纵轴截断）" if lo > 0 else ""))
    return save(fig, out / "bridge.svg")


def segment_forecast(run: Run, out: Path) -> str:
    """分部收入预测（基准情景，segment_forecast.json，百万元 → 亿元）。"""
    by, sc = run.seg["base_year"], run.seg["scenarios"]["base"]
    cats = [f"{run.period}A"] + [y[2:] + "E" for y in run.seg["years"]]
    series = [(b["name"], [b["revenue"] / 100] + [v / 100 for v in s["revenue"]])
              for b, s in zip(by["segments"], sc["segments"])]
    return stacked(out, "segment_forecast", cats, series, title="分部收入预测（亿元，基准情景）",
                   fmt=fmt_of(*[sum(v) for v in zip(*[vals for _, vals in series])], big=1000), min_label=0.08)


def margins(run: Run, out: Path) -> str:
    """毛利率、归母净利率（实际 + 预测）；有分部预测时下方加销售费用率。"""
    ys = run.fs["years"]
    lab = [y["year"] for y in ys]
    gm = [y["gross_margin"] for y in ys]
    nm = [y["net_margin_parent"] for y in ys]
    sell = None
    if run.seg and "selling" in run.seg["scenarios"]["base"]["expense_ratios"]:
        hist = [run.v("selling_ratio", y[:4]) for y in lab if y.endswith("A")]
        sell = hist + [v * 100 for v in run.seg["scenarios"]["base"]["expense_ratios"]["selling"]]
        sell = sell[:len(lab)] if None not in sell else None
    if sell:
        fig, (a1, a2) = fig_size(HALF, 52, nrows=2, sharex=True, gridspec_kw={"height_ratios": [1.5, 1]})
    else:
        fig, a1 = fig_size(HALF, H)
    for vals, c, n in ((gm, NAVY, "毛利率"), (nm, BRICK, "归母净利率")):
        a1.plot(lab, vals, color=c, marker="o", ms=2.5, lw=1.1, label=n)
        for x, v in zip(lab, vals):
            a1.annotate(f"{v:.2f}", (x, v), xytext=(0, 3), textcoords="offset points", ha="center", fontsize=5.6,
                        color=c)
    lo, hi = min(gm + nm), max(gm + nm)
    a1.set_ylim(lo - (hi - lo) * 0.3 - 2, hi + (hi - lo) * 0.2 + 2)
    clean(a1)
    a1.legend(frameon=False, loc="center right", ncol=2, handlelength=1.2, fontsize=6.2)
    subtitle(a1, "利润率（%）")
    if sell:
        act = sum(1 for s in lab if s.endswith("A"))
        labels(a2, a2.bar(lab, sell, 0.5, color=[SLATE] * act + [LIGHT] * (len(lab) - act)), "{:.2f}", size=5.6)
        a2.set_ylim(0, max(sell) * 1.4)
        clean(a2)
        subtitle(a2, "销售费用率（%）")
        a2.tick_params(axis="x", labelsize=6.2)
        fig.tight_layout(h_pad=0.6)
    return save(fig, out / "margins.svg")


def scenarios(run: Run, out: Path) -> str:
    """三情景营业收入（segment_forecast.json；没有分部预测时用 DCF 预测）。"""
    cats = [f"{run.period}A"] + [y[2:] + "E" for y in run.seg["years"]]
    base = run.seg["base_year"]["revenue"] / 100
    fig, ax = fig_size(HALF, H + 8)
    style = {"upside": (NAVY, "乐观"), "base": (INK, "基准"), "downside": (BRICK, "悲观")}
    for k, (c, n) in style.items():
        vals = [base] + [v / 100 for v in run.seg["scenarios"][k]["revenue"]]
        ax.plot(cats, vals, color=c, marker="o", ms=2.5, lw=1.1, label=n, ls="-" if k == "base" else (0, (3, 1.5)))
        ax.annotate(fmt_of(base).format(vals[-1]), (cats[-1], vals[-1]), xytext=(4, 0), textcoords="offset points", va="center",
                    fontsize=6.2, color=c)
    hgrid(ax)
    ax.tick_params(axis="x", labelsize=6.4)
    ax.legend(frameon=False, loc="upper left", ncol=3, handlelength=1.5)
    subtitle(ax, "三情景营业收入（亿元）")
    return save(fig, out / "scenarios.svg")


def ev_bridge(run: Run, out: Path) -> str:
    """从企业价值到股权价值（valuation.pv_base / bridge_base，百万元 → 亿元）。"""
    pv, br = run.valuation["pv_base"], run.valuation["bridge_base"]
    steps = [("预测期\nFCFF 现值", pv["pv_fcf"], "add"), ("终值现值", pv["pv_terminal_value"], "add"),
             ("企业价值", pv["total_pv"], "total"), ("加：非经营\n性资产", br["add_backs"], "add"),
             ("减：债务及\n类负债项目", -br["deductions"], "add"), ("股权价值", br["equity_value"], "total")]
    fig, ax = fig_size(FULL, 54)
    level = 0.0
    for i, (lab, v, kind) in enumerate(steps):
        v = v / 100
        if kind == "total":
            ax.bar(i, v, 0.55, color=NEUTRAL)
            ax.annotate(f"{v:,.2f}", (i, v), xytext=(0, 1.5), textcoords="offset points", ha="center", fontsize=6.6,
                        fontweight=600)
            level = v
        else:
            ax.bar(i, abs(v), 0.55, bottom=level if v >= 0 else level + v, color=NAVY if v >= 0 else BRICK)
            ax.annotate(f"{v:+,.2f}", (i, max(level, level + v)), xytext=(0, 1.5), textcoords="offset points",
                        ha="center", fontsize=6.6, color=NAVY if v >= 0 else BRICK)
            level += v
    b = run.scen["base"]
    top = max(pv["total_pv"], br["equity_value"]) / 100
    ax.annotate(f"每股价值 {b['value_per_share']:,.2f} 元", (len(steps) - 1, br["equity_value"] / 100), xytext=(0, 12),
                textcoords="offset points", ha="center", fontsize=7, color=NAVY, fontweight=600)
    ax.set_xticks(range(len(steps)), [s[0] for s in steps], fontsize=6.8)
    hgrid(ax)
    ax.set_ylim(0, top * 1.18)
    subtitle(ax, "基准情景，单位：亿元")
    return save(fig, out / "ev_bridge.svg")


SHORT = {"WACC × 永续增长率": "WACC × 永续增长", "WACC × 退出 EV/EBITDA 倍数": "WACC × 退出倍数",
         "收入增速 × EBIT 利润率": "收入增速 × 利润率"}


def football(run: Run, out: Path) -> str:
    """每股价值区间：三情景 + 各敏感性矩阵的最小～最大值 + 可比公司估值区间（有 comps.json 时），虚线为参考股价。"""
    val = run.valuation
    by = {s["scenario"]: s["value_per_share"] for s in val["scenarios"]}
    rows = [("DCF 三情景", by["downside"], by["upside"], by["base"])]
    for s in val["sensitivities"]:
        flat = [x for r in s["matrix"] for x in r if x is not None]
        rows.append((SHORT.get(s["name"], s["name"]), min(flat), max(flat), None))
    comps = (run.comps or {}).get("range")
    if comps and comps.get("low") is not None:
        rows.append(("可比公司估值", comps["low"], comps["high"], comps.get("mid")))
    price = val["current_price"]
    f = fmt_of(price, by["base"])
    lo_all, hi_all = min(r[1] for r in rows + [("", price, price, None)]), max(r[2] for r in rows + [("", price, price, None)])
    fig, ax = fig_size(HALF, H + 5)
    for i, (lab, lo, hi, mid) in enumerate(reversed(rows)):
        ax.barh(i, hi - lo, left=lo, height=0.46, color=NAVY if lab == "DCF 三情景" else (GOLD if mid else SLATE))
        ax.annotate(f.format(lo), (lo, i), xytext=(-3, 0), textcoords="offset points", ha="right", va="center", fontsize=6.4)
        ax.annotate(f.format(hi), (hi, i), xytext=(3, 0), textcoords="offset points", ha="left", va="center", fontsize=6.4)
        if mid:
            ax.plot([mid, mid], [i - 0.23, i + 0.23], color="white", lw=1.2)
    ax.axvline(price, color=BRICK, lw=0.9, ls=(0, (3, 2)))
    ax.annotate(f"参考股价 {price:,.2f}", (price, len(rows) - 0.45), xytext=(3, 0), textcoords="offset points",
                color=BRICK, fontsize=6.6, va="center")
    ax.set_yticks(range(len(rows)), [r[0] for r in reversed(rows)], fontsize=6.8)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    span = hi_all - lo_all
    ax.set_xlim(lo_all - span * 0.25, hi_all + span * 0.2)
    ax.set_ylim(-0.6, len(rows) + 0.15)
    ax.xaxis.grid(True, color=GRID, lw=0.5)
    ax.set_axisbelow(True)
    subtitle(ax, "每股价值（元）；白线为基准情景或中值")
    return save(fig, out / "football.svg")
