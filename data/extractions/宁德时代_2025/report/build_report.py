"""宁德时代 2025 年报深度点评：读 LEDGER 运行产物 → 图表 → HTML → PDF。

通用部分（读产物、格式化、标准图表、目录、附录、免责声明、打印）在 reportkit（.claude/skills/finagent-report/），
本脚本只写宁德时代专属的经营数据图表（extras.json 的表与比率）和正文编排。数字全部从运行产物读出，
脚本只做单位换算（千元已由程序换算为元；元 → 亿元）与格式化。分析框架见同目录 framework.md。

    .venv/bin/python data/extractions/宁德时代_2025/report/build_report.py --run-dir runs/<run_id>
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / ".claude" / "skills" / "finagent-report").exists())
sys.path.insert(0, str(ROOT / ".claude" / "skills" / "finagent-report"))

from reportkit import charts as C  # noqa: E402
from reportkit import tables as T  # noqa: E402
from reportkit.core import BRICK, GOLD, LIGHT, NAVY, NAVY2, SLATE, Run, md, md_parts, mm, num, pct, pp, yi  # noqa: E402
from reportkit.layout import Config, Doc, appendix, equity_bridge, main, two, valuation_ranges  # noqa: E402
from reportkit.tables import grp, table, td, tr  # noqa: E402

SEGS = [("动力电池", "动力电池系统"), ("储能电池", "储能电池系统")]  # (正文名, extras 行名)
PRODUCTS = ["动力电池系统", "储能电池系统", "电池材料及回收", "电池矿产资源"]


def side_rows(run: Run) -> list[tuple[str, str]]:
    return [(f"{run.period} 年度每 10 股派息（元）", f"{run.cell('dps10', '2025年度', '每10股派息'):.2f}"),
            ("第一大股东持股", pct(run.cell("holders", "厦门瑞庭投资有限公司", "持股比例"), sign=False))]


CFG = Config(
    company="宁德时代", ticker="300750.SZ", sector="电力设备 · 锂电池", date="2026 年 9 月 30 日",
    narrative=HERE / "narrative.md", output_name="宁德时代0930.pdf", side_rows=side_rows,
    method_note="其他收益（含政府补助）与减值留在 EBIT 中；交易性金融资产、长期股权投资、其他权益工具投资与其他非流动金融资产"
                "按账面价值加回，货币资金全额加回（含受限资金）；预计负债（售后综合服务费、销售返利）视为经营性负债，不作债务扣减；"
                "营运资本不含应付票据与合同负债；预测期净利润不含投资收益与公允价值变动收益，净利息收入按 2025 年财务费用与有息负债之比滚动；"
                "电池材料及回收、电池矿产资源与其他业务预测期保持 2025 年金额；分部预测表单价单位为万元/GWh；",
)


def g(v, d=2):  # 同比标注
    return f"{v:+.{d}f}%"


# ================================================================== 经营数据图（extras → 原语）
def ch_mix(run, out):
    rows = ["动力电池系统", "储能电池系统", "电池材料及回收", "电池矿产资源", "其他业务"]
    return C.donuts(out, "mix", [(f"{run.prev} 年", [run.cell("revenue_mix", r, "上期占比") for r in rows]),
                                 (f"{run.period} 年", [run.cell("revenue_mix", r, "本期占比") for r in rows])],
                    ["动力", "储能", "材料回收", "矿产", "其他"])


def ch_holders(run, out):
    short = {"厦门瑞庭投资有限公司": "厦门瑞庭", "香港中央结算有限公司": "香港中央结算",
             "宁波联合创新新能源投资管理合伙企业（有限合伙）": "宁波联合创新", "HKSCC NOMINEES LIMITED": "H 股登记代理"}
    rows = run.rows("holders")
    return C.hbars(out, "holders", [short.get(r, r) for r in rows], [run.cell("holders", r, "持股比例") for r in rows],
                   fmt="{:.2f}%", title="期末持股比例", h=44)


def ch_employees(run, out):
    rows = [r for r in run.rows("employees") if r != "员工合计"]
    return C.hbars(out, "employees", rows, [run.cell("employees", r, "人数") for r in rows],
                   title=f"期末在职员工 {run.cell('employees', '员工合计', '人数'):,.0f} 人")


def ch_industry(run, out):
    rows = run.rows("industry")
    short = {"全球动力电池使用量": "全球动力电池\n使用量", "全球储能电池出货量": "全球储能电池\n出货量",
             "我国新型储能新增装机规模": "我国新型储能\n新增装机"}
    return C.grouped(out, "industry", [short[r] for r in rows], [("2025 年", [run.cell("industry", r, "数量") for r in rows])],
                     notes=[f"同比 {g(run.cell('industry', r, '同比'), 1)}" for r in rows], colors=[NAVY],
                     fmt="{:,.1f}", title="单位：GWh（公司引用第三方统计）", ylim=1.3)


def ch_share(run, out):
    rows = run.rows("market_share")
    short = {"全球动力电池使用量": "全球动力电池", "国内动力电池装机量": "国内动力电池", "海外动力电池使用量": "海外动力电池"}
    return C.hbars(out, "market_share", [short[r] for r in rows], [run.cell("market_share", r, "市占率") for r in rows],
                   fmt="{:.2f}%", title="公司 2025 年市占率（公司引用第三方统计）", h=36)


def ch_product(run, out):
    cats = ["动力", "储能", "材料回收", "矿产"]
    return C.grouped(out, "product", cats, [("2025 年毛利率", [run.cell("product", r, "毛利率") for r in PRODUCTS])],
                     notes=[f"{run.cell('product', r, '毛利率同比'):+.2f}pp" for r in PRODUCTS], colors=[NAVY],
                     fmt="{:.2f}%", title="毛利率（%）；灰字为同比变动", ylim=1.35, h=38)


def ch_rev_pair(run, out):
    rows = ["动力电池系统", "储能电池系统", "电池材料及回收", "电池矿产资源", "其他业务"]
    short = {"动力电池系统": "动力", "储能电池系统": "储能", "电池材料及回收": "材料\n回收", "电池矿产资源": "矿产",
             "其他业务": "其他\n业务"}
    return C.grouped(out, "rev_pair", [short[r] for r in rows],
                     [(f"{run.prev} 年", [run.cell("revenue_mix", r, "上期") / 1e8 for r in rows]),
                      (f"{run.period} 年", [run.cell("revenue_mix", r, "本期") / 1e8 for r in rows])],
                     notes=[g(run.cell("revenue_mix", r, "同比")) for r in rows], fmt="{:,.0f}",
                     title="单位：亿元；灰字为同比", size=5.6, h=38)


def ch_volume(run, out):
    cats = [n for n, _ in SEGS]
    return C.grouped(out, "volume", cats, [("2025 年销量", [run.cell("volume", r, "销量") for _, r in SEGS])],
                     notes=[f"同比 {g(run.cell('volume', r, '销量同比'))}" for _, r in SEGS], colors=[NAVY],
                     fmt="{:,.0f}", title="单位：GWh", ylim=1.3, h=38)


def ch_unit(run, out):
    return C.grouped(out, "unit_economics", [n for n, _ in SEGS],
                     [("单位售价", [run.ratios["price_power"], run.ratios["price_ess"]]),
                      ("单位成本", [run.ratios["unitcost_power"], run.ratios["unitcost_ess"]])],
                     colors=[NAVY, GOLD], fmt="{:.3f}", title="单位：元/Wh", ylim=1.25, h=38)


def ch_price(run, out):
    r = run.ratios
    return C.grouped(out, "price_batt", ["电池系统平均单位售价"],
                     [(f"{run.prev} 年", [r["price_batt_prev"]]), (f"{run.period} 年", [r["price_batt"]])],
                     notes=[g(r["price_batt_g"])], fmt="{:.3f}", title="单位：元/Wh；标注为同比", ylim=1.3, h=38)


def ch_capacity(run, out):
    c = lambda col: run.cell("capacity", "电池系统", col)  # noqa: E731
    return C.grouped(out, "capacity", ["产能", "产量", "销量", "在建产能"],
                     [("2025 年", [c("产能"), c("产量"), run.cell("psi", "销售量", "本期"), c("在建产能")])],
                     notes=[f"利用率 {c('产能利用率'):.1f}%", None, None, None], note_color=NAVY, colors=[NAVY],
                     fmt="{:,.0f}", title="单位：GWh", ylim=1.3, h=38)


def ch_psi(run, out):
    rows = run.rows("psi")
    return C.grouped(out, "psi", rows,
                     [(f"{run.prev} 年", [run.cell("psi", r, "上期") for r in rows]),
                      (f"{run.period} 年", [run.cell("psi", r, "本期") for r in rows])],
                     notes=[g(run.cell("psi", r, "同比")) for r in rows], fmt="{:,.0f}", title="电池系统产销存（GWh）；灰字为同比")


def ch_projects(run, out):
    short = {"宜昌邦普一体化电池材料产业园": "宜昌邦普材料产业园", "印度尼西亚动力电池产业链": "印尼动力电池产业链",
             "山东时代新能源电池产业基地": "山东（济宁）电池基地", "中州时代新能源电池生产基地": "中州（洛阳）电池基地",
             "匈牙利时代新能源电池产业基地": "匈牙利电池基地"}
    rows = run.rows("projects")
    return C.grouped(out, "projects", [short[r].replace("电池", "\n电池", 1) if len(short[r]) > 7 else short[r] for r in rows],
                     [("本期投入", [run.cell("projects", r, "本期投入") / 1e8 for r in rows]),
                      ("累计投入", [run.cell("projects", r, "累计投入") / 1e8 for r in rows])],
                     colors=[GOLD, NAVY], title="单位：亿元", w=172, h=40, size=6.2)


def ch_region(run, out):
    rows = ["境内", "境外"]
    return C.grouped(out, "region", rows,
                     [(f"{run.prev} 年", [run.cell("revenue_mix", r, "上期") / 1e8 for r in rows]),
                      (f"{run.period} 年", [run.cell("revenue_mix", r, "本期") / 1e8 for r in rows])],
                     notes=[g(run.cell("revenue_mix", r, "同比")) for r in rows], fmt="{:,.0f}",
                     title="单位：亿元；灰字为同比", h=38)


def ch_region_gm(run, out):
    rows = ["境内", "境外"]
    return C.grouped(out, "region_gm", rows, [("毛利率", [run.cell("region", r, "毛利率") for r in rows])],
                     notes=[f"{run.cell('region', r, '毛利率同比'):+.2f}pp" for r in rows], colors=[NAVY],
                     fmt="{:.2f}%", title="2025 年毛利率（%）；灰字为同比变动", ylim=1.35, h=38)


def ch_gm_layers(run, out):
    r = run.ratios
    cats = ["综合毛利率", "主营业务", "其他业务"]
    return C.grouped(out, "gm_layers", cats,
                     [(f"{run.prev} 年", [run.v("gross_margin", run.prev), r["main_gm_prev"], r["oth_gm_prev"]]),
                      (f"{run.period} 年", [run.v("gross_margin"), r["main_gm"], r["oth_gm"]])],
                     fmt="{:.2f}", title="毛利率（%）", ylim=1.2, h=40)


def ch_expense_ratios(run, out):
    items = [("销售费用率", "selling_ratio"), ("管理费用率", "admin_ratio"), ("研发费用率", "rd_ratio")]
    return C.grouped(out, "expense_ratios", [n for n, _ in items],
                     [(f"{run.prev} 年", [run.v(k, run.prev) for _, k in items]),
                      (f"{run.period} 年", [run.v(k) for _, k in items])],
                     fmt="{:.2f}", title="占营业收入比例（%）", ylim=1.25, h=40)


def ch_rd(run, out):
    rows = [r for r in run.rows("rd_detail") if r != "研发费用合计"]
    ids = {"职工薪酬": "rd_pay_g", "材料费": "rd_mat_g"}
    return C.grouped(out, "rd", rows, [(f"{run.prev} 年", [run.cell("rd_detail", r, "上期") / 1e8 for r in rows]),
                                       (f"{run.period} 年", [run.cell("rd_detail", r, "本期") / 1e8 for r in rows])],
                     notes=[g(run.ratios[ids[r]]) if r in ids else None for r in rows], title="研发费用明细（亿元）；灰字为同比", h=40)


def ch_nonop(run, out):
    items = [("其他收益", lambda c: run.cell("other_gains", "其他收益", c)),
             ("投资收益", lambda c: run.cell("other_gains", "投资收益合计", c)),
             ("资产减值\n损失", lambda c: run.cell("impairment", "资产减值损失合计", c))]
    cats = [n for n, _ in items] + ["财务费用\n（负为净收益）"]
    return C.signed(out, "nonop", cats,
                    [(f"{run.prev} 年", [f("上期") / 1e8 for _, f in items] + [run.v("finance_expense", run.prev) / 1e8]),
                     (f"{run.period} 年", [f("本期") / 1e8 for _, f in items] + [run.v("finance_expense") / 1e8])],
                    title="非主业损益项目（亿元）")


def ch_assets(run, out):
    rows = ["货币资金", "交易性金融资产", "存货", "长期股权投资", "固定资产"]
    short = {"货币资金": "货币\n资金", "交易性金融资产": "交易性\n金融资产", "长期股权投资": "长期股权\n投资",
             "固定资产": "固定\n资产"}
    return C.grouped(out, "assets", [short.get(r, r) for r in rows],
                     [(f"{run.prev} 年末", [run.cell("assets", r, "期初占总资产") for r in rows]),
                      (f"{run.period} 年末", [run.cell("assets", r, "期末占总资产") for r in rows])],
                     size=5.4, title="占总资产比例（%）", ylim=1.2)


def ch_inventory(run, out):
    rows = ["发出商品", "库存商品", "自制半成品", "原材料", "合同履约成本", "委托加工物资"]
    return C.stacked(out, "inventory", [f"{run.prev} 年末", f"{run.period} 年末"],
                     [(r, [run.cell("inventory_detail", r, "期初") / 1e8, run.cell("inventory_detail", r, "期末") / 1e8])
                      for r in rows],
                     totals=[run.cell("inventory_detail", "存货合计", "期初") / 1e8,
                             run.cell("inventory_detail", "存货合计", "期末") / 1e8],
                     colors=[NAVY, BRICK, SLATE, GOLD, NAVY2, LIGHT], legend="right", title="存货账面价值构成（亿元）")


def ch_wc(run, out):
    rows = ["应付票据", "应付账款", "合同负债", "预计负债"]
    return C.grouped(out, "wc", rows, [(f"{run.prev} 年末", [run.cell("wc", r, "期初") / 1e8 for r in rows]),
                                       (f"{run.period} 年末", [run.cell("wc", r, "期末") / 1e8 for r in rows])],
                     notes=[g(run.ratios["bills_g"]), g(run.ratios["ap_g"]), g(run.ratios["contract_g"]), None],
                     fmt="{:,.0f}", title="经营性负债（亿元）；灰字为同比", size=5.6, h=36)


def ch_cashflows(run, out):
    rows = run.rows("cashflow_total")
    return C.signed(out, "cashflows", ["经营活动", "投资活动", "筹资活动"],
                    [(f"{run.prev} 年", [run.cell("cashflow_total", r, "上期") / 1e8 for r in rows]),
                     (f"{run.period} 年", [run.cell("cashflow_total", r, "本期") / 1e8 for r in rows])],
                    title="现金流量净额（亿元）")


def ch_payout(run, out):
    return C.composition(out, "payout", [
        ("中期现金分红", run.cell("dividend", "中期现金分红", "金额") / 1e8),
        ("年度现金分红", run.cell("dividend", "年度现金分红", "金额") / 1e8),
        ("回购计入现金分红", run.cell("dividend", "回购计入现金分红", "金额") / 1e8)],
        note=f"合计 {run.cell('dividend', '现金分红总额（含其他方式）', '金额') / 1e8:,.2f} 亿元，占归母净利润 "
             f"{run.ratios['payout_all']:.2f}%")


def ch_dps(run, out):
    rows = run.rows("dps10")
    short = {"2024年特别分红": "2024 特别", "2024年度": "2024 年度", "2025年中期": "2025 中期", "2025年度": "2025 年度"}
    return C.grouped(out, "dps", [short[r] for r in rows], [("每 10 股派息", [run.cell("dps10", r, "每10股派息") for r in rows])],
                     colors=[NAVY], title="单位：元（含税）", ylim=1.2)


# ================================================================== 经营数据表
def tb_quarterly(run):
    r = run.ratios
    qoq = [None, r["q2_rev_qoq"], r["q3_rev_qoq"], r["q4_rev_qoq"]]
    return T.quarterly(run, [
        tr(["营业收入环比"] + [td(pct(v), v) if v is not None else "—" for v in qoq]),
        tr(["收入占全年比例", pct(r["q1_rev_share"], sign=False), "—", "—", pct(r["q4_rev_share"], sign=False)])])


def tb_volume(run):
    r = run.ratios
    rows = []
    for (label, key), (pid, cid) in zip(SEGS, [("price_power", "unitcost_power"), ("price_ess", "unitcost_ess")]):
        rows.append(tr([label, mm(run.cell("volume", key, "销量")), td(pct(run.cell("volume", key, "销量同比")), 1),
                        yi(run.cell("product", key, "营业收入")), td(pct(run.cell("product", key, "营业收入同比")), 1),
                        f"{r[pid]:.3f}", f"{r[cid]:.3f}", pct(run.cell("product", key, "毛利率"), sign=False)]))
    rows.append(tr(["电池系统合计", mm(run.cell("psi", "销售量", "本期")), td(pct(run.cell("psi", "销售量", "同比")), 1),
                    yi(r["batt_rev"]), td(pct(r["batt_rev_g"]), r["batt_rev_g"]), f"{r['price_batt']:.3f}", "—", "—"], "sub"))
    rows.append(tr([f"电池系统合计（{run.prev}）", mm(run.cell("psi", "销售量", "上期")), "—", yi(r["batt_rev_prev"]), "—",
                    f"{r['price_batt_prev']:.3f}", "—", "—"]))
    return table(["产品", "销量（GWh）", "同比", "收入（亿元）", "同比", "单位售价（元/Wh）", "单位成本（元/Wh）", "毛利率"],
                 rows, "data nw")


def tb_segments(run):
    blocks = [("按产品", "product", [(p, p) for p in PRODUCTS]), ("按地区", "region", [("境内", "境内"), ("境外", "境外")])]
    rows = []
    for title, tid, items in blocks:
        rows.append(grp(title, 6))
        for key, label in items:
            v = [run.cell(tid, key, c) for c in ("营业收入", "营业收入同比", "营业成本同比", "毛利率", "毛利率同比")]
            rows.append(tr([label, yi(v[0]), td(pct(v[1]), v[1]), td(pct(v[2]), v[2]), pct(v[3], sign=False),
                            td(pp(v[4]), v[4])]))
    return table(["主营业务", "收入（亿元）", "收入同比", "成本同比", "毛利率", "毛利率变动"], rows)


def tb_psi(run):
    r = run.ratios
    c = lambda col: run.cell("capacity", "电池系统", col)  # noqa: E731
    rows = [tr(["产能（GWh）", mm(c("产能")), "—"]),
            tr(["在建产能（GWh）", mm(c("在建产能")), "—"]),
            tr(["在建产能 / 现有产能", pct(r["capacity_under_pct"], sign=False), "—"]),
            tr(["产能利用率", pct(c("产能利用率"), 1, sign=False), "—"]),
            tr(["产销率（销量 / 产量）", pct(r["prod_to_sales"], sign=False), pct(r["prod_to_sales_prev"], sign=False)]),
            tr(["库存量 / 销量", pct(r["stock_to_sales"], sign=False), pct(r["stock_to_sales_prev"], sign=False)])]
    return table(["产能与库存", run.period, run.prev], rows)


def tb_cost(run):
    r = run.ratios
    v = [run.cell("cost", "直接材料", k) for k in ("本期", "本期占比", "上期", "上期占比")]
    rows = [tr(["直接材料（亿元）", yi(v[0]), yi(v[2]), td(pct(r["material_g"]), r["material_g"])]),
            tr(["直接材料占主营成本比例", pct(v[1], sign=False), pct(v[3], sign=False), td(pp(r["share_material"]), r["share_material"])]),
            tr(["主营业务毛利率", pct(r["main_gm"], sign=False), pct(r["main_gm_prev"], sign=False), td(pp(r["main_gm_chg"]), r["main_gm_chg"])]),
            tr(["其他业务毛利率", pct(r["oth_gm"], sign=False), pct(r["oth_gm_prev"], sign=False), "—"]),
            tr(["电池系统平均单位售价（元/Wh）", f"{r['price_batt']:.3f}", f"{r['price_batt_prev']:.3f}",
                td(pct(r["price_batt_g"]), r["price_batt_g"])])]
    return table(["成本与毛利率", run.period, run.prev, "变动"], rows)


def tb_two_period(run, tbl, head, total, cur="本期", prev="上期", extra=None):
    rows = [tr([r, td(yi(run.cell(tbl, r, cur)), run.cell(tbl, r, cur)), td(yi(run.cell(tbl, r, prev)), run.cell(tbl, r, prev))],
               "sub" if r == total else "") for r in run.rows(tbl)]
    return table([head, run.period, run.prev], rows + (extra or []))


def tb_inventory(run):
    r = run.ratios
    c = lambda row, col: run.cell("inventory_detail", row, col)  # noqa: E731
    rows = [tr(["存货合计（亿元）", yi(c("存货合计", "期末")), yi(c("存货合计", "期初")), td(pct(r["inv_g"]), r["inv_g"])]),
            tr(["发出商品（亿元）", yi(c("发出商品", "期末")), yi(c("发出商品", "期初")), td(pct(r["inv_ship_g"]), r["inv_ship_g"])]),
            tr(["库存商品（亿元）", yi(c("库存商品", "期末")), yi(c("库存商品", "期初")), td(pct(r["inv_fg_g"]), r["inv_fg_g"])]),
            tr(["发出商品占存货比例", pct(r["inv_ship_share"], sign=False), "—", "—"]),
            tr(["库存商品占存货比例", pct(r["inv_fg_share"], sign=False), "—", "—"]),
            tr(["存货跌价准备（亿元）", yi(run.cell("inventory_reserve", "存货跌价准备合计", "期末")),
                yi(run.cell("inventory_reserve", "存货跌价准备合计", "期初")), "—"])]
    return table(["存货", f"{run.period} 年末", f"{run.prev} 年末", "同比"], rows)


def tb_nonop(run):
    r = run.ratios
    return table(["非主业损益", run.period, "说明"], [
        tr(["其他收益占利润总额", pct(r["other_inc_rate"], sign=False), "含政府补助等"]),
        tr(["投资收益占利润总额", pct(r["inv_inc_rate"], sign=False), "主要为联营合营企业"]),
        tr(["联营合营企业投资收益同比", pct(r["equity_inc_g"]), "权益法核算"]),
        tr(["资产减值损失占利润总额", pct(r["impair_rate"]), "以存货跌价为主"]),
        tr(["存货跌价损失同比", pct(r["inv_impair_g"]), "—"]),
        tr(["非经常性损益占归母净利润", pct(r["nr_share"], sign=False), "—"])])


def tb_provisions(run):
    r = run.ratios
    extra = [tr(["售后综合服务费同比", pct(r["warranty_g"]), "—"]),
             tr(["售后综合服务费 / 营业收入", pct(r["warranty_to_rev"], sign=False), "—"]),
             tr(["合同负债 / 营业收入", pct(r["contract_to_rev"], sign=False), pct(r["contract_to_rev_prev"], sign=False)])]
    return tb_two_period(run, "provisions", "预计负债（亿元）", "预计负债合计", "期末", "期初", extra)


def tb_cash_items(run):
    r = run.ratios
    extra = [tr(["经营现金流 − 资本开支", yi(r["fcf_simple"]), yi(r["fcf_simple_prev"])]),
             tr(["资本开支 / 营业收入", pct(r["capex_to_rev"], sign=False), "—"]),
             tr(["资本开支 / 固定资产折旧（倍）", num(r["capex_to_da"]), "—"])]
    return tb_two_period(run, "cashflow_items", "现金流量项目（亿元）", "", extra=extra)


def tb_returns(run):
    r = run.ratios
    d = lambda k: run.cell("dividend", k, "金额")  # noqa: E731
    rows = [tr(["按归母净利润 50% 确定的分配额（亿元）", yi(d("按归母净利润50%确定的分配额"))]),
            tr(["　其中：中期分红（亿元）", yi(d("中期现金分红"))]),
            tr(["　　　　年度分红（亿元）", yi(d("年度现金分红"))]),
            tr(["年度现金分红率", pct(r["payout"], sign=False)]),
            tr(["回购计入现金分红（亿元）", yi(d("回购计入现金分红"))]),
            tr(["现金分红总额（含回购，亿元）", yi(d("现金分红总额（含其他方式）"))]),
            tr(["含回购分红占归母净利润", pct(r["payout_all"], sign=False)]),
            tr(["2025 年度每 10 股派息（元）", num(run.cell("dps10", "2025年度", "每10股派息"))])]
    return table(["股东回报", run.period], rows)


BASIS = {  # 关键假设的依据，写明对应正文第几节
    "动力电池销量增速": "利用率 96.9%、在建产能 321 GWh，全球份额提升，海外定点落地（第 4、5 节）",
    "动力电池单价增速": "原材料价格下行传导接近尾声，降幅收窄（第 4 节）",
    "动力电池毛利率": "单位毛利稳定；2026 年价格竞争小幅压低（第 4、6 节）",
    "储能电池销量增速": "全球储能需求高增长、系统集成放量（第 2、4 节）",
    "储能电池单价增速": "储能价格竞争更激烈，降幅高于动力（第 4 节）",
    "储能电池毛利率": "海外项目支撑，竞争使毛利率小幅下移（第 4、5 节）",
    "销售费用率": "规模效应下维持 2025 年水平（第 6 节）",
    "其他费用率": "管理、研发费用率与其他经营损益维持 2025 年水平（第 6 节）",
    "现金分红率": "与 2025 年度一致（第 8 节）",
}


# ================================================================== 正文编排
def body(doc: Doc, S: dict[str, str]) -> str:
    run, img, fig = doc.run, doc.img, doc.fig
    I = lambda fn, w=83: img(fn(run, doc.ch), w)  # noqa: E731,E741  公司专属图
    p, q = run.period, run.prev
    part = lambda k: md_parts(S.get(k, "")) + [""] * 4  # noqa: E731
    thesis, overview, perf = part("thesis"), part("overview"), part("performance")
    prod, cap, prof = part("product"), part("capacity"), part("profitability")
    bal, cash, val = part("balance"), part("cashflow"), part("valuation")
    return f"""
<section class="body">
  {doc.h2(1, "投资逻辑：以量换价份额再升，单位盈利稳住")}
  {thesis[0]}
  {fig(f"{run.prev2}A～{int(p) + 5}E 营业收入与归母净利润", img(C.history, 172), "预测为基准情景；预测期归母净利润不含投资收益与公允价值变动收益")}
  {thesis[1]}

  {doc.h2(2, "公司概况与行业：动力与储能双龙头，A+H 两地上市")}
  {overview[0]}
  {two(fig("营业收入结构（%）", I(ch_mix)), fig("前六大股东持股比例", I(ch_holders)))}
  {overview[1]}
  {two(fig(f"{p} 年员工专业构成（人）", I(ch_employees)), fig("盈利质量：ROE 与净现比", img(C.quality)))}
  {overview[2]}
  {fig("近三年主要会计数据与财务指标", T.three_year(run), cls="split")}
  <h3>行业环境：需求高增，份额向龙头集中</h3>
  {md(S["industry"])}
  {two(fig("2025 年行业需求", I(ch_industry)), fig("公司市占率", I(ch_share)))}

  {doc.h2(3, "业绩回顾：量增驱动收入增长，利润增速快于收入")}
  {perf[0]}
  {fig("主要财务指标", T.core(run), cls="split")}
  {perf[1]}
  {two(fig(f"{p} 年分季度营业收入与归母净利润（亿元）", img(C.quarterly)), fig(f"{p} 年分季度主要财务数据", tb_quarterly(run)))}

  {doc.h2(4, "产品与量价：动力电池放量，平均售价随原材料下行")}
  {prod[0]}
  {two(fig("分业务营业收入（亿元）", I(ch_rev_pair)), fig("分产品毛利率", I(ch_product)))}
  {prod[1]}
  {two(fig("动力与储能电池销量（GWh）", I(ch_volume)),
       fig("单位售价与单位成本（元/Wh）", I(ch_unit), "单位售价 = 分产品收入 ÷ 销量，单位成本 = 分产品营业成本 ÷ 销量"))}
  {prod[2]}
  {fig("量价拆分", tb_volume(run), "单位售价、单位成本由程序按收入、成本与销量计算；上年分产品销量未披露，单价同比仅按电池系统合计口径计算", cls="split")}
  {two(fig("电池系统平均单位售价（元/Wh）", I(ch_price), "合计收入 = 电气机械及器材制造业 − 电池材料及回收 − 其他业务"),
       fig("主营业务构成", tb_segments(run)))}
  {prod[3]}

  {doc.h2(5, "产能、库存与区域：满产扩产，境外毛利率更高")}
  {cap[0]}
  {two(fig("电池系统产能、产销与在建产能（GWh）", I(ch_capacity)), fig("产能利用与库存", tb_psi(run)))}
  {fig("重大在建项目投入", I(ch_projects, 172))}
  {cap[1]}
  {two(fig("电池系统产销存（GWh）", I(ch_psi)), fig("存货构成", I(ch_inventory)))}
  {md(S["region"])}
  {two(fig("境内与境外营业收入（亿元）", I(ch_region)), fig("境内与境外毛利率", I(ch_region_gm)))}

  {doc.h2(6, "盈利能力：毛利率逆势提升，非主业贡献可观")}
  {prof[0]}
  {two(fig("毛利率分层（%）", I(ch_gm_layers)), fig("成本与毛利率", tb_cost(run)))}
  {prof[1]}
  {two(fig("研发费用明细（亿元）", I(ch_rd)), fig("费用率变化", I(ch_expense_ratios)))}
  {two(fig("管理费用明细", tb_two_period(run, "admin_detail", "管理费用（亿元）", "管理费用合计")),
       fig("财务费用明细", tb_two_period(run, "finance_detail", "财务费用（亿元）", "财务费用合计")))}
  {prof[2]}
  {two(fig("非主业损益项目（亿元）", I(ch_nonop)), fig("非主业损益占比", tb_nonop(run)))}
  {prof[3]}
  {fig(f"归母净利润变动归因（{q} 年至 {p} 年，亿元）", img(C.bridge, 172),
       "收入规模效应 = Δ营业收入 × 上年毛利率；毛利率效应 = 本年营业收入 × Δ毛利率；其他经营损益含投资收益、其他收益与减值")}

  {doc.h2(7, "资产负债与现金流：占款增强现金流，存货与质保需跟踪")}
  {bal[0]}
  {two(fig("主要资产占总资产比例", I(ch_assets)), fig("资产负债与营运资本", T.balance(run)))}
  {bal[1]}
  {two(fig("存货结构与跌价准备", tb_inventory(run)), fig("资产减值损失", tb_two_period(run, "impairment", "资产减值损失（亿元）", "资产减值损失合计")))}
  {bal[2]}
  {bal[3]}
  {two(fig("经营性负债（亿元）", I(ch_wc)), fig("预计负债与先行指标", tb_provisions(run)))}
  {cash[0]}
  {two(fig("三类现金流量净额（亿元）", I(ch_cashflows)), fig(f"{p} 年分季度经营现金流与归母净利润", img(C.cash_quarterly)))}
  {cash[1]}
  {fig("现金流量主要项目", tb_cash_items(run), cls="split")}

  {doc.h2(8, "股东回报：分红率 50%，叠加回购")}
  {md(S["return"])}
  {fig(f"{p} 年度现金分红构成（亿元）", I(ch_payout, 172))}
  {two(fig("股东回报指标", tb_returns(run)), fig("每 10 股派息（元，含税）", I(ch_dps)))}

  {doc.h2(9, "盈利预测：量价拆分，收入保持两位数增长")}
  {md(S["forecast"])}
  {fig("关键假设与依据", T.assumptions(run, BASIS, price_label="单价"), "假设为分析师观点")}
  {fig("分部收入预测", T.segment_forecast(run, volume_unit="GWh", price_unit="万元/GWh", price_label="单价"), "基准情景；单价 = 分部收入 ÷ 销量，单位万元/GWh", cls="split")}
  {two(fig("分产品收入预测", img(C.segment_forecast), "基准情景"), fig("利润率与费用率", img(C.margins), "基准情景"))}
  {fig("盈利预测", T.forecast(run, last=5), "基准情景；归母净利润不含投资收益与公允价值变动收益")}

  {doc.h2(10, f"估值：DCF 基准情景每股价值 {num(run.scen['base']['value_per_share'])} 元")}
  {val[0]}
  {two(fig("折现参数", T.wacc(run), "参数为分析师假设"), fig("三情景营业收入", img(C.scenarios)))}
  {fig("FCFF 预测与折现（基准情景）", T.fcff(run))}
  {fig("从企业价值到每股价值", img(C.ev_bridge, 172))}
  {equity_bridge(doc)}
  {val[1]}
  {fig("三情景关键驱动与估值", T.scenario_table(run, price_label="单价"))}
  {valuation_ranges(doc)}

  {doc.h2(11, "投资建议")}
  {md(S["recommendation"])}

  {doc.h2(12, "风险提示")}
  {md(S["risks"])}
</section>
{appendix(doc, CFG, "第 9、10 节")}"""


if __name__ == "__main__":
    sys.exit(main(CFG, body))
