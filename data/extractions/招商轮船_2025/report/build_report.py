"""招商轮船 2025 年报深度点评：读 LEDGER 运行产物 → 图表 → HTML → PDF。

通用部分（读产物、格式化、标准图表、目录、附录、免责声明、打印）在 reportkit（.claude/skills/finagent-report/），
本脚本只写招商轮船专属的经营数据图表（extras.json 的表与比率）与正文编排。数字全部从运行产物读出，
脚本只做单位换算与格式化。

航运收入无法按“运力 × 运价”可靠拆分（年报未披露分船型营运天数与 TCE），估值未使用 segment_forecast，
关键假设表与三情景表由本脚本从三表模型明细（three_statement_detail.json）与 valuation.json 读出。

    .venv/bin/python data/extractions/招商轮船_2025/report/build_report.py --run-dir runs/<run_id>
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / ".claude" / "skills" / "finagent-report"))

from reportkit import charts as C  # noqa: E402
from reportkit import tables as T  # noqa: E402
from reportkit.core import (BRICK, GOLD, INK, LIGHT, NAVY, NAVY2, SLATE, Run, clean, fig_size, legend_below, md, md_parts,  # noqa: E402
                            mm, num, pct, pp, save, subtitle, yi)
from reportkit.layout import Config, Doc, appendix, equity_bridge, main, two, valuation_ranges  # noqa: E402
from reportkit.tables import grp, table, td, tr  # noqa: E402

# (正文简称, 主营业务分行业表行名, 分部报告行名, 管理口径行名)
SEGS = [("油轮", "油轮运输", "油轮运输", "油轮船队"), ("散货", "散货船运输", "散货船运输", "干散货船队"),
        ("集运", "集装箱运输", "集装箱运输", "集装箱船队"), ("滚装", "滚装船运输", "滚装船运输", "滚装船队"),
        ("LNG", "LNG运输", "天然气运输", "LNG船队")]
MIX = {"油轮": "tanker", "散货": "bulk", "集运": "box", "滚装": "roro", "LNG": "lng"}


def side_rows(run: Run) -> list[tuple[str, str]]:
    return [(f"{run.period} 年度每股现金分红（元）", f"{run.ratios['dps']:.2f}"),
            ("控股股东持股", pct(run.cell("holders", "招商局轮船有限公司", "持股比例"), sign=False)),
            ("净有息负债 / 所有者权益", pct(run.ratios["net_debt_to_equity"], sign=False))]


CFG = Config(
    company="招商轮船", ticker="601872.SH", sector="交通运输 · 航运", date="2026 年 9 月 30 日",
    narrative=HERE / "narrative.md", output_name="招商轮船0930.pdf", side_rows=side_rows,
    method_note="航运收入无法按“运力 × 运价”可靠拆分，预测直接设定合并收入增速与毛利率路径，未使用分部量价模型；"
                "营业成本中已含船舶折旧，引擎经营费用轧差项（毛利 − EBIT − 折旧摊销）因此为负值，预测期取剔除资产处置收益后的水平；"
                "引擎折旧摊销仅含固定资产折旧与无形资产摊销，坞修（长期待摊费用）摊销与使用权资产摊销留在轧差项中视同现金成本，"
                "同时租赁负债作为有息负债扣减，二者对租赁存在重复扣减，每股价值偏保守；"
                "长期股权投资（主要为合营企业 CLNG 与安通控股）按账面价值加回，未按市值重估；长期应付款（租赁公司借款）作为类负债扣减；",
)


def g(v, d=2):
    return "—" if v is None else f"{v:+.{d}f}%"


# ================================================================== 经营数据图（extras → 原语）
def ch_mix(run, out):
    names = [n for n, *_ in SEGS[:4]] + ["LNG"]
    return C.grouped(out, "mix", names,
                     [("收入占比", [run.ratios[f"mix_{MIX[n]}"] for n in names]),
                      ("分部净利润占合并净利润", [run.ratios[f"np_share_{MIX[n]}"] for n in names])],
                     colors=[SLATE, NAVY], title="单位：%；分部净利润未扣未分配项目与抵销，合计不等于 100%", ylim=1.25)


def ch_segment(run, out):
    cats = [n for n, *_ in SEGS[:4]]
    return C.panels(out, "segment", [
        ("分船型收入（亿元）与同比", cats, [run.cell("segment", r, "营业收入") / 1e8 for _, r, _, _ in SEGS[:4]],
         [g(run.cell("segment", r, "营业收入同比")) for _, r, _, _ in SEGS[:4]], "{:,.2f}"),
        ("毛利率与同比变动", cats, [run.cell("segment", r, "毛利率") for _, r, _, _ in SEGS[:4]],
         [f"{run.cell('segment', r, '毛利率同比'):+.2f}pp" for _, r, _, _ in SEGS[:4]], "{:.2f}%")], w=172, h=48)


def ch_seg_profit(run, out):
    return C.grouped(out, "seg_profit", [n for n, *_ in SEGS],
                     [("2025 年分部净利润", [run.cell("seg_brief", b, "净利润") / 1e8 for *_, b in SEGS])],
                     notes=[g(run.cell("seg_brief", b, "净利润同比")) for *_, b in SEGS], colors=[NAVY],
                     title="单位：亿元（管理口径）；灰字为同比", ylim=1.3)


def ch_cost(run, out, tid, name, short=None):
    rows = run.rows(tid)
    return C.grouped(out, name, [(short or {}).get(r, r) for r in rows],
                     [(f"{run.period} 年", [run.cell(tid, r, "本期金额") / 1e8 for r in rows])],
                     notes=[g(run.cell(tid, r, "同比")) if run.cell(tid, r, "同比") is not None else "新增" for r in rows],
                     colors=[NAVY], size=6.0, title=f"{run.period} 年金额（亿元）；灰字为同比", ylim=1.3)


def ch_fleet(run, out):
    rows = [("油轮", "油轮小计"), ("气体船", "气体船小计"), ("散货船", "散货船小计"), ("件杂货船", "件杂货船小计"),
            ("滚装船", "滚装船小计"), ("集装箱船", "集装箱船小计")]
    return C.grouped(out, "fleet", [n for n, _ in rows],
                     [("现有运力", [run.cell("fleet", r, "总载重量") for _, r in rows]),
                      ("手持订单", [run.cell("fleet", r, "订单载重量") or 0 for _, r in rows])],
                     notes=[[f"{run.cell('fleet', r, '船舶艘数'):,.0f} 艘" for _, r in rows],
                            [f"{run.cell('fleet', r, '订单艘数'):,.0f} 艘" if run.cell('fleet', r, '订单艘数') else None
                             for _, r in rows]],
                     colors=[NAVY, GOLD], fmt="{:,.0f}", w=172, h=33, title="单位：万载重吨；标注为船舶艘数", ylim=1.3)


def ch_projects(run, out):
    rows = [r for r in run.rows("projects") if r != "合计"]
    return C.hbars(out, "projects", [f"{r}（进度 {run.cell('projects', r, '项目进度'):.2f}%）" for r in rows],
                   [run.cell("projects", r, "累计投入") / 1e8 for r in rows], fmt="{:,.2f}", w=172, h=52,
                   title="新造船项目累计投入（亿元）", highlight_first=False)


def ch_debt(run, out):
    rows = [r for r in run.rows("finliab") if r != "合计"]
    short = {"长期借款（含一年内到期）": "长期借款", "长期应付款（含一年内到期）": "长期应付款", "租赁负债（含一年内到期）": "租赁负债"}
    return C.stacked(out, "debt", [f"{run.prev} 年末", f"{run.period} 年末"],
                     [(short.get(r, r), [run.cell("finliab", r, "期初余额") / 1e8, run.cell("finliab", r, "期末余额") / 1e8])
                      for r in rows],
                     totals=[run.cell("finliab", "合计", "期初余额") / 1e8, run.cell("finliab", "合计", "期末余额") / 1e8],
                     colors=[SLATE, NAVY, GOLD, NAVY2], legend="right", title="筹资性负债构成（亿元，含一年内到期）")


def ch_amort(run, out):
    rows = ["固定资产折旧", "使用权资产摊销", "长期待摊费用摊销"]
    return C.grouped(out, "amort", ["固定资产\n折旧", "使用权资产\n摊销", "坞修等长期\n待摊费用摊销"],
                     [(f"{run.prev} 年", [run.cell("amort", r, "上期") / 1e8 for r in rows]),
                      (f"{run.period} 年", [run.cell("amort", r, "本期") / 1e8 for r in rows])],
                     notes=[g(run.ratios["dep_g"]), g(run.ratios["rou_amort_g"]), None], title="单位：亿元；灰字为同比")


def ch_cashflows(run, out):
    rows = run.rows("cashflow_total")
    return C.signed(out, "cashflows", ["经营活动", "投资活动", "筹资活动"],
                    [(f"{run.prev} 年", [run.cell("cashflow_total", r, "上期") / 1e8 for r in rows]),
                     (f"{run.period} 年", [run.cell("cashflow_total", r, "本期") / 1e8 for r in rows])],
                    title="现金流量净额（亿元）")


def ch_holders(run, out):
    short = {"招商局轮船有限公司": "招商局轮船", "中国石油化工集团有限公司": "中国石化集团",
             "中国诚通控股集团有限公司": "中国诚通", "香港中央结算有限公司": "香港中央结算"}
    rows = run.rows("holders")
    return C.hbars(out, "holders", [short.get(r, r) for r in rows], [run.cell("holders", r, "持股比例") for r in rows],
                   fmt="{:.2f}%", title="期末持股比例")


def ch_subsidiaries(run, out):
    rows = run.rows("subsidiaries")
    short = {"油轮控股（CMES Tanker）": "油轮控股", "散货控股（CMES Bulker）": "散货控股", "LNG投资（CMES LNG）": "LNG投资",
             "中外运集运": "中外运集运", "广州招商滚装": "招商滚装", "上海明华（件杂货）": "上海明华", "CLNG（参股50%）": "CLNG\n(参股)"}
    return C.grouped(out, "subsidiaries", [short.get(r, r) for r in rows],
                     [("营业收入", [run.cell("subsidiaries", r, "营业收入") for r in rows]),
                      ("净利润", [run.cell("subsidiaries", r, "净利润") for r in rows])],
                     colors=[SLATE, NAVY], w=172, h=46, size=5.6, title="单位：亿元", ylim=1.2)


def ch_payout(run, out):
    return C.composition(out, "payout", [
        ("中期现金分红", run.cell("dividend_detail", "中期现金分红", "金额") / 1e8),
        ("年度现金分红", run.cell("dividend_detail", "年度现金分红", "金额") / 1e8),
        ("已回购股份", run.cell("dividend_detail", "已回购股份金额", "金额") / 1e8)],
        note=f"现金分红占归母净利润 {run.cell('payout_pct', '现金分红占归母净利润', '比例'):.2f}%；"
             f"计入回购 {run.cell('payout_pct', '分红和回购占归母净利润', '比例'):.2f}%")


def ch_nonrec(run, out):
    rows = [r for r in run.rows("nonrec") if r != "非经常性损益合计"]
    return C.grouped(out, "nonrec", ["资产处置", "公允价值\n变动", "营业外\n收支", "政府补助"],
                     [(f"{run.prev} 年", [(run.cell("nonrec", r, "2024年") or 0) / 1e8 for r in rows]),
                      (f"{run.period} 年", [run.cell("nonrec", r, "2025年") / 1e8 for r in rows])],
                     title="非经常性损益主要项目（亿元）", ylim=1.25)


def ch_gm_scenarios(run, out):
    """三情景毛利率假设（输入值，不是计算结果）与历史毛利率。"""
    ys = run.fs["years"]
    act = [y for y in ys if y["year"].endswith("A")]
    cats = [y["year"] for y in act] + [p[2:] + "E" for p in run.detail["periods"]]
    fig, ax = fig_size(83, 50)
    style = {"upside": (NAVY, "乐观"), "base": (INK, "基准"), "downside": (BRICK, "悲观")}
    hist = [y["gross_margin"] for y in act]
    for k, (c, n) in style.items():
        vals = hist + [v * 100 for v in run.detail["scenarios"][k]["gross_margin"]]
        ax.plot(cats, vals, color=c, marker="o", ms=2.5, lw=1.1, label=n, ls="-" if k == "base" else (0, (3, 1.5)))
        ax.annotate(f"{vals[-1]:.0f}%", (cats[-1], vals[-1]), xytext=(4, 0), textcoords="offset points", va="center",
                    fontsize=6.2, color=c)
    for x, v in zip(cats[:len(hist)], hist):
        ax.annotate(f"{v:.2f}%", (x, v), xytext=(0, -9), textcoords="offset points", ha="center", fontsize=5.8)
    clean(ax)
    ax.tick_params(axis="x", labelsize=6.2)
    legend_below(ax, ncol=3)
    subtitle(ax, "毛利率：历史与三情景假设（%）")
    return save(fig, out / "gm_scenarios.svg")


def ch_growth_scenarios(run, out):
    """三情景收入增速假设（输入值）。"""
    cats = [p[2:] + "E" for p in run.detail["periods"]]
    series = [(n, [v * 100 for v in run.detail["scenarios"][k]["revenue_growth"]])
              for k, n in (("downside", "悲观"), ("base", "基准"), ("upside", "乐观"))]
    fig, ax = fig_size(83, 50)
    width = 0.24
    for i, ((n, vals), c) in enumerate(zip(series, [BRICK, INK, NAVY])):
        xs = [x - 0.36 + width * (i + 0.5) for x in range(len(cats))]
        bars = ax.bar(xs, vals, width * 0.95, color=c, label=n)
        for b, v in zip(bars, vals):
            ax.annotate(f"{v:.0f}", (b.get_x() + b.get_width() / 2, v), xytext=(0, 1.5 if v >= 0 else -7),
                        textcoords="offset points", ha="center", fontsize=5.4)
    ax.axhline(0, color="#9CA3AF", lw=0.6)
    ax.set_xticks(range(len(cats)), cats, fontsize=6.4)
    clean(ax)
    legend_below(ax, ncol=3)
    subtitle(ax, "营业收入增速：三情景假设（%）")
    return save(fig, out / "growth_scenarios.svg")


# ================================================================== 经营数据表
def tb_quarterly(run):
    qoq = [None, run.ratios["rev_q2_qoq"], run.ratios["rev_q3_qoq"], run.ratios["rev_q4_qoq"]]
    return T.quarterly(run, [
        tr(["营业收入环比"] + [td(pct(v), v) if v is not None else "—" for v in qoq]),
        tr(["归母净利润占全年比例", "—", "—", "—", pct(run.ratios["np_q4_share"], sign=False)])])


def tb_segments(run):
    rows = []
    for n, r, _, _ in SEGS:
        v = [run.cell("segment", r, c) for c in ("营业收入", "营业收入同比", "营业成本同比", "毛利率", "毛利率同比")]
        rows.append(tr([r, yi(v[0]), td(pct(v[1]), v[1]), td(pct(v[2]), v[2]), pct(v[3], sign=False), td(pp(v[4]), v[4]),
                        pct(run.ratios[f"mix_{MIX[n]}"], sign=False)]))
    return table(["主营业务分行业", "收入（亿元）", "收入同比", "成本同比", "毛利率", "毛利率变动", "收入占比"], rows, "data nw")


def tb_seg_pl(run):
    cols = [("对外交易收入", "收入"), ("投资收益", "投资收益"), ("资产处置收益", "资产处置"), ("利润总额", "利润总额"),
            ("净利润", "净利润"), ("折旧和摊销费用", "折旧摊销"), ("资本性支出", "资本性支出")]
    rows = []
    for r in run.rows("seg_pl"):
        vals = [run.cell("seg_pl", r, c) for c, _ in cols]
        vals = [0.0 if v is not None and abs(v) < 5e5 else v for v in vals]  # 不足 0.01 亿元的显示为 0.00
        rows.append(tr([r] + [td(yi(v), v) for v in vals],
                       "sub" if r == "合计" else ""))
    return table(["分部（亿元）"] + [h for _, h in cols], rows, "data nw")


def tb_cost(run, tid):
    rows = []
    for r in run.rows(tid):
        v = [run.cell(tid, r, c) for c in ("本期金额", "本期占比", "上期金额", "同比")]
        rows.append(tr([r, yi(v[0]), pct(v[1], sign=False), yi(v[2]), td(pct(v[3]), v[3]) if v[3] is not None else "—"]))
    return table(["成本项目", f"{run.period}（亿元）", "占成本比", f"{run.prev}（亿元）", "同比"], rows)


def tb_fleet(run):
    rows = []
    for r in run.rows("fleet"):
        v = [run.cell("fleet", r, c) for c in ("船舶艘数", "总载重量", "平均船龄", "订单艘数", "订单载重量")]
        rows.append(tr([r, mm(v[0]), num(v[1]), num(v[2]) if v[2] is not None else "—", mm(v[3]) if v[3] else "—",
                        num(v[4]) if v[4] else "—"], "sub" if r == "自有船总计" else ""))
    rows.append(tr(["订单载重吨 / 自有船队载重吨", "", pct(run.ratios["order_to_fleet"], sign=False), "", "", ""]))
    return table(["船型", "艘数", "载重量（万吨）", "平均船龄（年）", "订单艘数", "订单载重量（万吨）"], rows, "data nw")


def tb_fleet_short(run):
    rows = []
    for r in run.rows("fleet"):
        v = [run.cell("fleet", r, c) for c in ("船舶艘数", "平均船龄", "订单艘数")]
        rows.append(tr([r, mm(v[0]), num(v[1], 1) if v[1] is not None else "—", mm(v[2]) if v[2] else "—"],
                       "sub" if r == "自有船总计" else ""))
    rows.append(tr(["订单载重吨 / 自有载重吨", "", "", pct(run.ratios["order_to_fleet"], sign=False)]))
    return table(["船型", "艘数", "船龄（年）", "订单（艘）"], rows)


def tb_ops(run):
    rows = [tr([r, num(run.cell("volume", r, "货运量"), 0), "—"]) for r in run.rows("volume")]
    for r in run.rows("ops"):
        v, y = run.cell("ops", r, "数值"), run.cell("ops", r, "同比")
        rows.append(tr([r, num(v), td(pct(y, 1), y) if y is not None else "—"]))
    return table(["经营指标", run.period, "同比"], [grp("货运量（万吨）", 3)] + rows[:4] + [grp("集运与滚装", 3)] + rows[4:])


def tb_capex(run):
    r = run.ratios
    rows = [tr(["购建长期资产支付的现金（亿元）", yi(run.v("capex")), yi(run.v("capex", run.prev))]),
            tr(["资本开支 / 营业收入", pct(r["capex_to_rev"], sign=False), "—"]),
            tr(["资本开支 / 经营现金流", pct(r["capex_to_ocf"], sign=False), "—"]),
            tr(["新造船项目本年投入（亿元）", yi(run.cell("projects", "合计", "本年投入")), "—"]),
            tr(["在建工程（亿元）", yi(run.v("construction_in_progress")), yi(run.v("construction_in_progress", run.prev))]),
            tr(["已签约未确认资本性支出（亿元）", yi(run.cell("commit", "购建资产", "年末数")), "—"]),
            tr(["资本承诺 / 当年资本开支（倍）", num(r["commit_to_capex"]), "—"]),
            tr(["资本承诺 / 所有者权益", pct(r["commit_to_equity"], sign=False), "—"]),
            tr(["2026 年预计新造船交付（艘）", mm(run.cell("deliveries_2026", "2026年预计新造船交付合计", "艘数")), "—"])]
    return table(["资本开支与承诺", run.period, run.prev], rows)


def tb_debt(run):
    r = run.ratios
    rows = [tr(["筹资性负债合计（亿元）", yi(run.cell("finliab", "合计", "期末余额")), yi(run.cell("finliab", "合计", "期初余额"))]),
            tr(["净有息负债（亿元）", yi(r["net_debt"]), yi(r["net_debt_prev"])]),
            tr(["净有息负债 / 所有者权益", pct(r["net_debt_to_equity"], sign=False), pct(r["net_debt_to_equity_prev"], sign=False)]),
            tr(["利息费用（亿元）", yi(run.cell("fin_exp", "利息费用", "本期")), yi(run.cell("fin_exp", "利息费用", "上期"))]),
            tr(["利润总额 / 利息费用（倍）", num(r["interest_cover"]), "—"]),
            tr(["资产负债率", pct(run.v("debt_ratio"), sign=False), pct(run.v("debt_ratio", run.prev), sign=False)]),
            tr(["抵押受限固定资产（亿元）", yi(run.cell("pledged", "固定资产（抵押贷款）", "年末账面价值")), "—"]),
            tr(["抵押受限在建工程（亿元）", yi(run.cell("pledged", "在建工程（抵押贷款）", "年末账面价值")), "—"])]
    return table(["负债与偿债能力", f"{run.period} 年末", f"{run.prev} 年末"], rows)


def tb_cf_items(run):
    rows = [tr([r, td(yi(run.cell("cf_items", r, "本期")), run.cell("cf_items", r, "本期")),
                td(yi(run.cell("cf_items", r, "上期")), run.cell("cf_items", r, "上期"))]) for r in run.rows("cf_items")]
    rows.append(tr(["经营现金流 − 资本开支", td(yi(run.ratios["fcf_simple"]), run.ratios["fcf_simple"]),
                    td(yi(run.ratios["fcf_simple_prev"]), run.ratios["fcf_simple_prev"])], "sub"))
    return table(["现金流量项目（亿元）", run.period, run.prev], rows)


def tb_returns(run):
    r = run.ratios
    rows = [tr([f"{run.period} 年度现金分红（亿元）", yi(run.cell("dividend", "现金分红金额", "金额"))]),
            tr(["　其中：中期（亿元）", yi(run.cell("dividend_detail", "中期现金分红", "金额"))]),
            tr(["　　　　年度（亿元）", yi(run.cell("dividend_detail", "年度现金分红", "金额"))]),
            tr(["每 10 股派息（元，含税）", num(run.cell("dps10", "2025年度合计", "每10股派息"), 1)]),
            tr(["现金分红率", pct(run.cell("payout_pct", "现金分红占归母净利润", "比例"), sign=False)]),
            tr(["年度现金分红同比", pct(r["div_g"])]),
            ]
    rows2 = [tr(["已回购股份金额（亿元）", yi(run.cell("dividend_detail", "已回购股份金额", "金额"))]),
            tr(["分红和回购占归母净利润", pct(run.cell("payout_pct", "分红和回购占归母净利润", "比例"), sign=False)]),
            tr(["回购注销股份（股）", mm(run.cell("buyback", "回购注销股份", "数量"))]),
            tr(["回购注销占期初总股本", pct(r["buyback_pct"], sign=False)]),
            tr(["近三年分红与回购 / 年均净利润", pct(run.cell("three_year", "现金分红比例", "比例"), sign=False)])]
    return two(table(["现金分红", run.period], rows), table(["回购与累计回报", run.period], rows2))


def tb_market(run):
    m = run.fs["market"]
    ys = run.years
    rows = [tr(["参考股价（元）", num(m["price"])]), tr(["股价日期", m["price_date"]]),
            tr(["总市值（亿元）", yi(m["market_cap"])]),
            tr([f"P/E（{run.period}A，倍）", num(m["pe_latest"], 1)])]
    rows += [tr([f"P/E（{y}，倍）", num(ys[y]["pe"], 1)]) for y in ys if y.endswith("E")][:3]
    rows += [tr(["P/B（倍）", num(m["pb"])]), tr(["DCF 基准情景每股价值（元）", f"<b>{num(run.scen['base']['value_per_share'])}</b>"])]
    return table(["市场数据与估值", "取值"], rows)


BASIS = {
    "营业收入增速": "2026E 油轮运价高点 + 28 艘新船交付；2027～2028E 地缘溢价消退（第 1、4、5 节）",
    "毛利率": "油轮运价弹性；2029E 起回归周期中枢，略高于 2025A（第 4、6 节）",
    "经营费用率（轧差）": "营业成本含船舶折旧致轧差为负；剔除资产处置收益（第 6 节）",
    "资本开支 / 营业收入": "资本承诺 358.72 亿元集中于 2026～2028 年支付（第 5 节）",
    "折旧率（期初 PP&E）": "取 2025A；新船交付后折旧随 PP&E 增加（第 7 节）",
    "所得税率": "取 2025A 有效税率，境外单船公司为主（第 6 节）",
    "现金分红率": "与 2025 年度一致（第 8 节）",
}


def tb_assumptions(run, years=3):
    d = run.detail
    b = d["scenarios"]["base"]
    ys = " / ".join(p[2:] + "E" for p in d["periods"][:years])
    f = lambda arr, dd=0, sign=True: " / ".join(f"{v * 100:{'+' if sign else ''}.{dd}f}%" for v in arr[:years])  # noqa: E731
    items = [("营业收入增速", f(b["revenue_growth"])), ("毛利率", f(b["gross_margin"], sign=False)),
             ("经营费用率（轧差）", f(b["opex_pct"])), ("资本开支 / 营业收入", f(b["capex_pct_revenue"], sign=False)),
             ("折旧率（期初 PP&E）", f(d["drivers"]["dep_rate"], 2, False)),
             ("所得税率", f"{d['drivers']['tax_rate'] * 100:.2f}%"),
             ("现金分红率", f"{d['drivers']['dividend_payout'][0] * 100:.0f}%")]
    rows = [tr([a, v, f'<td class="basis">{html.escape(BASIS.get(a, ""))}</td>']) for a, v in items]
    return table(["关键假设（基准情景）", ys, "依据"], rows, "data assume")


def tb_scenarios(run):
    cn = {"base": "基准", "downside": "悲观", "upside": "乐观"}
    y = run.detail["periods"][0][2:] + "E"
    rows = []
    for k in ("downside", "base", "upside"):
        sc, s = run.detail["scenarios"][k], run.scen[k]
        rows.append(tr([cn[k], td(pct(sc["revenue_growth"][0] * 100, 0), sc["revenue_growth"][0]),
                        pct(sc["gross_margin"][0] * 100, 0, sign=False), pct(sc["gross_margin"][-1] * 100, 0, sign=False),
                        f"{s['wacc'] * 100:.2f}%", f"{s['terminal_growth'] * 100:.1f}%", f"{s['enterprise_value_mm'] / 100:,.0f}",
                        f"<b>{num(s['value_per_share'])}</b>", td(f"{s['upside_vs_price'] * 100:+.1f}%", s["upside_vs_price"]),
                        f"{s['tv_percent_ev'] * 100:.1f}%"], "base" if k == "base" else ""))
    head = ["情景", f"收入增速（{y}）", f"毛利率（{y}）", "终期毛利率", "WACC", "永续增长", "企业价值（亿元）", "每股价值（元）",
            "较参考股价", "终值占比"]
    return table(head, rows, "data nw")


# ================================================================== 正文编排
def body(doc: Doc, S: dict[str, str]) -> str:
    run, img, fig = doc.run, doc.img, doc.fig
    I = lambda fn, w=83, *a: img(fn(run, doc.ch, *a), w)  # noqa: E731,E741
    p, q = run.period, run.prev
    thesis, overview, perf = md_parts(S["thesis"]), md_parts(S["overview"]), md_parts(S["performance"])
    segs, fleet, prof = md_parts(S["segments"]), md_parts(S["fleet"]), md_parts(S["profitability"])
    bal, cash, fc, val = md_parts(S["balance"]), md_parts(S["cashflow"]), md_parts(S["forecast"]), md_parts(S["valuation"])
    return f"""
<section class="body">
  {doc.h2(1, "投资逻辑：油轮景气推升业绩，估值已透支中枢盈利")}
  {thesis[0]}
  {fig(f"{run.prev2}A～{int(p) + 5}E 营业收入与归母净利润", img(C.history, 172), "预测为基准情景")}
  {thesis[1]}

  {doc.h2(2, "公司概况：油散双核，招商局控股的全船型航运平台")}
  {overview[0]}
  {two(fig("各船型收入占比与分部净利润占比", I(ch_mix)), fig("前四大股东持股比例", I(ch_holders)))}
  {overview[1]}
  {two(fig("盈利质量：ROE 与净现比", img(C.quality)), fig("近三年主要会计数据与财务指标", T.three_year(run)))}
  {overview[2]}
  <h3>行业环境：细分市场分化，VLCC 领涨</h3>
  {md(S["industry"])}
  {fig("主要控股参股公司营业收入与净利润", I(ch_subsidiaries, 172))}

  {doc.h2(3, "业绩回顾：收入稳增、扣非持平，四季度利润近半")}
  {perf[0]}
  {fig("主要财务指标", T.core(run), cls="split")}
  {two(fig("非经常性损益主要项目", I(ch_nonrec)), fig(f"{p} 年分季度营业收入与归母净利润（亿元）", img(C.quarterly)))}
  {perf[1]}
  {fig(f"{p} 年分季度主要财务数据", tb_quarterly(run))}

  {doc.h2(4, "分船型：油轮量价齐升，散货与集运以量补价")}
  {segs[0]}
  {fig("分船型收入与毛利率", I(ch_segment, 172))}
  {fig("主营业务分行业", tb_segments(run), "毛利率变动单位为百分点")}
  {segs[1]}
  {two(fig("油轮运输成本构成（亿元）", I(ch_cost, 83, "cost_tanker", "cost_tanker", {"坞修、航修": "坞修\n航修"})),
       fig("散货船运输成本构成（亿元）", I(ch_cost, 83, "cost_bulk", "cost_bulk")))}
  {segs[2]}
  {two(fig("集装箱运输成本构成（亿元）", I(ch_cost, 83, "cost_box", "cost_box")),
       fig("各分部净利润与同比（亿元）", I(ch_seg_profit)))}
  {segs[3]}
  {fig("分部报告：收入、利润、折旧与资本性支出", tb_seg_pl(run), "未分配项目含件杂货运输及对子公司的投资收益（合并时抵销）", cls="split")}
  {fig("船队经营指标", tb_ops(run))}

  {doc.h2(5, "船队与资本开支：订单占运力两成，LNG 船队规模将翻倍")}
  {fleet[0]}
  {fig("现有运力与手持订单（万载重吨）", I(ch_fleet, 172))}
  {fleet[1]}
  {fig("主要新造船项目累计投入与进度", I(ch_projects, 172))}
  {two(fig("资本开支与资本承诺", tb_capex(run)), fig("报告期末船队概况", tb_fleet_short(run)))}

  {doc.h2(6, "盈利能力：燃油降、租金与折旧升，卖船收益抬高利润")}
  {prof[0]}
  {two(fig("折旧与摊销（亿元）", I(ch_amort)), fig("毛利率与归母净利率（实际与预测）", img(C.margins), "预测为基准情景"))}
  {prof[1]}
  {prof[2]}
  {fig(f"归母净利润变动归因（{q} 年至 {p} 年，亿元）", img(C.bridge, 172),
       "收入规模效应 = Δ营业收入 × 上年毛利率；毛利率效应 = 本年营业收入 × Δ毛利率")}

  {doc.h2(7, "资产负债与现金流：净负债上行，现金流覆盖资本开支但余量有限")}
  {bal[0]}
  {fig("资产负债与营运资本", T.balance(run), cls="split")}
  {bal[1]}
  {two(fig("筹资性负债构成", I(ch_debt)), fig("负债与偿债能力", tb_debt(run)))}
  {cash[0]}
  {two(fig("三类现金流量净额（亿元）", I(ch_cashflows)), fig(f"{p} 年分季度经营现金流与归母净利润", img(C.cash_quarterly)))}
  {fig("投资与筹资主要现金流", tb_cf_items(run))}

  {doc.h2(8, "股东回报：分红率 43%，回购注销常态化")}
  {md(S["return"])}
  {fig(f"{p} 年度现金股东回报构成（亿元）", I(ch_payout, 172))}
  {fig("股东回报指标", tb_returns(run))}

  {doc.h2(9, "盈利预测：2026 年见顶，2027～2028 年回落至周期中枢")}
  {fc[0]}
  {fig("关键假设与依据", tb_assumptions(run), "假设为分析师观点；未使用分部量价模型")}
  {two(fig("营业收入增速假设", I(ch_growth_scenarios)), fig("毛利率假设", I(ch_gm_scenarios)))}
  {fc[1]}
  {fig("盈利预测", T.forecast(run, last=5), "基准情景")}

  {doc.h2(10, f"估值：DCF 基准情景每股价值 {num(run.scen['base']['value_per_share'])} 元")}
  {val[0]}
  {two(fig("折现参数", T.wacc(run), "参数为分析师假设"), fig("参考股价对应的估值水平", tb_market(run), "股价为外部行情数据"))}
  {fig("FCFF 预测与折现（基准情景）", T.fcff(run))}
  {fig("从企业价值到每股价值", img(C.ev_bridge, 172))}
  {equity_bridge(doc)}
  {val[1]}
  {fig("三情景关键驱动与估值", tb_scenarios(run))}
  {valuation_ranges(doc)}

  {doc.h2(11, "投资建议")}
  {md(S["recommendation"])}

  {doc.h2(12, "风险提示")}
  {md(S["risks"])}
</section>
{appendix(doc, CFG, "第 9、10 节")}"""


if __name__ == "__main__":
    sys.exit(main(CFG, body))
