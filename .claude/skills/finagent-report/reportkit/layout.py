"""排版：图表编号与目录（两遍定位页码）、首页、附录、免责声明、HTML → PDF、逐页预览与缩略图总览。

公司脚本只需提供 Config 与 body(doc, S) -> str（正文 HTML），调用 main(config, body) 即可。
"""

from __future__ import annotations

import argparse
import html
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import charts as C
from . import tables as T
from .core import Run, dec, inline, load_sections, load_sources, md, mm, neg, num, pct

KIT = Path(__file__).resolve().parent
CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def chrome() -> str:
    """无头浏览器：环境变量 FINAGENT_CHROME 优先，其次常见安装路径，再次 PATH 中的 chrome / chromium / msedge。"""
    import os
    import shutil
    env = os.environ.get("FINAGENT_CHROME")
    if env:
        path = Path(env).expanduser()
        if path.is_file():
            return str(path)
        raise SystemExit(f"FINAGENT_CHROME 指向的浏览器不存在：{path}")
    local = os.environ.get("LOCALAPPDATA")
    local_candidates = ([str(Path(local) / "Google/Chrome/Application/chrome.exe"),
                         str(Path(local) / "Microsoft/Edge/Application/msedge.exe")] if local else [])
    for c in [*local_candidates, *CHROME_CANDIDATES]:
        if Path(c).exists():
            return c
    for name in ("chrome", "chrome.exe", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                 "msedge", "msedge.exe"):
        if shutil.which(name):
            return shutil.which(name)
    raise SystemExit("找不到 Chrome / Chromium / Edge：请安装，或设置环境变量 FINAGENT_CHROME 指向浏览器可执行文件")


@dataclass
class Config:
    company: str                      # 贵州茅台
    ticker: str                       # 600519.SH
    sector: str                       # 食品饮料 · 白酒
    date: str                         # 2026 年 9 月 29 日
    narrative: Path                   # narrative.md（已过 guard）
    kind: str = "公司深度"             # 首页右上：公司深度 / 公司点评
    report_name: str = ""             # 页眉：默认“<年度> 年报深度点评”
    side_rows: Callable[[Run], list[tuple[str, str]]] | None = None  # 首页“基本数据”追加行：run → [(名称, 已格式化的值)]
    method_note: str = ""             # 附录“估值方法说明”追加的公司口径说明
    rating_note: str = "（首次）"
    output_name: str = ""             # PDF 另存名（如“贵州茅台0929.pdf”），留空只输出 report.pdf
    sources: Path | None = None       # 外部调研登记；留空时取 narrative 同级目录上一层的 research/sources.json


# ------------------------------------------------------------------ 图表编号与目录
class Doc:
    """按出现顺序给图表编号，并收集章节与图表清单供目录使用。"""

    def __init__(self, run: Run, charts_dir: Path):
        self.run, self.ch = run, charts_dir
        self.n = 0
        self.figs: list[tuple[int, str]] = []
        self.secs: list[tuple[str, str]] = []
        self.nonop_shown = False  # 正文已展示非经营性资产明细时，附录不再重复

    def fig(self, title: str, body: str, note: str = "", cls: str = "", src: str = "公司公告，FinAgent") -> str:
        """图表外框：编号、标题、来源行。note 追加在来源之后（口径说明、“基准情景”等）；cls 可取 half / split。
        src 换成外部资料时写发布方并带编号，如 src="Clarksons [S2]，FinAgent 整理"。"""
        self.n += 1
        self.figs.append((self.n, title))
        extra = f"；{note}" if note else ""
        return (f'<figure class="{cls}"><figcaption><span class="fno">图表 {self.n}</span>{html.escape(title)}</figcaption>'
                f'{body}<div class="src">资料来源：{inline(src)}{extra}</div></figure>')

    def img(self, fn: Callable | str, width_mm: int = 83, *args, **kw) -> str:
        """fn 为标准图函数（传入 run 与输出目录）或已生成的 SVG 文件名。"""
        name = fn if isinstance(fn, str) else fn(self.run, self.ch, *args, **kw)
        return f'<img src="charts/{name}" style="width:{width_mm}mm">'

    def h2(self, n: int | str, title: str) -> str:
        self.secs.append((str(n), title))
        return f'<h2><span class="num">{html.escape(str(n))}</span>{html.escape(title)}</h2>'


def two(a: str, b: str) -> str:
    """两个半栏图表并排。"""
    return f'<div class="two">{a}{b}</div>'


def toc(doc: Doc, pages: dict[str, int]) -> str:
    sec = "".join(f'<div class="toc-row"><span class="toc-n">{n}</span><span class="toc-t">{html.escape(t)}</span>'
                  f'<span class="toc-dots"></span><span class="toc-p">{pages.get("s" + n, "")}</span></div>'
                  for n, t in doc.secs)
    figs = "".join(f'<div class="toc-row fig"><span class="toc-t">图表 {n}：{html.escape(t)}</span>'
                   f'<span class="toc-dots"></span><span class="toc-p">{pages.get(f"f{n}", "")}</span></div>'
                   for n, t in doc.figs)
    return (f'<section class="toc"><div class="toc-h">目　录</div>{sec}'
            f'<div class="toc-h small-gap">图表目录</div><div class="toc-figs">{figs}</div>'
            f'<span class="toc-end">{TOC_END}</span></section>')


TOC_END = "FINAGENTTOCEND"  # 目录末尾的不可见标记：定位页码时从它之后开始找，目录多页也不会误判


def _norm(t: str) -> str:
    # 康熙部首字等兼容字符归一；只比对文字与数字（“～”“：”等符号在不同字体下抽出的字符不一致）
    return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", t or ""))


def locate_pages(pdf: Path, doc: Doc) -> dict[str, int]:
    """在 PDF 文本中定位章节标题与图表编号所在页（跳过首页与目录页）。"""
    import logging

    import pdfplumber
    logging.disable(logging.WARNING)
    with pdfplumber.open(pdf) as p:
        texts = [_norm(pg.extract_text()) for pg in p.pages]
    out: dict[str, int] = {}
    start = next((i + 1 for i, t in enumerate(texts) if TOC_END in t), 2)
    for n, t in doc.secs:
        key = _norm(f"{n}{t}")[:14]
        out["s" + n] = next((i + 1 for i in range(start, len(texts)) if key in texts[i]), "")
    for n, t in doc.figs:
        key = _norm(f"图表{n}{t}")[:len(str(n)) + 8]
        out[f"f{n}"] = next((i + 1 for i in range(start, len(texts)) if key in texts[i]), "")
    return out


def equity_bridge(doc: Doc) -> str:
    """股权价值桥表 + 非经营性资产净额明细（有明细时并排），读者可逐项对回企业价值到每股价值。"""
    run = doc.run
    table_ = doc.fig("股权价值桥（亿元）", T.equity_bridge(run))
    if not run.non_op.get("items"):
        return f'<div class="two">{table_}<div></div></div>'
    doc.nonop_shown = True
    return two(table_, doc.fig("非经营性资产净额明细（亿元）", T.nonop(run), "类负债项目以负数列示，已在合计中扣减"))


def valuation_ranges(doc: Doc) -> str:
    """每股价值区间图 + 运行产物里全部敏感性矩阵，两两并排；有可比公司时追加可比公司表。"""
    run = doc.run
    items = [doc.fig("每股价值区间（元）", doc.img(C.football))]
    for i, s in enumerate(run.valuation.get("sensitivities", [])):
        items.append(doc.fig(f"敏感性：{s['name']}（元/股）", T.sensitivity(run, i)))
    if len(items) % 2:
        items.append("<div></div>")
    html_ = "".join(two(items[k], items[k + 1]) for k in range(0, len(items), 2))
    if run.comps.get("rows"):
        html_ += doc.fig("可比公司估值倍数与利润率", T.comps(run), "市场数据见估值假设文件", cls="split")
        html_ += doc.fig("可比公司隐含每股价值与 DCF 交叉验证", T.comps_implied(run), cls="half")
    return html_


# ------------------------------------------------------------------ 首页
def summary_html(text: str) -> str:
    """投资要点：每段“**小标题。** 正文”；事件、盈利预测及投资建议、风险提示用冒号。"""
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        m = re.match(r"\*\*(.+?)\*\*\s*(.*)", block.strip(), re.S)
        head, body = (m.group(1).rstrip("：:。"), m.group(2)) if m else ("", block)
        sep = "：" if head in ("事件", "风险提示", "盈利预测及投资建议") else "。"
        out.append(f'<p class="point"><span class="point-h">{html.escape(head)}{sep}</span>{inline(body)}</p>')
    return "\n".join(out)


def cover_side(doc: Doc, cfg: Config) -> str:
    run = doc.run
    m, val = run.fs["market"], run.valuation
    base = run.scen["base"]
    rt = run.fs["rating"]
    g = lambda k, scale=1.0, d=2: "—" if m.get(k) is None else f"{m[k] / scale:,.{d}f}"  # noqa: E731
    cap = m.get("market_cap")
    rows = [
        ("当前股价（元）", g("price")),
        ("总股本（亿股）", g("total_shares", 1e8)),
        ("总市值（亿元）", g("market_cap", 1e8, dec(cap / 1e8) if cap else 2)),
        ("每股净资产（元）", g("bvps")),
        ("市净率（倍）", g("pb")),
        (f"市盈率（{run.period}A，倍）", g("pe_latest") if (m.get("pe_latest") or 0) > 0 else "—"),  # 亏损时不显示
        ("资产负债率", pct(m.get("debt_ratio"), sign=False)),
    ] + (cfg.side_rows(run) if cfg.side_rows else [])
    kv = "".join(f'<div class="kv"><span>{html.escape(a)}</span><b>{html.escape(b)}</b></div>' for a, b in rows)
    date = m.get("price_date") or "0000-00-00"
    return f"""
<aside class="side">
  <div class="rating"><span>投资评级</span><b>{html.escape(str(rt.get('rating') or '—'))}</b><em>{html.escape(cfg.rating_note)}</em></div>
  <div class="kv strong"><span>DCF 每股价值（元）</span><b>{num(base['value_per_share'])}</b></div>
  <div class="kv strong"><span>估值区间（元）</span><b>{num(val['value_range']['low'])}～{num(val['value_range']['high'])}</b></div>
  <div class="kv strong"><span>较当前股价空间</span><b>{base['upside_vs_price'] * 100:+.1f}%</b></div>
  <div class="side-h gap">基本数据</div>
  {kv}
  <div class="note">股价日期：{date[:4]} 年 {int(date[5:7])} 月 {int(date[8:])} 日收盘；财务数据截至 {run.period} 年末</div>
  <div class="side-h gap">营业收入与归母净利润（亿元）</div>
  {doc.img(C.cover, 56)}
</aside>"""


def cover(doc: Doc, cfg: Config, S: dict[str, str]) -> str:
    return f"""
<section class="cover">
  <div class="mast">
    <div><div class="date">{html.escape(cfg.date)}</div><div class="who">{html.escape(cfg.company)}（{html.escape(cfg.ticker)}）<span>{html.escape(cfg.sector)}</span></div></div>
    <div class="brand">FinAgent<small>投资研究</small></div>
  </div>
  <h1>{html.escape(S['title'])}</h1>
  <div class="subline"><span>{html.escape(S['subtitle'])}</span><span class="kind">{html.escape(cfg.kind)}</span></div>
  <div class="cover-grid">
    <div class="cover-main"><div class="kicker">投资要点</div>{summary_html(S['summary'])}</div>
    {cover_side(doc, cfg)}
  </div>
  <figure class="cover-table"><figcaption>盈利预测与估值</figcaption>
    {T.forecast(doc.run, keys=T.COVER_ROWS)}
    <div class="src">资料来源：公司公告、分析师预测（基准情景）；A 为历史实际值，E 为预测值。</div></figure>
</section>"""


# ------------------------------------------------------------------ 附录
def _fin_table(title: str, cols: list[str], rows: list[tuple[str, list, str]]) -> str:
    head = "".join(f"<th{' class=est' if c.endswith('E') else ''}>{c}</th>" for c in cols)
    trs = []
    for label, vals, kind in rows:
        k = kind.rstrip("!")
        cells = "".join(f"<td{neg(v)}>{T.fmt(v, k) if k in ('pct', 'pctn', 'num', 'x') else mm(v)}</td>" for v in vals)
        trs.append(f"<tr{' class=total' if kind.endswith('!') else ''}><td>{label}</td>{cells}</tr>")
    return f'<table class="fin"><thead><tr><th>{title}</th>{head}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


def appendix_statements(run: Run, n: int = 5) -> str:
    """财务报表预测（三表模型基准情景，百万元）与主要财务比率。"""
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
    divs = run.detail.get("base", {}).get("equity_flows", {}).get("dividends")
    cfs = _fin_table("现金流量表（百万元）", cols, [
        ("净利润", [h_cf["net_income"]] + f(CF, "net_income"), "mm"),
        ("折旧摊销", [h_cf["da"]] + f(CF, "da"), "mm"),
        ("营运资本增加", [run.plan["historicals"]["change_nwc"]] + f(CF, "change_nwc"), "mm"),
        ("经营活动现金流", [h_cf["cfo"]] + f(CF, "cash_flow_from_operations"), "mm!"),
        ("资本开支", [h_cf["capex"]] + f(CF, "capex"), "mm"),
        ("现金分红", [None] + ([-x for x in divs[:n]] if divs else [None] * n), "mm"),
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
    return f'{inc}{bal}<div class="two fin-grid"><div>{cfs}</div><div>{rat}</div></div>'


def appendix_notes(run: Run, cfg: Config, forecast_secs: str) -> str:
    m = run.manifest
    rt = run.fs.get("rating") or {"basis": "", "rule": "未设置参考股价，未生成评级"}
    inputs = "".join(f"<tr><td><code>{html.escape(k)}</code></td><td><code>{v[:16]}…</code></td></tr>"
                     for k, v in m["inputs"].items())
    notes = "；".join(run.fs.get("notes", []))
    return f"""
<h3>估值方法说明</h3>
<p class="small">DCF 采用 FCFF 口径、年中折现，经营预测取自{'分部驱动的' if run.seg else ''}三表模型；EBIT = 利润总额 + 财务费用 − 投资收益 −
公允价值变动收益，剔除的投资类资产在股权桥中逐项加回。{html.escape(cfg.method_note)}{notes}。
估值输入（无风险利率、β、股权风险溢价、永续增长率、分部量价与费用率）为分析师假设，参考股价为外部行情数据。</p>
<h3>数据来源与方法</h3>
<p class="small">历史财务与经营数据取自公司 {run.period} 年年度报告。逐项页码见估值模型“历史财务”“经营数据”页；
预测值依据第 7 节的分析师假设。表内单价、占比、增速按已披露数据计算。
当前股价为外部行情数据（{run.fs.get("market", {}).get("price_date", "—")} 收盘）。</p>
<table class="data slim mono"><thead><tr><th>输入文件（运行 {m['run_id']}）</th><th>SHA-256</th></tr></thead><tbody>{inputs}</tbody></table>
{sources_html(cfg)}
<h3>内容说明</h3>
<p class="small">经营归因、盈利预测、估值及评级依赖{forecast_secs}所列假设，请结合敏感性分析与风险提示使用。</p>
<h3>投资评级说明</h3>
<p class="small">评级依据{rt['basis']}：{rt['rule']}。</p>"""


def sources_html(cfg: Config) -> str:
    """附录“外部资料来源”：正文 [S编号] 对应的检索来源（发布方、标题、日期、网址）。"""
    path = cfg.sources or Path(cfg.narrative).parent.parent / "research" / "sources.json"
    src = load_sources(path).get("sources") or []
    if not src:
        return ""
    rows = "".join(f"<tr><td>{html.escape(s['id'])}</td><td>{html.escape(s.get('publisher', ''))}</td>"
                   f"<td>{html.escape(s.get('title', ''))}</td><td>{html.escape(s.get('published') or '—')}</td>"
                   f"<td>{html.escape(s.get('url', ''))}</td></tr>" for s in src)
    return ("<h3>外部资料来源</h3><p class=\"small\">正文与图表中标注 S 编号的内容来自以下公开资料，检索与访问日期、"
            "原文摘句见 research/sources.json。</p>"
            f'<table class="data slim sources"><thead><tr><th>编号</th><th>发布方</th><th>标题</th><th>发布日期</th>'
            f"<th>网址</th></tr></thead><tbody>{rows}</tbody></table>")


def appendix(doc: Doc, cfg: Config, forecast_secs: str = "盈利预测与估值章节") -> str:
    run = doc.run
    return f"""
<section class="appendix">
  {doc.h2("附", "财务报表预测")}
  {appendix_statements(run)}
  <div class="src">资料来源：公司公告，FinAgent 预测（基准情景）。经营费用为轧差项，含税金及附加；{run.period}A 净利润为报表值。</div>
  {doc.fig("股权价值桥中的非经营性资产净额（亿元）", T.nonop(run), "类负债项目以负数列示，已在合计中扣减", cls="half")
   if run.non_op.get("items") and not doc.nonop_shown else ""}
  {appendix_notes(run, cfg, forecast_secs)}
</section>
<section class="disclaimer-page">
  <div class="disc-h">免责声明</div>
  {md((KIT / "disclaimer.md").read_text(encoding="utf-8"))}
</section>"""


# ------------------------------------------------------------------ 渲染
def css(cfg: Config, run: Run) -> str:
    name = cfg.report_name or f"{run.period} 年报深度点评"
    return ((KIT / "report.css").read_text(encoding="utf-8")
            .replace("__HEADER__", f"{cfg.company}（{cfg.ticker}）{name}")
            .replace("__KIND__", f"公司研究｜{cfg.kind}"))


def build(run: Run, cfg: Config, S: dict[str, str], body: Callable[[Doc, dict], str], out: Path,
          pages: dict[str, int] | None = None) -> tuple[Path, Doc]:
    ch = out / "charts"
    ch.mkdir(parents=True, exist_ok=True)
    doc = Doc(run, ch)
    head = cover(doc, cfg, S)
    main_html = body(doc, S)
    name = cfg.report_name or f"{run.period} 年报深度点评"
    page = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>{cfg.company}（{cfg.ticker}）{name}</title>
<style>{css(cfg, run)}</style></head><body>
{head}
{toc(doc, pages or {})}
{main_html}
</body></html>"""
    path = out / "report.html"
    path.write_text(page, encoding="utf-8")
    return path, doc


def to_pdf(html_path: Path) -> Path:
    pdf = html_path.with_suffix(".pdf")
    subprocess.run([chrome(), "--headless=new", "--no-pdf-header-footer", f"--print-to-pdf={pdf}",
                    "--virtual-time-budget=10000", html_path.resolve().as_uri()], check=True, capture_output=True)
    return pdf


def preview(pdf: Path) -> list[Path]:
    """逐页 PNG（110dpi）+ 每 8 页一张缩略图总览 sheet*.png；打印嵌入字体，确认没有意外回退。"""
    import logging

    import pdfplumber
    from PIL import Image

    logging.disable(logging.WARNING)
    out = pdf.parent / "preview"
    out.mkdir(exist_ok=True)
    for old in list(out.glob("page*.png")) + list(out.glob("sheet*.png")):
        old.unlink()
    paths = []
    with pdfplumber.open(pdf) as doc:
        for i, page in enumerate(doc.pages, 1):
            p = out / f"page{i:02d}.png"
            page.to_image(resolution=110).save(p)
            paths.append(p)
        fonts = sorted({c["fontname"].split("+")[-1] for pg in doc.pages for c in pg.chars})
    print("嵌入字体：", ", ".join(fonts))
    ims = [Image.open(p) for p in paths]
    w, h = ims[0].size
    W, H = int(w * 0.42), int(h * 0.42)
    for k in range(0, len(ims), 8):
        sheet = Image.new("RGB", (W * 4 + 30, H * 2 + 10), "#888")
        for i, im in enumerate(ims[k:k + 8]):
            sheet.paste(im.resize((W, H)), ((i % 4) * (W + 10), (i // 4) * (H + 10)))
        sheet.save(out / f"sheet{k // 8 + 1}.png")
    return paths


def main(cfg: Config, body: Callable[[Doc, dict], str], argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=f"{cfg.company} 研报：运行产物 → HTML → PDF")
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--narrative", default=str(cfg.narrative))
    ap.add_argument("--no-pdf", action="store_true")
    args = ap.parse_args(argv)
    run = Run(Path(args.run_dir))
    S = load_sections(Path(args.narrative))
    out = run.dir / "report"
    html_path, doc = build(run, cfg, S, body, out)
    print("HTML：", html_path)
    if args.no_pdf:
        return 0
    pages = locate_pages(to_pdf(html_path), doc)  # 第一遍：定位页码
    missing = [k for k, v in pages.items() if v == ""]
    if missing:
        print("目录未定位（检查标题是否被截断或含特殊字符）：", ", ".join(missing))
    html_path, _ = build(run, cfg, S, body, out, pages)
    pdf = to_pdf(html_path)  # 第二遍：回填目录页码
    shots = preview(pdf)
    if cfg.output_name:
        stem, suffix = Path(cfg.output_name).stem, Path(cfg.output_name).suffix or ".pdf"
        named = pdf.with_name(stem + suffix)
        named.write_bytes(pdf.read_bytes())
        print("另存：", named)
    print("PDF：", pdf, f"（{len(shots)} 页，图表 {doc.n} 个，预览与缩略图 {shots[0].parent}）")
    return 0


if __name__ == "__main__":
    sys.exit(0)
