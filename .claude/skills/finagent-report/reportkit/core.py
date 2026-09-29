"""公共部分：读运行产物、单位换算与格式化（不产生新数字）、narrative.md → HTML、配色与画图参数。"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

NAVY, SLATE, LIGHT, BRICK, NEUTRAL, GRID, INK, MUTED, GOLD, NAVY2, LIGHT2 = (
    "#1B365D", "#8A9BB0", "#C9D3DF", "#B5482F", "#7F8C9A", "#E5E7EB", "#1F2937", "#6B7280", "#C9A227",
    "#3A5680", "#E4E9F0")
PALETTE = [NAVY, SLATE, GOLD, NAVY2, LIGHT, BRICK]  # 多系列时按序取色
HEAT_POS, HEAT_NEG = (27, 54, 93), (181, 72, 47)  # 敏感性热力表：高于 / 低于参考股价

# ------------------------------------------------------------------ 主题
# 颜色按角色命名（沿用默认主题的常量名）：NAVY 主数据、NAVY2 主色第二层、SLATE 对比系列、LIGHT 上期/预测、LIGHT2 更浅的上期、
# GOLD 强调、BRICK 负向、NEUTRAL 合计、GRID 网格、INK 文字、MUTED 次要文字。css 追加在 report.css 之后覆盖变量与细节。
THEMES: dict[str, dict] = {
    "navy": {"css": ""},
    "warm_red": {
        "NAVY": "#A21316", "NAVY2": "#C6342C", "SLATE": "#235D96", "LIGHT": "#F2DAB3", "LIGHT2": "#F8F0E0",
        "GOLD": "#E0B97A", "BRICK": "#235D96", "NEUTRAL": "#9A958C", "GRID": "#D8D8D5", "INK": "#222222",
        "MUTED": "#6F6A62", "HEAT_POS": (162, 19, 22), "HEAT_NEG": (35, 93, 150),
        "css": """
:root { --ink: #222222; --muted: #6F6A62; --rule: #D8D8D5; --light: #F8F5EE;
        --navy: #C6342C; --slate: #235D96; --brick: #235D96; }
body { color: #222222; }
h1 { color: #222222; }
h2, h3, .kicker, .point-h, .toc-h, .disc-h { color: #CC2931; }
h2 { border-bottom-color: #C6342C; }
.subline { color: #222222; border-bottom-color: #C6342C; }
p strong, li strong { color: #CC2931; }
.cover::before { content: ""; display: block; height: 3.2mm; background: #C6342C; margin-bottom: 4mm; }
.mast .brand { color: #C6342C; }
.rating { border-top-color: #C6342C; border-bottom-color: #C6342C; }
.rating b { color: #CC2931; }
.kv.strong b, .fno, .toc-n { color: #A21316; }
.side { background: #F8F5EE; padding: 2mm 2.6mm 3mm; }
.side-h { color: #C6342C; border-bottom-color: #C6342C; }
table.data tr.base td { background: #FBF0DC; }
table.forecast th.est, table.forecast td.est { background: #FAF6EE; }
table.fin { border-top-color: #C6342C; border-bottom-color: #C6342C; }
table.fin th { background: #C6342C; }
table.fin th.est { background: #A21316; }
table.data tr.grp td { color: #A21316; background: #F8F5EE; }
.kv, table.data td, table.fin td { border-bottom-color: #E8E6E1; }
.disclaimer-page h3 { color: #CC2931; }
""",
    },
}
ROLE_NAMES = ("NAVY", "NAVY2", "SLATE", "LIGHT", "LIGHT2", "GOLD", "BRICK", "NEUTRAL", "GRID", "INK", "MUTED",
              "HEAT_POS", "HEAT_NEG", "PALETTE")
_DEFAULTS: dict = {}


def apply_theme(name: str, *namespaces: dict) -> None:
    """切换主题：改写 reportkit 各模块及传入命名空间（公司脚本的 globals）里的颜色常量。先恢复默认再覆盖，可反复切换。"""
    import sys
    g = globals()
    if not _DEFAULTS:
        _DEFAULTS.update({k: g[k] for k in ROLE_NAMES})
    if name not in THEMES:
        raise SystemExit(f"未知主题 {name}，可选：{', '.join(THEMES)}")
    vals = dict(_DEFAULTS)
    vals.update({k: v for k, v in THEMES[name].items() if k in ROLE_NAMES})
    vals["PALETTE"] = [vals["NAVY"], vals["SLATE"], vals["GOLD"], vals["NAVY2"], vals["LIGHT"], vals["BRICK"]]
    targets = [m.__dict__ for n, m in sys.modules.items() if n.startswith("reportkit")] + list(namespaces)
    for ns in targets:
        for k, v in vals.items():
            if k in ns:
                ns[k] = v
    plt.rcParams.update({"axes.edgecolor": vals["MUTED"] if name != "navy" else "#9CA3AF"})
MM = 1 / 25.4
FULL, HALF = 172, 83  # 通栏、半栏宽度（mm）

plt.rcParams.update({
    # 数字与西文用 Helvetica，汉字回退楷体（非 macOS：Arial / KaiTi，见 SKILL.md“字体”）
    "font.family": ["Helvetica Neue", "Arial", "Kaiti SC", "KaiTi", "STKaiti"],
    "font.size": 7.5, "axes.titlesize": 7.5, "axes.labelsize": 7, "xtick.labelsize": 7, "ytick.labelsize": 7,
    "legend.fontsize": 7, "axes.edgecolor": "#9CA3AF", "axes.linewidth": 0.6, "axes.unicode_minus": False,
    "axes.spines.top": False, "axes.spines.right": False, "svg.fonttype": "path",
})
import logging  # noqa: E402

logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)  # 字重回退告警


# ------------------------------------------------------------------ 数据
class Run:
    """一次 finagent 运行的产物。缺失的产物读成空字典，对应图表由调用方跳过。"""

    def __init__(self, run_dir: Path):
        self.dir = Path(run_dir)

        def j(rel: str) -> dict:
            p = self.dir / rel
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}

        self.analysis, self.earnings = j("financials/analysis.json"), j("financials/earnings.json")
        self.extras = j("financials/extras.json")
        self.valuation, self.plan = j("valuation/valuation.json"), j("valuation/plan.json")
        self.ts, self.ts_plan = j("valuation/three_statement.json"), j("valuation/three_statement_plan.json")
        self.fs, self.non_op = j("valuation/forecast_summary.json"), j("valuation/non_operating_assets.json")
        self.seg, self.detail = j("valuation/segment_forecast.json"), j("valuation/three_statement_detail.json")
        self.comps = j("valuation/comps.json")  # 有 --peers 时才有
        self.manifest = j("manifest.json")
        self.period = self.analysis["period"]
        self.prev = str(int(self.period) - 1)
        self.prev2 = str(int(self.period) - 2)
        self.tt = {(c["metric_id"], c["period"]): c for c in self.analysis["truth_table"]}
        self.quarterly = {r["metric_id"]: r for r in (self.analysis.get("quarterly") or {}).get("rows", [])}
        self.tables = {t["id"]: t for t in self.extras.get("tables", [])}
        self.ratios = {r["id"]: r["value"] for r in self.extras.get("ratios", [])}
        self.years = {y["year"]: y for y in self.fs.get("years", [])}
        self.changes = {c["metric_id"]: c for c in self.analysis.get("changes", [])}
        self.scen = {s["scenario"]: s for s in self.valuation.get("scenarios", [])}

    def v(self, metric: str, period: str | None = None) -> float | None:
        c = self.tt.get((metric, period or self.period))
        return None if c is None else c["value"]

    def yoy(self, metric: str) -> float | None:
        return (self.changes.get(metric) or {}).get("yoy_pct")

    def cell(self, table: str, row: str, col: str) -> float | None:
        t = self.tables[table]
        names = [c["name"] for c in t["columns"]]
        r = next(r for r in t["rows"] if r["label"] == row)
        return r["values"][names.index(col)]

    def rows(self, table: str) -> list[str]:
        return [r["label"] for r in self.tables[table]["rows"]]

    def has(self, *tables: str) -> bool:
        return all(t in self.tables for t in tables)

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


def pp(x, d=2):
    return "—" if x is None else f"{x:+.{d}f} pp"


def num(x, d=2):
    return "—" if x is None else f"{x:,.{d}f}"


def dec(*values, big: float = 100) -> int:
    """按数量级选小数位：最大绝对值 ≥ big 取 0 位，否则 2 位（小公司的亿元金额、低价股的每股价值不被取整）。"""
    vals = [abs(v) for v in values if v is not None]
    return 0 if vals and max(vals) >= big else 2


def fmt_of(*values, big: float = 100) -> str:
    return "{:,.%df}" % dec(*values, big=big)


def neg(x):
    return ' class="neg"' if x is not None and x < 0 else ""


# ------------------------------------------------------------------ narrative.md → HTML
def load_sections(path: Path) -> dict[str, str]:
    """按 <!-- section: 名称 --> 分节；HTML 注释（写作提示）去掉。"""
    text = Path(path).read_text(encoding="utf-8")
    parts = re.split(r"<!--\s*section:\s*(\w+)\s*-->", text)
    strip = lambda s: re.sub(r"<!--.*?-->", "", s, flags=re.S).strip()  # noqa: E731
    return {parts[i]: strip(parts[i + 1]) for i in range(1, len(parts), 2)}


def inline(s: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(s))


def md(text: str) -> str:
    """段落、列表、### 小标题、**加粗**。"""
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = block.strip().splitlines()
        if lines and lines[0].startswith("### "):
            out.append(f"<h3>{inline(lines[0][4:])}</h3>")
            lines = lines[1:]
            if not lines:
                continue
        if all(ln.startswith("- ") for ln in lines):
            out.append("<ul>" + "".join(f"<li>{inline(ln[2:])}</li>" for ln in lines) + "</ul>")
        else:
            out.append(f"<p>{inline(' '.join(lines))}</p>")
    return "\n".join(out)


def md_parts(text: str) -> list[str]:
    """按 ### 小标题把一节拆成若干块，便于在小节之间插入图表。"""
    chunks = re.split(r"\n(?=### )", "\n" + text.strip())
    return [md(c) for c in chunks if c.strip()]


# ------------------------------------------------------------------ 画图辅助
def save(fig, path: Path) -> str:
    fig.savefig(path, format="svg", bbox_inches="tight", pad_inches=0.02, transparent=True)
    plt.close(fig)
    return path.name


def labels(ax, bars, fmt="{:,.0f}", color=INK, size=6.4, inside=False):
    for b in bars:
        h = b.get_height()
        if inside:
            ax.text(b.get_x() + b.get_width() / 2, b.get_y() + h / 2, fmt.format(h), ha="center", va="center",
                    fontsize=size, color=color)
        else:
            ax.annotate(fmt.format(h), (b.get_x() + b.get_width() / 2, b.get_y() + max(h, 0)), xytext=(0, 1.5),
                        textcoords="offset points", ha="center", va="bottom", fontsize=size, color=color)


def clean(ax):
    ax.set_yticks([])
    ax.spines["left"].set_visible(False)


def hgrid(ax):
    ax.yaxis.grid(True, color=GRID, lw=0.5)
    ax.set_axisbelow(True)


def subtitle(ax, text):
    ax.set_title(text, loc="left", color=MUTED, fontsize=6.8)


def fig_size(w_mm, h_mm, **kw):
    return plt.subplots(figsize=(w_mm * MM, h_mm * MM), **kw)


def legend_below(ax, ncol=2, **kw):
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.2), ncol=ncol, handlelength=1,
              columnspacing=1.2, **kw)


def note_above(ax, bar, text, color=None, dy=10):
    """柱顶上方的第二行标注（同比、占比等）；负数用砖红。"""
    ax.annotate(text, (bar.get_x() + bar.get_width() / 2, bar.get_y() + bar.get_height()), xytext=(0, dy),
                textcoords="offset points", ha="center", va="bottom", fontsize=6,
                color=color or (BRICK if text.startswith("-") else MUTED))
