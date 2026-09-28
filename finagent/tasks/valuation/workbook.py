"""估值模型工作簿 model.xlsx（投行排版）：估值汇总 → DCF → WACC → 敏感性 → 三表 → 可比公司 → 模型检查。

期间横排（FY2024A 实际 + 预测期），单位写在表头；蓝色为输入（财报抽取值与三表模型输出），黑色为公式。
DCF 页的 NOPAT、自由现金流、折现、终值、股权桥与每股价值、WACC 页的股权成本与 WACC 都写成公式，
缓存值取自引擎计算结果，在 Excel 中重算结果相同（tests/test_quarterly_ebit.py 核对）。
"""

from __future__ import annotations

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
        self.at: dict[str, int] = {}

    def add(self, row: list[Any], *, key: str | None = None, role: str | None = None, fmt: str | None = None) -> int:
        self.rows.append(row)
        i = len(self.rows) - 1
        if role:
            self.roles[i] = role
        if fmt:
            self.row_formats[i] = fmt
        if key:
            self.at[key] = i + 1
        return i + 1

    def sheet(self, **kw: Any) -> Sheet:
        header = next((i for i, r in self.roles.items() if r == "header"), 3)
        kw.setdefault("freeze", (header + 1, 1))
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
def _dcf(plan: dict[str, Any], res: dict[str, Any], wacc_ref: str) -> Sheet:
    h, fr, pv = plan["historicals"], res["forecast_base"], res["pv_base"]["pv_rows"]
    base = next(s for s in res["scenarios"] if s["scenario"] == "base")
    n = len(fr)
    hist_col, cols = "B", [_col(i + 1) for i in range(n)]  # 历史列 B，预测列 C 起
    last = cols[-1]
    g = _Grid(f"{plan['meta']['company']} DCF 估值（FCFF，基准情景）")
    g.add(["项目（百万元）", f"FY{h['latest_year']}A"] + [f"FY{r['period']}E" for r in fr], role="header")

    def inputs(label: str, key: str, hist_v: float | None, fc_key: str, **kw: Any) -> int:
        return g.add([label, hist_v] + [r[fc_key] for r in fr], key=key, fmt="num1", **kw)

    inputs("营业收入", "rev", h["revenue"], "revenue")
    a = g.at
    g.add(["收入增速", None] + [Formula(f"{c}{a['rev']}/{p}{a['rev']}-1", r["revenue_growth"])
                                for p, c, r in zip([hist_col] + cols, cols, fr)], key="g", fmt="pct1")
    inputs("EBIT（剔除投资收益与公允价值变动）", "ebit", h["ebit"], "ebit")
    g.add(["EBIT 利润率"] + [Formula(f"{c}{a['ebit']}/{c}{a['rev']}", e / r) for c, e, r in
                            zip([hist_col] + cols, [h["ebit"]] + [x["ebit"] for x in fr],
                                [h["revenue"]] + [x["revenue"] for x in fr])], key="m", fmt="pct1")
    inputs("减：现金税（EBIT × 税率）", "tax", h["cash_taxes"], "cash_taxes")
    g.add(["NOPAT"] + [Formula(f"{c}{a['ebit']}-{c}{a['tax']}", e - t) for c, e, t in
                       zip([hist_col] + cols, [h["ebit"]] + [x["ebit"] for x in fr],
                           [h["cash_taxes"]] + [x["cash_taxes"] for x in fr])], key="nopat", fmt="num1", role="total")
    inputs("加：折旧摊销", "da", h["da"], "da")
    inputs("减：资本开支", "capex", h["capex"], "capex")
    inputs("减：营运资本增加", "dnwc", h["change_nwc"], "change_nwc")
    fcf = [h["unlevered_fcf"]] + [x["unlevered_fcf"] for x in fr]
    g.add(["无杠杆自由现金流（FCFF）"] + [Formula(f"{c}{a['nopat']}+{c}{a['da']}-{c}{a['capex']}-{c}{a['dnwc']}", v)
                                    for c, v in zip([hist_col] + cols, fcf)], key="fcf", fmt="num1", role="total")
    g.add([])
    g.add(["折现期（年，年中折现）", None] + [x["discount_period"] for x in pv], key="t", fmt="num1")
    g.add(["折现系数", None] + [Formula(f"1/(1+{wacc_ref})^{c}{a['t']}", x["pv_cash_flow"] / x["cash_flow"]
                                        if x["cash_flow"] else None) for c, x in zip(cols, pv)], key="df", fmt="factor")
    g.add(["FCFF 现值", None] + [Formula(f"{c}{a['fcf']}*{c}{a['df']}", x["pv_cash_flow"]) for c, x in zip(cols, pv)],
          key="pv", fmt="num1", role="total")
    g.add([])

    # 估值与股权桥（B 列）
    g.add(["估值与股权桥", "百万元"], role="header")
    rate, tg = base["wacc"], base["terminal_growth"]
    g.add(["WACC", Formula(wacc_ref, rate, fmt="pct2")], key="wacc")
    g.add(["永续增长率", Cell(tg, fmt="pct2", input=True)], key="tg")
    pv_fcf, pv_tv = res["pv_base"]["pv_fcf"], res["pv_base"]["pv_terminal_value"]
    g.add(["预测期 FCFF 现值合计", Formula(f"SUM(C{a['pv']}:{last}{a['pv']})", pv_fcf)], key="sum_pv")
    tv = pv_tv * (1 + rate) ** n
    if plan["terminal_value"]["method"] == "perpetual_growth":
        g.add(["终值（永续增长法）", Formula(f"{last}{a['fcf']}*(1+B{a['tg']})/(B{a['wacc']}-B{a['tg']})", tv)], key="tv")
    else:
        g.add(["退出 EV/EBITDA 倍数", Cell(float(plan["terminal_value"]["exit_ebitda_multiple"]), fmt="mult", input=True)],
              key="mult")
        g.add(["终值（退出倍数法）", Formula(f"({last}{a['ebit']}+{last}{a['da']})*B{a['mult']}", tv)], key="tv")
    g.add(["终值现值", Formula(f"B{a['tv']}/(1+B{a['wacc']})^COUNT(C{a['t']}:{last}{a['t']})", pv_tv)], key="pv_tv")
    ev = base["enterprise_value_mm"]
    g.add(["企业价值（EV）", Formula(f"B{a['sum_pv']}+B{a['pv_tv']}", ev)], key="ev", role="total")
    g.add(["终值占 EV", Formula(f"B{a['pv_tv']}/B{a['ev']}", pv_tv / ev, fmt="pct1")], key="tvp")
    b = plan["ev_to_equity_bridge"]
    bridge = [("cash", "加：货币资金", 1), ("non_operating_assets", "加：非经营性资产", 1), ("associates", "加：联营投资", 1),
              ("debt", "减：有息负债", -1), ("leases", "减：租赁负债", -1), ("minorities", "减：少数股东权益", -1)]
    other = sum(float(b.get(k) or 0.0) for k in ("pensions", "preferred_stock", "options", "other_debt_like_items"))
    terms = [f"B{a['ev']}"]
    for k, label, sign in bridge:
        g.add([label, Cell(float(b.get(k) or 0.0), input=True)], key=k)
        terms.append(("+" if sign > 0 else "-") + f"B{a[k]}")
    g.add(["减：养老金、优先股、期权及其他类债务", Cell(other, input=True)], key="other")
    terms.append(f"-B{a['other']}")
    g.add(["股权价值", Formula("".join(terms), base["equity_value_mm"])], key="eq", role="total")
    g.add(["摊薄股本（百万股）", Cell(float(b["diluted_shares"]), input=True)], key="sh")
    g.add(["每股价值（元）", Formula(f"B{a['eq']}/B{a['sh']}", base["value_per_share"], fmt="num2")], key="vps", role="key")
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
def _statement(name: str, st: dict[str, Any]) -> Sheet:
    g = _Grid(f"三表联动预测：{name}（基准情景）", "单位：百万元；口径见 valuation/report.md 第五节")
    g.add(["项目（百万元）"] + [f"{p}E" for p in st["periods"]], role="header")
    for r in st["rows"]:
        g.add([r["name"]] + r["values"], role="total" if r["name"] in TOTAL_ROWS else None,
              fmt="num2" if r["key"] == "balance_check" else None)
    return g.sheet(formats={c: "num1" for c in range(1, len(st["periods"]) + 1)}, widths={0: 26})


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


def _checks(res: dict[str, Any]) -> Sheet:
    g = _Grid("模型检查", "硬性失败会使模型状态变为 blocked；警示需在报告中说明")
    g.add(["类型", "内容"], role="header")
    for k, cn in (("hard_failures", "硬性失败"), ("warnings", "警示"), ("informational", "提示")):
        for m in res["checks"].get(k) or []:
            g.add([cn, m])
    return g.sheet(widths={0: 12, 1: 100}, wrap_cols=(1,))


def model_sheets(company: str, plan: dict[str, Any], res: dict[str, Any], three_statement: dict[str, Any] | None,
                 comps: dict[str, Any] | None) -> dict[str, Sheet]:
    wacc_sheet, wacc_ref = _wacc(plan, res)
    sheets = {"估值汇总": _summary(company, plan, res, comps), "DCF": _dcf(plan, res, wacc_ref), "WACC": wacc_sheet,
              "敏感性": _sensitivity(plan, res)}
    for name, st in (three_statement or {}).get("statements", {}).items():
        sheets[f"三表-{name}"] = _statement(name, st)
    if comps:
        sheets["可比公司"] = _comps(comps)
    sheets["模型检查"] = _checks(res)
    return sheets
