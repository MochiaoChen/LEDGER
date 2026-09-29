"""model.xlsx 的三表联动页：假设（情景开关 + 驱动 + 辅助计算）→ 利润表 → 资产负债表 → 现金流量表。

预测期每一格都是公式：利润表取驱动与辅助计算，资产负债表取利润表、辅助计算和现金流量表，现金流量表取利润表与
辅助计算，勾稽检查也是公式。缓存值取自 ts_engine 基准情景（three_statement_detail.json），Excel 重算结果相同；
改“情景开关”即按悲观 / 乐观情景联动重算三表与 DCF（与引擎各情景结果一致）。

公式口径与 ts_engine 一致（本项目用到的功能）：收入按增速滚动；营业成本 = 收入 ×（1 − 毛利率）；经营费用 = 收入 × 费用率；
营运资本按周转天数；折旧 =（期初 PP&E + 半年资本开支）× 折旧率；利息 = 期初有息负债（扣半年还款）× 利率；
所得税 = max(税前利润, 0) × 税率；分红 = max(净利润, 0) × 分红率。循环贷、现金扫还、可抵扣亏损等未用到的功能
不写公式（detail["supported"] 为 False 时退回数值表）。
"""

from __future__ import annotations

import re
from typing import Any

from ...output.xlsx import Cell, Formula, Sheet
from .workbook import _col, _Grid

SHEETS = {"S": "分部预测", "A": "三表-假设", "IS": "三表-利润表", "BS": "三表-资产负债表", "CF": "三表-现金流量表"}
TOKEN = re.compile(r"«(S|A|IS|BS|CF)\.(\w+)\.(\$?[A-Z]+)»")
SCEN_CN = (("downside", "悲观"), ("base", "基准"), ("upside", "乐观"))
NOTE = "单位：百万元；蓝色为输入（报表值、驱动假设），黑色为公式，绿色为跨表引用"

ROW_NOTES = {
    ("A", "g"): "实际期由历史收入反算；预测期按情景开关选用悲观、基准或乐观假设。",
    ("A", "gm"): "实际期由收入与营业成本反算；预测期按情景开关选用。",
    ("A", "opex"): "经营费用率不含折旧摊销，含税金及附加；预测期按收入比例计算。",
    ("A", "tax"): "所得税率 = 所得税费用 / 利润总额；预测期用于计算账面税与现金税。",
    ("A", "ar_days"): "应收账款周转天数 = 应收账款 / 营业收入 × 365。",
    ("A", "inv_days"): "存货周转天数 = 存货 / 营业成本 × 365。",
    ("A", "ap_days"): "应付账款周转天数 = 应付账款 / 营业成本 × 365。",
    ("A", "capex_pct"): "资本开支率 = 资本开支 / 营业收入。",
    ("A", "nwc"): "经营营运资本 = 应收账款 + 存货 − 应付账款。",
    ("A", "ppe_end"): "期末 PP&E = 期初 PP&E + 资本开支 − 折旧摊销。",
    ("A", "debt_end"): "期末有息负债 = 期初有息负债 − 计划偿还。",
    ("IS", "rev"): "实际期取合并利润表；预测期 = 上年收入 × (1 + 收入增速)。",
    ("IS", "cogs"): "营业成本 = 营业收入 × (1 − 毛利率)。",
    ("IS", "gp"): "毛利 = 营业收入 − 营业成本。",
    ("IS", "ebit"): "经营 EBIT = 毛利 − 经营费用 − 折旧摊销；不含投资收益与公允价值变动收益。",
    ("IS", "tp"): "利润总额 = 经营 EBIT − 利息费用 + 投资收益及公允价值变动收益。",
    ("IS", "ni"): "净利润 = 利润总额 − 所得税费用。",
    ("BS", "cash"): "预测期货币资金引用现金流量表期末现金。",
    ("BS", "ar"): "应收账款 = 营业收入 × 应收账款周转天数 / 365。",
    ("BS", "inv"): "存货 = 营业成本 × 存货周转天数 / 365。",
    ("BS", "ap"): "应付账款 = 营业成本 × 应付账款周转天数 / 365。",
    ("BS", "ppe"): "固定资产及在建工程引用固定资产滚动辅助计算。",
    ("BS", "ta"): "资产总计 = 各项资产合计。",
    ("BS", "tle"): "负债和权益总计 = 各项负债与权益合计。",
    ("BS", "chk_bs"): "模型检查 = 资产总计 − 负债和权益总计；容差内应为 0.00。",
    ("BS", "chk_all"): "汇总资产负债、现金、留存收益、PP&E 与有息负债滚动检查。",
    ("CF", "cfo"): "经营活动现金流 = 净利润 + 折旧摊销 − 营运资本增加 + 其他经营项目。",
    ("CF", "capex"): "资本开支为现金流出，取负号列示。",
    ("CF", "end"): "期末现金 = 期初现金 + 经营、投资与筹资活动现金流。",
}


def _t(sheet: str, key: str, col: str) -> str:
    """跨表引用占位符，所有表建完后替换为 '表名'!列行。"""
    return f"«{sheet}.{key}.{col}»"


def _prev(col: str) -> str:
    return chr(ord(col) - 1)


def _segment_sheet(seg: dict[str, Any], F: list[str], n: int, add: Any, head: Any) -> _Grid:
    """分部预测页：各情景 产品销量 × 吨价 → 收入、毛利率；费用率分项 → 经营费用率。基期列 C 为报表值。"""
    g = _Grid("分部预测：产品量价、毛利率与费用率（驱动三表）",
              NOTE + "；吨价单位万元/吨；收入增速、综合毛利率、经营费用率由“三表-假设”按情景开关引用")
    add(g, "S", None, head("分部预测（百万元）"), role="header")
    by = seg["base_year"]
    for k, cn in (("base", "基准"), ("downside", "悲观"), ("upside", "乐观")):  # 阅读顺序：基准在前
        sc = seg["scenarios"][k]
        add(g, "S", None, [f"{cn}情景"], role="section")
        rev_rows, cogs_rows = [], []
        for b, sg in zip(by["segments"], sc["segments"]):
            nm, key = b["name"], f"{k}_{b['id']}"
            r_vg = add(g, "S", None, [f"{nm}：销量增速", None, None] + [Cell(x, fmt="pct1", input=True) for x in sg["volume_growth"]])
            r_v = len(g.rows) + 1
            add(g, "S", None, [f"{nm}：销量（吨）", None, Cell(b["volume"], fmt="num0", input=True)]
                + [Formula(f"{_prev(c)}{r_v}*(1+{c}{r_vg})", x, fmt="num0") for c, x in zip(F, sg["volume"])])
            r_pg = add(g, "S", None, [f"{nm}：吨价增速", None, None] + [Cell(x, fmt="pct1", input=True) for x in sg["price_growth"]])
            r_p = len(g.rows) + 1
            r_r = r_p + 1
            add(g, "S", None, [f"{nm}：吨价（万元/吨）", None, Formula(f"C{r_r}*100/C{r_v}", b["price"], fmt="num2")]
                + [Formula(f"{_prev(c)}{r_p}*(1+{c}{r_pg})", x, fmt="num2") for c, x in zip(F, sg["price"])])
            add(g, "S", f"{key}_rev", [f"{nm}：收入", None, Cell(b["revenue"], input=True)]
                + [Formula(f"{c}{r_v}*{c}{r_p}/100", x) for c, x in zip(F, sg["revenue"])], role="total")
            r_gc = add(g, "S", None, [f"{nm}：毛利率变动（百分点）", None, None]
                       + [Cell(x, fmt="pp2", input=True) for x in sg["gm_change_pp"]])
            r_gm = len(g.rows) + 1
            r_c = r_gm + 1
            add(g, "S", None, [f"{nm}：毛利率", None, Formula(f"1-C{r_c}/C{r_r}", b["gross_margin"], fmt="pct1")]
                + [Formula(f"{_prev(c)}{r_gm}+{c}{r_gc}/100", x, fmt="pct1") for c, x in zip(F, sg["gross_margin"])])
            add(g, "S", None, [f"{nm}：营业成本", None, Cell(b["cogs"], input=True)]
                + [Formula(f"{c}{r_r}*(1-{c}{r_gm})", x) for c, x in zip(F, sg["cogs"])])
            rev_rows.append(r_r)
            cogs_rows.append(r_c)
        r_or = len(g.rows) + 1
        add(g, "S", None, ["其他业务收入（保持不变）", None, Cell(by["other_revenue"], input=True)]
            + [Formula(f"{_prev(c)}{r_or}", by["other_revenue"]) for c in F])
        r_oc = len(g.rows) + 1
        add(g, "S", None, ["其他业务成本（保持不变）", None, Cell(by["other_cogs"], input=True)]
            + [Formula(f"{_prev(c)}{r_oc}", by["other_cogs"]) for c in F])
        cols = ["C"] + F
        r_tr = len(g.rows) + 1
        add(g, "S", None, ["营业收入"] + [None] + [Formula("+".join(f"{c}{r}" for r in rev_rows + [r_or]), x)
                                                  for c, x in zip(cols, [by["revenue"]] + sc["revenue"])], role="total")
        add(g, "S", f"g_{k}", ["营业收入增速", None, None]
            + [Formula(f"{c}{r_tr}/{_prev(c)}{r_tr}-1", x, fmt="pct1") for c, x in zip(F, sc["revenue_growth"])])
        r_tc = len(g.rows) + 1
        tc = [by["cogs"]] + [r * (1 - m) for r, m in zip(sc["revenue"], sc["gross_margin"])]
        add(g, "S", None, ["营业成本"] + [None] + [Formula("+".join(f"{c}{r}" for r in cogs_rows + [r_oc]), x)
                                                  for c, x in zip(cols, tc)])
        add(g, "S", f"gm_{k}", ["综合毛利率"] + [None] + [Formula(f"1-{c}{r_tc}/{c}{r_tr}", x, fmt="pct1")
                                                        for c, x in zip(cols, [by["gross_margin"]] + sc["gross_margin"])],
            role="total")
        er = sc["expense_ratios"]
        first = len(g.rows) + 1
        for ek, label in (("tax_surcharge", "税金及附加率"), ("selling", "销售费用率"), ("admin", "管理费用率"),
                          ("rd", "研发费用率"), ("other", "其他（基期轧差：财务公司利息、折旧重分类等）")):
            add(g, "S", None, [f"　{label}", None, Cell(by["expense_ratios"][ek], fmt="pct2", input=True)]
                + [Cell(x, fmt="pct2", input=True) for x in er[ek]])
        last = len(g.rows)
        add(g, "S", f"opex_{k}", ["经营费用率（不含折旧摊销）"] + [None]
            + [Formula(f"SUM({c}{first}:{c}{last})", x, fmt="pct2")
               for c, x in zip(cols, [by["opex_pct"]] + sc["opex_pct"])], role="total")
    return g


def linked_three_statement(detail: dict[str, Any], ts_plan: dict[str, Any], analysis: dict[str, Any],
                           dcf_plan: dict[str, Any],
                           segment: dict[str, Any] | None = None) -> tuple[dict[str, Sheet], dict[str, Any]]:
    periods = detail["periods"]
    n = len(periods)
    F = [_col(2 + j) for j in range(n)]          # 预测列 D 起
    H = ["B", "C"]                                # 实际列：上年、本年
    hist = ts_plan["historicals"]
    hy = sorted(hist["income_statement"])[-2:]   # ["FY2024", "FY2025"]
    his = [hist["income_statement"][y] for y in hy]
    hbs = [hist["balance_sheet"][y] for y in hy]
    truth = {(c["metric_id"], c["period"]): c["value"] for c in analysis["truth_table"]}
    tv = lambda m, fy: (truth.get((m, fy[2:])) or 0.0) / 1e6  # noqa: E731
    b = detail["base"]
    IS_, WC, PPE, DEBT = b["income_statement"], b["working_capital"], b["ppe"], b["debt"]
    CF_, BS_, EQ = b["cash_flow_statement"], b["balance_sheet"], b["equity_flows"]
    drv, sc = detail["drivers"], detail["scenarios"]
    rows: dict[tuple[str, str], int] = {}
    head = lambda title: [title] + [f"{y}A" for y in hy] + [f"{p}E" for p in periods]  # noqa: E731

    def add(g: _Grid, sid: str, key: str | None, cells: list[Any], **kw: Any) -> int:
        if key and (sid, key) in ROW_NOTES:
            kw.setdefault("note", ROW_NOTES[(sid, key)])
        r = g.add(cells, **kw)
        if key:
            rows[(sid, key)] = r
        return r

    # ------------------------------------------------ 利润表历史与缓存值（先算好，假设页的历史比率要用）
    h_nonop = [tv("investment_income", y) + tv("fair_value_change", y) for y in hy]
    h_gp = [x["revenue"] - x["cogs"] for x in his]
    h_ebit = [gp - x["opex"] - x["da"] for gp, x in zip(h_gp, his)]
    h_tp = [e - x["interest"] + nn for e, x, nn in zip(h_ebit, his, h_nonop)]
    h_capex = [tv("capex", y) for y in hy]
    h_nwc = [bs["ar"] + bs["inventory"] - bs["ap"] for bs in hbs]

    gS = _segment_sheet(segment, F, n, add, head) if segment else None

    # ================================================ 三表-假设
    gA = _Grid("三表联动模型：驱动假设与辅助计算", NOTE + "；改 B5 情景开关（1 悲观 / 2 基准 / 3 乐观）即联动三表与 DCF")
    add(gA, "A", None, head("驱动假设"), role="header")
    sel = add(gA, "A", "sel", ["情景开关（1 悲观 / 2 基准 / 3 乐观）", Cell(2, fmt="int", input=True, role="key"),
                               Formula('CHOOSE(B5,"悲观","基准","乐观")', "基准", role="key")])
    assert sel == 5, "情景开关须在 B5（说明文字引用）"

    def scen_rows(key: str, label: str, name: str, fmt: str, hist_cells: list[Any] | None = None,
                  seg_key: str | None = None) -> None:
        rs = {}
        for k, cn in SCEN_CN:
            if gS is not None and seg_key:  # 分部驱动：引用“分部预测”页（绿色）
                vals = [Formula(_t("S", f"{seg_key}_{k}", c), v, fmt=fmt) for c, v in zip(F, sc[k][name])]
            else:
                vals = [Cell(v, fmt=fmt, input=True) for v in sc[k][name]]
            rs[k] = add(gA, "A", f"{key}_{k}", [f"　{label}：{cn}", None, None] + vals)
        add(gA, "A", key, [f"{label}（选用）"] + (hist_cells or [None, None])
            + [Formula(f"CHOOSE($B${sel},{c}{rs['downside']},{c}{rs['base']},{c}{rs['upside']})", v, fmt=fmt)
               for c, v in zip(F, sc["base"][name])], role="total")

    def one_row(key: str, label: str, vals: list[float], fmt: str, hist_cells: list[Any] | None = None) -> None:
        add(gA, "A", key, [label] + (hist_cells or [None, None]) + [Cell(v, fmt=fmt, input=True) for v in vals])

    add(gA, "A", None, ["收入与利润率"], role="section")
    scen_rows("g", "收入增速", "revenue_growth", "pct1",
              [None, Formula(f"{_t('IS', 'rev', 'C')}/{_t('IS', 'rev', 'B')}-1", his[1]["revenue"] / his[0]["revenue"] - 1, fmt="pct1")],
              seg_key="g")
    scen_rows("gm", "毛利率", "gross_margin", "pct1",
              [Formula(f"1-{_t('IS', 'cogs', c)}/{_t('IS', 'rev', c)}", 1 - x["cogs"] / x["revenue"], fmt="pct1") for c, x in zip(H, his)],
              seg_key="gm")
    opex_hist = [Formula(f"{_t('IS', 'opex', c)}/{_t('IS', 'rev', c)}", x["opex"] / x["revenue"], fmt="pct1") for c, x in zip(H, his)]
    if gS is not None:
        scen_rows("opex", "经营费用率（不含折旧摊销，含税金及附加）", "opex_pct", "pct1", opex_hist, seg_key="opex")
    else:
        one_row("opex", "经营费用率（不含折旧摊销，含税金及附加）", drv["opex_pct"], "pct1", opex_hist)
    one_row("tax", "所得税率", [drv["tax_rate"]] * n, "pct1",
            [Formula(f"{_t('IS', 'tax', c)}/{_t('IS', 'tp', c)}", x["taxes"] / tp, fmt="pct1") for c, x, tp in zip(H, his, h_tp)])
    if drv.get("dividend_payout"):
        one_row("payout", "现金分红率（占净利润）", drv["dividend_payout"], "pct1")

    add(gA, "A", None, ["营运资本（天）"], role="section")
    scen_rows("ar_days", "应收账款周转天数", "ar_days", "num2",
              [Formula(f"{_t('BS', 'ar', c)}/{_t('IS', 'rev', c)}*365", bs["ar"] / x["revenue"] * 365, fmt="num2")
               for c, x, bs in zip(H, his, hbs)])
    one_row("inv_days", "存货周转天数（按营业成本）", drv["inventory_days"], "num1",
            [Formula(f"{_t('BS', 'inv', c)}/{_t('IS', 'cogs', c)}*365", bs["inventory"] / x["cogs"] * 365, fmt="num1")
             for c, x, bs in zip(H, his, hbs)])
    one_row("ap_days", "应付账款周转天数（按营业成本）", drv["ap_days"], "num1",
            [Formula(f"{_t('BS', 'ap', c)}/{_t('IS', 'cogs', c)}*365", bs["ap"] / x["cogs"] * 365, fmt="num1")
             for c, x, bs in zip(H, his, hbs)])

    add(gA, "A", None, ["资本开支、折旧与财务"], role="section")
    scen_rows("capex_pct", "资本开支 / 收入", "capex_pct_revenue", "pct1",
              [Formula(f"-{_t('CF', 'capex', c)}/{_t('IS', 'rev', c)}", cx / x["revenue"], fmt="pct1") for c, x, cx in zip(H, his, h_capex)])
    one_row("dep_rate", "折旧率（期初 PP&E + 半年资本开支）", drv["dep_rate"], "pct1",
            [None, Formula(f"{_t('IS', 'da', 'C')}/({_t('BS', 'ppe', 'B')}-0.5*{_t('CF', 'capex', 'C')})",
                           his[1]["da"] / (hbs[0]["ppe_net"] + 0.5 * h_capex[1]), fmt="pct1")])
    one_row("int_rate", "利率（财务费用 / 平均有息负债；财务费用为净利息收入时为负）", drv["interest_rate"], "pct1",
            [None, Formula(f"{_t('IS', 'int', 'C')}/AVERAGE({_t('BS', 'debt', 'B')},{_t('BS', 'debt', 'C')})",
                           his[1]["interest"] / ((hbs[0]["debt"] + hbs[1]["debt"]) / 2), fmt="pct1")])
    one_row("mand", "有息负债计划还款", drv["mandatory_amortization"], "num1")

    add(gA, "A", None, ["估值参数（DCF，全预测期适用）"], role="section")
    dsc = dcf_plan["scenarios"]
    for key, label, field, fmt in (("tg", "永续增长率", "terminal_growth_rate", "pct2"),
                                   ("wacc_adj", "WACC 情景调整", "wacc_adjustment", "pct2")):
        rs = {k: add(gA, "A", f"{key}_{k}", [f"　{label}：{cn}", None, None, Cell(float(dsc[k][field]), fmt=fmt, input=True)])
              for k, cn in (("downside", "悲观"), ("base", "基准"), ("upside", "乐观"))}
        add(gA, "A", key, [f"{label}（选用）", None, None,
                           Formula(f"CHOOSE($B${sel},D{rs['downside']},D{rs['base']},D{rs['upside']})",
                                   float(dsc["base"][field]), fmt=fmt)], role="total")

    # 辅助计算
    ra = rows
    add(gA, "A", None, ["辅助计算：营运资本"], role="section")
    add(gA, "A", "ar", ["应收账款"] + [Formula(_t("BS", "ar", c), bs["ar"]) for c, bs in zip(H, hbs)]
        + [Formula(f"{_t('IS', 'rev', c)}*{c}{ra[('A', 'ar_days')]}/365", v) for c, v in zip(F, WC["ar"])])
    add(gA, "A", "inv", ["存货"] + [Formula(_t("BS", "inv", c), bs["inventory"]) for c, bs in zip(H, hbs)]
        + [Formula(f"{_t('IS', 'cogs', c)}*{c}{ra[('A', 'inv_days')]}/365", v) for c, v in zip(F, WC["inventory"])])
    add(gA, "A", "ap", ["应付账款"] + [Formula(_t("BS", "ap", c), bs["ap"]) for c, bs in zip(H, hbs)]
        + [Formula(f"{_t('IS', 'cogs', c)}*{c}{ra[('A', 'ap_days')]}/365", v) for c, v in zip(F, WC["ap"])])
    r_nwc = len(gA.rows) + 1
    add(gA, "A", "nwc", ["营运资本（应收 + 存货 − 应付）"]
        + [Formula(f"{c}{ra[('A', 'ar')]}+{c}{ra[('A', 'inv')]}-{c}{ra[('A', 'ap')]}", v)
           for c, v in zip(H + F, h_nwc + WC["nwc"])], role="total")
    add(gA, "A", "dnwc", ["营运资本增加", None, Formula(f"C{r_nwc}-B{r_nwc}", h_nwc[1] - h_nwc[0])]
        + [Formula(f"{c}{r_nwc}-{_prev(c)}{r_nwc}", v) for c, v in zip(F, WC["change_nwc"])])

    add(gA, "A", None, ["辅助计算：固定资产（固定资产 + 在建工程）"], role="section")
    r_beg = len(gA.rows) + 1
    r_cap, r_dep, r_end = r_beg + 1, r_beg + 2, r_beg + 3
    add(gA, "A", "ppe_beg", ["期初余额", None, None]
        + [Formula(_t("BS", "ppe", "C") if j == 0 else f"{_prev(c)}{r_end}", v) for j, (c, v) in enumerate(zip(F, PPE["beginning_ppe"]))])
    add(gA, "A", "capex", ["加：资本开支", None, None]
        + [Formula(f"{_t('IS', 'rev', c)}*{c}{ra[('A', 'capex_pct')]}", v) for c, v in zip(F, PPE["capex"])])
    add(gA, "A", "dep", ["减：折旧摊销", None, None]
        + [Formula(f"({c}{r_beg}+0.5*{c}{r_cap})*{c}{ra[('A', 'dep_rate')]}", v) for c, v in zip(F, PPE["depreciation"])])
    add(gA, "A", "ppe_end", ["期末余额"] + [Formula(_t("BS", "ppe", c), bs["ppe_net"]) for c, bs in zip(H, hbs)]
        + [Formula(f"MAX(0,{c}{r_beg}+{c}{r_cap}-{c}{r_dep})", v) for c, v in zip(F, PPE["ending_ppe"])], role="total")

    add(gA, "A", None, ["辅助计算：有息负债与利息"], role="section")
    r_db = len(gA.rows) + 1
    r_rp, r_de = r_db + 1, r_db + 2
    add(gA, "A", "debt_beg", ["期初余额", None, None]
        + [Formula(_t("BS", "debt", "C") if j == 0 else f"{_prev(c)}{r_de}", v) for j, (c, v) in enumerate(zip(F, DEBT["beginning_debt"]))])
    add(gA, "A", "repay", ["减：偿还", None, None]
        + [Formula(f"MIN(MAX(0,{c}{ra[('A', 'mand')]}),{c}{r_db})", v) for c, v in zip(F, DEBT["mandatory_repayment"])])
    add(gA, "A", "debt_end", ["期末余额"] + [Formula(_t("BS", "debt", c), bs["debt"]) for c, bs in zip(H, hbs)]
        + [Formula(f"{c}{r_db}-{c}{r_rp}", v) for c, v in zip(F, DEBT["ending_debt"])], role="total")
    add(gA, "A", "interest", ["利息费用（负数为净利息收入）", None, None]
        + [Formula(f"MAX(0,{c}{r_db}-0.5*{c}{r_rp})*{c}{ra[('A', 'int_rate')]}", v) for c, v in zip(F, DEBT["interest"])])

    add(gA, "A", None, ["辅助计算：现金分红"], role="section")
    if drv.get("dividend_payout"):
        add(gA, "A", "div", ["现金分红", None, None]
            + [Formula(f"MAX(0,{_t('IS', 'ni', c)})*{c}{ra[('A', 'payout')]}", v) for c, v in zip(F, EQ["dividends"])])
    else:
        add(gA, "A", "div", ["现金分红", None, None] + [Cell(v, input=True) for v in EQ["dividends"]])

    # ================================================ 三表-利润表
    gI = _Grid("三表联动模型：利润表（情景见“三表-假设”B5，默认基准）", NOTE + "；预测期由“三表-假设”驱动")
    add(gI, "IS", None, head("利润表（百万元）"), role="header")
    ri = lambda k: rows[("IS", k)]  # noqa: E731
    add(gI, "IS", "rev", ["营业收入"] + [Cell(x["revenue"], input=True) for x in his]
        + [Formula(f"{_prev(c)}{len(gI.rows) + 1}*(1+{_t('A', 'g', c)})", v) for c, v in zip(F, IS_["revenue"])], role="total")
    add(gI, "IS", "cogs", ["营业成本"] + [Cell(x["cogs"], input=True) for x in his]
        + [Formula(f"{c}{ri('rev')}*(1-{_t('A', 'gm', c)})", v) for c, v in zip(F, IS_["cogs"])])
    add(gI, "IS", "gp", ["毛利"] + [Formula(f"{c}{ri('rev')}-{c}{ri('cogs')}", v) for c, v in zip(H + F, h_gp + IS_["gross_profit"])],
        role="total")
    add(gI, "IS", "opex", ["经营费用（不含折旧摊销）"] + [Cell(x["opex"], input=True) for x in his]
        + [Formula(f"{c}{ri('rev')}*{_t('A', 'opex', c)}", v) for c, v in zip(F, IS_["opex"])])
    add(gI, "IS", "ebitda", ["EBITDA"] + [Formula(f"{c}{ri('gp')}-{c}{ri('opex')}", v)
                                          for c, v in zip(H + F, [g - x["opex"] for g, x in zip(h_gp, his)] + IS_["ebitda"])],
        role="total")
    add(gI, "IS", "da", ["折旧摊销"] + [Cell(x["da"], input=True) for x in his]
        + [Formula(_t("A", "dep", c), v) for c, v in zip(F, IS_["da"])])
    add(gI, "IS", "ebit", ["EBIT（经营性）"] + [Formula(f"{c}{ri('ebitda')}-{c}{ri('da')}", v)
                                             for c, v in zip(H + F, h_ebit + IS_["ebit"])], role="total")
    add(gI, "IS", "int", ["利息费用（财务费用）"] + [Cell(x["interest"], input=True) for x in his]
        + [Formula(_t("A", "interest", c), v) for c, v in zip(F, IS_["interest"])])
    add(gI, "IS", "ebt", ["经营性税前利润"] + [Formula(f"{c}{ri('ebit')}-{c}{ri('int')}", v)
                                            for c, v in zip(H + F, [e - x["interest"] for e, x in zip(h_ebit, his)] + IS_["ebt"])])
    add(gI, "IS", "nonop", ["加：投资收益与公允价值变动"] + [Cell(v, input=True) for v in h_nonop] + [Cell(0.0, input=True) for _ in F])
    add(gI, "IS", "tp", ["利润总额"] + [Formula(f"{c}{ri('ebt')}+{c}{ri('nonop')}", v) for c, v in zip(H + F, h_tp + IS_["ebt"])],
        role="total")
    add(gI, "IS", "tax", ["减：所得税"] + [Cell(x["taxes"], input=True) for x in his]
        + [Formula(f"MAX({c}{ri('tp')},0)*{_t('A', 'tax', c)}", v) for c, v in zip(F, IS_["book_taxes"])])
    add(gI, "IS", "ni", ["净利润"] + [Formula(f"{c}{ri('tp')}-{c}{ri('tax')}", v)
                                    for c, v in zip(H + F, [tp - x["taxes"] for tp, x in zip(h_tp, his)] + IS_["net_income"])],
        role="key")
    add(gI, "IS", None, [])
    add(gI, "IS", None, ["主要比率"], role="section")
    revs = [x["revenue"] for x in his] + IS_["revenue"]
    gps = h_gp + IS_["gross_profit"]
    ebits = h_ebit + IS_["ebit"]
    nis = [tp - x["taxes"] for tp, x in zip(h_tp, his)] + IS_["net_income"]
    tps = h_tp + IS_["ebt"]
    taxes = [x["taxes"] for x in his] + IS_["book_taxes"]
    cols = H + F
    add(gI, "IS", None, ["营业收入增长率", None] + [Formula(f"{c}{ri('rev')}/{_prev(c)}{ri('rev')}-1", revs[i + 1] / revs[i] - 1)
                                              for i, c in enumerate(cols[1:])], fmt="pct1")
    for label, num, vals in (("毛利率", "gp", gps), ("EBIT 利润率", "ebit", ebits), ("净利率", "ni", nis)):
        add(gI, "IS", None, [label] + [Formula(f"{c}{ri(num)}/{c}{ri('rev')}", v / r) for c, v, r in zip(cols, vals, revs)], fmt="pct1")
    add(gI, "IS", None, ["有效税率"] + [Formula(f"{c}{ri('tax')}/{c}{ri('tp')}", t / p) for c, t, p in zip(cols, taxes, tps)], fmt="pct1")

    # ================================================ 三表-资产负债表
    gB = _Grid("三表联动模型：资产负债表（情景见“三表-假设”B5，默认基准）", NOTE + "；权益（含少数股东）合并列示，留存收益为预测期累计")
    add(gB, "BS", None, head("资产负债表（百万元）"), role="header")
    rb = lambda k: rows[("BS", k)]  # noqa: E731
    hv = lambda k: [Cell(bs[k], input=True) for bs in hbs]  # noqa: E731
    add(gB, "BS", None, ["资产"], role="section")
    add(gB, "BS", "cash", ["货币资金"] + hv("cash") + [Formula(_t("CF", "end", c), v) for c, v in zip(F, BS_["cash"])])
    add(gB, "BS", "ar", ["应收账款"] + hv("ar") + [Formula(_t("A", "ar", c), v) for c, v in zip(F, BS_["ar"])])
    add(gB, "BS", "inv", ["存货"] + hv("inventory") + [Formula(_t("A", "inv", c), v) for c, v in zip(F, BS_["inventory"])])
    add(gB, "BS", "ppe", ["固定资产 + 在建工程"] + hv("ppe_net") + [Formula(_t("A", "ppe_end", c), v) for c, v in zip(F, BS_["ppe_net"])])
    r_oa = len(gB.rows) + 1
    add(gB, "BS", "oa", ["其他资产（含财务公司类现金资产）"] + hv("other_assets")
        + [Formula(f"{_prev(c)}{r_oa}", v) for c, v in zip(F, BS_["other_assets"])])
    ta = [bs["total_assets"] for bs in hbs] + BS_["total_assets"]
    add(gB, "BS", "ta", ["资产总计"] + [Formula(f"SUM({c}{rb('cash')}:{c}{r_oa})", v) for c, v in zip(cols, ta)], role="total")
    add(gB, "BS", None, ["负债"], role="section")
    add(gB, "BS", "ap", ["应付账款"] + hv("ap") + [Formula(_t("A", "ap", c), v) for c, v in zip(F, BS_["ap"])])
    add(gB, "BS", "debt", ["有息负债（含租赁负债）"] + hv("debt") + [Formula(_t("A", "debt_end", c), v) for c, v in zip(F, BS_["debt"])])
    r_ol = len(gB.rows) + 1
    add(gB, "BS", "ol", ["其他负债"] + hv("other_liabilities")
        + [Formula(f"{_prev(c)}{r_ol}", v) for c, v in zip(F, BS_["other_liabilities"])])
    tl = [bs["ap"] + bs["debt"] + bs["other_liabilities"] for bs in hbs] + \
         [a + d + o for a, d, o in zip(BS_["ap"], BS_["debt"], BS_["other_liabilities"])]
    add(gB, "BS", "tl", ["负债合计"] + [Formula(f"SUM({c}{rb('ap')}:{c}{r_ol})", v) for c, v in zip(cols, tl)], role="total")
    add(gB, "BS", None, ["所有者权益"], role="section")
    r_ce = len(gB.rows) + 1
    add(gB, "BS", "ce", ["股本、资本公积及其他权益"] + hv("common_equity")
        + [Formula(f"{_prev(c)}{r_ce}", v) for c, v in zip(F, BS_["common_equity"])])
    r_re = len(gB.rows) + 1
    add(gB, "BS", "re", ["留存收益（预测期累计）"] + hv("retained_earnings")
        + [Formula(f"{_prev(c)}{r_re}+{_t('IS', 'ni', c)}-{_t('A', 'div', c)}", v) for c, v in zip(F, BS_["retained_earnings"])])
    te = [bs["common_equity"] + bs["retained_earnings"] for bs in hbs] + \
         [a + b_ for a, b_ in zip(BS_["common_equity"], BS_["retained_earnings"])]
    add(gB, "BS", "te", ["所有者权益合计"] + [Formula(f"{c}{r_ce}+{c}{r_re}", v) for c, v in zip(cols, te)], role="total")
    tle = [a + b_ for a, b_ in zip(tl, te)]
    add(gB, "BS", "tle", ["负债和所有者权益总计"] + [Formula(f"{c}{rb('tl')}+{c}{rb('te')}", v) for c, v in zip(cols, tle)],
        role="key")
    add(gB, "BS", None, [])
    add(gB, "BS", None, ["勾稽检查（应全部为 0，显示为“-”）"], role="section")
    r_c1 = add(gB, "BS", "chk_bs", ["资产总计 − 负债和所有者权益总计"]
               + [Formula(f"ROUND({c}{rb('ta')}-{c}{rb('tle')},6)", 0.0) for c in cols], fmt="num2")
    add(gB, "BS", "chk_cash", ["现金流量表期末现金 − 货币资金", None, None]
        + [Formula(f"ROUND({_t('CF', 'end', c)}-{c}{rb('cash')},6)", 0.0) for c in F], fmt="num2")
    add(gB, "BS", "chk_re", ["留存收益滚动（期初 + 净利润 − 分红 − 期末）", None, None]
        + [Formula(f"ROUND({_prev(c)}{r_re}+{_t('IS', 'ni', c)}-{_t('A', 'div', c)}-{c}{r_re},6)", 0.0) for c in F], fmt="num2")
    add(gB, "BS", "chk_ppe", ["PP&E 滚动（期初 + 资本开支 − 折旧 − 期末）", None, None]
        + [Formula(f"ROUND({_t('A', 'ppe_beg', c)}+{_t('A', 'capex', c)}-{_t('A', 'dep', c)}-{_t('A', 'ppe_end', c)},6)", 0.0)
           for c in F], fmt="num2")
    r_c5 = add(gB, "BS", "chk_debt", ["有息负债滚动（期初 − 偿还 − 期末）", None, None]
               + [Formula(f"ROUND({_t('A', 'debt_beg', c)}-{_t('A', 'repay', c)}-{_t('A', 'debt_end', c)},6)", 0.0)
                  for c in F], fmt="num2")
    # 不用 SUMPRODUCT(ABS(二维区域))：Excel 支持该数组写法，但部分轻量重算引擎会返回 #VALUE!。
    # 逐单元格 ABS 后求和数学等价，也能在 Windows Excel、LibreOffice 与验证引擎中稳定重算。
    check_sum = ",".join(f"ABS({c}{r})" for r in range(r_c1, r_c5 + 1) for c in cols)
    add(gB, "BS", "chk_all", ["勾稽结论", Formula(f'IF(SUM({check_sum})<0.001,"全部平衡","不平衡，请检查")',
                                                "全部平衡", role="key")])

    # ================================================ 三表-现金流量表
    gC = _Grid("三表联动模型：现金流量表（情景见“三表-假设”B5，默认基准）", NOTE + "；实际年度经营现金流为报表值，“其他经营项目”为轧差（含财务公司存款变动）")
    add(gC, "CF", None, head("现金流量表（百万元）"), role="header")
    rc = lambda k: rows[("CF", k)]  # noqa: E731
    h_cfo = [tv("ocf", y) for y in hy]
    add(gC, "CF", None, ["经营活动"], role="section")
    add(gC, "CF", "ni", ["净利润"] + [Formula(_t("IS", "ni", c), v) for c, v in zip(cols, nis)])
    add(gC, "CF", "da", ["加：折旧摊销"] + [Formula(_t("IS", "da", c), v) for c, v in zip(cols, [x["da"] for x in his] + IS_["da"])])
    add(gC, "CF", "dnwc", ["减：营运资本增加", None, Formula(f"-{_t('A', 'dnwc', 'C')}", -(h_nwc[1] - h_nwc[0]))]
        + [Formula(f"-{_t('A', 'dnwc', c)}", -v) for c, v in zip(F, CF_["change_nwc"])])
    r_other = len(gC.rows) + 1
    r_cfo = r_other + 1
    other_c = h_cfo[1] - nis[1] - his[1]["da"] + (h_nwc[1] - h_nwc[0])
    add(gC, "CF", "other", ["其他经营项目", None,
                            Formula(f"C{r_cfo}-C{rc('ni')}-C{rc('da')}-C{rc('dnwc')}", other_c)]
        + [Cell(0.0, input=True) for _ in F])
    add(gC, "CF", "cfo", ["经营活动现金流量净额"] + [Cell(v, input=True) for v in h_cfo]
        + [Formula(f"SUM({c}{rc('ni')}:{c}{r_other})", v) for c, v in zip(F, CF_["cash_flow_from_operations"])], role="total")
    add(gC, "CF", None, ["投资活动"], role="section")
    add(gC, "CF", "capex", ["购建长期资产（资本开支）"] + [Cell(-v, input=True) for v in h_capex]
        + [Formula(f"-{_t('A', 'capex', c)}", -v) for c, v in zip(F, CF_["capex"])])
    add(gC, "CF", "cfi", ["投资活动现金流量净额（模型口径）", None, None]
        + [Formula(f"{c}{rc('capex')}", v) for c, v in zip(F, CF_["cash_flow_from_investing"])], role="total")
    add(gC, "CF", None, ["筹资活动"], role="section")
    add(gC, "CF", "repay", ["偿还有息负债", None, None] + [Formula(f"-{_t('A', 'repay', c)}", -v) for c, v in zip(F, DEBT["total_repayments"])])
    add(gC, "CF", "div", ["现金分红", None, None] + [Formula(f"-{_t('A', 'div', c)}", -v) for c, v in zip(F, EQ["dividends"])])
    add(gC, "CF", "cff", ["筹资活动现金流量净额（模型口径）", None, None]
        + [Formula(f"{c}{rc('repay')}+{c}{rc('div')}", v) for c, v in zip(F, CF_["cash_flow_from_financing"])], role="total")
    add(gC, "CF", None, [])
    add(gC, "CF", "net", ["现金净增加额", None, None]
        + [Formula(f"{c}{rc('cfo')}+{c}{rc('cfi')}+{c}{rc('cff')}", v) for c, v in zip(F, CF_["cash_change"])])
    r_beg_c = len(gC.rows) + 1
    add(gC, "CF", "beg", ["期初现金", None, None]
        + [Formula(_t("BS", "cash", "C") if j == 0 else f"{_prev(c)}{r_beg_c + 1}", v)
           for j, (c, v) in enumerate(zip(F, DEBT["beginning_cash"]))])
    add(gC, "CF", "end", ["期末现金", None, None] + [Formula(f"{c}{r_beg_c}+{c}{rc('net')}", v) for c, v in zip(F, CF_["ending_cash"])],
        role="key")

    # ------------------------------------------------ 替换跨表占位符
    def sub(expr: str) -> str:
        return TOKEN.sub(lambda m: f"'{SHEETS[m.group(1)]}'!{m.group(3)}{rows[(m.group(1), m.group(2))]}", expr)

    for g in (gA, gI, gB, gC) + ((gS,) if gS is not None else ()):
        for row in g.rows:
            for cell in row:
                if isinstance(cell, Formula):
                    cell.expr = sub(cell.expr)

    fmt = {c: "num1" for c in range(1, n + 3)}
    kw = dict(formats=fmt, widths={0: 40, **{c: 12 for c in range(1, n + 3)}})
    sheets = {
        **({SHEETS["S"]: gS.sheet(**kw, tab_color="C65911")} if gS is not None else {}),
        SHEETS["A"]: gA.sheet(**kw, tab_color="C65911"),
        SHEETS["IS"]: gI.sheet(**kw, tab_color="1F3864"),
        SHEETS["BS"]: gB.sheet(**kw, tab_color="1F3864"),
        SHEETS["CF"]: gC.sheet(**kw, tab_color="1F3864"),
    }
    link = lambda sid, key: [f"'{SHEETS[sid]}'!{c}{rows[(sid, key)]}" for c in F]  # noqa: E731
    links = {"rev": link("IS", "rev"), "cogs": link("IS", "cogs"), "gp": link("IS", "gp"), "ebit": link("IS", "ebit"),
             "da": link("IS", "da"), "ni": link("IS", "ni"), "capex": link("A", "capex"), "dnwc": link("A", "dnwc"),
             "tax": link("A", "tax"), "tg": f"'{SHEETS['A']}'!$D${rows[('A', 'tg')]}",
             "wacc_adj": f"'{SHEETS['A']}'!$D${rows[('A', 'wacc_adj')]}"}
    return sheets, links
