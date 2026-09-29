"""估值模型工作簿 model.xlsx（投行排版）：估值汇总 → 盈利预测 → DCF → WACC → 敏感性 → 非经营性资产 → 三表 → 历史财务 → 分季度 → 经营数据 → 可比公司 → 模型检查。

期间横排（FY2024A 实际 + 预测期），单位写在表头；蓝色为输入（财报抽取值与三表模型输出），黑色为公式。
DCF 页的 NOPAT、自由现金流、折现、终值、股权桥与每股价值、WACC 页的股权成本与 WACC 都写成公式，
缓存值取自引擎计算结果，在 Excel 中重算结果相同（tests/test_quarterly_ebit.py 核对）。
"""

from __future__ import annotations

import re
from typing import Any

from ...output.xlsx import Cell, Formula, Sheet
from .run import SCEN_CN

UNIT_NOTE = "单位：百万元（每股为元）；蓝色为输入（财报抽取值、三表模型输出、估值假设），黑色为公式，绿色为跨表引用"
TOTAL_ROWS = {"毛利", "EBITDA", "EBIT", "净利润", "资产总计", "负债和权益总计", "经营活动现金流", "期末现金"}


class _Grid:
    """按行追加内容并记住行号，便于公式引用（行号为 Excel 的 1 起始行号）。"""

    def __init__(self, title: str, note: str = UNIT_NOTE):
        self.rows: list[list[Any]] = [[title], [note], []]
        self.roles: dict[int, str] = {0: "title", 1: "note"}
        self.row_formats: dict[int, str] = {}
        self.notes: dict[int, str] = {}
        self.at: dict[str, int] = {}

    def add(self, row: list[Any], *, key: str | None = None, role: str | None = None, fmt: str | None = None,
            note: str | None = None) -> int:
        self.rows.append(row)
        i = len(self.rows) - 1
        if role:
            self.roles[i] = role
        if fmt:
            self.row_formats[i] = fmt
        if note:
            self.notes[i] = note
        if key:
            self.at[key] = i + 1
        return i + 1

    def sheet(self, **kw: Any) -> Sheet:
        header = next((i for i, r in self.roles.items() if r == "header"), 3)
        kw.setdefault("freeze", (header + 1, 1))
        kw.setdefault("notes", self.notes)
        return Sheet(self.rows, roles=self.roles, row_formats=self.row_formats, header_rows=0, **kw)


def _col(i: int) -> str:
    return chr(66 + i)  # 第 i 个数据列（B 起）


# ------------------------------------------------------------------ 估值汇总
def _summary(company: str, plan: dict[str, Any], res: dict[str, Any], comps: dict[str, Any] | None) -> Sheet:
    g = _Grid(f"{company} 估值汇总", f"估值基准日 {plan['meta']['valuation_date']}；模型状态 {res['model_status']}；"
                                     "DCF 各情景经营预测取自三表模型；不构成投资建议")
    g.add(["情景", "WACC", "永续增长率", "企业价值（百万元）", "股权价值（百万元）", "每股价值（元）", "较现价空间",
           "终值占 EV", "隐含 EV/EBITDA", "情景说明"], role="header")
    for s in res["scenarios"]:
        g.add([s["scenario_cn"], s["wacc"], s["terminal_growth"], s["enterprise_value_mm"], s["equity_value_mm"],
               s["value_per_share"], s["upside_vs_price"], s["tv_percent_ev"], s["implied_exit_ebitda"],
               s["description"]], role="key" if s["scenario"] == "base" else None)
    g.add([])
    g.add(["方法", "低", "中/基准", "高"], role="header")
    vr = res["value_range"]
    g.add(["DCF 每股价值（元）", vr["low"], vr["base"], vr["high"]], fmt="num2")
    if comps and comps.get("range"):
        r = comps["range"]
        g.add(["可比公司隐含股价（元）", r["low"], r["mid"], r["high"]], fmt="num2")
    if res.get("current_price"):
        g.add(["参考股价（元）", None, res["current_price"], None], fmt="num2")
    tie = res.get("three_statement_tie")
    if tie:
        g.add([f"DCF 与三表模型逐期核对：最大偏差 {tie['max_abs_diff_mm']:.2e} 百万元（{'一致' if tie['status'] == 'pass' else '不一致'}）"],
              role="note")
    return g.sheet(formats={1: "pct2", 2: "pct1", 3: "num1", 4: "num1", 5: "num2", 6: "pct1", 7: "pct1", 8: "mult"},
                   widths={0: 24, 9: 46}, wrap_cols=(9,), tab_color="1F3864")


# ------------------------------------------------------------------ WACC
WACC_ROWS = [  # (键, 标签, 格式, 说明)
    ("risk_free_rate", "无风险利率", "pct2", "10 年期国债收益率"),
    ("beta", "β", "num2", "可比公司均值"),
    ("equity_risk_premium", "股权风险溢价", "pct2", ""),
    ("size_premium", "规模溢价", "pct2", ""),
    ("company_specific_premium", "公司特定风险溢价", "pct2", ""),
    ("country_risk_premium", "国别风险溢价", "pct2", ""),
]


def _wacc(plan: dict[str, Any], res: dict[str, Any]) -> tuple[Sheet, str]:
    w, wb = plan["wacc"], res["wacc_base"]
    g = _Grid("WACC 测算（基准情景）", "蓝色为估值假设文件输入，黑色为公式；各情景在基准 WACC 上加情景调整")
    g.add(["项目", "数值", "说明"], role="header")
    for k, label, fmt, note in WACC_ROWS:
        g.add([label, Cell(float(w.get(k) or 0.0), fmt=fmt, input=True), note], key=k)
    a = g.at
    ke = f"B{a['risk_free_rate']}+B{a['beta']}*B{a['equity_risk_premium']}+B{a['size_premium']}" \
         f"+B{a['company_specific_premium']}+B{a['country_risk_premium']}"
    g.add(["股权成本 Ke", Formula(ke, wb["cost_of_equity"], fmt="pct2"), "Rf + β × ERP + 各项溢价"], key="ke", role="total")
    g.add(["税前债务成本", Cell(float(w["pre_tax_cost_of_debt"]), fmt="pct2", input=True), ""], key="kd_pre")
    g.add(["边际税率", Cell(float(w["marginal_tax_rate"]), fmt="pct1", input=True), ""], key="tax")
    g.add(["税后债务成本 Kd", Formula(f"B{a['kd_pre']}*(1-B{a['tax']})", wb["after_tax_cost_of_debt"], fmt="pct2"),
           "税前债务成本 × (1 − 税率)"], key="kd", role="total")
    g.add(["目标债务占比", Cell(float(w["target_debt_pct"]), fmt="pct1", input=True), ""], key="wd")
    g.add(["目标股权占比", Cell(float(w["target_equity_pct"]), fmt="pct1", input=True), ""], key="we")
    g.add(["优先股占比", Cell(float(w.get("preferred_pct") or 0.0), fmt="pct1", input=True), ""], key="wp")
    g.add(["优先股成本", Cell(float(w.get("pre_tax_cost_of_preferred") or 0.0), fmt="pct2", input=True), ""], key="kp")
    g.add(["情景调整（基准）", Cell(float(wb["scenario_wacc_adjustment"]), fmt="pct2", input=True), ""], key="adj")
    g.add(["WACC", Formula(f"B{a['we']}*B{a['ke']}+B{a['wd']}*B{a['kd']}+B{a['wp']}*B{a['kp']}+B{a['adj']}",
                           wb["wacc"], fmt="pct2"), "E% × Ke + D% × Kd + P% × Kp + 情景调整"], key="wacc", role="key")
    return g.sheet(widths={0: 22, 1: 12, 2: 36}), f"WACC!$B${a['wacc']}"


# ------------------------------------------------------------------ DCF
def _dcf(plan: dict[str, Any], res: dict[str, Any], wacc_ref: str, non_op_ref: str | None = None,
         ts: dict[str, Any] | None = None) -> Sheet:
    h, fr, pv = plan["historicals"], res["forecast_base"], res["pv_base"]["pv_rows"]
    base = next(s for s in res["scenarios"] if s["scenario"] == "base")
    n = len(fr)
    hist_col, cols = "B", [_col(i + 1) for i in range(n)]  # 历史列 B，预测列 C 起
    last = cols[-1]
    g = _Grid(f"{plan['meta']['company']} DCF 估值（FCFF，" + ("情景随“三表-假设”B5 开关，默认基准）" if ts else "基准情景）"),
              UNIT_NOTE + ("；预测期经营数据引用三表联动页" if ts else ""))
    g.add(["项目（百万元）", f"FY{h['latest_year']}A"] + [f"FY{r['period']}E" for r in fr], role="header")

    def inputs(label: str, key: str, hist_v: float | None, fc_key: str, link: str | None = None,
               note: str | None = None, **kw: Any) -> int:
        if ts and link:  # 预测期引用三表联动页（绿色跨表引用）
            return g.add([label, hist_v] + [Formula(ref, r[fc_key]) for ref, r in zip(ts[link], fr)],
                         key=key, fmt="num1", note=note, **kw)
        return g.add([label, hist_v] + [r[fc_key] for r in fr], key=key, fmt="num1", note=note, **kw)

    inputs("营业收入", "rev", h["revenue"], "revenue", "rev",
           note="历史期取合并报表真值表；预测期引用三表-利润表。")
    a = g.at
    g.add(["收入增速", None] + [Formula(f"{c}{a['rev']}/{p}{a['rev']}-1", r["revenue_growth"])
                                for p, c, r in zip([hist_col] + cols, cols, fr)], key="g", fmt="pct1")
    inputs("EBIT（剔除投资收益与公允价值变动）", "ebit", h["ebit"], "ebit", "ebit",
           note="经营 EBIT = 利润总额 + 财务费用 − 投资收益 − 公允价值变动收益；预测期引用三表-利润表。")
    g.add(["EBIT 利润率"] + [Formula(f"{c}{a['ebit']}/{c}{a['rev']}", e / r) for c, e, r in
                            zip([hist_col] + cols, [h["ebit"]] + [x["ebit"] for x in fr],
                                [h["revenue"]] + [x["revenue"] for x in fr])], key="m", fmt="pct1")
    if ts:
        g.add(["减：现金税（EBIT × 税率）", h["cash_taxes"]]
              + [Formula(f"{c}{a['ebit']}*{t}", r["cash_taxes"]) for c, t, r in zip(cols, ts["tax"], fr)],
              key="tax", fmt="num1", note="现金税 = 经营 EBIT × 所得税率；税率引用三表-假设。")
    else:
        inputs("减：现金税（EBIT × 税率）", "tax", h["cash_taxes"], "cash_taxes",
               note="现金税 = 经营 EBIT × 所得税率。")
    g.add(["NOPAT"] + [Formula(f"{c}{a['ebit']}-{c}{a['tax']}", e - t) for c, e, t in
                       zip([hist_col] + cols, [h["ebit"]] + [x["ebit"] for x in fr],
                       [h["cash_taxes"]] + [x["cash_taxes"] for x in fr])], key="nopat", fmt="num1", role="total",
          note="NOPAT = 经营 EBIT − 现金税。")
    inputs("加：折旧摊销", "da", h["da"], "da", "da", note="预测期引用三表-现金流量表。")
    inputs("减：资本开支", "capex", h["capex"], "capex", "capex", note="预测期引用三表-现金流量表。")
    inputs("减：营运资本增加", "dnwc", h["change_nwc"], "change_nwc", "dnwc",
           note="经营营运资本 = 应收账款 + 存货 − 应付账款；预测期引用三表-假设的辅助计算。")
    fcf = [h["unlevered_fcf"]] + [x["unlevered_fcf"] for x in fr]
    g.add(["无杠杆自由现金流（FCFF）"] + [Formula(f"{c}{a['nopat']}+{c}{a['da']}-{c}{a['capex']}-{c}{a['dnwc']}", v)
                                    for c, v in zip([hist_col] + cols, fcf)], key="fcf", fmt="num1", role="total",
          note="FCFF = NOPAT + 折旧摊销 − 资本开支 − 营运资本增加。")
    g.add([])
    g.add(["折现期（年，年中折现）", None] + [x["discount_period"] for x in pv], key="t", fmt="num1")
    g.add(["折现系数", None] + [Formula(f"1/(1+__WACC__)^{c}{a['t']}", x["pv_cash_flow"] / x["cash_flow"]
                                        if x["cash_flow"] else None) for c, x in zip(cols, pv)], key="df", fmt="factor",
          note="年中折现：1 / (1 + WACC) ^ 折现期。")
    g.add(["FCFF 现值", None] + [Formula(f"{c}{a['fcf']}*{c}{a['df']}", x["pv_cash_flow"]) for c, x in zip(cols, pv)],
          key="pv", fmt="num1", role="total")
    g.add([])

    # 估值与股权桥（B 列）
    g.add(["估值与股权桥", "百万元"], role="header")
    rate, tg = base["wacc"], base["terminal_growth"]
    if ts:  # WACC = 基准 WACC + 情景调整；永续增长率随三表情景开关
        g.add(["WACC（基准 + 情景调整）", Formula(f"{wacc_ref}+{ts['wacc_adj']}", rate, fmt="pct2")], key="wacc")
        g.add(["永续增长率", Formula(ts["tg"], tg, fmt="pct2")], key="tg")
    else:
        g.add(["WACC", Formula(wacc_ref, rate, fmt="pct2")], key="wacc")
        g.add(["永续增长率", Cell(tg, fmt="pct2", input=True)], key="tg")
    for row in g.rows:  # 折现系数引用本页 WACC 单元格
        for cell in row:
            if isinstance(cell, Formula) and "__WACC__" in cell.expr:
                cell.expr = cell.expr.replace("__WACC__", f"$B${a['wacc']}")
    pv_fcf, pv_tv = res["pv_base"]["pv_fcf"], res["pv_base"]["pv_terminal_value"]
    g.add(["预测期 FCFF 现值合计", Formula(f"SUM(C{a['pv']}:{last}{a['pv']})", pv_fcf)], key="sum_pv")
    tv = pv_tv * (1 + rate) ** n
    if plan["terminal_value"]["method"] == "perpetual_growth":
        g.add(["终值（永续增长法）", Formula(f"{last}{a['fcf']}*(1+B{a['tg']})/(B{a['wacc']}-B{a['tg']})", tv)],
              key="tv", note="Gordon 增长模型：末年 FCFF × (1 + g) / (WACC − g)。")
    else:
        g.add(["退出 EV/EBITDA 倍数", Cell(float(plan["terminal_value"]["exit_ebitda_multiple"]), fmt="mult", input=True)],
              key="mult")
        g.add(["终值（退出倍数法）", Formula(f"({last}{a['ebit']}+{last}{a['da']})*B{a['mult']}", tv)], key="tv")
    g.add(["终值现值", Formula(f"B{a['tv']}/(1+B{a['wacc']})^COUNT(C{a['t']}:{last}{a['t']})", pv_tv)], key="pv_tv")
    ev = base["enterprise_value_mm"]
    g.add(["企业价值（EV）", Formula(f"B{a['sum_pv']}+B{a['pv_tv']}", ev)], key="ev", role="total",
          note="企业价值 = 预测期 FCFF 现值合计 + 终值现值。")
    g.add(["终值占 EV", Formula(f"B{a['pv_tv']}/B{a['ev']}", pv_tv / ev, fmt="pct1")], key="tvp")
    b = plan["ev_to_equity_bridge"]
    bridge = [("cash", "加：货币资金", 1), ("non_operating_assets", "加：非经营性资产", 1), ("associates", "加：联营投资", 1),
              ("debt", "减：有息负债", -1), ("leases", "减：租赁负债", -1), ("minorities", "减：少数股东权益", -1)]
    other = sum(float(b.get(k) or 0.0) for k in ("pensions", "preferred_stock", "options", "other_debt_like_items"))
    terms = [f"B{a['ev']}"]
    for k, label, sign in bridge:
        v = float(b.get(k) or 0.0)
        g.add([label, Formula(non_op_ref, v) if k == "non_operating_assets" and non_op_ref else Cell(v, input=True)], key=k)
        terms.append(("+" if sign > 0 else "-") + f"B{a[k]}")
    g.add(["减：养老金、优先股、期权及其他类债务", Cell(other, input=True)], key="other")
    terms.append(f"-B{a['other']}")
    g.add(["股权价值", Formula("".join(terms), base["equity_value_mm"])], key="eq", role="total",
          note="股权价值 = 企业价值 + 货币资金 + 非经营性资产 + 联营投资 − 有息负债 − 租赁负债 − 少数股东权益等。")
    g.add(["摊薄股本（百万股）", Cell(float(b["diluted_shares"]), input=True)], key="sh")
    g.add(["每股价值（元）", Formula(f"B{a['eq']}/B{a['sh']}", base["value_per_share"], fmt="num2")],
          key="vps", role="key", note="每股价值 = 股权价值（百万元）/ 摊薄股本（百万股）。")
    if res.get("current_price"):
        g.add(["参考股价（元）", Cell(res["current_price"], fmt="num2", input=True)], key="px")
        g.add(["较现价空间", Formula(f"B{a['vps']}/B{a['px']}-1", base["upside_vs_price"], fmt="pct1")])
    rows_with_inputs = {a[k] - 1 for k in ("rev", "ebit", "tax", "da", "capex", "dnwc", "t")}
    for i in rows_with_inputs:  # 输入行标蓝（公式行由 Formula 自动为黑色）
        g.rows[i] = [g.rows[i][0]] + [Cell(v, input=True) if isinstance(v, (int, float)) else v for v in g.rows[i][1:]]
    return g.sheet(formats={c: "num1" for c in range(1, n + 2)}, widths={0: 34})


# ------------------------------------------------------------------ 敏感性
AXES = {  # 轴 → (标签, 格式, 基准值取法)
    "wacc_delta": ("WACC", "pct2", lambda base, plan: base["wacc"]),
    "terminal_growth_delta": ("永续增长率", "pct2", lambda base, plan: base["terminal_growth"]),
    "exit_multiple_delta": ("退出 EV/EBITDA", "mult", lambda base, plan: float(plan["terminal_value"].get("exit_ebitda_multiple") or 0)),
    "revenue_growth_delta": ("收入增速变动", "dpct", None),
    "ebit_margin_delta": ("EBIT 利润率变动", "dpct", None),
}


def _sensitivity(plan: dict[str, Any], res: dict[str, Any]) -> Sheet:
    base = next(s for s in res["scenarios"] if s["scenario"] == "base")
    g = _Grid("DCF 敏感性分析（基准情景，每股价值，元）", "黄色为基准情景；WACC、永续增长率与退出倍数为绝对值，收入增速与利润率为相对基准的变动")

    def axis(name: str, vals: list[float]) -> tuple[str, str, list[float]]:
        label, fmt, fn = AXES.get(name, (name, "dpct", None))
        return label, fmt, [v + fn(base, plan) for v in vals] if fn else vals

    for grid in res["sensitivities"]:
        xl, xf, xs = axis(grid["x_axis"], grid["x_values"])
        yl, yf, ys = axis(grid["y_axis"], grid["y_values"])
        g.add([grid["name"]], role="section")
        g.add([f"{xl} ↓ ／ {yl} →"] + [Cell(y, fmt=yf) for y in ys], role="header")
        for x0, x, row in zip(grid["x_values"], xs, grid["matrix"]):
            g.add([Cell(x, fmt=xf, role="axis")] + [Cell(v, role="key" if x0 == 0 and y0 == 0 else None)
                                        for y0, v in zip(grid["y_values"], row)])
        g.add([])
    width = max(len(gr["y_values"]) for gr in res["sensitivities"])
    return g.sheet(formats={c: "num2" for c in range(1, width + 1)}, widths={0: 30}, freeze=(3, 1))


# ------------------------------------------------------------------ 三表、可比公司、检查
# 三表实际列：利润表的毛利、EBITDA、EBIT、税前利润与资产负债表平衡差写成公式，其余取三表模型历史基数（蓝色）
_HIST_KEYS = {"利润表": ("income_statement", {"book_taxes": "taxes"}),
              "资产负债表": ("balance_sheet", {}),
              "现金流量表": ("cash_flow", {"cash_flow_from_operations": "cfo"})}
_HIST_FORMULAS = {"gross_profit": ("revenue", "-", "cogs"), "ebitda": ("gross_profit", "-", "opex"),
                  "ebit": ("ebitda", "-", "da"), "ebt": ("ebit", "-", "interest"),
                  "balance_check": ("total_assets", "-", "total_liabilities_equity")}
_STATEMENT_NOTES = {
    "利润表": "；实际列净利润为报表值，含投资收益与公允价值变动（EBIT 口径已剔除），故与税前利润 − 所得税不完全相等",
    "现金流量表": "；实际列经营活动现金流为报表值（含财务公司存款变动等），不是净利润 + 折旧摊销 − 营运资本增加",
}


def _statement(name: str, st: dict[str, Any], hist: dict[str, Any] | None = None) -> Sheet:
    section, alias = _HIST_KEYS.get(name, ("", {}))
    actual = None
    if hist and section in hist:
        year = sorted(hist[section])[-1]
        actual = (year, hist[section][year])
    if name == "现金流量表" and actual and hist.get("balance_sheet"):
        actual[1].setdefault("ending_cash", hist["balance_sheet"].get(actual[0], {}).get("cash"))
    note = "单位：百万元；口径见 valuation/report.md 第五节" + (_STATEMENT_NOTES.get(name, "") if actual else "")
    g = _Grid(f"三表联动预测：{name}（基准情景）", note)
    g.add(["项目（百万元）"] + ([f"{actual[0]}A"] if actual else []) + [f"{p}E" for p in st["periods"]], role="header")
    rows_at: dict[str, int] = {}
    for r in st["rows"]:
        vals = [0.0 if r["key"] == "balance_check" and v is not None and abs(v) < 1e-6 else v for v in r["values"]]
        lead: list[Any] = []
        if actual:
            f = _HIST_FORMULAS.get(r["key"])
            if f and f[0] in rows_at and f[2] in rows_at:
                expr = f"B{rows_at[f[0]]}{f[1]}B{rows_at[f[2]]}"
                lead = [Formula(f"ROUND({expr},6)" if r["key"] == "balance_check" else expr, None)]
            else:
                v = actual[1].get(alias.get(r["key"], r["key"]))
                lead = [Cell(v, input=True) if v is not None else None]
        rows_at[r["key"]] = g.add([r["name"]] + lead + vals, role="total" if r["name"] in TOTAL_ROWS else None,
                                  fmt="num2" if r["key"] == "balance_check" else None)
    # 公式列的缓存值：按同一公式在 Python 里算一遍（打开即显示，Excel 重算结果相同）
    if actual:
        cache: dict[str, float] = {}
        for i, r in enumerate(st["rows"]):
            row = g.rows[rows_at[r["key"]] - 1]
            cell = row[1]
            if isinstance(cell, Formula):
                a, op, b = _HIST_FORMULAS[r["key"]]
                if a in cache and b in cache:
                    cell.value = cache[a] - cache[b]
                    if r["key"] == "balance_check" and abs(cell.value) < 1e-6:
                        cell.value = 0.0
            val = cell.value if isinstance(cell, (Cell, Formula)) else None
            if isinstance(val, (int, float)):
                cache[r["key"]] = val
    n = len(st["periods"]) + (1 if actual else 0)
    return g.sheet(formats={c: "num1" for c in range(1, n + 1)}, widths={0: 26})


# ------------------------------------------------------------------ 历史财务（真值表）
_HIST_SECTIONS = [
    ("利润表", ["revenue", "operating_cost", "selling_expense", "admin_expense", "rd_expense", "finance_expense",
               "investment_income", "fair_value_change", "operating_profit", "total_profit", "income_tax",
               "net_profit", "np_parent", "np_parent_deducted", "non_recurring"]),
    ("资产负债表", ["cash", "accounts_receivable", "inventory", "fixed_assets", "construction_in_progress",
                "total_assets", "accounts_payable", "current_ltd", "lease_liab", "total_liabilities",
                "equity_parent", "minority_equity", "total_equity"]),
    ("现金流量表", ["ocf", "capex", "depreciation", "amortization"]),
    ("每股与比率", ["eps_basic", "roe_weighted", "gross_margin", "net_margin", "debt_ratio", "ocf_to_np"]),
]
# 派生比率写成公式（引用本页金额行），与 analyze 的派生口径一致
_HIST_DERIVED = {"gross_margin": "({revenue}-{operating_cost})/{revenue}", "net_margin": "{net_profit}/{revenue}",
                 "debt_ratio": "{total_liabilities}/{total_assets}", "ocf_to_np": "{ocf}/{np_parent}"}
_HIST_TOTALS = {"operating_profit", "total_profit", "net_profit", "np_parent", "total_assets", "total_liabilities",
                "total_equity", "ocf"}


def _history(analysis: dict[str, Any]) -> Sheet:
    """财报真值表：金额百万元、每股元、比率存小数；同比与合计写公式，来源列给年报页码。"""
    from ..financials.schema import BY_ID

    period = str(analysis["period"])
    prev = str(int(period[:4]) - 1)
    tt = {(c["metric_id"], c["period"]): c for c in analysis["truth_table"]}
    g = _Grid(f"历史财务数据（{prev}A / {period}A，合并报表）",
              "金额单位：百万元（每股为元）；蓝色为年报抽取值（逐字核对原文），黑色为公式；来源为年报 PDF 页码")
    g.add(["项目", f"FY{prev}A", f"FY{period}A", "同比 / 变动", "来源页", "原文科目"], role="header")

    def val(c: dict[str, Any] | None, kind: str) -> float | None:
        if c is None:
            return None
        return c["value"] / 1e6 if kind == "amount" else c["value"] / 100 if kind == "pct" else c["value"]

    rows_at: dict[str, int] = {}
    for title, metrics in _HIST_SECTIONS:
        g.add([title], role="section")
        for mid in metrics:
            m = BY_ID.get(mid)
            cur, old = tt.get((mid, period)), tt.get((mid, prev))
            if m is None or cur is None:
                continue
            kind = "amount" if m.kind == "amount" else "pct" if m.kind == "pct" or mid.endswith(("margin", "ratio")) else "other"
            if mid == "ocf_to_np":
                kind = "other"
            v1, v0 = val(cur, kind), val(old, kind)
            fmt = {"amount": "num1", "pct": "pct2"}.get(kind, "num2")
            r = len(g.rows) + 1
            if v0 is None:
                chg = None
            elif kind == "pct":
                chg = Formula(f"(C{r}-B{r})*100", (v1 - v0) * 100, fmt="pp")
            else:
                chg = Formula(f"IF(B{r}=0,\"NM\",(C{r}-B{r})/ABS(B{r}))", (v1 - v0) / abs(v0) if v0 else "NM", fmt="dpct")
            derived = cur.get("method") == "derived" or not cur.get("source", {}).get("page")
            src = "派生" if derived else f"p.{cur['source']['page']}"
            label = m.name + ("（百万元）" if kind == "amount" else "（元）" if m.kind == "per_share" else "")
            expr = _HIST_DERIVED.get(mid) if derived else None
            if expr and all(k in rows_at for k in re.findall(r"\{(\w+)\}", expr)):
                cells = [Formula(expr.format(**{k: f"{col}{n}" for k, n in rows_at.items()}), x, fmt=fmt)
                         if x is not None else None for col, x in (("B", v0), ("C", v1))]
            else:
                cells = [Cell(x, fmt=fmt, input=not derived) if x is not None else None for x in (v0, v1)]
            rows_at[mid] = g.add([label] + cells + [chg, src, "" if derived else cur.get("label", "")],
                                 role="total" if mid in _HIST_TOTALS else None)

    return g.sheet(widths={0: 46, 4: 9, 5: 44}, formats={1: "num1", 2: "num1"})


def _quarterly(analysis: dict[str, Any]) -> Sheet | None:
    """分季度数据：年报列示的单季为蓝色；非经常性损益单季 = 归母净利润 − 扣非归母净利润（公式）；四季合计与全年核对。"""
    q = analysis.get("quarterly") or {}
    if not q.get("rows"):
        return None
    tt = {(c["metric_id"], c["period"]): c for c in analysis["truth_table"]}
    qs = ("Q1", "Q2", "Q3", "Q4")
    g = _Grid(f"{q['year']} 年分季度数据（单季，合并报表）",
              "单位：百万元；蓝色为年报“分季度主要财务数据”列示值，黑色为公式；差异 = 四季合计 − 全年报表值")
    g.add(["项目（百万元）", *qs, "四季合计", "全年（报表）", "差异"], role="header")
    rows_at: dict[str, int] = {}
    for row in q["rows"]:
        vals = [row["values"].get(k) for k in qs]
        if any(v is None for v in vals):
            continue
        r = len(g.rows) + 1
        cells: list[Any] = []
        for col, k, v in zip("BCDE", qs, vals):
            if row["methods"].get(k) == "reported":
                cells.append(Cell(v / 1e6, input=True))
            elif row["metric_id"] == "non_recurring" and {"np_parent", "np_parent_deducted"} <= rows_at.keys():
                cells.append(Formula(f"{col}{rows_at['np_parent']}-{col}{rows_at['np_parent_deducted']}", v / 1e6))
            else:
                cells.append(Cell(v / 1e6, input=True))
        full = tt.get((row["metric_id"], str(q["year"])))
        fy = full["value"] / 1e6 if full else None
        diff = round(sum(vals) / 1e6 - fy, 2) if fy is not None else None
        rows_at[row["metric_id"]] = g.add(
            [row["metric"]] + cells + [Formula(f"SUM(B{r}:E{r})", sum(vals) / 1e6),
                                       Cell(fy, input=True) if fy is not None else None,
                                       Formula(f"ROUND(F{r}-G{r},2)", diff, fmt="num2") if fy is not None else None])
    return g.sheet(widths={0: 46}, formats={c: "num1" for c in range(1, 7)})


def _non_operating(items: list[dict[str, Any]]) -> tuple[Sheet, str]:
    """股权桥加回的非经营性资产明细：逐项为年报原文数（蓝色），合计为公式；DCF 页以绿色跨表引用。"""
    g = _Grid("股权桥：非经营性资产明细", "单位：百万元；逐项核对年报原文（valuation/non_operating_assets.json）；负数为类负债项")
    g.add(["项目", "百万元", "来源页", "原文数（元）"], role="header")
    first = len(g.rows) + 1
    for it in items:
        g.add([("减：" if it["sign"] < 0 else "") + it["label"], Cell(it["value_mm"], input=True),
               f"p.{(it.get('source') or {}).get('page', '')}", it["raw"]])
    last = len(g.rows)
    total = sum(it["value_mm"] for it in items)
    r = g.add(["合计", Formula(f"SUM(B{first}:B{last})", total)], role="total")
    return g.sheet(formats={1: "num1"}, widths={0: 30, 2: 9, 3: 22}), f"'非经营性资产'!$B${r}"


COMPS_COLS = [("ticker", "代码", None), ("company", "公司", None), ("peer_tier", "分层", None),
              ("equity_value", "股权价值（百万元）", "num0"), ("ev", "EV（百万元）", "num0"),
              ("ev_revenue", "EV/营业收入", "mult"), ("ev_ebitda", "EV/EBITDA", "mult"), ("ev_ebit", "EV/EBIT", "mult"),
              ("pe_ltm", "P/E（LTM）", "mult"), ("pe_ntm", "P/E（NTM）", "mult"),
              ("ebitda_margin", "EBITDA 利润率", "pct1"), ("ebit_margin", "EBIT 利润率", "pct1"), ("net_margin", "净利率", "pct1")]


def _comps(cp: dict[str, Any]) -> Sheet:
    g = _Grid("可比公司估值", "目标公司为第一行（黄色）；分母 ≤ 0 记 NM；带公式的完整版本见 comps_formula_workbook.xlsx")
    g.add([n for _, n, _ in COMPS_COLS], role="header")
    for i, r in enumerate(cp["rows"]):
        g.add([r.get(k) for k, _, _ in COMPS_COLS], role="key" if i == 0 else None)
    return g.sheet(formats={i: f for i, (_, _, f) in enumerate(COMPS_COLS) if f}, freeze=(4, 2))


# ------------------------------------------------------------------ 盈利预测（研报首页表格的公式版）
def _forecast(fs: dict[str, Any], ts: dict[str, Any] | None = None) -> Sheet:
    """实际年度为报表值（蓝色），预测年度收入、成本、净利润取三表模型基准情景（蓝色）；
    毛利、增速、归母净利润（预测期）、EPS（预测期）、P/E 写成公式。金额单位百万元。"""
    ys = fs["years"]
    cols = [_col(i) for i in range(len(ys))]
    g = _Grid("盈利预测（基准情景）", "单位：百万元（每股为元）；蓝色为报表值或三表模型输出，黑色为公式；"
                                  "预测期归母净利润 = 净利润 × 最近实际年度归母占比；EPS 按最近期末总股本摊薄")
    g.add(["项目"] + [y["year"] for y in ys], role="header")
    m6 = lambda v: None if v is None else v / 1e6  # noqa: E731
    n_a = sum(1 for y in ys if y["year"].endswith("A"))

    def src(key: str, link: str) -> list[Any]:
        """实际年度为报表值（蓝色）；预测期引用三表利润表（绿色），无三表页时为引擎输出（蓝色）。"""
        return [Cell(m6(y[key]), input=True) if (i < n_a or not ts) else Formula(ts[link][i - n_a], m6(y[key]))
                for i, y in enumerate(ys)]

    r_rev = g.add(["营业收入"] + src("revenue", "rev"), role="total")
    g.add(["营业收入增长率", None] + [Formula(f"{c}{r_rev}/{p}{r_rev}-1", (y["revenue_growth"] or 0) / 100, fmt="pct1")
                                   for p, c, y in zip(cols, cols[1:], ys[1:])])
    r_cogs = g.add(["营业成本"] + src("cogs", "cogs"))
    r_gp = g.add(["毛利"] + [Formula(f"{c}{r_rev}-{c}{r_cogs}", m6(y["gross_profit"])) for c, y in zip(cols, ys)],
                 role="total")
    g.add(["毛利率"] + [Formula(f"{c}{r_gp}/{c}{r_rev}", (y["gross_margin"] or 0) / 100, fmt="pct1")
                        for c, y in zip(cols, ys)])
    g.add(["EBIT（经营性）"] + src("ebit", "ebit"))
    r_np = g.add(["净利润"] + src("net_profit", "ni"))
    last_a = max(i for i, y in enumerate(ys) if y["year"].endswith("A"))
    a_col = cols[last_a]
    r_npp = len(g.rows) + 1
    g.add(["归母净利润"] + [Cell(m6(y["np_parent"]), input=True) if y["year"].endswith("A") else
                           Formula(f"{c}{r_np}*${a_col}${r_npp}/${a_col}${r_np}", m6(y["np_parent"]))
                           for c, y in zip(cols, ys)], role="total")
    g.add(["归母净利润增长率", None] + [Formula(f"{c}{r_npp}/{p}{r_npp}-1", (y["np_parent_growth"] or 0) / 100, fmt="pct1")
                                    for p, c, y in zip(cols, cols[1:], ys[1:])])
    g.add(["归母净利率"] + [Formula(f"{c}{r_npp}/{c}{r_rev}", (y["net_margin_parent"] or 0) / 100, fmt="pct1")
                         for c, y in zip(cols, ys)])
    m = fs["market"]
    g.add([])
    r_sh = g.add(["总股本（百万股）", Cell(m6(m["total_shares"]), input=True)], fmt="num1")
    r_px = g.add(["参考股价（元）", Cell(m["price"], input=True)], fmt="num2")
    g.add(["总市值（百万元）", Formula(f"B{r_sh}*B{r_px}", m6(m["market_cap"]))], fmt="num1")
    g.add([])
    g.add(["每股指标与估值"] + [y["year"] for y in ys], role="header")
    r_eps = g.add(["每股收益（元）"] + [Cell(y["eps"], input=True) if y["year"].endswith("A") else
                                     Formula(f"{c}{r_npp}/$B${r_sh}", y["eps"]) for c, y in zip(cols, ys)], fmt="num2")
    g.add(["P/E（倍，按参考股价）"] + [Formula(f"$B${r_px}/{c}{r_eps}", y["pe"], fmt="mult") for c, y in zip(cols, ys)])
    g.add(["注：实际年度 EPS 为报表基本每股收益（加权平均股本）；" + "；".join(fs.get("notes", []))], role="note")
    return g.sheet(formats={c: "num1" for c in range(1, len(ys) + 1)}, widths={0: 26})


# ------------------------------------------------------------------ 经营数据（补充表格）
_PLAIN_FMT = {"%": "pct2", "pp": "pp2", "吨": "num2", "个": "int", "元/股": "num2", "倍": "mult", "人": "int"}


def _operations(extras: dict[str, Any]) -> Sheet:
    """年报经营数据：逐格核对原文（蓝色）；金额换算为百万元，比例存小数；比率行写成公式。"""
    g = _Grid("经营数据（分产品 / 渠道 / 地区，量价）", "金额单位：百万元；蓝色为年报原文数（逐格核对，见 financials/extras.json），"
                                               "黑色为公式；页码为年报 PDF 页")
    at: dict[tuple[str, str, str], tuple[str, str]] = {}  # (表, 行, 列) → (单元格, 单位)
    for t in extras.get("tables", []):
        g.add([f"{t['title']}（p.{t.get('page') or ''}）"], role="section")
        names = [c["name"] for c in t["columns"]]
        units = [c["unit"] for c in t["columns"]]
        g.add(["项目"] + [n + ("（百万元）" if u == "元" else f"（{u}）" if u not in ("%", "pp") else "") for n, u in zip(names, units)],
              role="header")
        for row in t["rows"]:
            r = len(g.rows) + 1
            cells = []
            for i, (v, u) in enumerate(zip(row["values"], units)):
                at[(t["id"], row["label"], names[i])] = (f"{_col(i)}{r}", u)
                if v is None:
                    cells.append(None)
                elif u == "元":
                    cells.append(Cell(v / 1e6, fmt="num1", input=True))
                elif u == "%":
                    cells.append(Cell(v / 100, fmt="pct2", input=True))
                else:
                    cells.append(Cell(v, fmt=_PLAIN_FMT.get(u, "num2"), input=True))
            g.add([row["label"]] + cells)
    ratios = extras.get("ratios") or []
    if ratios:
        g.add(["程序计算的比率（公式引用上表）"], role="section")
        g.add(["比率", "数值", "单位"], role="header")
        for rt in ratios:
            num, den = at.get(tuple(rt["num"])), at.get(tuple(rt["den"]))
            fmt = "pct2" if rt["unit"] == "%" else "num2"
            value = rt["value"] / 100 if rt["unit"] == "%" else rt["value"]
            if num and den and num[1] == "元" and den[1] == "吨" and rt["unit"] == "万元/吨":
                cell = Formula(f"{num[0]}*100/{den[0]}", value, fmt=fmt)  # 百万元 × 100 = 万元
            elif num and den and num[1] == den[1] and rt["unit"] == "%":
                cell = Formula(f"{num[0]}/{den[0]}", value, fmt=fmt)
            else:
                cell = Cell(value, fmt=fmt, input=True)  # 引用真值表（如归母净利润）的比率按程序结果列示
            g.add([rt["label"], cell, rt["unit"]])
    width = max([len(t["columns"]) for t in extras.get("tables", [])] + [2])
    return g.sheet(widths={0: 26, **{c: 16 for c in range(1, width + 1)}}, freeze=(3, 1))


def _checks(res: dict[str, Any]) -> Sheet:
    g = _Grid("模型检查", "硬性失败会使模型状态变为 blocked；警示需在报告中说明")
    g.add(["类型", "内容"], role="header")
    for k, cn in (("hard_failures", "硬性失败"), ("warnings", "警示"), ("informational", "提示")):
        for m in res["checks"].get(k) or []:
            g.add([cn, m])
    return g.sheet(widths={0: 12, 1: 100}, wrap_cols=(1,))


def model_sheets(company: str, plan: dict[str, Any], res: dict[str, Any], three_statement: dict[str, Any] | None,
                 comps: dict[str, Any] | None, *, analysis: dict[str, Any] | None = None,
                 three_statement_plan: dict[str, Any] | None = None,
                 non_operating_items: list[dict[str, Any]] | None = None,
                 forecast_summary: dict[str, Any] | None = None,
                 extras: dict[str, Any] | None = None,
                 three_statement_detail: dict[str, Any] | None = None,
                 segment_forecast: dict[str, Any] | None = None) -> dict[str, Sheet]:
    wacc_sheet, wacc_ref = _wacc(plan, res)
    non_op_sheet, non_op_ref = _non_operating(non_operating_items) if non_operating_items else (None, None)
    ts_sheets, ts_links = {}, None
    if three_statement_detail and three_statement_detail.get("supported") and three_statement_plan and analysis:
        from .workbook_ts import linked_three_statement

        ts_sheets, ts_links = linked_three_statement(three_statement_detail, three_statement_plan, analysis, plan,
                                                     segment_forecast)
    sheets = {"估值汇总": _summary(company, plan, res, comps), "DCF": _dcf(plan, res, wacc_ref, non_op_ref, ts_links),
              "WACC": wacc_sheet, "敏感性": _sensitivity(plan, res)}
    if forecast_summary and forecast_summary.get("years"):
        sheets = {"估值汇总": sheets.pop("估值汇总"), "盈利预测": _forecast(forecast_summary, ts_links), **sheets}
    if non_op_sheet:
        sheets["非经营性资产"] = non_op_sheet
    if ts_sheets:
        sheets.update(ts_sheets)
    else:
        hist = (three_statement_plan or {}).get("historicals")
        for name, st in (three_statement or {}).get("statements", {}).items():
            sheets[f"三表-{name}"] = _statement(name, st, hist)
    if analysis:
        sheets["历史财务"] = _history(analysis)
        qs = _quarterly(analysis)
        if qs:
            sheets["分季度"] = qs
    if extras and extras.get("tables"):
        sheets["经营数据"] = _operations(extras)
    if comps:
        sheets["可比公司"] = _comps(comps)
    sheets["模型检查"] = _checks(res)
    return sheets
