"""可比公司估值（相对估值）。

计算规则依据原插件 comps-valuation/references（valuation-readthrough.md、comps-framework.md、peer-selection.md）：
  - 股权价值 = 股价 × 股本；EV = 股权价值 + 有息负债 + 少数股东权益 − 现金 − 非经营性资产
  - EV 倍数配 EV 口径分母（收入/EBITDA/EBIT），P/E 配归母净利润；分母 ≤ 0 记 NM
  - 统计：中位数优先；P25/P75 作为估值区间；IQR 法（Q1 − 1.5×IQR, Q3 + 1.5×IQR）标记离群值但不删除数据
  - 仅核心同业（Core）驱动估值区间；次要同业（Secondary）仅作参照；Excluded 列示剔除理由
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
from ...output.xlsx import Formula, write_xlsx
from ..financials.analyze import FactTable

MM = 1e6
MULTIPLES = [
    ("ev_revenue", "EV/营业收入", "ev", "revenue_ltm"),
    ("ev_ebitda", "EV/EBITDA", "ev", "ebitda_ltm"),
    ("ev_ebit", "EV/EBIT", "ev", "ebit_ltm"),
    ("pe_ltm", "P/E（LTM）", "equity_value", "net_income_ltm"),
]
PRIMARY = ["ev_ebitda", "pe_ltm"]


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
        rows.append({**r, "peer_tier": tier, **_metrics(r)})
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
    core_n = sum(1 for r in rows[1:] if r["peer_tier"] == "Core")
    status = "screen-grade" if core_n < 4 else "senior-review-ready"
    return {"rows": rows, "stats": stats, "implied": implied, "range": comps_range, "dcf_cross_check": cross,
            "status": status, "core_peer_count": core_n,
            "excluded": [{"ticker": r["ticker"], "company": r["company"], "reason": r.get("exclusion_rationale", "")}
                         for r in rows if r["peer_tier"] == "Excluded"]}


# ---------------------------------------------------------------- 公式工作簿

INPUT_COLUMNS = ["ticker", "company", "peer_tier", "price", "basic_shares", "debt", "minority_interest", "cash",
                 "other_non_op_assets", "revenue_ltm", "ebitda_ltm", "ebit_ltm", "net_income_ltm", "eps_cy1",
                 "market_data_date", "source_name", "inclusion_rationale", "exclusion_rationale", "confidence"]
IN = {c: chr(65 + i) for i, c in enumerate(INPUT_COLUMNS)}  # 同业数据 列字母
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

    inputs = [INPUT_COLUMNS] + [[_num_or_text(r.get(c)) for c in INPUT_COLUMNS] for r in rows]

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

    readme = [
        ["项目", "内容"],
        ["目标公司", target.get("company")], ["代码", target.get("ticker")], ["估值日期", valuation_date],
        ["币种与单位", f"{currency}；金额百万元，股本百万股，股价与每股价值元"],
        ["同业数据", "输入表：第 2 行为目标公司，其余为同业；可直接修改输入，其他表公式自动重算"],
        ["倍数", "股权价值 = 股价 × 股本；EV = 股权价值 + 有息负债 + 少数股东权益 − 现金 − 非经营性资产；分母 ≤ 0 记 NM"],
        ["统计", "仅核心同业（Core）；P25/P75 按 QUARTILE（与 PERCENTILE.INC 一致）；样本 ≥ 4 时按 IQR 法标记离群，不删除数据"],
        ["隐含股价", "核心同业（剔除离群）P25 / 中位数 / P75 倍数 × 目标公司分母，EV 倍数再扣股权桥后除以股本"],
        ["状态", f"{result['status']}（核心同业 {result['core_peer_count']} 家）"],
    ]
    write_xlsx(path, {"说明": readme, "同业数据": inputs, "倍数": mult, "统计": stat, "隐含股价": implied})
