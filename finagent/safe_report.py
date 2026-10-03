"""Render a company report from verified run data and declarative layout JSON.

The model may author prose and select verified extra tables, but never Python or HTML.
This is a content boundary, not an operating-system sandbox for the browser process.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any


SECTIONS = ("thesis", "overview", "performance", "business", "profitability",
            "balance", "cashflow", "forecast", "valuation", "recommendation", "risks")
HEADINGS = ("投资逻辑", "公司概况", "业绩回顾", "经营分析", "盈利能力", "资产负债与现金流",
            "盈利预测", "估值", "投资建议", "风险提示")


def required_basis_keys(seg: dict[str, Any], detail: dict[str, Any]) -> set[str]:
    base = (seg.get("scenarios") or {}).get("base")
    if not base:
        return set()
    keys = {f"{s['name']}{field}" for s in base.get("segments", [])
            for field in ("销量增速", "单价增速", "毛利率")}
    if "selling" in base.get("expense_ratios", {}):
        keys.add("销售费用率")
    keys.add("其他费用率")
    if (detail.get("drivers", {}).get("dividend_payout") or [None])[0] is not None:
        keys.add("现金分红率")
    return keys


def validate_layout(raw: Any, table_ids: set[str] | None = None,
                    basis_keys: set[str] | None = None) -> dict[str, Any]:
    """Reject executable markup, unknown fields, and unverified table references."""
    if not isinstance(raw, dict) or set(raw) != {"sector", "headings", "extra_tables", "assumption_basis", "method_note"}:
        raise ValueError("layout.json 必须且只能含 sector/headings/extra_tables/assumption_basis/method_note")
    sector, headings = raw["sector"], raw["headings"]
    if not isinstance(sector, str) or not 1 <= len(sector) <= 60:
        raise ValueError("sector 须为 1–60 字符")
    if not isinstance(headings, list) or len(headings) != 10:
        raise ValueError("headings 须有 10 个章节标题")
    for index, heading in enumerate(headings):
        if not isinstance(heading, str) or not heading.startswith(HEADINGS[index]) or not 4 <= len(heading) <= 90:
            raise ValueError(f"第 {index + 1} 节标题须以 {HEADINGS[index]} 开头且在 4–90 字符内")
    ids = raw["extra_tables"]
    if not isinstance(ids, list) or len(ids) > 8 or any(not isinstance(x, str) or not x for x in ids):
        raise ValueError("extra_tables 须为最多 8 个非空表 ID")
    if len(ids) != len(set(ids)) or (table_ids is not None and not set(ids) <= table_ids):
        raise ValueError("extra_tables 含重复或未经核验的表 ID")
    if table_ids and not ids:
        raise ValueError("已有核验的经营表，经营分析至少选择一张")
    basis = raw["assumption_basis"]
    if not isinstance(basis, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                           or len(k) > 100 or len(v) > 300 for k, v in basis.items()):
        raise ValueError("assumption_basis 须为短文本映射")
    missing_basis = (basis_keys or set()) - set(basis)
    if missing_basis or any(len(basis[k].strip()) < 8 for k in (basis_keys or set())):
        raise ValueError("关键假设依据缺失或过短：" + ", ".join(sorted(missing_basis)))
    note = raw["method_note"]
    if not isinstance(note, str) or len(note) > 500:
        raise ValueError("method_note 须为不超过 500 字的说明")
    return raw


def _extra_table(run: Any, table_id: str) -> tuple[str, str, str]:
    from reportkit import tables as T

    item = run.tables[table_id]
    columns = item["columns"]
    head = ["项目"] + [str(c["name"]) + (f"（{c['unit']}）" if c.get("unit") else "") for c in columns]
    rows = []
    for row in item["rows"]:
        cells = [str(row["label"])] + ["—" if v is None else f"{v:,.2f}" if isinstance(v, (int, float))
                                             else str(v) for v in row["values"]]
        rows.append(T.tr([html.escape(c) for c in cells]))
    page = item.get("page")
    source = f"年报 PDF 物理第 {page} 页；单位与原表一致" if page else "年报原表；单位与原表一致"
    return str(item["title"]), T.table([html.escape(x) for x in head], rows, "data split"), source


def render(run_dir: Path, narrative: Path, layout_file: Path, meta_file: Path, *, no_pdf: bool = False) -> int:
    ws = meta_file.parent.resolve()
    for path in (run_dir, narrative, layout_file):
        if not path.resolve().is_relative_to(ws):
            raise ValueError("所有输入须位于同一工作区")
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    kit = ws / ".claude/skills/finagent-report"
    sys.path.insert(0, str(kit))
    from reportkit import charts as C, tables as T
    from reportkit.core import Run, load_sections, md, num
    from reportkit.layout import Config, Doc, appendix, equity_bridge, main, two, valuation_ranges

    run = Run(run_dir)
    layout = validate_layout(json.loads(layout_file.read_text(encoding="utf-8")), set(run.tables),
                             required_basis_keys(run.seg, run.detail))
    sections = load_sections(narrative)
    absent = [key for key in SECTIONS if not sections.get(key, "").strip()]
    if absent:
        raise ValueError("文稿章节缺失或为空：" + ", ".join(absent))
    market = run.fs.get("market", {})
    stamp = market.get("price_date") or date.today().isoformat()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", stamp):
        raise ValueError("行情日期格式错误")
    suffix = {"SSE": "SH", "SZSE": "SZ"}.get(meta["exchange"], meta["exchange"])
    cfg = Config(company=meta["company"], ticker=f"{meta['ticker']}.{suffix}",
                 sector=layout["sector"], date=f"{stamp[:4]} 年 {int(stamp[5:7])} 月 {int(stamp[8:])} 日",
                 narrative=narrative, method_note=layout["method_note"],
                 output_name=f"{meta['company']}{stamp.replace('-', '')}.pdf")

    def body(doc: Doc, s: dict[str, str]) -> str:
        r, img, fig = doc.run, doc.img, doc.fig
        h = lambda n: doc.h2(n, layout["headings"][n - 1])  # noqa: E731
        business = "".join(fig(*_extra_table(r, ident)) for ident in layout["extra_tables"])
        q = (two(fig(f"{r.period} 年分季度营业收入与归母净利润（亿元）", img(C.quarterly)),
                 fig(f"{r.period} 年分季度主要财务数据", T.quarterly(r))) if r.quarterly else "")
        cash = (two(fig("资产负债与营运资本", T.balance(r)),
                    fig(f"{r.period} 年分季度经营现金流与归母净利润", img(C.cash_quarterly)))
                if r.quarterly else fig("资产负债与营运资本", T.balance(r)))
        segments = (fig("关键假设与依据", T.assumptions(r, layout["assumption_basis"]), "假设为分析师观点")
                    + fig("分部收入预测", T.segment_forecast(r), "基准情景", cls="split")
                    + two(fig("分部收入预测", img(C.segment_forecast), "基准情景"),
                          fig("利润率与销售费用率", img(C.margins), "基准情景"))) if r.seg else ""
        scenario = (two(fig("折现参数", T.wacc(r), "参数为分析师假设"),
                        fig("三情景营业收入", img(C.scenarios)))
                    + fig("三情景关键驱动与估值", T.scenario_table(r))) if r.seg else fig("折现参数", T.wacc(r))
        return f'''<section class="body">
        {h(1)}{md(s["thesis"])}{fig("营业收入与归母净利润（实际与预测）", img(C.history, 172), "预测为基准情景")}
        {h(2)}{md(s["overview"])}{two(fig("盈利质量：ROE 与净现比", img(C.quality)), fig("近三年主要会计数据与财务指标", T.three_year(r)))}
        {h(3)}{md(s["performance"])}{fig("主要财务指标", T.core(r), cls="split")}{q}
        {h(4)}{md(s["business"])}{business}
        {h(5)}{md(s["profitability"])}{fig(f"归母净利润变动归因（{r.prev} 年至 {r.period} 年，亿元）", img(C.bridge, 172))}
        {h(6)}{md(s["balance"])}{md(s["cashflow"])}{cash}
        {h(7)}{md(s["forecast"])}{segments}{fig("盈利预测", T.forecast(r, last=5), "基准情景")}
        {h(8)}{md(s["valuation"])}{scenario}{fig("FCFF 预测与折现（基准情景）", T.fcff(r))}
        {fig("从企业价值到每股价值", img(C.ev_bridge, 172))}{equity_bridge(doc)}{valuation_ranges(doc)}
        {h(9)}{md(s["recommendation"])}
        {h(10)}{md(s["risks"])}
        </section>{appendix(doc, cfg, "第 7、8 节")}'''

    argv = ["--run-dir", str(run_dir), "--narrative", str(narrative)]
    if no_pdf:
        argv.append("--no-pdf")
    return main(cfg, body, argv)


def main_cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="以声明式布局渲染已核验的 FinAgent 研报")
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--narrative", required=True, type=Path)
    ap.add_argument("--layout", required=True, type=Path)
    ap.add_argument("--no-pdf", action="store_true", help="仅生成 HTML 与图表，用于无浏览器的兼容性测试")
    args = ap.parse_args(argv)
    return render(args.run_dir, args.narrative, args.layout, Path("sample.json"), no_pdf=args.no_pdf)


if __name__ == "__main__":
    sys.exit(main_cli())
