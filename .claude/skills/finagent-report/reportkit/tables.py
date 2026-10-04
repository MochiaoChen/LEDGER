"""研报表格（HTML）。数字全部取自运行产物，这里只做单位换算与格式化。

- 标准表（第一个参数是 Run）：业绩、预测、估值等，任何公司都能用。
- table()/tr()/td()：公司专属表（经营数据）的拼装工具，单元格文字由公司脚本用 core 里的格式化函数生成。
"""

from __future__ import annotations

import html

from .core import Run, dec, mm, neg, num, pct, pp, updown, yi


# ================================================================== 拼装工具
def table(head: list[str], rows: list[str], cls: str = "data") -> str:
    th = "".join(f"<th>{h}</th>" for h in head)
    return f'<table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


def tr(cells: list[str], cls: str = "") -> str:
    """cells 为文字或已拼好的 <td>；cls 可取 sub（小计加粗）、grp（分组行）、base（高亮）。"""
    return f"<tr{f' class={cls}' if cls else ''}>" + "".join(
        c if c.startswith("<td") else f"<td>{c}</td>" for c in cells) + "</tr>"


def chg(text: str, v: float | None = None) -> str:
    """变化列（同比、变动、上行空间）：涨跌两个方向都着色。v 传变化量本身，不要传常数。"""
    return f"<td{updown(v)}>{text}</td>"


def td(text: str, v: float | None = None) -> str:
    """负数标红。"""
    return f"<td{neg(v)}>{text}</td>"


def grp(title: str, span: int) -> str:
    return f'<tr class="grp"><td colspan="{span}">{html.escape(title)}</td></tr>'


def text_table(head: list[str], rows: list[list[str]]) -> str:
    """文字对比表（同行定性对比、产品矩阵、管理层履历、政策梳理）：单元格是短句，左对齐，首列加粗。
    外部内容在单元格里带 [S编号]。"""
    from .core import inline
    body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in rows)
    th = "".join(f"<th>{html.escape(h)}</th>" for h in head)
    return f'<table class="data text"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>'


def fmt(v, kind):
    if v is None:
        return "—"
    return {"yi": lambda: yi(v), "pct": lambda: pct(v), "num": lambda: num(v),
            "pctn": lambda: pct(v, sign=False), "x": lambda: f"{v:.1f}", "mm": lambda: mm(v)}[kind]()


# ================================================================== 业绩
FORECAST_ROWS = [("营业收入（亿元）", "revenue", "yi"), ("同比增长", "revenue_growth", "pct"),
                 ("归母净利润（亿元）", "np_parent", "yi"), ("同比增长", "np_parent_growth", "pct"),
                 ("每股收益（元）", "eps", "num"), ("毛利率", "gross_margin", "pctn"),
                 ("归母净利率", "net_margin_parent", "pctn"), ("ROE（加权平均）", "roe", "pctn"), ("P/E（倍）", "pe", "x")]
COVER_ROWS = ("revenue", "revenue_growth", "np_parent", "np_parent_growth", "eps", "pe")


def forecast(run: Run, last: int = 3, keys: tuple[str, ...] | None = None) -> str:
    """盈利预测表（forecast_summary.years）。"""
    ys = [y for y in run.fs["years"] if y["year"] <= f"{int(run.period) + last}E"]
    head = "".join(f"<th{' class=est' if y['year'].endswith('E') else ''}>{y['year']}</th>" for y in ys)
    trs = []
    for label, key, kind in [r for r in FORECAST_ROWS if keys is None or r[1] in keys]:
        cells = []
        for y in ys:
            v = y.get(key)
            c = ["est"] if y["year"].endswith("E") else []
            if kind == "pct" and v is not None and v < 0:
                c.append("neg")
            cells.append(f'<td class="{" ".join(c)}">{fmt(v, kind)}</td>')
        trs.append(f"<tr><td>{label}</td>{''.join(cells)}</tr>")
    return f'<table class="data forecast"><thead><tr><th>指标</th>{head}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


def three_year(run: Run) -> str:
    """近三年主要会计数据（真值表中有上上年数据的指标）。"""
    ys = [run.prev2, run.prev, run.period]
    items = [("营业收入（亿元）", "revenue", "yi"), ("利润总额（亿元）", "total_profit", "yi"),
             ("归母净利润（亿元）", "np_parent", "yi"), ("扣非归母净利润（亿元）", "np_parent_deducted", "yi"),
             ("经营现金流净额（亿元）", "ocf", "yi"), ("总资产（亿元）", "total_assets", "yi"),
             ("归母净资产（亿元）", "equity_parent", "yi"), ("基本每股收益（元）", "eps_basic", "num"),
             ("加权平均 ROE", "roe_weighted", "pctn"), ("净现比（倍）", "ocf_to_np", "num")]
    rows = [tr([label] + [fmt(run.v(mid, y), kind) for y in ys]) for label, mid, kind in items
            if any(run.v(mid, y) is not None for y in ys)]
    return table(["指标"] + [f"{y}A" for y in ys], rows)


def core(run: Run) -> str:
    """主要财务指标（本期、上期、同比）。"""
    items = [("营业收入", "revenue", "yi"), ("营业成本", "operating_cost", "yi"), ("税金及附加", "tax_surcharge", "yi"),
             ("销售费用", "selling_expense", "yi"), ("管理费用", "admin_expense", "yi"), ("研发费用", "rd_expense", "yi"),
             ("财务费用", "finance_expense", "yi"), ("营业利润", "operating_profit", "yi"), ("归母净利润", "np_parent", "yi"),
             ("扣非归母净利润", "np_parent_deducted", "yi"), ("基本每股收益（元）", "eps_basic", "num"),
             ("毛利率", "gross_margin", "pp"), ("销售费用率", "selling_ratio", "pp"), ("管理费用率", "admin_ratio", "pp"),
             ("研发费用率", "rd_ratio", "pp")]
    rows = []
    for label, mid, kind in items:
        cur, prev = run.v(mid), run.v(mid, run.prev)
        if cur is None and prev is None:
            continue
        c = run.changes.get(mid) or {}
        if kind == "pp":
            a, b, d = pct(cur, sign=False), pct(prev, sign=False), c.get("yoy_change_pp")
            change = pp(d)
        else:
            a, b = (yi(cur), yi(prev)) if kind == "yi" else (num(cur), num(prev))
            d = c.get("yoy_pct")
            change = pct(d) if d is not None and (cur or 0) > 0 and (prev or 0) > 0 else "—"  # 负基数的同比无意义
        rows.append(tr([label, a, b, chg(change, d if change != "—" else None)]))
    return table(["亿元 / %", f"{run.period}A", f"{run.prev}A", "同比"], rows)


def quarterly(run: Run, extra_rows: list[str] | None = None) -> str:
    """分季度主要财务数据；extra_rows 为公司脚本追加的行（如环比、占全年比例，取自 extras 比率）。"""
    qs = ["Q1", "Q2", "Q3", "Q4"]
    items = [("营业收入", "revenue"), ("归母净利润", "np_parent"), ("扣非归母净利润", "np_parent_deducted"),
             ("经营现金流净额", "ocf")]
    rows = [tr([label] + [yi(run.quarterly[mid]["values"][q]) for q in qs]) for label, mid in items
            if mid in run.quarterly]
    return table(["亿元", *[f"{run.period}{q}" for q in qs]], rows + (extra_rows or []))


def balance(run: Run, extra_rows: list[str] | None = None) -> str:
    """资产负债与营运资本（真值表）。"""
    rows = [tr([f"{label}（亿元）", yi(run.v(mid)), yi(run.v(mid, run.prev)), chg(pct(run.yoy(mid)), run.yoy(mid))])
            for label, mid in (("货币资金", "cash"), ("应收账款", "accounts_receivable"), ("存货", "inventory"),
                               ("合同负债", "contract_liab"), ("应付账款", "accounts_payable"), ("总资产", "total_assets"))
            if run.v(mid) is not None]
    rows.append(tr(["资产负债率", pct(run.v("debt_ratio"), sign=False), pct(run.v("debt_ratio", run.prev), sign=False),
                    pp((run.changes.get("debt_ratio") or {}).get("yoy_change_pp"))]))
    rows.append(tr(["净现比（倍）", num(run.v("ocf_to_np")), num(run.v("ocf_to_np", run.prev)), "—"]))
    return table(["项目", f"{run.period} 年末", f"{run.prev} 年末", "同比"], rows + (extra_rows or []))


# ================================================================== 预测与估值
def assumptions(run: Run, basis: dict[str, str], years: int = 3, price_label: str = "单价") -> str:
    """关键假设（基准情景）与依据。参数取自 segment_forecast.json 与三表驱动；basis 为依据文字（写明对应第几节），
    键为“<分部名>销量增速 / <分部名><price_label>增速 / <分部名>毛利率”“销售费用率”“其他费用率”“现金分红率”。"""
    sc = run.seg["scenarios"]["base"]
    ys = [y[2:] + "E" for y in run.seg["years"][:years]]
    f = lambda arr, d=1: " / ".join(f"{v * 100:+.{d}f}%" for v in arr[:years])  # noqa: E731
    g = lambda arr, d=2: " / ".join(f"{v * 100:.{d}f}%" for v in arr[:years])  # noqa: E731
    unit = price_label  # 按公司的定价口径命名（吨价、ASP、日租金……），basis 的键随之改
    items = []
    for s in sc["segments"]:
        n = s["name"]
        items += [(f"{n}销量增速", f(s["volume_growth"])), (f"{n}{unit}增速", f(s["price_growth"])),
                  (f"{n}毛利率", g(s["gross_margin"]))]
    if "selling" in sc["expense_ratios"]:
        items.append(("销售费用率", g(sc["expense_ratios"]["selling"], 1)))
    items.append(("其他费用率", "同 " + f"{run.period}A"))
    payout = (run.detail.get("drivers", {}).get("dividend_payout") or [None])[0]
    if payout is not None:
        items.append(("现金分红率", f"{payout * 100:.0f}%"))
    if missing := [a for a, _ in items if not str(basis.get(a, "")).strip()]:
        raise ValueError("关键假设缺依据（BASIS 未填）：" + "、".join(missing) + "。依据写依据数字和对应第几节")
    rows = [tr([a, b, f'<td class="basis">{html.escape(basis.get(a, ""))}</td>']) for a, b in items]
    return table(["关键假设（基准情景）", " / ".join(ys), "依据"], rows, "data assume")


def segment_forecast(run: Run, n: int = 3, volume_unit: str = "", price_unit: str = "",
                     price_label: str = "单价") -> str:
    """分部收入预测（基准情景）：销量、单价、收入、毛利率，合计行含收入增速、综合毛利率、销售费用率。
    单价 = 收入（百万元）÷ 销量 × 100，单位是“万元/<销量单位>”；volume_unit / price_unit 只影响表头。"""
    by, sc = run.seg["base_year"], run.seg["scenarios"]["base"]
    cols = [f"{run.period}A"] + [y[2:] + "E" for y in run.seg["years"][:n]]
    head = "".join(f"<th{' class=est' if c.endswith('E') else ''}>{c}</th>" for c in cols)
    trs = []

    def line(label, vals, f, cls=""):
        return f"<tr{f' class={cls}' if cls else ''}><td>{label}</td>" + "".join(
            f'<td class="{"est" if i else ""}{" neg" if v is not None and v < 0 else ""}">{"—" if v is None else f(v)}</td>'
            for i, v in enumerate(vals)) + "</tr>"

    for b, sg in zip(by["segments"], sc["segments"]):
        trs.append(grp(b["name"], len(cols) + 1))
        vu, pu = (f"（{volume_unit}）" if volume_unit else ""), (f"（{price_unit}）" if price_unit else "")
        trs += [line(f"销量{vu}", [b["volume"]] + sg["volume"][:n], lambda v: mm(v)),
                line("销量增速", [None] + sg["volume_growth"][:n], lambda v: pct(v * 100, 1)),
                line(f"{price_label}{pu}", [b["price"]] + sg["price"][:n], lambda v: num(v)),
                line(f"{price_label}增速", [None] + sg["price_growth"][:n], lambda v: pct(v * 100, 1)),
                line("收入（亿元）", [b["revenue"]] + sg["revenue"][:n], lambda v: num(v / 100)),
                line("毛利率", [b["gross_margin"]] + sg["gross_margin"][:n], lambda v: pct(v * 100, 2, sign=False))]
    trs.append(grp("合计", len(cols) + 1))
    trs += [line("营业收入（亿元）", [by["revenue"]] + sc["revenue"][:n], lambda v: num(v / 100), "sub"),
            line("营业收入增速", [None] + sc["revenue_growth"][:n], lambda v: pct(v * 100, 2), "sub"),
            line("综合毛利率", [by["gross_margin"]] + sc["gross_margin"][:n], lambda v: pct(v * 100, 2, sign=False), "sub")]
    if "selling" in sc["expense_ratios"]:
        trs.append(line("销售费用率", [by["expense_ratios"]["selling"]] + sc["expense_ratios"]["selling"][:n],
                        lambda v: pct(v * 100, 2, sign=False), "sub"))
    return f'<table class="data forecast"><thead><tr><th>基准情景</th>{head}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


def wacc(run: Run) -> str:
    w, wb = run.plan["wacc"], run.valuation["wacc_base"]
    tv = run.plan["terminal_value"]
    rows = [tr(["无风险利率", pct(w["risk_free_rate"] * 100, sign=False)]),
            tr(["β", f"{w['beta']:.2f}"]),
            tr(["股权风险溢价", pct(w["equity_risk_premium"] * 100, sign=False)]),
            tr(["股权成本", pct(wb["cost_of_equity"] * 100, sign=False)])]
    if w.get("target_debt_pct"):
        rows += [tr(["税后债务成本", pct(wb["after_tax_cost_of_debt"] * 100, sign=False)])]
    rows += [tr(["目标负债占比", pct(w["target_debt_pct"] * 100, 0, sign=False)]),
             tr(["WACC（基准）", pct(wb["wacc"] * 100, sign=False)], "sub"),
             tr(["永续增长率", pct(tv["perpetual_growth_rate"] * 100, 1, sign=False)]),
             tr(["退出 EV/EBITDA（交叉验证，倍）", f"{tv['exit_ebitda_multiple']:.1f}"])]
    return table(["折现参数", "取值"], rows)


def fcff(run: Run) -> str:
    fb = run.valuation["forecast_base"]
    pvs = {r["period"]: r for r in run.valuation["pv_base"]["pv_rows"]}
    items = [("营业收入", "revenue"), ("EBIT", "ebit"), ("EBIT 利润率", "ebit_margin"), ("所得税", "cash_taxes"),
             ("NOPAT", "nopat"), ("加：折旧摊销", "da"), ("减：资本开支", "capex"), ("减：营运资本增加", "change_nwc"),
             ("FCFF", "unlevered_fcf")]
    rows = []
    for label, k in items:
        cells = [pct(r[k] * 100, sign=False) if k == "ebit_margin" else td(num(r[k] / 100), r[k]) for r in fb]
        rows.append(tr([label] + cells, "sub" if k in ("nopat", "unlevered_fcf") else ""))
    rows.append(tr(["折现期（年）"] + [f"{pvs[r['period']]['discount_period']:.1f}" for r in fb]))
    rows.append(tr(["FCFF 现值"] + [td(num(pvs[r["period"]]["pv_cash_flow"] / 100), pvs[r["period"]]["pv_cash_flow"])
                                   for r in fb], "sub"))
    return table(["亿元"] + [f"{r['period']}E" for r in fb], rows)


def scenario_table(run: Run, price_label: str = "单价") -> str:
    """三情景：各分部首年单价增速、收入增速、WACC、永续增长与估值结果。"""
    cn = {"base": "基准", "downside": "悲观", "upside": "乐观"}
    y = run.seg["years"][0][2:] + "E"
    names = [s["name"] for s in run.seg["scenarios"]["base"]["segments"]]
    rows = []
    for k in ("downside", "base", "upside"):
        sc, s = run.seg["scenarios"][k], run.scen[k]
        cells = [cn[k]] + [chg(pct(sg["price_growth"][0] * 100, 1), sg["price_growth"][0]) for sg in sc["segments"]]
        cells += [chg(pct(sc["revenue_growth"][0] * 100, 2), sc["revenue_growth"][0]), f"{s['wacc'] * 100:.2f}%",
                  f"{s['terminal_growth'] * 100:.1f}%", f"{s['enterprise_value_mm'] / 100:,.0f}",
                  f"<b>{num(s['value_per_share'])}</b>", chg(f"{s['upside_vs_price'] * 100:+.1f}%", s["upside_vs_price"]),
                  f"{s['tv_percent_ev'] * 100:.1f}%"]
        rows.append(tr(cells, "base" if k == "base" else ""))
    head = ["情景"] + [f"{n}{price_label}（{y}）" for n in names] + [
        f"收入增速（{y}）", "WACC", "永续增长", "企业价值（亿元）", "每股价值（元）", "较参考股价", "终值占比"]
    return table(head, rows, "data nw")


SENS_KIND = {"WACC × 永续增长率": 0, "WACC × 退出 EV/EBITDA 倍数": 1, "收入增速 × EBIT 利润率": 2}


def sensitivity(run: Run, idx: int) -> str:
    """敏感性矩阵热力表，idx 为 valuation.sensitivities 的下标；行列标签按矩阵名称识别
    （WACC × 永续增长率 / WACC × 退出 EV/EBITDA 倍数 / 收入增速 × EBIT 利润率）。"""
    s = run.valuation["sensitivities"][idx]
    idx = SENS_KIND.get(s["name"], 2)
    base = run.scen["base"]
    price = run.valuation["current_price"]

    def shade(v):  # 相对参考股价着色，仅用于配色
        r = max(-1.0, min(1.0, (v / price - 1) / 0.6))
        from . import core
        rgb = core.HEAT_POS if r >= 0 else core.HEAT_NEG
        a = 0.08 + 0.5 * abs(r)
        return f"background: rgba({rgb[0]},{rgb[1]},{rgb[2]},{a:.2f});" + ("color:#fff;" if a > 0.4 else "")

    if idx == 0:
        col = lambda g: f"{(base['terminal_growth'] + g) * 100:.1f}%"  # noqa: E731
        row = lambda d: f"{(base['wacc'] + d) * 100:.2f}%"  # noqa: E731
        corner = "WACC ＼ g"
    elif idx == 1:
        col = lambda g: f"{run.plan['terminal_value']['exit_ebitda_multiple'] + g:.0f}x"  # noqa: E731
        row = lambda d: f"{(base['wacc'] + d) * 100:.2f}%"  # noqa: E731
        corner = "WACC ＼ 退出倍数"
    else:
        col = lambda g: f"{g * 100:+.1f}pp"  # noqa: E731
        row = lambda d: f"{d * 100:+.0f}pp"  # noqa: E731
        corner = "收入增速 ＼ 利润率"
    d = dec(price, base["value_per_share"])  # 低价股保留两位小数
    head = "".join(f"<th>{col(g)}</th>" for g in s["y_values"])
    trs = []
    for i, dx in enumerate(s["x_values"]):
        cells = "".join(f'<td style="{shade(v)}"{" class=center" if dx == 0 and s["y_values"][j] == 0 else ""}>{v:,.{d}f}</td>'
                        for j, v in enumerate(s["matrix"][i]))
        trs.append(f"<tr><th>{row(dx)}</th>{cells}</tr>")
    return f'<table class="heat"><thead><tr><th class="corner">{corner}</th>{head}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


BRIDGE_ITEMS = [("cash", "加：货币资金", 1), ("non_operating_assets", "加：非经营性资产净额（明细见附录）", 1),
                ("associates", "加：联营合营企业投资", 1), ("debt", "减：有息负债", -1), ("leases", "减：租赁负债", -1),
                ("minorities", "减：少数股东权益", -1), ("pensions", "减：设定受益计划净负债", -1),
                ("preferred_stock", "减：优先股", -1), ("options", "减：期权", -1),
                ("other_debt_like_items", "减：其他类负债项目", -1)]  # 与 finagent/tasks/valuation/dcf.py 的 BRIDGE_ADD/SUB 一致


def equity_bridge(run: Run) -> str:
    """股权价值桥（基准情景）：企业价值 → 逐项加减（plan.json ev_to_equity_bridge，百万元）→ 股权价值 → 每股价值。
    为零的项目不列。"""
    b, base = run.plan["ev_to_equity_bridge"], run.scen["base"]
    rows = [tr(["企业价值", num(base["enterprise_value_mm"] / 100)], "sub")]
    for key, label, sign in BRIDGE_ITEMS:
        v = b.get(key) or 0.0
        if v:
            rows.append(tr([label, td(num(sign * v / 100), sign * v)]))
    rows.append(tr(["股权价值", num(base["equity_value_mm"] / 100)], "sub"))
    rows.append(tr(["总股本（亿股）", num(b["diluted_shares"] / 100)]))
    rows.append(tr(["每股价值（元）", f"<b>{num(base['value_per_share'])}</b>"], "sub"))
    return table(["股权价值桥（基准情景）", "亿元"], rows)


def nonop(run: Run) -> str:
    """股权桥中加回的非经营性资产明细（non_operating_assets.json）。"""
    trs = "".join(f"<tr><td>{'减：' if it['sign'] < 0 else ''}{it['label']}</td>"
                  f"<td{neg(it['value_mm'])}>{it['value_mm'] / 100:,.2f}</td></tr>" for it in run.non_op["items"])
    trs += f"<tr class='total'><td>合计</td><td>{run.non_op['total_mm'] / 100:,.2f}</td></tr>"
    return (f'<table class="data slim"><thead><tr><th>非经营性资产净额（{run.period} 年末）</th><th>亿元</th></tr></thead>'
            f'<tbody>{trs}</tbody></table>')


# ================================================================== 可比公司（有 --peers 时）
def comps(run: Run) -> str:
    """可比公司估值倍数与利润率（comps.json：目标公司 + 核心可比公司，排除的公司不列）。"""
    rows = []
    for r in run.comps["rows"]:
        target = r.get("peer_tier") == "Target"
        # 倍数可能是 None 或 "NM"（亏损、分母为负时无意义），原样显示
        x = lambda v: f"{v:.1f}x" if isinstance(v, (int, float)) else (v or "—")  # noqa: E731
        m = lambda v: pct(v * 100, 1, sign=False) if isinstance(v, (int, float)) else (v or "—")  # noqa: E731
        rows.append(tr([f"{r['company']}{'（目标）' if target else ''}", x(r.get("ev_revenue")), x(r.get("ev_ebitda")),
                        x(r.get("pe_ltm")), m(r.get("ebitda_margin")), m(r.get("ebit_margin"))], "base" if target else ""))
    st = run.comps.get("stats", {})
    med = lambda k: st.get(k, {}).get("core", {}).get("median")  # noqa: E731
    rows.append(tr(["核心可比中位数", *(f"{med(k):.1f}x" if isinstance(med(k), (int, float)) else "—"
                                      for k in ("ev_revenue", "ev_ebitda", "pe_ltm")),
                    "—", "—"], "sub"))
    return table(["公司", "EV/营业收入", "EV/EBITDA", "P/E（LTM）", "EBITDA 利润率", "EBIT 利润率"], rows, "data nw")


def comps_implied(run: Run) -> str:
    """可比公司隐含每股价值（四分位）与 DCF 交叉验证。"""
    d = dec(run.valuation["current_price"])
    f = lambda v: f"{v:,.{d}f}" if isinstance(v, (int, float)) else "—"  # noqa: E731
    rows = [tr([i["multiple"], str(i["n_core"]), f(i["p25"]), f(i["median"]), f(i["p75"])]) for i in run.comps.get("implied", [])]
    cc = run.comps.get("dcf_cross_check") or {}
    if cc:
        rows.append(tr(["DCF 基准情景", "—", "—", f(cc.get("dcf_base")), "—"], "sub"))
    return table(["方法", "样本数", "P25（元/股）", "中位数（元/股）", "P75（元/股）"], rows)


def reverse_dcf(run: Run) -> str:
    """反向 DCF：参考股价隐含的单变量取值、基准假设、历史区间与程序分档（valuation/reverse_dcf.json）。"""
    def v(lever: str, x) -> str:
        if not isinstance(x, (int, float)):
            return "—"
        return f"{x:.1f}x" if lever == "exit_multiple" else pct(x * 100, sign=False)

    rows = [tr([r["name"], v(r["lever"], r.get("implied")), v(r["lever"], r["base"]),
                v(r["lever"], r.get("historical_max")), v(r["lever"], r.get("historical_avg")), r["grade"]])
            for r in run.rdcf.get("levers", [])]
    return table(["变量", "股价隐含", "基准假设", "历史最高", "历史平均", "分档"], rows)
