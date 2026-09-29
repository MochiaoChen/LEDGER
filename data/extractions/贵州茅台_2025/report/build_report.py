"""贵州茅台 2025 年报深度点评：读 FinAgent 运行产物 → 图表 → HTML → PDF。

通用部分（读产物、格式化、标准图表、目录、附录、免责声明、打印）在 reportkit（.claude/skills/finagent-report/），
本脚本只写茅台专属的经营数据图表（extras.json 的表与比率）和正文编排。数字全部从运行产物读出。

    .venv/bin/python data/extractions/贵州茅台_2025/report/build_report.py --run-dir runs/<run_id>
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / ".claude" / "skills" / "finagent-report"))

from reportkit import charts as C  # noqa: E402
from reportkit import tables as T  # noqa: E402
from reportkit.core import GOLD, LIGHT, NAVY, NAVY2, SLATE, Run, md, md_parts, mm, num, pct, pp, yi  # noqa: E402
from reportkit.layout import Config, Doc, appendix, equity_bridge, main, two, valuation_ranges  # noqa: E402
from reportkit.tables import grp, table, td, tr  # noqa: E402

PRODUCTS = [("茅台酒", "茅台酒"), ("系列酒", "其他系列酒")]  # (正文名, extras 行名)


def side_rows(run: Run) -> list[tuple[str, str]]:
    return [(f"{run.period} 年度每股派息（元）", f"{run.cell('dps', '2025年年度利润分配', '每股派息'):.3f}"),
            ("控股股东持股", pct(run.cell("holders", "中国贵州茅台酒厂（集团）有限责任公司", "持股比例"), sign=False))]


CFG = Config(
    company="贵州茅台", ticker="600519.SH", sector="食品饮料 · 白酒", date="2026 年 9 月 29 日",
    narrative=HERE / "narrative.md", output_name="贵州茅台0929.pdf", side_rows=side_rows,
    method_note="营业收入取合并利润表“其中：营业收入”，不含财务公司利息收入；财务公司利息收入仍计入经营费用轧差项，"
                "股权桥逐项加回财务公司持有的类现金资产并扣减其吸收的存款，二者存在少量重复计算；"
                "经营费用率中的“其他”为基期轧差项（含财务公司利息、折旧重分类等），预测期保持不变；",
)


def g(v, d=2):  # 同比标注
    return f"{v:+.{d}f}%"


# ================================================================== 经营数据图（extras → 原语）
def ch_mix(run, out):
    return C.donuts(out, "mix", [("收入占比", [run.ratios["mix_moutai"], run.ratios["mix_series"]]),
                                 ("销量占比", [run.ratios["vol_share_moutai"], run.ratios["vol_share_series"]])],
                    ["茅台酒", "系列酒"])


def ch_employees(run, out):
    rows = [r for r in run.rows("employees") if r != "员工合计"]
    return C.hbars(out, "employees", rows, [run.cell("employees", r, "人数") for r in rows],
                   title=f"期末在职员工 {run.cell('employees', '员工合计', '人数'):,.0f} 人")


def ch_holders(run, out):
    short = {"中国贵州茅台酒厂（集团）有限责任公司": "茅台集团", "贵州省国有资本运营有限责任公司": "贵州省国资运营",
             "香港中央结算有限公司": "香港中央结算", "贵州茅台酒厂（集团）技术开发有限公司": "集团技术开发公司"}
    rows = run.rows("holders")
    return C.hbars(out, "holders", [short.get(r, r) for r in rows], [run.cell("holders", r, "持股比例") for r in rows],
                   fmt="{:.2f}%", title="期末持股比例")


def ch_product(run, out):
    cats = [n for n, _ in PRODUCTS]
    return C.panels(out, "product", [
        ("主营收入（亿元）与同比", cats, [run.cell("product", r, "营业收入") / 1e8 for _, r in PRODUCTS],
         [g(run.cell("product", r, "营业收入同比")) for _, r in PRODUCTS], "{:,.2f}"),
        ("毛利率与同比变动", cats, [run.cell("product", r, "毛利率") for _, r in PRODUCTS],
         [f"{run.cell('product', r, '毛利率同比'):+.2f}pp" for _, r in PRODUCTS], "{:.2f}%")])


def ch_unit(run, out):
    return C.grouped(out, "unit_economics", [n for n, _ in PRODUCTS],
                     [("吨价", [run.ratios["price_moutai"], run.ratios["price_series"]]),
                      ("吨成本", [run.ratios["unitcost_moutai"], run.ratios["unitcost_series"]])],
                     colors=[NAVY, GOLD], title="单位：万元/吨", ylim=1.2)


def ch_production(run, out):
    return C.grouped(out, "production", [n for n, _ in PRODUCTS],
                     [("基酒产量", [run.cell("volume", r, "产量") for _, r in PRODUCTS]),
                      ("销量", [run.cell("volume", r, "销量") for _, r in PRODUCTS])],
                     notes=[[g(run.cell("volume", r, "产量同比")) for _, r in PRODUCTS],
                            [g(run.cell("volume", r, "销量同比")) for _, r in PRODUCTS]],
                     colors=[NAVY, SLATE], fmt="{:,.0f}", title="单位：吨；灰字为同比")


def ch_capacity(run, out):
    rows = [("茅台酒", "茅台酒制酒车间"), ("系列酒", "系列酒制酒车间")]
    return C.grouped(out, "capacity", [n for n, _ in rows],
                     [("设计产能", [run.cell("capacity", r, "设计产能") for _, r in rows]),
                      ("实际基酒产量", [run.cell("capacity", r, "实际产能") for _, r in rows])],
                     notes=[[f"新增 {run.cell('capacity_new', n, '新增设计产能'):,.0f}" for n, _ in rows], None],
                     note_color=NAVY, colors=[NAVY, SLATE], fmt="{:,.0f}", title="单位：吨；新增产能 2026 年释放")


def ch_projects(run, out):
    short = {"3万吨酱香系列酒技改工程及配套设施": "3 万吨系列酒技改", "“十四五”酱香酒习水同民坝一期": "习水同民坝一期",
             "茅台酒“十四五”技改建设": "茅台酒“十四五”技改"}
    rows = run.rows("projects")
    return C.progress(out, "projects", [short.get(r, r) for r in rows],
                      [run.cell("projects", r, "累计投资") / 1e8 for r in rows],
                      [run.cell("projects", r, "计划投资") / 1e8 for r in rows],
                      title="单位：亿元（累计投资 / 计划投资）", done_label="累计投资", total_label="计划投资")


def ch_channel(run, out):
    cv = lambda row, col: run.cell("channel_volume", row, col) / 1e8  # noqa: E731
    return C.stacked(out, "channel", [f"{run.prev} 年", f"{run.period} 年"],
                     [("直销", [cv("直销", "上期销售收入"), cv("直销", "本期销售收入")]),
                      ("批发代理", [cv("批发代理", "上期销售收入"), cv("批发代理", "本期销售收入")])],
                     tops=[f"直销占比 {run.ratios['mix_direct_prev']:.2f}%", f"直销占比 {run.ratios['mix_direct']:.2f}%"],
                     colors=[NAVY, LIGHT])


def ch_direct(run, out):
    im = "i茅台数字营销平台"
    return C.stacked(out, "direct_split", [f"{run.prev} 年", f"{run.period} 年"],
                     [("自营及其他", [run.ratios["direct_ex_imoutai_prev"] / 1e8, run.ratios["direct_ex_imoutai"] / 1e8]),
                      ("i茅台", [run.cell("online", im, "上期销售收入") / 1e8, run.cell("online", im, "本期销售收入") / 1e8])],
                     tops=["", f"自营及其他 {g(run.ratios['direct_ex_imoutai_g'])}｜i茅台 {g(run.cell('online', im, '同比'))}"],
                     colors=[NAVY, GOLD], title="直销收入构成（亿元）")


def ch_channel_volume(run, out):
    rows = [("直销", "vol_direct_g"), ("批发代理", "vol_wholesale_g")]
    return C.grouped(out, "channel_volume", [r for r, _ in rows],
                     [(f"{run.prev} 年", [run.cell("channel_volume", r, "上期销量") for r, _ in rows]),
                      (f"{run.period} 年", [run.cell("channel_volume", r, "本期销量") for r, _ in rows])],
                     notes=[g(run.ratios[k]) for _, k in rows], fmt="{:,.0f}", title="单位：吨；灰字为同比")


def ch_channel_price(run, out):
    rows = [("直销", "price_direct"), ("批发代理", "price_wholesale")]
    return C.grouped(out, "channel_price", [r for r, _ in rows],
                     [(f"{run.prev} 年", [run.ratios[k + "_prev"] for _, k in rows]),
                      (f"{run.period} 年", [run.ratios[k] for _, k in rows])],
                     notes=[g(run.ratios[k + "_g"]) for _, k in rows], title="单位：万元/吨；砖红为同比")


def ch_subsidiaries(run, out):
    rows = [("茅台酒销售公司", "贵州茅台酒销售有限公司", "sub_sales_margin"),
            ("酱香酒营销公司", "贵州茅台酱香酒营销有限公司", "sub_jx_margin")]
    return C.grouped(out, "subsidiaries", [n for n, _, _ in rows],
                     [("营业收入", [run.cell("subsidiaries", r, "营业收入") / 1e8 for _, r, _ in rows]),
                      ("净利润", [run.cell("subsidiaries", r, "净利润") / 1e8 for _, r, _ in rows])],
                     notes=[f"净利率 {run.ratios[k]:.2f}%" for _, _, k in rows], note_color=NAVY,
                     colors=[NAVY, SLATE], title="单位：亿元", ylim=1.2)


def _pair(run, out, name, tbl, rows, cur, prev, yoy, short=None):
    """上期 vs 本期分组柱（亿元），柱顶标同比。"""
    return C.grouped(out, name, [(short or {}).get(r, r) for r in rows],
                     [(f"{run.prev} 年", [run.cell(tbl, r, prev) / 1e8 for r in rows]),
                      (f"{run.period} 年", [run.cell(tbl, r, cur) / 1e8 for r in rows])],
                     notes=[g(v) if v is not None else None for v in yoy], size=5.4, title="单位：亿元；灰字为同比")


def ch_cost(run, out):
    rows = [r for r in run.rows("cost") if r != "酒类营业成本"]
    return _pair(run, out, "cost", "cost", rows, "本期金额", "上期金额", [run.cell("cost", r, "同比") for r in rows],
                 {r: r[:2] + "\n" + r[2:] for r in rows})


def ch_procurement(run, out):
    rows = run.rows("procurement")
    ids = {"酿酒原材料": "proc_raw_g", "包装材料": "proc_pack_g", "能源": "proc_energy_g"}
    return _pair(run, out, "procurement", "procurement", rows, "本期", "上期",
                 [run.ratios.get(ids.get(r, "")) for r in rows],
                 {"酿酒原材料": "酿酒\n原材料", "包装材料": "包装\n材料", "车间辅助材料": "车间辅助\n材料"})


def ch_selling(run, out):
    rows = [r for r in run.rows("selling_detail") if r != "销售费用合计"]
    ids = {"广告宣传费": "sell_ad_g", "市场推广及服务费": "sell_promo_g", "其他销售费用": "sell_other_g"}
    return _pair(run, out, "selling", "selling_detail", rows, "本期", "上期", [run.ratios.get(ids.get(r, "")) for r in rows],
                 {"广告宣传费": "广告\n宣传费", "市场推广及服务费": "市场推广\n及服务费", "营销办公及差旅费": "办公\n及差旅",
                  "其他销售费用": "其他"})


def ch_expense_ratios(run, out):
    items = [("销售\n费用率", run.v("selling_ratio", run.prev), run.v("selling_ratio")),
             ("管理\n费用率", run.v("admin_ratio", run.prev), run.v("admin_ratio")),
             ("广告宣传\n费率", run.ratios["sell_ad_rate_prev"], run.ratios["sell_ad_rate"]),
             ("市场推广\n费率", run.ratios["sell_promo_rate_prev"], run.ratios["sell_promo_rate"]),
             ("研发\n费用率", run.v("rd_ratio", run.prev), run.v("rd_ratio"))]
    return C.grouped(out, "expense_ratios", [n for n, _, _ in items],
                     [(f"{run.prev} 年", [a for _, a, _ in items]), (f"{run.period} 年", [b for _, _, b in items])],
                     size=5.6, title="占营业收入比例（%）", ylim=1.25)


def ch_assets(run, out):
    rows = run.rows("assets")
    return C.grouped(out, "assets", [{"一年内到期的非流动资产": "一年内到期\n非流动资产"}.get(r, r) for r in rows],
                     [(f"{run.prev} 年末", [run.cell("assets", r, "期初占总资产") for r in rows]),
                      (f"{run.period} 年末", [run.cell("assets", r, "期末占总资产") for r in rows])],
                     size=5.6, title="占总资产比例（%）", ylim=1.25)


def ch_inventory(run, out):
    rows = [r for r in run.rows("inventory_detail") if r != "存货合计"]
    return C.stacked(out, "inventory", [f"{run.prev} 年末", f"{run.period} 年末"],
                     [(r, [run.cell("inventory_detail", r, "期初") / 1e8, run.cell("inventory_detail", r, "期末") / 1e8])
                      for r in rows],
                     totals=[run.cell("inventory_detail", "存货合计", "期初") / 1e8,
                             run.cell("inventory_detail", "存货合计", "期末") / 1e8],
                     colors=[SLATE, NAVY, NAVY2, GOLD], legend="right", title="存货账面价值构成（亿元）")


def ch_cashflows(run, out):
    rows = run.rows("cashflow_total")
    return C.signed(out, "cashflows", ["经营活动", "投资活动", "筹资活动"],
                    [(f"{run.prev} 年", [run.cell("cashflow_total", r, "上期") / 1e8 for r in rows]),
                     (f"{run.period} 年", [run.cell("cashflow_total", r, "本期") / 1e8 for r in rows])],
                    title="现金流量净额（亿元）")


def ch_payout(run, out):
    return C.composition(out, "payout", [
        ("中期现金分红", run.cell("interim", "中期现金分红", "金额") / 1e8),
        ("年度现金分红", run.cell("payout_detail", "年度现金分红", "金额") / 1e8),
        ("回购计入分红", run.cell("payout_detail", "回购计入现金分红", "金额") / 1e8)],
        note=f"合计 {run.cell('payout_detail', '合计分红金额', '金额') / 1e8:,.2f} 亿元，占归母净利润 "
             f"{run.cell('payout_pct', '合计分红占归母净利润', '比例'):.2f}%")


def ch_dps(run, out):
    rows = run.rows("dps10")
    return C.grouped(out, "dps", rows, [("每 10 股派息", [run.cell("dps10", r, "每10股派息") for r in rows])],
                     colors=[NAVY], title="单位：元（含税）", ylim=1.2)


# ================================================================== 经营数据表
def tb_quarterly(run):
    qoq = [None, run.ratios["q2_rev_qoq"], run.ratios["q3_rev_qoq"], run.ratios["q4_rev_qoq"]]
    return T.quarterly(run, [
        tr(["营业收入环比"] + [td(pct(v), v) if v is not None else "—" for v in qoq]),
        tr(["收入占全年比例", pct(run.ratios["q1_rev_share"], sign=False), "—", "—", pct(run.ratios["q4_rev_share"], sign=False)])])


def tb_volume(run):
    rows = []
    for (label, key), (pid, cid) in zip(PRODUCTS, [("price_moutai", "unitcost_moutai"), ("price_series", "unitcost_series")]):
        v = [run.cell("volume", key, c) for c in ("产量", "产量同比", "销量", "销量同比")]
        rows.append(tr([label, mm(v[0], 2), td(pct(v[1]), v[1]), mm(v[2], 2), td(pct(v[3]), v[3]),
                        num(run.ratios[pid]), num(run.ratios[cid])]))
    t = [run.cell("volume_total", "酒类", c) for c in ("生产量", "生产量同比", "销售量", "销售量同比")]
    rows.append(tr(["酒类合计", mm(t[0], 2), td(pct(t[1]), t[1]), mm(t[2], 2), td(pct(t[3]), t[3]), "—", "—"], "sub"))
    return table(["产品", "产量（吨）", "同比", "销量（吨）", "同比", "吨价（万元）", "吨成本（万元）"], rows, "data nw")


def tb_stock(run):
    r = run.ratios
    stock_yoy = run.cell("volume_total", "酒类", "库存量同比")
    rows = [tr(["酒类库存量（吨）", mm(run.cell("volume_total", "酒类", "库存量"), 2), td(pct(stock_yoy), stock_yoy)]),
            tr(["其中：成品酒（吨）", mm(run.cell("stock", "期末库存", "成品酒"), 2), "—"]),
            tr(["　　　半成品酒（含基础酒，吨）", mm(run.cell("stock", "期末库存", "半成品酒（含基础酒）"), 2), "—"]),
            tr(["半成品酒库存 / 全年销量（倍）", num(r["stock_to_sales"]), "—"]),
            tr(["茅台酒基酒产量 / 设计产能", pct(r["cap_util_moutai"], sign=False), "—"]),
            tr(["系列酒基酒产量 / 设计产能", pct(r["cap_util_series"], sign=False), "—"]),
            tr(["茅台酒新增设计产能占比", pct(r["cap_new_moutai_pct"], sign=False), "—"]),
            tr(["系列酒新增设计产能占比", pct(r["cap_new_series_pct"], sign=False), "—"])]
    return table(["库存与产能", f"{run.period} 年末", "同比"], rows)


def tb_segments(run):
    blocks = [("按产品", "product", [("茅台酒", "茅台酒"), ("其他系列酒", "系列酒"), ("小计", "合计")]),
              ("按渠道", "channel", [("直销", "直销"), ("批发代理", "批发代理")]),
              ("按地区", "region", [("国内", "国内"), ("国外", "国外")])]
    rows = []
    for title, tid, items in blocks:
        rows.append(grp(title, 6))
        for key, label in items:
            v = [run.cell(tid, key, c) for c in ("营业收入", "营业收入同比", "营业成本同比", "毛利率", "毛利率同比")]
            rows.append(tr([label, yi(v[0]), td(pct(v[1]), v[1]), td(pct(v[2]), v[2]), pct(v[3], sign=False),
                            td(pp(v[4]), v[4])], "sub" if key == "小计" else ""))
    return table(["主营业务", "收入（亿元）", "收入同比", "成本同比", "毛利率", "毛利率变动"], rows)


def tb_ops(run):
    r = run.ratios
    on = [run.cell("online", "i茅台数字营销平台", c) for c in ("本期销售收入", "上期销售收入", "同比")]
    ot = [run.cell("online", "其他线上平台", c) for c in ("本期销售收入", "上期销售收入", "同比")]
    dealers = lambda k: f"+{mm(run.cell('dealers', k, '本期增加'))} / -{mm(run.cell('dealers', k, '本期减少'))}"  # noqa: E731
    rows = [tr(["直销收入占比", pct(r["mix_direct"], sign=False), pct(r["mix_direct_prev"], sign=False), pp(r["mix_direct_chg"])]),
            tr(["i茅台平台收入（亿元）", yi(on[0]), yi(on[1]), td(pct(on[2]), on[2])]),
            tr(["自营及其他直销收入（亿元）", yi(r["direct_ex_imoutai"]), yi(r["direct_ex_imoutai_prev"]),
                td(pct(r["direct_ex_imoutai_g"]), r["direct_ex_imoutai_g"])]),
            tr(["其他线上平台收入（亿元）", yi(ot[0]), yi(ot[1]), td(pct(ot[2]), ot[2])]),
            tr(["i茅台占直销收入比例", pct(r["imoutai_in_direct"], sign=False), "—", "—"]),
            tr(["i茅台毛利率", pct(run.cell("online", "i茅台数字营销平台", "毛利率"), sign=False), "—", "—"]),
            tr(["国内经销商（个，期末）", mm(run.cell("dealers", "国内", "期末数量")), "—", dealers("国内")]),
            tr(["国外经销商（个，期末）", mm(run.cell("dealers", "国外", "期末数量")), "—", dealers("国外")]),
            tr(["经销商保证金（亿元）", yi(run.cell("dealer_deposit", "经销商保证金", "期末")),
                yi(run.cell("dealer_deposit", "经销商保证金", "期初")), pct(r["deposit_g"])])]
    return table(["渠道指标", run.period, run.prev, "变动"], rows)


def tb_region(run):
    rows = []
    for reg, pid in (("国内", "price_domestic"), ("国外", "price_overseas")):
        yoy = run.cell("region", reg, "营业收入同比")
        rows.append(tr([reg, yi(run.cell("region", reg, "营业收入")), td(pct(yoy), yoy),
                        pct(run.cell("region_volume", reg, "收入占比"), sign=False),
                        mm(run.cell("region_volume", reg, "本期销量"), 2), num(run.ratios[pid + "_prev"]),
                        num(run.ratios[pid]), pct(run.cell("region", reg, "毛利率"), sign=False)]))
    return table(["地区", "收入（亿元）", "同比", "收入占比", "销量（吨）", f"吨价 {run.prev}", f"吨价 {run.period}", "毛利率"],
                 rows, "data nw")


def tb_cost(run):
    rows = []
    for r in run.rows("cost"):
        v = [run.cell("cost", r, c) for c in ("本期金额", "本期占比", "上期金额", "上期占比", "同比")]
        rows.append(tr([r, yi(v[0]), pct(v[1], sign=False), yi(v[2]), pct(v[3], sign=False), td(pct(v[4]), v[4])],
                       "sub" if r == "酒类营业成本" else ""))
    return table(["成本项目", f"{run.period}（亿元）", "占比", f"{run.prev}（亿元）", "占比", "同比"], rows)


def tb_two_period(run, tbl, head, total, extra=None):
    rows = [tr([r, yi(run.cell(tbl, r, "本期")), yi(run.cell(tbl, r, "上期"))], "sub" if r == total else "")
            for r in run.rows(tbl)]
    return table([head, run.period, run.prev], rows + (extra or []))


def tb_taxes(run):
    r = run.ratios
    return tb_two_period(run, "tax_detail", "税金及附加（亿元）", "税金及附加合计", [
        tr(["税金及附加率", pct(r["tax_rate"], sign=False), pct(r["tax_rate_prev"], sign=False)]),
        tr(["消费税占营业收入比例", pct(r["consump_rate"], sign=False), pct(r["consump_rate_prev"], sign=False)])])


def tb_fin_company(run):
    rows = [tr([r, td(yi(run.cell("cashflow_items", r, "本期")), run.cell("cashflow_items", r, "本期")),
                td(yi(run.cell("cashflow_items", r, "上期")), run.cell("cashflow_items", r, "上期"))])
            for r in run.rows("cashflow_items")]
    return table(["现金流量项目（亿元）", run.period, run.prev], rows)


def tb_returns(run):
    r = run.ratios
    rows = [tr([f"{run.period} 年度累计现金分红（亿元）", num(run.cell("dividend", "2025年度累计现金分红", "金额") / 1e8)]),
            tr(["　其中：中期分红（亿元）", num(run.cell("interim", "中期现金分红", "金额") / 1e8)]),
            tr(["　　　　年度分红（亿元）", yi(run.cell("payout_detail", "年度现金分红", "金额"))]),
            tr(["现金分红率", pct(r["payout"], sign=False)]),
            tr(["回购计入现金分红（亿元）", yi(run.cell("payout_detail", "回购计入现金分红", "金额"))]),
            tr(["合计分红占归母净利润", pct(run.cell("payout_pct", "合计分红占归母净利润", "比例"), sign=False)]),
            tr(["每股派息（年度，元）", f"{run.cell('dps', '2025年年度利润分配', '每股派息'):.3f}"]),
            tr(["回购注销股份（股）", mm(run.cell("buyback", "回购注销股份", "数量"))]),
            tr(["回购注销占总股本比例", pct(r["buyback_pct"], sign=False)]),
            tr(["近三年累计现金分红（亿元）", yi(run.cell("three_year", "累计现金分红", "金额"))]),
            tr(["近三年累计回购注销（亿元）", yi(run.cell("three_year", "累计回购并注销", "金额"))]),
            tr(["近三年分红与回购 / 年均净利润（倍）", num(r["three_year_payout"])])]
    return table(["股东回报", run.period], rows)


BASIS = {  # 关键假设的依据，写明对应正文第几节
    "茅台酒销量增速": "新增基酒产能 2026 年释放；半成品酒储备充足（第 4 节）",
    "茅台酒吨价增速": "批价承压先持平；直销占比提升、产品结构优化（第 5 节）",
    "茅台酒毛利率": "维持 2025 年水平；包材与人工成本上行由结构对冲（第 6 节）",
    "系列酒销量增速": "新增系列酒产能释放；经销商扩张以量补价（第 4、5 节）",
    "系列酒吨价增速": "产品结构调整延续，价格下移后企稳（第 4 节）",
    "系列酒毛利率": "随价格下移先降后稳（第 6 节）",
    "销售费用率": "渠道转型期维持投放强度，此后回落（第 6 节）",
    "其他费用率": "税金及附加、管理、研发费用率维持 2025 年水平（第 6 节）",
    "现金分红率": "与 2025 年度一致（第 8 节）",
}


# ================================================================== 正文编排
def body(doc: Doc, S: dict[str, str]) -> str:
    run, img, fig = doc.run, doc.img, doc.fig
    I = lambda fn, w=83: img(fn(run, doc.ch), w)  # noqa: E731,E741  公司专属图
    p, q, r = run.period, run.prev, run.ratios
    thesis, overview, perf = md_parts(S["thesis"]), md_parts(S["overview"]), md_parts(S["performance"])
    prod, cap, chan = md_parts(S["product"]), md_parts(S["capacity"]), md_parts(S["channel"])
    prof, bal, cash = md_parts(S["profitability"]), md_parts(S["balance"]), md_parts(S["cashflow"])
    val = md_parts(S["valuation"])
    return f"""
<section class="body">
  {doc.h2(1, "投资逻辑：主品稳价、渠道换挡、高分红托底")}
  {thesis[0]}
  {fig(f"{run.prev2}A～{int(p) + 5}E 营业收入与归母净利润", img(C.history, 172), "预测为基准情景")}
  {thesis[1]}

  {doc.h2(2, "公司概况：五年一瓶酒，单品过千亿的酱香龙头")}
  {overview[0]}
  {two(fig("茅台酒与系列酒：收入占比与销量占比", I(ch_mix)), fig(f"{p} 年员工专业构成（人）", I(ch_employees)))}
  {overview[1]}
  {two(fig("前四大股东持股比例", I(ch_holders)), fig("盈利质量：ROE 与净现比", img(C.quality)))}
  {overview[2]}
  {fig("近三年主要会计数据与财务指标", T.three_year(run), cls="split")}
  <h3>行业环境：调整期中资源向头部集中</h3>
  {md(S["industry"])}

  {doc.h2(3, "业绩回顾：收入与利润小幅回落，季度收入逐季回升")}
  {perf[0]}
  {fig("主要财务指标", T.core(run), cls="split")}
  {perf[1]}
  {two(fig(f"{p} 年分季度营业收入与归母净利润（亿元）", img(C.quarterly)), fig(f"{p} 年分季度主要财务数据", tb_quarterly(run)))}

  {doc.h2(4, "产品与产能：茅台酒量价平稳，系列酒以量补价")}
  {prod[0]}
  {two(fig("分产品收入与毛利率", I(ch_product)),
       fig("分产品吨价与吨成本（万元/吨）", I(ch_unit), "吨价 = 收入 ÷ 销量，吨成本 = 营业成本 ÷ 销量"))}
  {prod[1]}
  {fig("分产品量价拆分", tb_volume(run), "吨价、吨成本由程序按收入、成本与销量计算")}
  {prod[2]}
  {two(fig("分产品基酒产量与销量（吨）", I(ch_production)), fig("库存与产能利用", tb_stock(run)))}
  {cap[0]}
  {two(fig("基酒设计产能与实际产量（吨）", I(ch_capacity)), fig("主营业务构成", tb_segments(run)))}
  {fig("在建产能项目投资进度", I(ch_projects, 172))}

  {doc.h2(5, "渠道与区域：直销占比过半，自营体系成为增量来源")}
  {chan[0]}
  {two(fig("分渠道收入结构（亿元）", I(ch_channel)),
       fig("直销收入拆分：i茅台与自营及其他", I(ch_direct), "自营及其他 = 直销收入 − i茅台收入"))}
  {chan[1]}
  {two(fig("分渠道销量（吨）", I(ch_channel_volume)), fig("分渠道吨价（万元/吨）", I(ch_channel_price), "吨价 = 收入 ÷ 销量"))}
  {chan[2]}
  {fig("渠道、线上与经销商", tb_ops(run), cls="split")}
  {md(S["region"])}
  {two(fig("分区域收入、销量与吨价", tb_region(run)), fig("主要销售子公司营业收入与净利润", I(ch_subsidiaries)))}

  {doc.h2(6, "盈利能力：系列酒拖累毛利率，主动加大市场投入")}
  {prof[0]}
  {two(fig("酒类营业成本构成（亿元）", I(ch_cost)), fig("原料采购金额（亿元）", I(ch_procurement)))}
  {fig("酒类营业成本构成明细", tb_cost(run), cls="split")}
  {prof[1]}
  {two(fig("销售费用明细（亿元）", I(ch_selling)), fig("费用率变化", I(ch_expense_ratios)))}
  {two(fig("管理费用主要项目", tb_two_period(run, "admin_detail", "管理费用（亿元）", "管理费用合计")),
       fig("税金及附加", tb_taxes(run)))}
  {prof[2]}
  {fig(f"归母净利润变动归因（{q} 年至 {p} 年，亿元）", img(C.bridge, 172),
       "收入规模效应 = Δ营业收入 × 上年毛利率；毛利率效应 = 本年营业收入 × Δ毛利率")}

  {doc.h2(7, "资产负债与现金流：类现金资产充裕，经营现金流受财务公司扰动")}
  {bal[0]}
  {two(fig("主要资产占总资产比例", I(ch_assets)), fig("存货构成", I(ch_inventory)))}
  {bal[1]}
  {bal[2]}
  {fig("资产负债与营运资本", T.balance(run, [tr(["合同负债 / 营业收入", pct(r["contract_to_rev"], sign=False),
                                               pct(r["contract_to_rev_prev"], sign=False), "—"])]), cls="split")}
  {cash[0]}
  {two(fig("三类现金流量净额（亿元）", I(ch_cashflows)), fig(f"{p} 年分季度经营现金流与归母净利润", img(C.cash_quarterly)))}
  {fig("财务公司相关现金流量项目", tb_fin_company(run))}
  {"".join(cash[1:])}

  {doc.h2(8, "股东回报：分红率维持高位，回购常态化")}
  {md(S["return"])}
  {fig(f"{p} 年度分红构成（亿元）", I(ch_payout, 172))}
  {two(fig("股东回报指标", tb_returns(run)), fig("每 10 股派息（元，含税）", I(ch_dps)))}

  {doc.h2(9, "盈利预测：量价拆分，2026 年恢复增长")}
  {md(S["forecast"])}
  {fig("关键假设与依据", T.assumptions(run, BASIS, price_label="吨价"), "假设为分析师观点")}
  {fig("分部收入预测", T.segment_forecast(run, volume_unit="吨", price_unit="万元/吨", price_label="吨价"), "基准情景", cls="split")}
  {two(fig("分产品收入预测", img(C.segment_forecast), "基准情景"), fig("利润率与销售费用率", img(C.margins), "基准情景"))}
  {fig("盈利预测", T.forecast(run, last=5), "基准情景")}

  {doc.h2(10, f"估值：DCF 基准情景每股价值 {num(run.scen['base']['value_per_share'])} 元")}
  {val[0]}
  {two(fig("折现参数", T.wacc(run), "参数为分析师假设"), fig("三情景营业收入", img(C.scenarios)))}
  {fig("FCFF 预测与折现（基准情景）", T.fcff(run))}
  {fig("从企业价值到每股价值", img(C.ev_bridge, 172))}
  {equity_bridge(doc)}
  {val[1]}
  {fig("三情景关键驱动与估值", T.scenario_table(run, price_label="吨价"))}
  {valuation_ranges(doc)}

  {doc.h2(11, "投资建议")}
  {md(S["recommendation"])}

  {doc.h2(12, "风险提示")}
  {md(S["risks"])}
</section>
{appendix(doc, CFG, "第 9、10 节")}"""


if __name__ == "__main__":
    sys.exit(main(CFG, body))
