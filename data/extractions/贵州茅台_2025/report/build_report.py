"""贵州茅台 2025 年报点评（卖方研报体例）：读 FinAgent 运行产物 → 画图（SVG）→ 渲染 HTML → 无头 Chrome 打印 PDF。

规范见 .claude/skills/finagent-research/references/html-report.md：
表格与图中的数字全部从运行目录 JSON 读出，脚本只做单位换算与格式化；正文来自已过 guard 的 narrative.md。

    .venv/bin/python data/extractions/贵州茅台_2025/report/build_report.py --run-dir runs/<run_id>
"""

from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

COMPANY, TICKER, SECTOR = "贵州茅台", "600519.SH", "食品饮料 · 白酒"
REPORT_DATE = "2026 年 9 月 28 日"
NAVY, SLATE, LIGHT, BRICK, NEUTRAL, GRID, INK, MUTED = (
    "#1B365D", "#8A9BB0", "#C9D3DF", "#B5482F", "#7F8C9A", "#E5E7EB", "#1F2937", "#6B7280")
MM = 1 / 25.4

plt.rcParams.update({
    "font.family": ["Helvetica Neue", "PingFang SC"],  # 西文在前、中文回退
    "font.size": 7.5, "axes.titlesize": 7.5, "axes.labelsize": 7, "xtick.labelsize": 7, "ytick.labelsize": 7,
    "legend.fontsize": 7, "axes.edgecolor": "#9CA3AF", "axes.linewidth": 0.6, "axes.unicode_minus": False,
    "axes.spines.top": False, "axes.spines.right": False, "svg.fonttype": "path",
})


# ------------------------------------------------------------------ 数据
class Run:
    def __init__(self, run_dir: Path):
        self.dir = run_dir
        j = lambda rel: json.loads((run_dir / rel).read_text(encoding="utf-8"))  # noqa: E731
        self.analysis, self.earnings = j("financials/analysis.json"), j("financials/earnings.json")
        self.extras = j("financials/extras.json")
        self.valuation, self.plan = j("valuation/valuation.json"), j("valuation/plan.json")
        self.ts, self.ts_plan = j("valuation/three_statement.json"), j("valuation/three_statement_plan.json")
        self.fs, self.non_op = j("valuation/forecast_summary.json"), j("valuation/non_operating_assets.json")
        self.seg, self.detail = j("valuation/segment_forecast.json"), j("valuation/three_statement_detail.json")
        self.manifest = j("manifest.json")
        self.period = self.analysis["period"]
        self.prev = str(int(self.period) - 1)
        self.tt = {(c["metric_id"], c["period"]): c for c in self.analysis["truth_table"]}
        self.quarterly = {r["metric_id"]: r for r in self.analysis["quarterly"]["rows"]}
        self.tables = {t["id"]: t for t in self.extras["tables"]}
        self.ratios = {r["id"]: r["value"] for r in self.extras["ratios"]}
        self.years = {y["year"]: y for y in self.fs["years"]}

    def v(self, metric: str, period: str | None = None) -> float | None:
        c = self.tt.get((metric, period or self.period))
        return None if c is None else c["value"]

    def seg_v(self, table: str, row: str, col: str) -> float | None:
        return self.seg_(table, row, col)

    def seg_(self, table: str, row: str, col: str) -> float | None:
        t = self.tables[table]
        names = [c["name"] for c in t["columns"]]
        r = next(r for r in t["rows"] if r["label"] == row)
        return r["values"][names.index(col)]

    def seg_cell(self, table: str, row: str, col: str) -> float | None:
        return self.seg_(table, row, col)

    def stmt(self, name: str) -> dict[str, list[float]]:
        return {r["key"]: r["values"] for r in self.ts["statements"][name]["rows"]}


# ------------------------------------------------------------------ 格式化（只换算单位，不产生新数字）
def yi(x, d=2):
    return "—" if x is None else f"{x / 1e8:,.{d}f}"


def mm(x, d=0):
    if x is None:
        return "—"
    s = f"{x:,.{d}f}"
    return s[1:] if s.startswith("-") and not s.strip("-0.,") else s  # 不显示“-0”


def pct(x, d=2, sign=True):
    return "—" if x is None else (f"{x:+.{d}f}%" if sign else f"{x:.{d}f}%")


def num(x, d=2):
    return "—" if x is None else f"{x:,.{d}f}"


def neg(x):
    return ' class="neg"' if x is not None and x < 0 else ""


# ------------------------------------------------------------------ narrative.md → HTML
def load_sections(path: Path) -> dict[str, str]:
    parts = re.split(r"<!--\s*section:\s*(\w+)\s*-->", path.read_text(encoding="utf-8"))
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts), 2)}


TAGS = {"事实": "fact", "推论": "infer", "观点": "view"}


def md(text: str) -> str:
    def inline(s: str) -> str:
        s = html.escape(s)
        s = re.sub(r"\*\*(事实|推论|观点)(（[^*]*）)?。\*\*",
                   lambda m: f'<span class="tag {TAGS[m.group(1)]}">{m.group(1)}</span>'
                             + (f'<span class="tag-note">{m.group(2)[1:-1]}</span>' if m.group(2) else ""), s)
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)

    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        if all(ln.startswith("- ") for ln in lines):
            out.append("<ul>" + "".join(f"<li>{inline(ln[2:])}</li>" for ln in lines) + "</ul>")
        else:
            out.append(f"<p>{inline(' '.join(lines))}</p>")
    return "\n".join(out)


# ------------------------------------------------------------------ 图表
def _save(fig, path: Path) -> str:
    fig.savefig(path, format="svg", bbox_inches="tight", pad_inches=0.02, transparent=True)
    plt.close(fig)
    return path.name


def _labels(ax, bars, fmt="{:,.0f}", color=INK, size=6.4):
    for b in bars:
        h = b.get_height()
        ax.annotate(fmt.format(h), (b.get_x() + b.get_width() / 2, b.get_y() + h), xytext=(0, 1.5),
                    textcoords="offset points", ha="center", va="bottom", fontsize=size, color=color)


def _clean(ax):
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)


def chart_cover(run: Run, out: Path) -> str:
    """首页：营业收入与归母净利润（实际 + 预测）。"""
    ys = [y for y in run.fs["years"] if y["year"] <= f"{int(run.period) + 3}E"]
    labels = [y["year"] for y in ys]
    rev = [y["revenue"] / 1e8 for y in ys]
    npp = [y["np_parent"] / 1e8 for y in ys]
    fig, ax = plt.subplots(figsize=(56 * MM, 33 * MM))
    x = range(len(ys))
    act = [l.endswith("A") for l in labels]
    ax.bar([i - 0.2 for i in x], rev, 0.38, color=[NAVY if a else LIGHT for a in act], label="营业收入")
    ax.bar([i + 0.2 for i in x], npp, 0.38, color=[SLATE if a else "#E4E9F0" for a in act], label="归母净利润")
    ax.set_xticks(list(x), labels, fontsize=6.2)
    _clean(ax)
    ax.set_ylim(0, max(rev) * 1.12)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=NAVY, label="营业收入"), Patch(color=SLATE, label="归母净利润"),
                       Patch(color=LIGHT, label="预测值")],
              frameon=False, loc="upper left", ncol=3, fontsize=5.8, handlelength=0.8, columnspacing=0.6,
              bbox_to_anchor=(0, 1.16))
    return _save(fig, out / "c0_cover.svg")


def chart_quarterly(run: Run, out: Path) -> str:
    qs = ["Q1", "Q2", "Q3", "Q4"]
    rev = [run.quarterly["revenue"]["values"][q] / 1e8 for q in qs]
    npp = [run.quarterly["np_parent"]["values"][q] / 1e8 for q in qs]
    fig, ax = plt.subplots(figsize=(84 * MM, 56 * MM))
    x = range(4)
    _labels(ax, ax.bar([i - 0.19 for i in x], rev, 0.36, color=NAVY, label="营业收入"), "{:,.2f}")
    _labels(ax, ax.bar([i + 0.19 for i in x], npp, 0.36, color=SLATE, label="归母净利润"), "{:,.2f}")
    ax.set_xticks(list(x), [f"{run.period}{q}" for q in qs])
    _clean(ax)
    ax.set_ylim(0, max(rev) * 1.2)
    ax.legend(frameon=False, loc="upper right", ncol=2, handlelength=1, columnspacing=1)
    return _save(fig, out / "c1_quarterly.svg")


def chart_product(run: Run, out: Path) -> str:
    rows = [("茅台酒", "茅台酒"), ("系列酒", "其他系列酒")]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(84 * MM, 50 * MM), gridspec_kw={"width_ratios": [1.1, 1]})
    rev = [run.seg_cell("product", r, "营业收入") / 1e8 for _, r in rows]
    yoy = [run.seg_cell("product", r, "营业收入同比") for _, r in rows]
    for b, v, g in zip(a1.bar(range(2), rev, 0.55, color=[NAVY, SLATE]), rev, yoy):
        a1.annotate(f"{v:,.2f}\n({g:+.2f}%)", (b.get_x() + b.get_width() / 2, v), xytext=(0, 1.5),
                    textcoords="offset points", ha="center", va="bottom", fontsize=6.4, color=BRICK if g < 0 else INK)
    a1.set_xticks(range(2), [n for n, _ in rows])
    a1.set_ylim(0, max(rev) * 1.32)
    _clean(a1)
    a1.set_title("主营收入（亿元）与同比", loc="left", color=MUTED, fontsize=6.8)
    gm = [run.seg_cell("product", r, "毛利率") for _, r in rows]
    gmc = [run.seg_cell("product", r, "毛利率同比") for _, r in rows]
    for b, v, g in zip(a2.bar(range(2), gm, 0.55, color=[NAVY, SLATE]), gm, gmc):
        a2.annotate(f"{v:.2f}%\n({g:+.2f}pp)", (b.get_x() + b.get_width() / 2, v), xytext=(0, 1.5),
                    textcoords="offset points", ha="center", va="bottom", fontsize=6.4, color=BRICK if g < 0 else INK)
    a2.set_xticks(range(2), [n for n, _ in rows])
    a2.set_ylim(0, 122)
    _clean(a2)
    a2.set_title("毛利率与同比变动", loc="left", color=MUTED, fontsize=6.8)
    fig.tight_layout(w_pad=1.2)
    return _save(fig, out / "c2_product.svg")


def chart_channel(run: Run, out: Path) -> str:
    """分渠道收入结构（上期 vs 本期，亿元），标注直销占比。"""
    cv = lambda row, col: run.seg_cell("channel_volume", row, col) / 1e8  # noqa: E731
    d = [cv("直销", "上期销售收入"), cv("直销", "本期销售收入")]
    w = [cv("批发代理", "上期销售收入"), cv("批发代理", "本期销售收入")]
    share = [run.ratios["mix_direct_prev"], run.ratios["mix_direct"]]
    fig, ax = plt.subplots(figsize=(84 * MM, 50 * MM))
    x = [0, 1]
    b1 = ax.bar(x, d, 0.5, color=NAVY, label="直销")
    b2 = ax.bar(x, w, 0.5, bottom=d, color=LIGHT, label="批发代理")
    for b, v in zip(b1, d):
        ax.text(b.get_x() + b.get_width() / 2, v / 2, f"{v:,.2f}", ha="center", va="center", color="white", fontsize=6.6)
    for b, v, base in zip(b2, w, d):
        ax.text(b.get_x() + b.get_width() / 2, base + v / 2, f"{v:,.2f}", ha="center", va="center", color=INK, fontsize=6.6)
    for xi, s, bar in zip(x, share, b2):
        ax.annotate(f"直销占比 {s:.2f}%", (xi, bar.get_y() + bar.get_height()), xytext=(0, 2),
                    textcoords="offset points", ha="center", fontsize=6.6, color=NAVY, fontweight=600)
    ax.set_xticks(x, [f"{run.prev} 年", f"{run.period} 年"])
    _clean(ax)
    ax.set_xlim(-0.7, 1.7)
    ax.set_ylim(0, (d[1] + w[1]) * 1.16)
    ax.legend(frameon=False, loc="upper center", ncol=2, bbox_to_anchor=(0.5, 1.12), handlelength=1)
    return _save(fig, out / "c3_channel.svg")


def chart_price(run: Run, out: Path) -> str:
    groups = [("直销", "price_direct_prev", "price_direct"), ("批发代理", "price_wholesale_prev", "price_wholesale")]
    fig, ax = plt.subplots(figsize=(84 * MM, 46 * MM))
    x = range(len(groups))
    _labels(ax, ax.bar([i - 0.18 for i in x], [run.ratios[p] for _, p, _ in groups], 0.34, color=LIGHT,
                       label=f"{run.prev} 年"), "{:,.2f}")
    _labels(ax, ax.bar([i + 0.18 for i in x], [run.ratios[c] for _, _, c in groups], 0.34, color=NAVY,
                       label=f"{run.period} 年"), "{:,.2f}")
    ax.set_xticks(list(x), [g for g, _, _ in groups])
    _clean(ax)
    ax.set_ylim(0, max(run.ratios[p] for _, p, _ in groups) * 1.24)
    ax.legend(frameon=False, loc="upper right", ncol=2, handlelength=1)
    ax.set_title("单位：万元/吨", loc="left", color=MUTED, fontsize=6.8)
    return _save(fig, out / "c4_price.svg")


def chart_bridge(run: Run, out: Path) -> str:
    pb = run.earnings["profit_bridge"]
    items = pb["items"]
    labels = [f"{pb['base_period']}\n归母净利润"] + [i["item"] for i in items] + [f"{pb['period']}\n归母净利润"]
    labels = [s if "\n" in s or len(s) <= 4 else s[:-2] + "\n" + s[-2:] for s in labels]
    fig, ax = plt.subplots(figsize=(174 * MM, 50 * MM))
    start, end = pb["np_parent_start"] / 1e8, pb["np_parent_end"] / 1e8
    lo = end - 90  # 纵轴截断
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
    ax.set_xticks(range(n + 1), labels, fontsize=6.8)
    ax.set_ylim(lo, start + 12)
    ax.yaxis.grid(True, color=GRID, lw=0.5)
    ax.set_axisbelow(True)
    ax.set_title("单位：亿元（纵轴截断；深蓝为正向贡献，砖红为负向贡献）", loc="left", color=MUTED, fontsize=6.8)
    return _save(fig, out / "c5_bridge.svg")


def chart_cash(run: Run, out: Path) -> str:
    qs = ["Q1", "Q2", "Q3", "Q4"]
    ocf = [run.quarterly["ocf"]["values"][q] / 1e8 for q in qs]
    npp = [run.quarterly["np_parent"]["values"][q] / 1e8 for q in qs]
    fig, ax = plt.subplots(figsize=(84 * MM, 52 * MM))
    x = range(4)
    _labels(ax, ax.bar([i - 0.19 for i in x], ocf, 0.36, color=NAVY, label="经营现金流净额"), "{:,.1f}")
    _labels(ax, ax.bar([i + 0.19 for i in x], npp, 0.36, color=SLATE, label="归母净利润"), "{:,.1f}")
    ax.set_xticks(list(x), [f"{run.period}{q}" for q in qs])
    _clean(ax)
    ax.set_ylim(0, max(ocf + npp) * 1.22)
    ax.legend(frameon=False, loc="upper left", ncol=2, handlelength=1, columnspacing=0.8)
    return _save(fig, out / "c6_cash.svg")


SHORT = {"WACC × 永续增长率": "WACC × 永续增长", "WACC × 退出 EV/EBITDA 倍数": "WACC × 退出倍数",
         "收入增速 × EBIT 利润率": "收入增速 × 利润率"}


def chart_football(run: Run, out: Path) -> str:
    val = run.valuation
    by = {s["scenario"]: s["value_per_share"] for s in val["scenarios"]}
    rows = [("DCF 三情景", by["downside"], by["upside"], by["base"])]
    for s in val["sensitivities"]:
        flat = [x for r in s["matrix"] for x in r if x is not None]
        rows.append((SHORT.get(s["name"], s["name"]), min(flat), max(flat), None))
    price = val["current_price"]
    fig, ax = plt.subplots(figsize=(84 * MM, 50 * MM))
    for i, (lab, lo, hi, mid) in enumerate(reversed(rows)):
        ax.barh(i, hi - lo, left=lo, height=0.46, color=NAVY if mid else SLATE)
        ax.annotate(f"{lo:,.0f}", (lo, i), xytext=(-3, 0), textcoords="offset points", ha="right", va="center", fontsize=6.4)
        ax.annotate(f"{hi:,.0f}", (hi, i), xytext=(3, 0), textcoords="offset points", ha="left", va="center", fontsize=6.4)
        if mid:
            ax.plot([mid, mid], [i - 0.23, i + 0.23], color="white", lw=1.2)
    ax.axvline(price, color=BRICK, lw=0.9, ls=(0, (3, 2)))
    ax.annotate(f"参考股价 {price:,.2f}", (price, len(rows) - 0.45), xytext=(3, 0), textcoords="offset points",
                color=BRICK, fontsize=6.6, va="center")
    ax.set_yticks(range(len(rows)), [r[0] for r in reversed(rows)], fontsize=6.8)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.set_xlim(600, 2500)
    ax.xaxis.grid(True, color=GRID, lw=0.5)
    ax.set_axisbelow(True)
    ax.set_title("每股价值（元）；白线为基准情景", loc="left", color=MUTED, fontsize=6.8)
    return _save(fig, out / "c7_football.svg")


# ------------------------------------------------------------------ HTML 片段
def src(run: Run, *pages: int | None, extra: str = "") -> str:
    """图表来源行。页码不进正文与图注，逐项页码见 model.xlsx“历史财务”页与 financials/facts.csv。"""
    return f'<div class="src">资料来源：公司公告，FinAgent{("；" + extra) if extra else ""}</div>'


def fig(n: int, title: str, body: str, source: str, cls: str = "") -> str:
    return (f'<figure class="{cls}"><figcaption>图表 {n}：{title}</figcaption>'
            f'{body}{source}</figure>')


def img(name: str, width_mm: int) -> str:
    return f'<img src="charts/{name}" style="width:{width_mm}mm">'


def cover_side(run: Run, chart: str) -> str:
    m, val = run.fs["market"], run.valuation
    base = next(s for s in val["scenarios"] if s["scenario"] == "base")
    rt = run.fs["rating"]
    dps = run.seg_v("dps", "2025年年度利润分配", "每股派息")
    rows = [
        ("当前股价（元）", num(m["price"])),
        ("总股本（亿股）", f"{m['total_shares'] / 1e8:,.2f}"),
        ("总市值（亿元）", f"{m['market_cap'] / 1e8:,.0f}"),
        ("每股净资产（元）", num(m["bvps"])),
        ("市净率（倍）", f"{m['pb']:.2f}"),
        (f"市盈率（{run.period}A，倍）", f"{m['pe_latest']:.2f}"),
        ("资产负债率", pct(m["debt_ratio"], sign=False)),
        (f"{run.period} 年度每股派息（元）", f"{dps:.3f}"),
    ]
    kv = "".join(f'<div class="kv"><span>{a}</span><b>{b}</b></div>' for a, b in rows)
    date = m["price_date"]
    return f"""
<aside class="side">
  <div class="rating"><span>投资评级</span><b>{rt['rating']}</b><em>（首次）</em></div>
  <div class="kv strong"><span>DCF 每股价值（元）</span><b>{num(base['value_per_share'])}</b></div>
  <div class="kv strong"><span>估值区间（元）</span><b>{num(val['value_range']['low'])}～{num(val['value_range']['high'])}</b></div>
  <div class="side-h gap">基本数据</div>
  {kv}
  <div class="note">股价日期：{date[:4]} 年 {int(date[5:7])} 月 {int(date[8:])} 日收盘；财务数据截至 {run.period} 年末</div>
  <div class="side-h gap">营业收入与归母净利润（亿元）</div>
  <img src="charts/{chart}" style="width:56mm">
</aside>"""


FORECAST_ROWS = [("营业收入（亿元）", "revenue", "yi"), ("同比增长", "revenue_growth", "pct"),
                 ("归母净利润（亿元）", "np_parent", "yi"), ("同比增长", "np_parent_growth", "pct"),
                 ("每股收益（元）", "eps", "num"), ("毛利率", "gross_margin", "pctn"),
                 ("归母净利率", "net_margin_parent", "pctn"), ("P/E（倍）", "pe", "x")]


def _fmt(v, kind):
    if v is None:
        return "—"
    return {"yi": lambda: yi(v), "pct": lambda: pct(v), "num": lambda: num(v),
            "pctn": lambda: pct(v, sign=False), "x": lambda: f"{v:.1f}"}[kind]()


COVER_ROWS = ("revenue", "revenue_growth", "np_parent", "np_parent_growth", "eps", "pe")


def table_forecast(run: Run, last: int = 3, cls: str = "data forecast", keys: tuple[str, ...] | None = None) -> str:
    ys = [y for y in run.fs["years"] if y["year"] <= f"{int(run.period) + last}E"]
    head = "".join(f"<th{' class=est' if y['year'].endswith('E') else ''}>{y['year']}</th>" for y in ys)
    trs = []
    for label, key, kind in [r for r in FORECAST_ROWS if keys is None or r[1] in keys]:
        cells = []
        for y in ys:
            v = y[key]
            c = ["est"] if y["year"].endswith("E") else []
            if kind == "pct" and v is not None and v < 0:
                c.append("neg")
            cells.append(f'<td class="{" ".join(c)}">{_fmt(v, kind)}</td>')
        trs.append(f"<tr><td>{label}</td>{''.join(cells)}</tr>")
    return f'<table class="{cls}"><thead><tr><th>指标</th>{head}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


def table_core(run: Run) -> str:
    items = [("营业收入", "revenue", "yi"), ("营业成本", "operating_cost", "yi"), ("税金及附加", "tax_surcharge", "yi"),
             ("销售费用", "selling_expense", "yi"), ("管理费用", "admin_expense", "yi"),
             ("营业利润", "operating_profit", "yi"), ("归母净利润", "np_parent", "yi"),
             ("扣非归母净利润", "np_parent_deducted", "yi"), ("经营现金流净额", "ocf", "yi"),
             ("基本每股收益（元）", "eps_basic", "num"), ("毛利率", "gross_margin", "pp"),
             ("销售费用率", "selling_ratio", "pp"), ("管理费用率", "admin_ratio", "pp"),
             ("加权平均 ROE", "roe_weighted", "pp")]
    changes = {c["metric_id"]: c for c in run.analysis["changes"]}
    trs = []
    for label, mid, kind in items:
        cur, prev = run.v(mid), run.v(mid, run.prev)
        c = changes.get(mid) or {}
        if kind == "pp":
            a, b = pct(cur, sign=False), pct(prev, sign=False)
            d = c.get("yoy_change_pp")
            chg = f"{d:+.2f} pp" if d is not None else "—"
        else:
            a, b = (yi(cur), yi(prev)) if kind == "yi" else (num(cur), num(prev))
            d = c.get("yoy_pct")
            chg = pct(d) if d is not None else "—"
        trs.append(f"<tr><td>{label}</td><td>{a}</td><td>{b}</td><td{neg(d)}>{chg}</td></tr>")
    return (f'<table class="data"><thead><tr><th>亿元 / %</th><th>{run.period}A</th><th>{run.prev}A</th><th>同比</th>'
            f'</tr></thead><tbody>{"".join(trs)}</tbody></table>')


def table_segments(run: Run) -> str:
    blocks = [("按产品", "product", [("茅台酒", "茅台酒"), ("其他系列酒", "系列酒"), ("小计", "合计")]),
              ("按渠道", "channel", [("直销", "直销"), ("批发代理", "批发代理")]),
              ("按地区", "region", [("国内", "国内"), ("国外", "国外")])]
    trs = []
    for title, tid, rows in blocks:
        trs.append(f'<tr class="grp"><td colspan="6">{title}</td></tr>')
        for key, label in rows:
            r = [run.seg_cell(tid, key, c) for c in ("营业收入", "营业收入同比", "营业成本同比", "毛利率", "毛利率同比")]
            trs.append(f"<tr{' class=sub' if key == '小计' else ''}><td>{label}</td><td>{yi(r[0])}</td><td{neg(r[1])}>{pct(r[1])}</td>"
                       f"<td{neg(r[2])}>{pct(r[2])}</td><td>{pct(r[3], sign=False)}</td><td{neg(r[4])}>{r[4]:+.2f} pp</td></tr>")
    return ('<table class="data"><thead><tr><th>主营业务</th><th>收入（亿元）</th><th>收入同比</th><th>成本同比</th>'
            f'<th>毛利率</th><th>毛利率变动</th></tr></thead><tbody>{"".join(trs)}</tbody></table>')


def table_volume(run: Run) -> str:
    trs = []
    for key, label, pid in (("茅台酒", "茅台酒", "price_moutai"), ("其他系列酒", "系列酒", "price_series")):
        v = [run.seg_cell("volume", key, c) for c in ("产量", "产量同比", "销量", "销量同比")]
        trs.append(f"<tr><td>{label}</td><td>{mm(v[0], 2)}</td><td{neg(v[1])}>{pct(v[1])}</td><td>{mm(v[2], 2)}</td>"
                   f"<td{neg(v[3])}>{pct(v[3])}</td><td>{num(run.ratios[pid])}</td></tr>")
    return ('<table class="data nw"><thead><tr><th>产品</th><th>产量（吨）</th><th>同比</th><th>销量（吨）</th><th>同比</th>'
            f'<th>吨价（万元）</th></tr></thead><tbody>{"".join(trs)}</tbody></table>')


def table_ops(run: Run) -> str:
    on = [run.seg_cell("online", "i茅台数字营销平台", c) for c in ("本期销售收入", "上期销售收入", "同比")]
    rows = [
        ("i茅台平台收入（亿元）", yi(on[0]), yi(on[1]), pct(on[2]), on[2]),
        ("i茅台占直销收入比例", pct(run.ratios["imoutai_in_direct"], sign=False), "—", "—", None),
        ("直销收入占比", pct(run.ratios["mix_direct"], sign=False), pct(run.ratios["mix_direct_prev"], sign=False), "—", None),
        ("国内经销商（个，期末）", mm(run.seg_cell("dealers", "国内", "期末数量")), "—",
         f"+{mm(run.seg_cell('dealers', '国内', '本期增加'))} / -{mm(run.seg_cell('dealers', '国内', '本期减少'))}", None),
        ("茅台酒基酒设计产能（吨）", mm(run.seg_cell("capacity", "茅台酒制酒车间", "设计产能"), 2), "—", "—", None),
        ("茅台酒基酒实际产量（吨）", mm(run.seg_cell("capacity", "茅台酒制酒车间", "实际产能"), 2), "—", "—", None),
        ("半成品酒库存（吨，期末）", mm(run.seg_cell("stock", "期末库存", "半成品酒（含基础酒）"), 2), "—", "—", None),
    ]
    trs = "".join(f"<tr><td>{a}</td><td>{b}</td><td>{c}</td><td{neg(e)}>{d}</td></tr>" for a, b, c, d, e in rows)
    return (f'<table class="data"><thead><tr><th>经营指标</th><th>{run.period}</th><th>{run.prev}</th><th>变动</th></tr></thead>'
            f"<tbody>{trs}</tbody></table>")


def table_cash(run: Run) -> str:
    changes = {c["metric_id"]: c for c in run.analysis["changes"]}
    rows = [("经营现金流净额", "ocf"), ("合同负债", "contract_liab"), ("存货", "inventory"),
            ("应收账款", "accounts_receivable"), ("货币资金", "cash")]
    trs = []
    for label, mid in rows:
        d = (changes.get(mid) or {}).get("yoy_pct")
        trs.append(f"<tr><td>{label}（亿元）</td><td>{yi(run.v(mid))}</td><td>{yi(run.v(mid, run.prev))}</td>"
                   f"<td{neg(d)}>{pct(d) if d is not None else '—'}</td></tr>")
    trs.append(f"<tr><td>净现比</td><td>{num(run.v('ocf_to_np'))}</td><td>{num(run.v('ocf_to_np', run.prev))}</td><td>—</td></tr>")
    trs.append(f"<tr><td>年度累计现金分红（亿元）</td><td>{num(run.seg_cell('dividend', '2025年度累计现金分红', '金额') / 1e8)}</td>"
               "<td>—</td><td>—</td></tr>")
    trs.append(f"<tr><td>现金分红率</td><td>{pct(run.ratios['payout'], sign=False)}</td><td>—</td><td>—</td></tr>")
    return (f'<table class="data"><thead><tr><th>项目</th><th>{run.period}</th><th>{run.prev}</th><th>同比</th></tr></thead>'
            f'<tbody>{"".join(trs)}</tbody></table>')


def table_assumptions(run: Run) -> str:
    sc = run.plan["scenarios"]
    names = {"base": "基准", "downside": "悲观", "upside": "乐观"}
    yrs = [f"{int(run.period) + i}E" for i in range(1, len(sc["base"]["revenue_growth"]) + 1)]
    trs = []
    for k in ("downside", "base", "upside"):
        s = sc[k]
        cells = "".join(f"<td{neg(g)}>{g * 100:+.1f}%</td>" for g in s["revenue_growth"])
        trs.append(f"<tr{' class=base' if k == 'base' else ''}><td>{names[k]}</td>{cells}<td>{s['terminal_growth_rate'] * 100:.1f}%</td>"
                   f"<td>{s['wacc_adjustment'] * 100:+.2f}%</td></tr>")
    head = "".join(f"<th>{y}</th>" for y in yrs)
    w = run.plan["wacc"]
    return (f'<table class="data"><thead><tr><th>收入增速</th>{head}<th>永续增长</th><th>WACC 调整</th></tr></thead>'
            f'<tbody>{"".join(trs)}</tbody></table>'
            f'<p class="small tight">WACC：无风险利率 {w["risk_free_rate"] * 100:.2f}%，β {w["beta"]:.2f}，股权风险溢价 '
            f'{w["equity_risk_premium"] * 100:.2f}%，目标负债占比 {w["target_debt_pct"] * 100:.0f}%。</p>')


def table_scenarios(run: Run) -> str:
    trs = []
    for s in sorted(run.valuation["scenarios"], key=lambda s: s["value_per_share"]):
        trs.append(f"<tr{' class=base' if s['scenario'] == 'base' else ''}><td>{s['scenario_cn']}</td><td>{s['wacc'] * 100:.2f}%</td>"
                   f"<td>{s['terminal_growth'] * 100:.1f}%</td><td>{s['enterprise_value_mm'] / 100:,.0f}</td>"
                   f"<td>{s['equity_value_mm'] / 100:,.0f}</td><td><b>{num(s['value_per_share'])}</b></td>"
                   f"<td{neg(s['upside_vs_price'])}>{s['upside_vs_price'] * 100:+.1f}%</td><td>{s['tv_percent_ev'] * 100:.1f}%</td>"
                   f"<td>{s['implied_exit_ebitda']:.1f}x</td></tr>")
    return ('<table class="data"><thead><tr><th>情景</th><th>WACC</th><th>永续增长</th><th>企业价值（亿元）</th>'
            '<th>股权价值（亿元）</th><th>每股价值（元）</th><th>较参考股价</th><th>终值占比</th><th>隐含 EV/EBITDA</th>'
            f'</tr></thead><tbody>{"".join(trs)}</tbody></table>')


def table_sensitivity(run: Run) -> str:
    s = run.valuation["sensitivities"][0]
    base = next(x for x in run.valuation["scenarios"] if x["scenario"] == "base")
    price = run.valuation["current_price"]

    def shade(v):  # 相对参考股价着色，仅用于配色
        r = max(-1.0, min(1.0, (v / price - 1) / 0.6))
        rgb = (27, 54, 93) if r >= 0 else (181, 72, 47)
        a = 0.08 + 0.5 * abs(r)
        return f"background: rgba({rgb[0]},{rgb[1]},{rgb[2]},{a:.2f});" + ("color:#fff;" if a > 0.4 else "")

    head = "".join(f"<th>{(base['terminal_growth'] + g) * 100:.1f}%</th>" for g in s["y_values"])
    trs = []
    for i, dw in enumerate(s["x_values"]):
        cells = "".join(f'<td style="{shade(v)}"{" class=center" if dw == 0 and s["y_values"][j] == 0 else ""}>{v:,.0f}</td>'
                        for j, v in enumerate(s["matrix"][i]))
        trs.append(f"<tr><th>{(base['wacc'] + dw) * 100:.2f}%</th>{cells}</tr>")
    return f'<table class="heat"><thead><tr><th class="corner">WACC ＼ g</th>{head}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


def table_nonop(run: Run) -> str:
    trs = "".join(f"<tr><td>{'减：' if it['sign'] < 0 else ''}{it['label']}</td><td{neg(it['value_mm'])}>{it['value_mm'] / 100:,.2f}</td>"
                  f"<td class='pg'>p.{(it.get('source') or {}).get('page', '—')}</td></tr>" for it in run.non_op["items"])
    trs += f"<tr class='total'><td>合计</td><td>{run.non_op['total_mm'] / 100:,.2f}</td><td></td></tr>"
    return f'<table class="data slim"><thead><tr><th>非经营性资产（{run.period} 年末）</th><th>亿元</th><th class="pg">页码</th></tr></thead><tbody>{trs}</tbody></table>'


def table_segment_forecast(run: Run, n: int = 3) -> str:
    """分部收入预测（基准情景）：销量、吨价、收入、毛利率，全部取自 segment_forecast.json。"""
    by, sc = run.seg["base_year"], run.seg["scenarios"]["base"]
    cols = [f"{run.period}A"] + [y[2:] + "E" for y in run.seg["years"][:n]]
    head = "".join(f"<th{' class=est' if c.endswith('E') else ''}>{c}</th>" for c in cols)
    trs = []
    for b, sg in zip(by["segments"], sc["segments"]):
        trs.append(f'<tr class="grp"><td colspan="{len(cols) + 1}">{b["name"]}</td></tr>')
        rows = [("销量（吨）", [b["volume"]] + sg["volume"][:n], lambda v: mm(v)),
                ("销量增速", [None] + sg["volume_growth"][:n], lambda v: pct(v * 100, 1)),
                ("吨价（万元/吨）", [b["price"]] + sg["price"][:n], lambda v: num(v)),
                ("吨价增速", [None] + sg["price_growth"][:n], lambda v: pct(v * 100, 1)),
                ("收入（亿元）", [b["revenue"]] + sg["revenue"][:n], lambda v: num(v / 100)),
                ("毛利率", [b["gross_margin"]] + sg["gross_margin"][:n], lambda v: pct(v * 100, 2, sign=False))]
        for label, vals, f in rows:
            trs.append(f"<tr><td>{label}</td>" + "".join(
                f'<td class="{"est" if i else ""}{" neg" if v is not None and v < 0 else ""}">{"—" if v is None else f(v)}</td>'
                for i, v in enumerate(vals)) + "</tr>")
    trs.append(f'<tr class="grp"><td colspan="{len(cols) + 1}">合计</td></tr>')
    tot = [("营业收入（亿元）", [by["revenue"]] + sc["revenue"][:n], lambda v: num(v / 100)),
           ("营业收入增速", [None] + sc["revenue_growth"][:n], lambda v: pct(v * 100, 2)),
           ("综合毛利率", [by["gross_margin"]] + sc["gross_margin"][:n], lambda v: pct(v * 100, 2, sign=False)),
           ("销售费用率", [by["expense_ratios"]["selling"]] + sc["expense_ratios"]["selling"][:n],
            lambda v: pct(v * 100, 2, sign=False))]
    for label, vals, f in tot:
        trs.append(f"<tr class='sub'><td>{label}</td>" + "".join(
            f'<td class="{"est" if i else ""}{" neg" if v is not None and v < 0 else ""}">{"—" if v is None else f(v)}</td>'
            for i, v in enumerate(vals)) + "</tr>")
    return f'<table class="data forecast"><thead><tr><th>基准情景</th>{head}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


def table_scenario_drivers(run: Run) -> str:
    """三情景关键驱动（2026E）与估值参数。"""
    cn = {"base": "基准", "downside": "悲观", "upside": "乐观"}
    vs = {s["scenario"]: s for s in run.valuation["scenarios"]}
    trs = []
    for k in ("downside", "base", "upside"):
        sc = run.seg["scenarios"][k]
        mt, sr = sc["segments"][0], sc["segments"][1]
        trs.append(f"<tr{' class=base' if k == 'base' else ''}><td>{cn[k]}</td>"
                   f"<td{neg(mt['price_growth'][0])}>{pct(mt['price_growth'][0] * 100, 1)}</td>"
                   f"<td{neg(sr['price_growth'][0])}>{pct(sr['price_growth'][0] * 100, 1)}</td>"
                   f"<td{neg(sc['revenue_growth'][0])}>{pct(sc['revenue_growth'][0] * 100, 2)}</td>"
                   f"<td>{pct(sc['gross_margin'][0] * 100, 2, sign=False)}</td>"
                   f"<td>{vs[k]['wacc'] * 100:.2f}%</td><td>{vs[k]['terminal_growth'] * 100:.1f}%</td>"
                   f"<td><b>{num(vs[k]['value_per_share'])}</b></td></tr>")
    y = run.seg["years"][0][2:] + "E"
    return ('<table class="data nw"><thead><tr><th>情景</th>'
            f'<th>茅台酒吨价增速（{y}）</th><th>系列酒吨价增速（{y}）</th><th>收入增速（{y}）</th><th>毛利率（{y}）</th>'
            f'<th>WACC</th><th>永续增长</th><th>每股价值（元）</th></tr></thead><tbody>{"".join(trs)}</tbody></table>')


# ------------------------------------------------------------------ 附录：财务报表预测（百万元）
def _fin_table(title: str, cols: list[str], rows: list[tuple[str, list, str]]) -> str:
    head = "".join(f"<th{' class=est' if c.endswith('E') else ''}>{c}</th>" for c in cols)
    trs = []
    for label, vals, kind in rows:
        k = kind.rstrip("!")
        cells = "".join(f"<td{neg(v)}>{_fmt(v, k) if k in ('pct', 'pctn', 'num', 'x') else mm(v)}</td>" for v in vals)
        trs.append(f"<tr{' class=total' if kind.endswith('!') else ''}><td>{label}</td>{cells}</tr>")
    return f'<table class="fin"><thead><tr><th>{title}</th>{head}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


def appendix_statements(run: Run, n: int = 3) -> str:
    fy = f"FY{run.period}"
    cols = [f"{run.period}A"] + [p[2:] + "E" for p in run.ts["periods"][:n]]
    ys = [run.years[c] for c in cols]
    IS, BS, CF = run.stmt("利润表"), run.stmt("资产负债表"), run.stmt("现金流量表")
    h_is, h_bs, h_cf = (run.ts_plan["historicals"][k][fy] for k in ("income_statement", "balance_sheet", "cash_flow"))
    f = lambda d, k: d[k][:n]  # noqa: E731
    m6 = lambda v: None if v is None else v / 1e6  # noqa: E731
    inc = _fin_table("利润表（百万元）", cols, [
        ("营业收入", [m6(x["revenue"]) for x in ys], "mm!"),
        ("营业成本", [m6(x["cogs"]) for x in ys], "mm"),
        ("毛利", [m6(x["gross_profit"]) for x in ys], "mm!"),
        ("经营费用（不含折旧摊销）", [h_is["opex"]] + f(IS, "opex"), "mm"),
        ("折旧摊销", [h_is["da"]] + f(IS, "da"), "mm"),
        ("EBIT（经营性）", [m6(x["ebit"]) for x in ys], "mm!"),
        ("所得税", [h_is["taxes"]] + f(IS, "book_taxes"), "mm"),
        ("净利润", [m6(x["net_profit"]) for x in ys], "mm!"),
        ("归母净利润", [m6(x["np_parent"]) for x in ys], "mm!"),
        ("每股收益（元）", [x["eps"] for x in ys], "num"),
    ])
    bal = _fin_table("资产负债表（百万元）", cols, [
        ("货币资金", [h_bs["cash"]] + f(BS, "cash"), "mm"),
        ("应收账款", [h_bs["ar"]] + f(BS, "ar"), "mm"),
        ("存货", [h_bs["inventory"]] + f(BS, "inventory"), "mm"),
        ("固定资产+在建工程", [h_bs["ppe_net"]] + f(BS, "ppe_net"), "mm"),
        ("其他资产", [h_bs["other_assets"]] + f(BS, "other_assets"), "mm"),
        ("资产总计", [h_bs["total_assets"]] + f(BS, "total_assets"), "mm!"),
        ("应付账款", [h_bs["ap"]] + f(BS, "ap"), "mm"),
        ("有息负债（含租赁）", [h_bs["debt"]] + f(BS, "debt"), "mm"),
        ("其他负债", [h_bs["other_liabilities"]] + f(BS, "other_liabilities"), "mm"),
        ("股本、资本公积及其他权益", [h_bs["common_equity"]] + f(BS, "common_equity"), "mm"),
        ("留存收益（预测期累计）", [h_bs["retained_earnings"]] + f(BS, "retained_earnings"), "mm"),
        ("负债和权益总计", [h_bs["total_liabilities_equity"]] + f(BS, "total_liabilities_equity"), "mm!"),
    ])
    cfs = _fin_table("现金流量表（百万元）", cols, [
        ("净利润", [h_cf["net_income"]] + f(CF, "net_income"), "mm"),
        ("折旧摊销", [h_cf["da"]] + f(CF, "da"), "mm"),
        ("营运资本增加", [run.plan["historicals"]["change_nwc"]] + f(CF, "change_nwc"), "mm"),
        ("经营活动现金流", [h_cf["cfo"]] + f(CF, "cash_flow_from_operations"), "mm!"),
        ("资本开支", [h_cf["capex"]] + f(CF, "capex"), "mm"),
        ("现金分红", [None] + [-x for x in run.detail["base"]["equity_flows"]["dividends"][:n]], "mm"),
        ("期末现金", [h_bs["cash"]] + f(CF, "ending_cash"), "mm!"),
    ])
    rat = _fin_table("主要财务比率", cols, [
        ("营业收入增长率", [x["revenue_growth"] for x in ys], "pct"),
        ("归母净利润增长率", [x["np_parent_growth"] for x in ys], "pct"),
        ("毛利率", [x["gross_margin"] for x in ys], "pctn"),
        ("归母净利率", [x["net_margin_parent"] for x in ys], "pctn"),
        ("ROE（加权平均）", [x["roe"] for x in ys], "pctn"),
        ("每股收益（元）", [x["eps"] for x in ys], "num"),
        ("P/E（倍）", [x["pe"] for x in ys], "x"),
    ])
    return f'<div class="two fin-grid"><div>{inc}{cfs}</div><div>{bal}{rat}</div></div>'


def appendix_notes(run: Run) -> str:
    m = run.manifest
    n_tie = len(run.analysis["tieouts"])
    n_cells = sum(1 for t in run.extras["tables"] for r in t["rows"] for v in r["values"] if v is not None)
    n_facts = sum(1 for c in run.analysis["truth_table"] if c.get("method") != "derived" and "." not in c["metric_id"])
    rt = run.fs["rating"]
    inputs = "".join(f"<tr><td><code>{html.escape(k)}</code></td><td><code>{v[:16]}…</code></td></tr>"
                     for k, v in m["inputs"].items())
    return f"""
<h3>估值方法说明</h3>
<p class="small">DCF 采用 FCFF 口径、年中折现，经营预测取自分部驱动的三表模型；EBIT = 利润总额 + 财务费用 − 投资收益 −
公允价值变动收益。营业收入取合并利润表“其中：营业收入”，不含财务公司利息收入；财务公司利息收入仍计入经营费用轧差项，
股权桥逐项加回财务公司持有的类现金资产并扣减其吸收的存款，二者存在少量重复计算。{"；".join(run.fs["notes"])}。
经营费用率中的“其他”为基期轧差项（含财务公司利息、折旧重分类等），预测期保持不变。</p>
<h3>数据来源与方法</h3>
<p class="small">财务与经营数据来自公司 {run.period} 年年度报告：财务数据 {n_facts} 项、经营数据 {n_cells} 个数字由模型读取年报后，
经 FinAgent 逐字核对原文并与规则通道交叉校验，{n_tie} 项勾稽全部通过；全部计算由确定性程序完成，正文数字经数字护栏核对出处。
逐项页码见估值模型 model.xlsx“历史财务”“经营数据”页。当前股价为 {m["run_id"][:4]} 年行情数据（{run.fs["market"]["price_date"]} 收盘）。</p>
<table class="data slim mono"><thead><tr><th>输入文件（运行 {m['run_id']}）</th><th>SHA-256</th></tr></thead><tbody>{inputs}</tbody></table>
<h3>内容说明</h3>
<p class="small">本报告中直接引用的财务与经营数据为事实；以“主要系”“反映”等表述的归因为基于数据的推论；以“我们认为”“我们预计”
表述的判断、盈利预测、估值与评级为观点，依赖第 5 节所列假设。</p>
<h3>投资评级说明</h3>
<p class="small">评级依据{rt['basis']}：{rt['rule']}。评级由模型按上述规则生成。</p>"""


# ------------------------------------------------------------------ 页面
CSS = (HERE / "report.css").read_text(encoding="utf-8")


def summary_html(text: str) -> str:
    """首页投资要点：每段以“● 加粗小标题”开头。"""
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        m = re.match(r"\*\*(.+?)\*\*\s*(.*)", block.strip(), re.S)
        head, body = (m.group(1).rstrip("：:。"), m.group(2)) if m else ("", block)
        text = md(body)[3:-4] if md(body).startswith("<p>") else md(body)
        sep = "：" if head in ("事件", "风险提示", "盈利预测及投资建议") else "。"
        out.append(f'<p class="point"><span class="point-h">{html.escape(head)}{sep}</span>{text}</p>')
    return "\n".join(out)


def h2(n: int | str, title: str) -> str:
    return f'<h2><span class="num">{n}</span>{title}</h2>'


def build(run: Run, S: dict[str, str], out: Path) -> Path:
    ch = out / "charts"
    ch.mkdir(parents=True, exist_ok=True)
    c0, c1, c2, c3 = chart_cover(run, ch), chart_quarterly(run, ch), chart_product(run, ch), chart_channel(run, ch)
    c4, c5, c6, c7 = chart_price(run, ch), chart_bridge(run, ch), chart_cash(run, ch), chart_football(run, ch)
    period, prev = run.period, run.prev
    d = REPORT_DATE
    doc = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{COMPANY}（{TICKER}）{period} 年年报点评</title>
<style>{CSS}</style></head><body>

<section class="cover">
  <div class="mast">
    <div><div class="date">{d}</div><div class="who">{COMPANY}（{TICKER}）<span>{SECTOR}</span></div></div>
    <div class="brand">FinAgent<small>投资研究</small></div>
  </div>
  <h1>{html.escape(S['title'])}</h1>
  <div class="subline"><span>{html.escape(S['subtitle'])}</span><span class="kind">公司点评</span></div>
  <div class="cover-grid">
    <div class="cover-main"><div class="kicker">投资要点</div>{summary_html(S['summary'])}</div>
    {cover_side(run, c0)}
  </div>
  <figure class="cover-table"><figcaption>盈利预测与估值</figcaption>
    {table_forecast(run, keys=COVER_ROWS)}
    <div class="src">资料来源：公司公告，FinAgent 预测（基准情景）</div></figure>
</section>

<section>
  {h2(1, "业绩回顾：收入与利润小幅回落，季度收入逐季回升")}
  {md(S['performance'])}
  <div class="two">
    {fig(1, f"{period} 年分季度营业收入与归母净利润（亿元）", img(c1, 84), src(run))}
    {fig(2, "主要财务指标", table_core(run), src(run))}
  </div>
</section>

<section>
  {h2(2, "分产品与渠道：茅台酒量价平稳，系列酒量增价减，直销占比过半")}
  {md(S['segments'])}
  <div class="two">
    {fig(3, "分产品收入与毛利率", img(c2, 84), src(run))}
    {fig(4, "分渠道收入结构（亿元）", img(c3, 84), src(run))}
  </div>
  {fig(5, "主营业务构成", table_segments(run), src(run))}
  <div class="two">
    <div>{fig(6, "分产品量价拆分", table_volume(run), src(run, extra="吨价 = 收入 ÷ 销量"))}
    {fig(8, "渠道、产能与库存", table_ops(run), src(run))}</div>
    {fig(7, "分渠道吨价（万元/吨）", img(c4, 84), src(run, extra="吨价 = 收入 ÷ 销量"))}
  </div>
</section>

<section>
  {h2(3, "盈利能力：系列酒拖累毛利率，市场投入加大")}
  {md(S['profitability'])}
  {fig(9, f"归母净利润变动归因（{prev} 年至 {period} 年，亿元）", img(c5, 174), src(run))}
</section>

<section>
  {h2(4, "现金流与股东回报：经营现金流受财务公司扰动，分红率维持高位")}
  {md(S['cashflow'])}
  <div class="two">
    {fig(10, "分季度经营现金流与归母净利润（亿元）", img(c6, 84), src(run))}
    {fig(11, "现金流、营运资本与分红", table_cash(run), src(run))}
  </div>
</section>

<section>
  {h2(5, "盈利预测与估值")}
  {md(S['forecast'])}
  {fig(12, "分部收入预测", table_segment_forecast(run), src(run, extra="基准情景"))}
  {fig(13, "盈利预测", table_forecast(run, last=5, cls="data forecast"), src(run, extra="基准情景"))}
  {md(S['valuation'])}
  {fig(14, "三情景关键驱动与估值", table_scenario_drivers(run), src(run))}
  <div class="two">
    {fig(15, "每股价值区间（元）", img(c7, 84), src(run))}
    {fig(16, "敏感性：WACC × 永续增长率（元/股）", table_sensitivity(run), src(run))}
  </div>
</section>

<section>
  {h2(6, "投资建议")}
  {md(S['recommendation'])}
</section>

<section>
  {h2(7, "风险提示")}
  {md(S['risks'])}
</section>

<section class="appendix">
  {h2("附", "财务报表预测")}
  {appendix_statements(run)}
  <div class="src">资料来源：公司公告，FinAgent 预测（基准情景）。经营费用为轧差项，含税金及附加；{period}A 净利润为报表值。</div>
  {fig(17, "股权桥中加回的非经营性资产（亿元）", table_nonop(run), src(run))}
  {appendix_notes(run)}
  <div class="disclaimer"><b>免责声明</b>　本报告由 FinAgent（2026 北京市大学生金融人工智能竞赛参赛作品）生成，所载资料来源于公司公开披露信息，
  盈利预测、估值与评级基于报告所列假设，仅供研究方法展示，不构成任何投资建议。</div>
</section>
</body></html>"""
    path = out / "report.html"
    path.write_text(doc, encoding="utf-8")
    return path


def to_pdf(html_path: Path) -> Path:
    pdf = html_path.with_suffix(".pdf")
    subprocess.run([CHROME, "--headless=new", "--no-pdf-header-footer", f"--print-to-pdf={pdf}",
                    "--virtual-time-budget=10000", html_path.resolve().as_uri()], check=True, capture_output=True)
    return pdf


def preview(pdf: Path) -> list[Path]:
    import logging

    import pdfplumber

    logging.disable(logging.WARNING)  # pdfminer 对 Chrome 嵌入字体的 FontBBox 告警，无关紧要
    out = pdf.parent / "preview"
    out.mkdir(exist_ok=True)
    for old in out.glob("page*.png"):
        old.unlink()
    paths = []
    with pdfplumber.open(pdf) as doc:
        for i, page in enumerate(doc.pages, 1):
            p = out / f"page{i:02d}.png"
            page.to_image(resolution=110).save(p)
            paths.append(p)
        fonts = sorted({c["fontname"].split("+")[-1] for pg in doc.pages for c in pg.chars})
    print("嵌入字体：", ", ".join(fonts))
    return paths


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--narrative", default=str(HERE / "narrative.md"))
    ap.add_argument("--no-pdf", action="store_true")
    args = ap.parse_args()
    run = Run(Path(args.run_dir))
    html_path = build(run, load_sections(Path(args.narrative)), run.dir / "report")
    print("HTML：", html_path)
    if not args.no_pdf:
        pdf = to_pdf(html_path)
        pages = preview(pdf)
        print("PDF：", pdf, f"（{len(pages)} 页，预览 {pages[0].parent}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
