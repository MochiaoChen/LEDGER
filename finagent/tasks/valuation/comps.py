"""可比公司估值（相对估值）。

计算规则依据原插件 comps-valuation/references（valuation-readthrough.md、comps-framework.md、peer-selection.md）：
  - 股权价值 = 股价 × 股本；EV = 股权价值 + 有息负债 + 少数股东权益 − 现金 − 非经营性资产
  - EV 倍数配 EV 口径分母（收入/EBITDA/EBIT），P/E 配归母净利润；分母 ≤ 0 记 NM
  - 统计：中位数优先；P25/P75 作为估值区间；IQR 法（Q1 − 1.5×IQR, Q3 + 1.5×IQR）标记离群值但不删除数据
  - 仅核心同业（Core）驱动估值区间；次要同业（Secondary）仅作参照；Excluded 列示剔除理由
  - 利润率对比：EBITDA / EBIT / 净利率 = 对应利润 ÷ 营业收入（收入 ≤ 0 记 NM），核心同业分位数与目标公司差距，
    用于解释目标公司倍数相对同业的溢价/折价
另外：write_formula_workbook 生成带公式的 Excel comps 表（标准库写出，公式可在 Excel 中复算，缓存值与 comps.json 一致）。

同业 CSV 列名与原插件模板一致：ticker, company, peer_tier, price, basic_shares, debt, minority_interest, cash,
other_non_op_assets, revenue_ltm, ebitda_ltm, ebit_ltm, net_income_ltm, eps_cy1, market_data_date, source_name,
inclusion_rationale, exclusion_rationale, confidence（金额单位：百万元；股本：百万股；股价：元）
"""

from __future__ import annotations

import csv
import io
import statistics
from pathlib import Path
from typing import Any

from ...core import tracing
from ...output.xlsx import Chart, ChartSeries, Formula, Sheet, write_xlsx
from ..financials.analyze import FactTable

MM = 1e6
MULTIPLES = [
    ("ev_revenue", "EV/营业收入", "ev", "revenue_ltm"),
    ("ev_ebitda", "EV/EBITDA", "ev", "ebitda_ltm"),
    ("ev_ebit", "EV/EBIT", "ev", "ebit_ltm"),
    ("pe_ltm", "P/E（LTM）", "equity_value", "net_income_ltm"),
]
PRIMARY = ["ev_ebitda", "pe_ltm"]
MARGINS = [
    ("ebitda_margin", "EBITDA 利润率", "ebitda_ltm"),
    ("ebit_margin", "EBIT 利润率", "ebit_ltm"),
    ("net_margin", "净利率", "net_income_ltm"),
]


def _f(x: Any) -> float | None:
    try:
        return float(str(x).replace(",", "")) if str(x).strip() not in ("", "None") else None
    except ValueError:
        return None


def load_peers(path: str | Path) -> list[dict[str, Any]]:
    raw = tracing.read_file(path).decode("utf-8-sig")
    return [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(io.StringIO(raw))]


def target_row(facts: list[dict[str, Any]], period: str, plan: dict[str, Any], company: str,
               assumptions: dict[str, Any]) -> dict[str, Any]:
    t = FactTable(facts)
    y = period[:4]
    b = plan["ev_to_equity_bridge"]
    h = plan["historicals"]
    return {
        "ticker": assumptions.get("ticker", "TARGET"), "company": company, "peer_tier": "Target",
        "price": assumptions.get("current_price"), "basic_shares": b["diluted_shares"],
        "debt": b["debt"] + b.get("leases", 0.0), "minority_interest": b.get("minorities", 0.0), "cash": b["cash"],
        "other_non_op_assets": b.get("non_operating_assets", 0.0),
        "revenue_ltm": h["revenue"], "ebitda_ltm": h["ebitda"], "ebit_ltm": h["ebit"],
        "net_income_ltm": (t.v("np_parent", y) or 0.0) / MM,
        "market_data_date": assumptions.get("valuation_date"), "source_name": "财报抽取 + 估值假设文件",
        "confidence": "high",
    }


def _metrics(row: dict[str, Any]) -> dict[str, Any]:
    price, sh = _f(row.get("price")), _f(row.get("basic_shares"))
    eq = price * sh if price is not None and sh is not None else None
    ev = None
    if eq is not None:
        ev = (eq + (_f(row.get("debt")) or 0) + (_f(row.get("minority_interest")) or 0)
              - (_f(row.get("cash")) or 0) - (_f(row.get("other_non_op_assets")) or 0))
    out = {"equity_value": eq, "ev": ev}
    for key, _, num, den in MULTIPLES:
        n, d = out[num], _f(row.get(den))
        out[key] = None if n is None or d is None else ("NM" if d <= 0 else n / d)
    eps1 = _f(row.get("eps_cy1"))
    out["pe_ntm"] = None if price is None or eps1 is None else ("NM" if eps1 <= 0 else price / eps1)
    return out


def _margins(row: dict[str, Any]) -> dict[str, Any]:
    rev = _f(row.get("revenue_ltm"))
    out: dict[str, Any] = {}
    for key, _, num in MARGINS:
        n = _f(row.get(num))
        out[key] = None if n is None or rev is None else ("NM" if rev <= 0 else n / rev)
    return out


def _quantiles(vals: list[float]) -> dict[str, float | None]:
    if not vals:
        return {"n": 0, "median": None, "mean": None, "p25": None, "p75": None, "low_fence": None, "high_fence": None}
    if len(vals) == 1:
        q1 = q3 = vals[0]
    else:
        q1, _, q3 = statistics.quantiles(vals, n=4, method="inclusive")  # 与 Excel PERCENTILE.INC 一致
    iqr = q3 - q1
    return {"n": len(vals), "median": statistics.median(vals), "mean": statistics.fmean(vals), "p25": q1, "p75": q3,
            "low_fence": q1 - 1.5 * iqr, "high_fence": q3 + 1.5 * iqr}


@tracing.traced("run_comps")
def run(peers: list[dict[str, Any]], target: dict[str, Any], dcf_range: dict[str, float] | None = None) -> dict[str, Any]:
    rows = []
    for r in [target] + peers:
        tier = (r.get("peer_tier") or "Core").strip()
        rows.append({**r, "peer_tier": tier, **_metrics(r), **_margins(r)})
    tgt = rows[0]
    stats: dict[str, dict[str, Any]] = {}
    for key, name, _, _ in MULTIPLES + [("pe_ntm", "P/E（NTM）", "", "")]:
        core = [r[key] for r in rows[1:] if r["peer_tier"] == "Core" and isinstance(r[key], float)]
        allp = [r[key] for r in rows[1:] if r["peer_tier"] in ("Core", "Secondary") and isinstance(r[key], float)]
        qc = _quantiles(core)
        outliers = [r["ticker"] for r in rows[1:] if r["peer_tier"] == "Core" and isinstance(r[key], float)
                    and qc["n"] >= 4 and not (qc["low_fence"] <= r[key] <= qc["high_fence"])]
        core_clean = [v for r, v in ((r, r[key]) for r in rows[1:]) if r["peer_tier"] == "Core"
                      and isinstance(v, float) and r["ticker"] not in outliers]
        stats[key] = {"name": name, "core": qc, "core_ex_outliers": _quantiles(core_clean),
                      "all_peers": _quantiles(allp), "outliers": outliers,
                      "target": tgt.get(key),
                      "premium_vs_core_median": (tgt[key] / qc["median"] - 1)
                      if isinstance(tgt.get(key), float) and qc["median"] else None}

    # 隐含股价：核心同业（剔除离群值）P25 / 中位数 / P75 × 目标公司分母
    implied = []
    sh = _f(target["basic_shares"])
    bridge = (_f(target.get("debt")) or 0) + (_f(target.get("minority_interest")) or 0) \
        - (_f(target.get("cash")) or 0) - (_f(target.get("other_non_op_assets")) or 0)
    for key in PRIMARY:
        q = stats[key]["core_ex_outliers"]
        den = _f(target["ebitda_ltm"] if key == "ev_ebitda" else target["net_income_ltm"])
        row = {"multiple": stats[key]["name"], "denominator_mm": den, "n_core": q["n"]}
        for lvl in ("p25", "median", "p75"):
            m = q[lvl]
            if m is None or den is None or den <= 0 or not sh:
                row[lvl] = None
                continue
            equity = m * den - bridge if key.startswith("ev_") else m * den
            row[lvl] = equity / sh
        implied.append(row)
    lows = [r["p25"] for r in implied if r["p25"] is not None]
    highs = [r["p75"] for r in implied if r["p75"] is not None]
    mids = [r["median"] for r in implied if r["median"] is not None]
    comps_range = {"low": min(lows), "mid": statistics.median(mids), "high": max(highs)} if lows else None
    cross = None
    if comps_range and dcf_range:
        overlap = min(comps_range["high"], dcf_range["high"]) - max(comps_range["low"], dcf_range["low"])
        cross = {"dcf_base": dcf_range["base"], "comps_mid": comps_range["mid"],
                 "dcf_vs_comps_mid": dcf_range["base"] / comps_range["mid"] - 1, "ranges_overlap": overlap > 0}
    # 利润率对比：核心同业分位数（不剔除离群值，仅作参照）与目标公司差距
    margins: dict[str, dict[str, Any]] = {}
    for key, name, _ in MARGINS:
        q = _quantiles([r[key] for r in rows[1:] if r["peer_tier"] == "Core" and isinstance(r[key], float)])
        tv = tgt.get(key)
        margins[key] = {"name": name, "core": q, "target": tv,
                        "diff_vs_core_median": tv - q["median"]
                        if isinstance(tv, float) and q["median"] is not None else None}
    core_n = sum(1 for r in rows[1:] if r["peer_tier"] == "Core")
    status = "screen-grade" if core_n < 4 else "senior-review-ready"
    return {"rows": rows, "stats": stats, "margins": margins, "implied": implied, "range": comps_range,
            "dcf_cross_check": cross,
            "status": status, "core_peer_count": core_n,
            "excluded": [{"ticker": r["ticker"], "company": r["company"], "reason": r.get("exclusion_rationale", "")}
                         for r in rows if r["peer_tier"] == "Excluded"]}


# ---------------------------------------------------------------- 公式工作簿

INPUT_COLUMNS = ["ticker", "company", "peer_tier", "price", "basic_shares", "debt", "minority_interest", "cash",
                 "other_non_op_assets", "revenue_ltm", "ebitda_ltm", "ebit_ltm", "net_income_ltm", "eps_cy1",
                 "market_data_date", "source_name", "inclusion_rationale", "exclusion_rationale", "confidence"]
IN = {c: chr(65 + i) for i, c in enumerate(INPUT_COLUMNS)}  # 同业数据 列字母
INPUT_HEADERS = ["代码", "公司", "分层", "股价（元）", "股本（百万股）", "有息负债（百万元）", "少数股东权益（百万元）",
                 "现金（百万元）", "非经营性资产（百万元）", "营业收入 LTM（百万元）", "EBITDA LTM（百万元）",
                 "EBIT LTM（百万元）", "归母净利润 LTM（百万元）", "EPS CY1（元）", "数据日期", "来源", "入选理由",
                 "剔除理由", "可信度"]
INPUT_FORMATS = {3: "num2", 4: "num1", **{i: "num1" for i in range(5, 13)}, 13: "num2"}
# 倍数表：D 股权价值、E EV、F..J 五个倍数、K..O 对应离群标记；分子取 倍数 表列，分母取 同业数据 列
STAT_KEYS = [(k, n, num, den) for k, n, num, den in MULTIPLES] + [("pe_ntm", "P/E（NTM）", "price", "eps_cy1")]
MCOL = {k: chr(70 + i) for i, (k, *_) in enumerate(STAT_KEYS)}
FCOL = {k: chr(75 + i) for i, (k, *_) in enumerate(STAT_KEYS)}
SCOL = {k: chr(66 + i) for i, (k, *_) in enumerate(STAT_KEYS)}  # 统计 表列
# 统计表行：(行号, 标签, 结果路径)
STAT_ROWS = [(2, "核心同业样本数", ("core", "n")), (3, "核心中位数", ("core", "median")),
             (4, "核心均值", ("core", "mean")), (5, "核心 P25", ("core", "p25")), (6, "核心 P75", ("core", "p75")),
             (7, "IQR 下限（P25 − 1.5×IQR）", ("core", "low_fence")),
             (8, "IQR 上限（P75 + 1.5×IQR）", ("core", "high_fence")),
             (9, "剔除离群后样本数", ("core_ex_outliers", "n")), (10, "剔除离群后中位数", ("core_ex_outliers", "median")),
             (11, "剔除离群后 P25", ("core_ex_outliers", "p25")), (12, "剔除离群后 P75", ("core_ex_outliers", "p75")),
             (13, "核心+次要 样本数", ("all_peers", "n")), (14, "核心+次要 中位数", ("all_peers", "median")),
             (15, "目标公司倍数", ("target",)), (16, "目标相对核心中位数溢价", ("premium_vs_core_median",))]


def _num_or_text(v: Any) -> Any:
    x = _f(v)
    return x if x is not None else (None if v in (None, "") else str(v))


def _cached(v: Any) -> Any:
    return "" if v is None else v


def write_formula_workbook(path: Path, result: dict[str, Any], currency: str, valuation_date: str) -> None:
    """把 run() 的结果写成带公式的工作簿：输入 → 倍数 → 统计（核心同业、IQR 离群）→ 隐含股价区间。"""
    rows = result["rows"]
    last = len(rows) + 1  # 数据末行（第 2 行为目标公司）
    target = rows[0]

    inputs = [INPUT_HEADERS] + [[_num_or_text(r.get(c)) for c in INPUT_COLUMNS] for r in rows]

    mult = [["代码", "公司", "分层", "股权价值", "EV"] + [n for _, n, *_ in STAT_KEYS]
            + [f"{n} 离群" for _, n, *_ in STAT_KEYS]]
    for i, r in enumerate(rows, 2):
        d = lambda c: f"同业数据!{IN[c]}{i}"  # noqa: E731
        line: list[Any] = [Formula(d(c), r.get(c)) for c in ("ticker", "company", "peer_tier")]
        line.append(Formula(f'IF(AND(ISNUMBER({d("price")}),ISNUMBER({d("basic_shares")})),'
                            f'{d("price")}*{d("basic_shares")},"")', _cached(r["equity_value"])))
        line.append(Formula(f'IF(ISNUMBER(D{i}),D{i}+N({d("debt")})+N({d("minority_interest")})-N({d("cash")})'
                            f'-N({d("other_non_op_assets")}),"")', _cached(r["ev"])))
        for key, _, num, den in STAT_KEYS:
            n = {"ev": f"E{i}", "equity_value": f"D{i}", "price": d("price")}[num]
            line.append(Formula(f'IF(OR(NOT(ISNUMBER({n})),NOT(ISNUMBER({d(den)}))),"",'
                                f'IF({d(den)}<=0,"NM",{n}/{d(den)}))', _cached(r[key])))
        for key, *_ in STAT_KEYS:
            m, sc = f"{MCOL[key]}{i}", SCOL[key]
            flag = "离群" if r["ticker"] in result["stats"][key]["outliers"] else ""
            line.append(Formula(f'IF(AND(C{i}="Core",ISNUMBER({m}),统计!{sc}$2>=4),'
                                f'IF(OR({m}<统计!{sc}$7,{m}>统计!{sc}$8),"离群",""),"")', flag))
        mult.append(line)

    stat = [["统计量"] + [n for _, n, *_ in STAT_KEYS]] + [[label] for _, label, _ in STAT_ROWS]
    for key, *_ in STAT_KEYS:
        rng, fl, c = f"倍数!{MCOL[key]}$3:{MCOL[key]}${last}", f"倍数!{FCOL[key]}$3:{FCOL[key]}${last}", SCOL[key]
        core = f'(倍数!$C$3:$C${last}="Core")*ISNUMBER({rng})'
        clean = f'{core}*({fl}="")'
        allp = f'((倍数!$C$3:$C${last}="Core")+(倍数!$C$3:$C${last}="Secondary"))*ISNUMBER({rng})'

        def agg(fn: str, cond: str, n_row: int, extra: str = "") -> str:
            return f'IF({c}{n_row}=0,"",{fn}(IF({cond},{rng}){extra}))'

        exprs = {
            2: (f"SUMPRODUCT({core})", False), 3: (agg("MEDIAN", core, 2), True),
            4: (agg("AVERAGE", core, 2), True), 5: (agg("QUARTILE", core, 2, ",1"), True),
            6: (agg("QUARTILE", core, 2, ",3"), True), 7: (f'IF({c}2=0,"",{c}5-1.5*({c}6-{c}5))', False),
            8: (f'IF({c}2=0,"",{c}6+1.5*({c}6-{c}5))', False), 9: (f"SUMPRODUCT({clean})", False),
            10: (agg("MEDIAN", clean, 9), True), 11: (agg("QUARTILE", clean, 9, ",1"), True),
            12: (agg("QUARTILE", clean, 9, ",3"), True), 13: (f"SUMPRODUCT({allp})", False),
            14: (agg("MEDIAN", allp, 13), True), 15: (f"倍数!{MCOL[key]}2", False),
            16: (f'IF(AND(ISNUMBER({c}15),ISNUMBER({c}3)),IF({c}3<>0,{c}15/{c}3-1,""),"")', False),
        }
        st = result["stats"][key]
        for row, _, path_ in STAT_ROWS:
            v: Any = st
            for k in path_:
                v = v[k]
            expr, arr = exprs[row]
            stat[row - 1].append(Formula(expr, _cached(v), array=arr))

    implied = [["倍数", "目标公司分母（百万元）", "核心样本数（剔除离群）", "P25 隐含股价（元）", "中位数隐含股价（元）",
                "P75 隐含股价（元）"]]
    den_col = {"ev_ebitda": IN["ebitda_ltm"], "pe_ltm": IN["net_income_ltm"]}
    for i, (key, imp) in enumerate(zip(PRIMARY, result["implied"]), 2):
        c = SCOL[key]
        line = [imp["multiple"], Formula(f"同业数据!{den_col[key]}2", _cached(imp["denominator_mm"])),
                Formula(f"统计!{c}9", imp["n_core"])]
        for lvl, srow in (("p25", 11), ("median", 10), ("p75", 12)):
            m = f"统计!{c}{srow}"
            value = f"({m}*$B{i}-$B$5)/$B$6" if key.startswith("ev_") else f"{m}*$B{i}/$B$6"
            line.append(Formula(f'IF(AND(ISNUMBER({m}),ISNUMBER($B{i})),IF(AND($B{i}>0,N($B$6)<>0),{value},""),"")',
                                _cached(imp[lvl])))
        implied.append(line)
    t = lambda c: f"N(同业数据!{IN[c]}2)"  # noqa: E731
    implied += [  # 第 5、6 行被上方隐含股价公式引用
        [],
        ["股权桥调整（有息负债+少数股东权益−现金−非经营性资产，百万元）",
         Formula(f'{t("debt")}+{t("minority_interest")}-{t("cash")}-{t("other_non_op_assets")}',
                 sum(_f(target.get(c)) or 0 for c in ("debt", "minority_interest"))
                 - (_f(target.get("cash")) or 0) - (_f(target.get("other_non_op_assets")) or 0))],
        ["目标公司股本（百万股）", Formula(f"同业数据!{IN['basic_shares']}2", _f(target.get("basic_shares")))],
        [],
        ["估值区间", "低（P25 最小值）", "中（中位数的中位数）", "高（P75 最大值）"],
    ]
    rg = result["range"] or {}
    implied.append(["隐含股价（元）",
                    Formula('IF(COUNT(D2:D3)=0,"",MIN(D2:D3))', _cached(rg.get("low"))),
                    Formula('IF(COUNT(E2:E3)=0,"",MEDIAN(E2:E3))', _cached(rg.get("mid"))),
                    Formula('IF(COUNT(F2:F3)=0,"",MAX(F2:F3))', _cached(rg.get("high")))])

    # 敏感性：核心同业（剔除离群）P25/中位数/P75 倍数 × 目标公司分母变动 → 隐含股价
    shocks = [-0.10, -0.05, 0.0, 0.05, 0.10]
    bridge_v = (sum(_f(target.get(c)) or 0 for c in ("debt", "minority_interest"))
                - (_f(target.get("cash")) or 0) - (_f(target.get("other_non_op_assets")) or 0))
    shares_v = _f(target.get("basic_shares"))
    sens: list[list[Any]] = []
    for key, den_row, title, den_name in (("ev_ebitda", 2, "EV/EBITDA 倍数 × EBITDA 变动 → 隐含股价（元）", "EBITDA"),
                                          ("pe_ltm", 3, "P/E（LTM）倍数 × 归母净利润变动 → 隐含股价（元）", "归母净利润")):
        top = len(sens) + 1  # 标题行号
        sens += [[title], ["倍数档位", "倍数", *[f"{den_name} {s:+.0%}" for s in shocks]],
                 ["", "变动", *shocks]]
        den_v = dict(zip(PRIMARY, result["implied"]))[key]["denominator_mm"]
        for lvl, label, srow in (("p25", "P25", 11), ("median", "中位数", 10), ("p75", "P75", 12)):
            r = len(sens) + 1
            m_v = result["stats"][key]["core_ex_outliers"][lvl]
            line: list[Any] = [label, Formula(f"统计!{SCOL[key]}{srow}", _cached(m_v))]
            for j, s in enumerate(shocks):
                col = chr(67 + j)
                num = f"$B{r}*隐含股价!$B${den_row}*(1+{col}${top + 2})"
                expr = f"({num}-隐含股价!$B$5)/隐含股价!$B$6" if key == "ev_ebitda" else f"{num}/隐含股价!$B$6"
                ok = m_v is not None and den_v is not None and shares_v
                v = None
                if ok:
                    v = m_v * den_v * (1 + s)
                    v = (v - bridge_v) / shares_v if key == "ev_ebitda" else v / shares_v
                line.append(Formula(f'IF(AND(ISNUMBER($B{r}),ISNUMBER(隐含股价!$B${den_row})),'
                                    f'IF(N(隐含股价!$B$6)<>0,{expr},""),"")', _cached(v)))
            sens.append(line)
        sens.append([])

    # 来源台账：逐家公司的数据日期、来源、入选/剔除理由与可信度（引用同业数据，改输入即同步）
    ledger_cols = [("ticker", "代码"), ("company", "公司"), ("peer_tier", "分层"), ("market_data_date", "数据日期"),
                   ("source_name", "来源"), ("inclusion_rationale", "入选理由"),
                   ("exclusion_rationale", "剔除理由"), ("confidence", "可信度")]
    ledger = [[cn for _, cn in ledger_cols]] + [
        [Formula(f'同业数据!{IN[c]}{i}&""', "" if r.get(c) in (None, "") else str(r.get(c))) for c, _ in ledger_cols]
        for i, r in enumerate(rows, 2)]

    readme = [
        ["项目", "内容"],
        ["目标公司", target.get("company")], ["代码", target.get("ticker")], ["估值日期", valuation_date],
        ["币种与单位", f"{currency}；金额百万元，股本百万股，股价与每股价值元"],
        ["同业数据", "输入表：第 2 行为目标公司，其余为同业；可直接修改输入，其他表公式自动重算"],
        ["倍数", "股权价值 = 股价 × 股本；EV = 股权价值 + 有息负债 + 少数股东权益 − 现金 − 非经营性资产；分母 ≤ 0 记 NM"],
        ["统计", "仅核心同业（Core）；P25/P75 按 QUARTILE（与 PERCENTILE.INC 一致）；样本 ≥ 4 时按 IQR 法标记离群，不删除数据"],
        ["隐含股价", "核心同业（剔除离群）P25 / 中位数 / P75 倍数 × 目标公司分母，EV 倍数再扣股权桥后除以股本"],
        ["敏感性", "核心同业（剔除离群）P25 / 中位数 / P75 倍数 × 目标公司 EBITDA 或归母净利润 ±10% 的隐含股价"],
        ["来源台账", "每家公司的数据日期、来源、入选/剔除理由与可信度"],
        ["利润率对比", "EBITDA / EBIT / 净利率 = 对应利润 ÷ 营业收入（收入 ≤ 0 记 NM）；核心同业中位数与 P25/P75，"
                    "目标公司与核心中位数之差（百分点）。目标公司 EBIT 为剔除投资收益与公允价值变动后的经营性口径，"
                    "同业 EBIT 以来源数据为准"],
        ["状态", f"{result['status']}（核心同业 {result['core_peer_count']} 家）"],
    ]
    # 排版：只加样式，不改行列位置（公式按固定行列引用）；目标公司行浅黄底，同业数据为输入（蓝色）
    mult_fmt = {3: "num0", 4: "num0", **{i: "mult" for i in range(5, 10)}}
    stat_fmt = {r - 1: "mult" for r, *_ in STAT_ROWS}
    stat_fmt.update({1: "int", 8: "int", 12: "int", 15: "pct1"})
    n_sens = len(sens) // 2  # 两个敏感性块，每块：标题、表头、变动、P25/中位数/P75、空行
    sens_roles = {b + k: role for b in (0, n_sens) for k, role in ((0, "section"), (1, "header"), (4, "key"))}
    margin = _margin_sheet(result)
    top = len(rows) + 2  # 利润率统计区表头（0 起行号）
    summary = _summary_sheet(result, valuation_date, currency, top + 1)
    write_xlsx(path, {
        "估值摘要": Sheet(
            summary,
            header_rows=0,
            roles={0: "title", 1: "note", 2: "note", 4: "header", 5: "key", 7: "header", 13: "header"},
            formats={1: "mult", 2: "mult", 3: "pct1"},
            row_formats={5: "num2"},
            widths={0: 28, 1: 17, 2: 17, 3: 22, 4: 17, 5: 20},
            wrap_cols=(0,),
            freeze=(0, 0),
            tab_color="1F3864",
            charts=[
                Chart("当前股价与估值区间（元）", "B5:E5",
                      [ChartSeries("股价 / 每股价值", "B6:E6", "4472C4")], (7, 3, 15, 13), "0.00"),
                Chart("目标公司与核心同业利润率", "A15:A17",
                      [ChartSeries("目标公司", "B15:B17", "4472C4"),
                       ChartSeries("核心同业中位数", "C15:C17", "A5A5A5")], (7, 14, 15, 27), "0.0%"),
            ],
        ),
        "说明": Sheet(readme, widths={0: 16, 1: 110}, wrap_cols=(1,), freeze=(1, 0), tab_color="1F3864"),
        "同业数据": Sheet(inputs, formats=INPUT_FORMATS, inputs=True, roles={1: "key"}, freeze=(1, 2),
                      widths={15: 18, 16: 30, 17: 30}, wrap_cols=(16, 17)),
        "倍数": Sheet(mult, formats=mult_fmt, roles={1: "key"}, freeze=(1, 2)),
        "统计": Sheet(stat, row_formats=stat_fmt, roles={14: "key"}, widths={0: 30}),
        "隐含股价": Sheet(implied, formats={1: "num1", 2: "int", 3: "num2", 4: "num2", 5: "num2"},
                      row_formats={4: "num1", 5: "num1", 8: "num2"}, roles={7: "header", 8: "key"},
                      widths={0: 44}),
        "敏感性": Sheet(sens, header_rows=0, roles=sens_roles, formats={1: "mult", **{i: "num2" for i in range(2, 7)}},
                     row_formats={2: "dpct", n_sens + 2: "dpct"}, widths={0: 14}, freeze=(0, 1)),
        "来源台账": Sheet(ledger, widths={4: 18, 5: 36, 6: 36}, wrap_cols=(5, 6)),
        "利润率对比": Sheet(margin, formats={**{i: "num1" for i in range(3, 7)}, **{i: "pct1" for i in range(7, 10)}},
                       roles={1: "key", top: "header", top + 5: "key"},
                       row_formats={top + 1: "int", top + 6: "pp"}, freeze=(1, 2), widths={0: 26}),
    })


def _summary_sheet(result: dict[str, Any], valuation_date: str, currency: str, margin_top: int) -> list[list[Any]]:
    """估值摘要：把关键结论、核心倍数、利润率差异与图表数据集中在首屏。"""
    target = result["rows"][0]
    rg = result.get("range") or {}
    price = _f(target.get("price"))
    mid = rg.get("mid")
    upside = mid / price - 1 if isinstance(mid, (int, float)) and price else None
    sample = str(target.get("company")) == "星河智造"
    note = ("虚构样例：仅用于演示模型结构与公式联动，不构成投资建议；正式研究必须替换为真实同业、市场数据与可追溯来源。"
            if sample else "研究输出：估值结论须结合来源台账、口径一致性与最新市场数据复核，不构成投资建议。")
    out: list[list[Any]] = [
        ["可比公司估值摘要"],
        [f'{target.get("company", "")}（{target.get("ticker", "")}）', f"估值日：{valuation_date}", f"币种：{currency}"],
        [note],
        [],
        ["目标公司", "当前股价", "区间低", "区间中枢", "区间高", "中枢上涨空间"],
        [target.get("company"), Formula(f"同业数据!{IN['price']}2", _cached(price)),
         Formula("隐含股价!B9", _cached(rg.get("low"))), Formula("隐含股价!C9", _cached(mid)),
         Formula("隐含股价!D9", _cached(rg.get("high"))),
         Formula('IF(AND(ISNUMBER(D6),ISNUMBER(B6),B6<>0),D6/B6-1,"")', _cached(upside), fmt="pct1")],
        [],
        ["核心倍数与溢价/折价", "核心中位数", "目标公司", "目标相对核心中位数"],
    ]
    for key in ("ev_revenue", "ev_ebitda", "ev_ebit", "pe_ltm"):
        c, st = SCOL[key], result["stats"][key]
        out.append([st["name"], Formula(f"统计!{c}3", _cached(st["core"]["median"])),
                    Formula(f"统计!{c}15", _cached(st["target"])),
                    Formula(f"统计!{c}16", _cached(st["premium_vs_core_median"]))])
    out += [[], ["利润率对比", "目标公司", "核心同业中位数", "差异（百分点）"]]
    for i, (key, name, _) in enumerate(MARGINS):
        c = chr(72 + i)  # H / I / J
        m = result["margins"][key]
        diff = m["diff_vs_core_median"]
        out.append([name, Formula(f"利润率对比!{c}{margin_top + 5}", _cached(m["target"]), fmt="pct1"),
                    Formula(f"利润率对比!{c}{margin_top + 2}", _cached(m["core"]["median"]), fmt="pct1"),
                    Formula(f"利润率对比!{c}{margin_top + 6}", _cached(None if diff is None else diff * 100), fmt="pp")])
    return out


def _margin_sheet(result: dict[str, Any]) -> list[list[Any]]:
    """利润率对比页：逐家公司的利润与利润率（引用同业数据，改输入即同步），下方为核心同业统计。"""
    rows = result["rows"]
    last = len(rows) + 1
    num_cols = [("revenue_ltm", "营业收入（百万元）", "D"), ("ebitda_ltm", "EBITDA（百万元）", "E"),
                ("ebit_ltm", "EBIT（百万元）", "F"), ("net_income_ltm", "归母净利润（百万元）", "G")]
    mcol = {key: chr(72 + i) for i, (key, *_) in enumerate(MARGINS)}  # H / I / J
    num_of = {"ebitda_margin": "E", "ebit_margin": "F", "net_margin": "G"}
    sheet: list[list[Any]] = [["代码", "公司", "分层"] + [n for _, n, _ in num_cols] + [n for _, n, _ in MARGINS]]
    for i, r in enumerate(rows, 2):
        line: list[Any] = [Formula(f"同业数据!{IN[c]}{i}", r.get(c)) for c in ("ticker", "company", "peer_tier")]
        for c, _, _ in num_cols:
            ref = f"同业数据!{IN[c]}{i}"
            line.append(Formula(f'IF(ISNUMBER({ref}),{ref},"")', _cached(_f(r.get(c)))))
        for key, _, _ in MARGINS:
            n = num_of[key]
            line.append(Formula(f'IF(AND(ISNUMBER(D{i}),ISNUMBER({n}{i})),IF(D{i}<=0,"NM",{n}{i}/D{i}),"")',
                                _cached(r[key])))
        sheet.append(line)

    top = last + 2  # 空一行后为统计区
    labels = ["核心同业样本数", "核心中位数", "核心 P25", "核心 P75", "目标公司", "目标 − 核心中位数（百分点）"]
    stat_rows: list[list[Any]] = [["统计（核心同业）", "", "", "", "", "", ""] + [n for _, n, _ in MARGINS]]
    stat_rows += [[label, "", "", "", "", "", ""] for label in labels]
    for key, *_ in MARGINS:
        c, m = mcol[key], result["margins"][key]
        rng = f"{c}$3:{c}${last}"
        core = f'($C$3:$C${last}="Core")*ISNUMBER({rng})'
        n_ref, med_ref = f"{c}{top + 1}", f"{c}{top + 2}"
        diff = m["diff_vs_core_median"]
        cells = [
            Formula(f"SUMPRODUCT({core})", m["core"]["n"]),
            Formula(f'IF({n_ref}=0,"",MEDIAN(IF({core},{rng})))', _cached(m["core"]["median"]), array=True),
            Formula(f'IF({n_ref}=0,"",QUARTILE(IF({core},{rng}),1))', _cached(m["core"]["p25"]), array=True),
            Formula(f'IF({n_ref}=0,"",QUARTILE(IF({core},{rng}),3))', _cached(m["core"]["p75"]), array=True),
            Formula(f"{c}2", _cached(m["target"])),
            Formula(f'IF(AND(ISNUMBER({c}2),ISNUMBER({med_ref})),({c}2-{med_ref})*100,"")',
                    _cached(None if diff is None else diff * 100)),
        ]
        for j, cell in enumerate(cells, 1):
            stat_rows[j].append(cell)
    return sheet + [[]] + stat_rows
