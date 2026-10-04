"""程序判定的条目（L0 硬闸门、L1 数据闭合）：只读运行产物，不调用模型。

每个检查返回 {passed, detail, evidence}；输入文件缺失按未通过计，detail 写明缺什么。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from .rubric import Bundle

DISCLAIMER = re.compile(r"不构成.{0,4}投资建议")
RULE = re.compile(r"([^：；\s]+)：≥(-?\d+(?:\.\d+)?)%")


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _res(passed: bool, detail: str, evidence: str = "") -> dict[str, Any]:
    return {"passed": bool(passed), "detail": detail, "evidence": evidence}


def _missing(*paths: Path) -> dict[str, Any] | None:
    lost = [p.name for p in paths if not p.is_file()]
    return _res(False, "缺 " + "、".join(lost)) if lost else None


def _text(b: Bundle) -> str:
    return b.narrative.read_text(encoding="utf-8") if b.narrative.is_file() else ""


def check_guard(b: Bundle, params: dict) -> dict[str, Any]:
    from ..output.sources import run_guard

    if m := _missing(b.narrative):
        return m
    g = run_guard(b.run, _text(b), b.sources if b.sources.is_file() else None)
    bad = [*g["unverified_numbers"], *(str(x.get("quote", x)) for x in g["mismatched_claims"]),
           *(str(x.get("quote", x)) for x in g["uncited_external"])]
    return _res(g["ok"], f"无出处数字 {len(g['unverified_numbers'])}，指标期间不符 {len(g['mismatched_claims'])}，"
                f"外部数字缺引用 {len(g['uncited_external'])}", "；".join(map(str, bad[:5])))


def check_ts_integrity(b: Bundle, params: dict) -> dict[str, Any]:
    ts = _json(b.run / "valuation" / "three_statement.json")
    if ts is None:
        return _res(False, "缺 three_statement.json")
    from ..tasks.valuation.ts_engine import TOLERANCE

    # 按误差值与引擎容差判定，不依赖产物里记录的 status（旧版本用过更严的 1e-6）
    failed = [f"{c['check']}（误差 {c['max_abs_error']:.4g} 百万元）" for c in ts.get("integrity", [])
              if c.get("max_abs_error", 0) > TOLERANCE]
    hard = ts.get("hard_failures") or []
    return _res(not failed and not hard and bool(ts.get("integrity")),
                f"{len(ts.get('integrity', []))} 项勾稽，失败 {len(failed)}，硬性失败 {len(hard)}",
                "；".join(failed + [str(h) for h in hard]))


def check_dcf_tie(b: Bundle, params: dict) -> dict[str, Any]:
    v = _json(b.run / "valuation" / "valuation.json")
    if v is None:
        return _res(False, "缺 valuation.json")
    tie = v.get("three_statement_tie") or {}
    return _res(tie.get("status") == "pass", f"核对 {'、'.join(tie.get('items', []))}，最大偏差 "
                f"{tie.get('max_abs_diff_mm', '—')} 百万元" if tie else "valuation.json 无三表核对结果")


def check_disclaimer(b: Bundle, params: dict) -> dict[str, Any]:
    html = b.run / "report" / "report.html"
    for p in (html, b.narrative):
        if p.is_file() and (m := DISCLAIMER.search(p.read_text(encoding="utf-8"))):
            return _res(True, f"见 {p.name}", m.group(0))
    return _res(False, "报告与文稿中都没有“不构成投资建议”")


def _expected_rating(rule: str, upside: float) -> str | None:
    for name, pct in RULE.findall(rule):
        if upside >= float(pct) / 100:
            return name
    m = re.search(r"([^：；\s]+)：其余", rule)
    return m.group(1) if m else None


def check_rating(b: Bundle, params: dict) -> dict[str, Any]:
    fs = _json(b.run / "valuation" / "forecast_summary.json")
    r = (fs or {}).get("rating") or {}
    if not r.get("rating"):
        return _res(False, "forecast_summary.json 没有评级")
    exp = _expected_rating(r.get("rule", ""), float(r.get("upside", 0)))
    in_text = r["rating"] in _text(b)
    ok = exp == r["rating"] and in_text
    return _res(ok, f"评级 {r['rating']}，上行空间 {float(r['upside']):.1%}，按规则应为 {exp}"
                + ("" if in_text else "；正文未写该评级"), r.get("rule", ""))


def check_extraction(b: Bundle, params: dict) -> dict[str, Any]:
    v = _json(b.work / "facts.verified.json")
    if v is None:
        return _res(False, "缺 facts.verified.json")
    c = v.get("check", {})
    n = lambda k: len(c.get(k)) if isinstance(c.get(k), list) else int(c.get(k) or 0)
    return _res(bool(c.get("ok")) and not (n("rejected") or n("conflicts") or n("tieout_failures")),
                f"拒收 {n('rejected')}，冲突 {n('conflicts')}，勾稽失败 {n('tieout_failures')}")


def check_segment_base(b: Bundle, params: dict) -> dict[str, Any]:
    sf = _json(b.run / "valuation" / "segment_forecast.json")
    if sf is None:
        return _res(False, "没有分部驱动预测（segment_forecast.json）")
    base = sf.get("base_year", {})
    total = sum(s.get("revenue", 0) for s in base.get("segments", [])) + base.get("other_revenue", 0)
    rev = base.get("revenue", 0)
    diff = abs(total - rev)
    return _res(rev > 0 and diff <= max(0.5, abs(rev) * 1e-6),
                f"分部合计 {total:,.2f} vs 营业收入 {rev:,.2f} 百万元，差 {diff:.2f}")


def check_bridge(b: Bundle, params: dict) -> dict[str, Any]:
    v = _json(b.run / "valuation" / "valuation.json")
    if v is None or not v.get("bridge_base"):
        return _res(False, "缺 valuation.json 或股权价值桥")
    br = v["bridge_base"]
    net = br["add_backs"] - br["deductions"]
    bad = []
    for s in v.get("scenarios", []):
        diff = s["enterprise_value_mm"] + net - s["equity_value_mm"]
        if abs(diff) > 0.5:
            bad.append(f"{s.get('scenario_cn', s['scenario'])} 差 {diff:,.2f}")
    return _res(not bad and bool(v.get("scenarios")),
                f"加回 {br['add_backs']:,.2f}、扣减 {br['deductions']:,.2f} 百万元，{len(v.get('scenarios', []))} 个情景"
                + ("" if not bad else "；不闭合：" + "；".join(bad)))


def check_per_share(b: Bundle, params: dict) -> dict[str, Any]:
    v = _json(b.run / "valuation" / "valuation.json")
    fs = _json(b.run / "valuation" / "forecast_summary.json")
    shares = ((fs or {}).get("market") or {}).get("total_shares")
    if not v or not shares:
        return _res(False, "缺估值结果或总股本")
    bad = []
    for s in v.get("scenarios", []):
        calc = s["equity_value_mm"] * 1e6 / shares
        if abs(calc - s["value_per_share"]) > max(0.01, abs(calc) * 1e-4):
            bad.append(f"{s.get('scenario_cn', s['scenario'])} 复算 {calc:.2f} vs {s['value_per_share']:.2f}")
    return _res(not bad, f"总股本 {shares:,.0f} 股" + ("" if not bad else "；" + "；".join(bad)))


def check_scenario_order(b: Bundle, params: dict) -> dict[str, Any]:
    v = _json(b.run / "valuation" / "valuation.json")
    r = (v or {}).get("value_range") or {}
    if not r:
        return _res(False, "缺 value_range")
    return _res(r["low"] <= r["base"] <= r["high"], f"悲观 {r['low']:.2f} / 基准 {r['base']:.2f} / 乐观 {r['high']:.2f}")


def check_sensitivity(b: Bundle, params: dict) -> dict[str, Any]:
    v = _json(b.run / "valuation" / "valuation.json")
    sd = (v or {}).get("sensitivity_directionality") or {}
    if not sd:
        return _res(False, "缺敏感性方向检查结果")
    bad = [d["check"] for d in sd.get("details", []) if not d.get("passed")]
    return _res(bool(sd.get("passed")), f"{len(sd.get('details', []))} 项，失败 {len(bad)}", "；".join(bad[:3]))


def check_terminal_share(b: Bundle, params: dict) -> dict[str, Any]:
    v = _json(b.run / "valuation" / "valuation.json")
    base = next((s for s in (v or {}).get("scenarios", []) if s["scenario"] == "base"), None)
    if not base:
        return _res(False, "缺基准情景")
    cap = float(params.get("max", 0.8))
    return _res(base["tv_percent_ev"] <= cap, f"终值占 EV {base['tv_percent_ev']:.1%}（阈值 {cap:.0%}）")


def check_forecast_continuity(b: Bundle, params: dict) -> dict[str, Any]:
    fs = _json(b.run / "valuation" / "forecast_summary.json")
    years = (fs or {}).get("years") or []
    actual = [y for y in years if str(y.get("year", "")).endswith("A")]
    est = [y for y in years if str(y.get("year", "")).endswith("E")]
    if not actual or not est:
        return _res(False, "forecast_summary.json 缺实际年或预测年")
    a, e = actual[-1], est[0]
    gm = abs((e.get("gross_margin") or 0) - (a.get("gross_margin") or 0))
    g = abs((e.get("revenue_growth") or 0) - (a.get("revenue_growth") or 0))
    lim_gm, lim_g = float(params.get("gross_margin_pp", 5)), float(params.get("growth_pp", 30))
    return _res(gm <= lim_gm and g <= lim_g,
                f"{a['year']}→{e['year']}：毛利率变动 {gm:.2f}pct（阈值 {lim_gm:g}），收入增速变动 {g:.2f}pct（阈值 {lim_g:g}）")


def check_text_valuation(b: Bundle, params: dict) -> dict[str, Any]:
    v = _json(b.run / "valuation" / "valuation.json")
    fs = _json(b.run / "valuation" / "forecast_summary.json")
    if not v or not b.narrative.is_file():
        return _res(False, "缺估值结果或文稿")
    text = _text(b)
    vps = v["value_range"]["base"]
    shown = [f"{vps:{sep}.{d}f}" for d in (2, 1, 0) for sep in (",", "")]
    hit = next((s for s in shown if re.search(re.escape(s) + r"(?!\d)", text)), None)
    rating = ((fs or {}).get("rating") or {}).get("rating")
    ok_rating = bool(rating) and rating in text
    return _res(bool(hit) and ok_rating, f"基准每股价值 {vps:.2f} 元：{'正文写作 ' + hit if hit else '正文未出现'}；"
                f"评级 {rating or '—'}：{'正文已写' if ok_rating else '正文未写'}")


def check_sources(b: Bundle, params: dict) -> dict[str, Any]:
    """不只看 sources.json 在不在：结构校验、正文确有引用、引用编号已登记、外部数字所在句带对应编号。"""
    from ..output.guard import check_text, truth_values
    from ..output.sources import MARK, check_citations, verify_sources

    if miss := _missing(b.sources):
        return miss
    data, text = _json(b.sources), _text(b)
    vs = verify_sources(data)
    cited = MARK.findall(text)
    cite_problems = check_citations(text, data, truth_values(b.run), check_text) if text else []
    unused = sorted({s["id"] for s in data.get("sources") or []} - set(cited))
    detail = (f"{vs['n_questions']} 个问题、{vs['n_queries']} 次检索、{vs['n_sources']} 个来源，正文引用 {len(cited)} 处"
              + (f"；{len(vs['problems'])} 处结构问题" if vs["problems"] else "")
              + (f"；{len(cite_problems)} 处引用问题" if cite_problems else "")
              + (f"；{len(unused)} 个来源未在正文引用" if unused else ""))
    bad = vs["problems"][:3] + [f"{p['problem']}：{p['sentence']}" for p in cite_problems[:3]]
    return _res(vs["ok"] and bool(cited) and not cite_problems, detail, "；".join(bad))


def check_price(b: Bundle, params: dict) -> dict[str, Any]:
    fs = _json(b.run / "valuation" / "forecast_summary.json")
    mk = (fs or {}).get("market") or {}
    miss = [k for k in ("price", "price_date", "price_source") if not mk.get(k)]
    return _res(not miss, f"{mk.get('price', '—')} 元，{mk.get('price_date') or '无日期'}" + ("；缺 " + "、".join(miss) if miss else ""),
                str(mk.get("price_source", ""))[:120])


def check_numlock(b: Bundle, params: dict) -> dict[str, Any]:
    from ..output.numlock import numlock

    if miss := _missing(b.draft, b.narrative):
        return _res(False, miss["detail"] + "（没有经过独立复核改写）")
    lock = numlock(b.draft.read_text(encoding="utf-8"), _text(b))
    return _res(lock["ok"], f"删去数字 {lock['removed']} 个" + ("" if lock["ok"] else "，新增 " + "、".join(
        lock["added"] + lock["new_sources"])))


def check_review_list(b: Bundle, params: dict) -> dict[str, Any]:
    """只数填写完整的事项：表格行（去掉表头与分隔行）至少四格有内容，或列表项；明确写“无”也算通过。"""
    if miss := _missing(b.review):
        return miss
    lines = [ln.strip() for ln in b.review.read_text(encoding="utf-8").splitlines()]
    body = [ln for ln in lines if ln and not ln.startswith("#")]
    if body and all(re.fullmatch(r"[（(]?无[)）。]?", ln) for ln in body):
        return _res(True, "review.md 写明无待复核事项")
    rows = [ln for ln in body if ln.startswith("|")]
    cells = [[c.strip() for c in ln.strip("|").split("|")] for ln in rows]
    cells = [c for c in cells if not all(re.fullmatch(r":?-{3,}:?", x) for x in c if x)]  # 分隔行
    need = min(4, len(cells[0])) if cells else 0
    items = [c for c in cells[1:] if sum(bool(x) and x not in ("—", "-") for x in c) >= need]
    bullets = [ln for ln in body if re.match(r"[-*]\s+\S", ln) and len(ln) > 8]
    n = len(items) + len(bullets)
    return _res(n > 0, f"review.md {n} 条完整事项" + ("" if n else "（只有表头或空项）"))


CHECKS: dict[str, Callable[[Bundle, dict], dict[str, Any]]] = {
    name[len("check_"):]: fn for name, fn in globals().items() if name.startswith("check_") and callable(fn)}


def run_checks(rubric: dict[str, Any], b: Bundle) -> dict[str, dict[str, Any]]:
    out = {}
    for it in rubric["items"]:
        if it["judge"] != "program":
            continue
        fn = CHECKS.get(it["check"])
        if fn is None:
            raise ValueError(f"{it['id']}: 没有名为 {it['check']} 的程序检查")
        try:
            out[it["id"]] = fn(b, it.get("params") or {})
        except Exception as e:  # 产物格式异常也要出结果，不让一条检查拖垮整份评测
            out[it["id"]] = _res(False, f"检查出错：{type(e).__name__}: {e}")
    return out
