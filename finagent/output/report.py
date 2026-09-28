"""报告渲染：Markdown 报告 + CSV 表。报告统一区分【事实】【推论】【观点】，数字均附来源定位。"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from ..core.numbers import fmt_pct, fmt_yi
from ..tasks.financials.schema import BY_ID

SEV = {"high": "🔴 高", "medium": "🟠 中", "low": "🟡 低", "info": "⚪ 提示"}


def loc(src: dict[str, Any] | None) -> str:
    if not src:
        return "—"
    if "formula" in src:
        parts = [loc(s) for s in src.get("derived_from") or [] if s]
        return f"计算：{src['formula']}" + (f"（{'；'.join(parts)}）" if parts else "")
    if "derived_from" in src:
        parts = [loc(s) for s in src["derived_from"] if s]
        return "派生自 " + "；".join(parts)
    name = Path(src.get("source", "")).name
    cell = f" 行{src['row']}列{src['col']}" if "row" in src else ""
    return f"{name} p.{src.get('page')} {src.get('chunk_id', '')}{cell}"


def fmt_value(metric_id: str, v: float | None) -> str:
    if v is None:
        return "—"
    kind = BY_ID[metric_id].kind if metric_id in BY_ID else "amount"
    if kind == "amount":
        return fmt_yi(v)
    if kind == "pct":
        return f"{v:.2f}%"
    if kind == "per_share":
        return f"{v:.2f} 元/股"
    if kind == "shares":
        return f"{v / 1e8:.2f} 亿股"
    return f"{v:.2f}"


def to_csv(rows: list[dict[str, Any]], columns: list[str]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: (loc(v) if isinstance(v, dict) else v) for k, v in r.items()})
    return "﻿" + buf.getvalue()  # BOM，Excel 打开不乱码


# ------------------------------------------------------------------ 财报分析
def render_financials(company: str, extract: dict[str, Any], analysis: dict[str, Any],
                      commentary: dict[str, Any] | None) -> str:
    p = analysis["period"]
    L = [f"# {company} {p} 财务报告分析", "",
         f"- 抽取指标：{extract['stats']['merged']} 项（规则通道 {extract['stats']['rule_facts']}，LLM 通道 {extract['stats']['llm_facts']}）",
         f"- 勾稽校验：{sum(c['status'] == 'pass' for c in analysis['tieouts'])} 通过 / "
         f"{analysis['summary']['tieout_fail']} 失败 / {sum(c['status'] == 'not_assessable' for c in analysis['tieouts'])} 无法评估",
         f"- 异常信号：{analysis['summary']['signals_total']} 条（高 {analysis['summary']['signals_high']}）", "",
         "## 一、事实：关键财务指标", "",
         "| 指标 | 本期 | 上年同期 | 同比 | 环比 | 来源 |", "|---|---|---|---|---|---|"]
    cells = {(c["metric_id"], c["period"]): c for c in analysis["truth_table"]}
    for r in analysis["changes"]:
        mid = r["metric_id"]
        if r["kind"] == "pct":
            chg = "—" if r.get("yoy_change_pp") is None else f"{r['yoy_change_pp']:+.2f}pp"
            qchg = "—" if r.get("qoq_change_pp") is None else f"{r['qoq_change_pp']:+.2f}pp"
        else:
            chg, qchg = fmt_pct(r.get("yoy_pct")), fmt_pct(r.get("qoq_pct"))
        src = (cells.get((mid, p)) or {}).get("source")
        L.append(f"| {r['metric']} | {fmt_value(mid, r['value'])} | {fmt_value(mid, r['yoy_base'])} | {chg} | {qchg} | {loc(src)} |")

    q = analysis.get("quarterly")
    if q:
        L += ["", f"### 分季度（单季，{q['year']} 年）", "",
              "单季数优先取财报列示；缺失时由累计数相减推出（Q2 = 上半年 − Q1；Q3 = 前三季度 − 上半年；"
              "Q4 = 全年 − 前三季度），标 * 者为推算值。", "",
              "| 指标 | 第一季度 | 第二季度 | 第三季度 | 第四季度 |", "|---|---|---|---|---|"]
        for r in q["rows"]:
            vals = [fmt_value(r["metric_id"], r["values"][k]) + ("*" if r["methods"][k] == "derived" else "")
                    for k in ("Q1", "Q2", "Q3", "Q4")]
            L.append(f"| {r['metric']} | " + " | ".join(vals) + " |")

    L += ["", "## 二、事实：勾稽与一致性校验", "", "| 校验项 | 结果 | 差异 |", "|---|---|---|"]
    icon = {"pass": "✅ 通过", "fail": "❌ 失败", "not_assessable": "⚪ 无法评估"}
    for c in analysis["tieouts"]:
        diff = "" if c.get("diff") is None else f"{c['diff']:,.4f}"
        L.append(f"| {c['check']} | {icon[c['status']]} | {diff} |")

    if extract["issues"]:
        L += ["", "### 抽取过程问题", ""]
        L += [f"- [{i['severity']}] {i['type']}：{i['message']}" for i in extract["issues"]]

    L += ["", "## 三、推论：异常信号", ""]
    if not analysis["signals"]:
        L.append("未识别到触发阈值的异常信号。")
    for s in analysis["signals"]:
        L += [f"### {s['id']} {s['title']}（{SEV.get(s['severity'], s['severity'])}｜{s['type']}）", "",
              f"- **事实**：{s['fact']}", f"- **推论**：{s['inference']}",
              "- **证据**：" + "；".join(loc(e) if "keywords" not in e else f"{Path(e['source']).name} p.{e['page']}「{e['quote'][:40]}…」"
                                     for e in s["evidence"] if e), ""]

    L += ["## 四、观点与待验证事项", ""]
    if commentary and commentary.get("text"):
        L.append(commentary["text"])
        if commentary.get("unverified_numbers"):
            L += ["", f"> ⚠️ 数字护栏：解读中出现未在输入数据中的数字 {commentary['unverified_numbers']}，请人工复核。"]
        L += ["", f"> 由 {commentary.get('model')} 生成，仅基于上表已核验数据；属于观点，不构成投资建议。"]
    else:
        L += ["（未启用 LLM，以下为规则生成的待验证清单）", ""]
        for s in analysis["signals"]:
            L.append(f"- [{s['id']}] {s['title']}：建议查阅附注/问询函核实原因。")
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ 估值
def render_valuation(company: str, plan: dict[str, Any], res: dict[str, Any], notes: list[dict[str, Any]],
                     assumptions: dict[str, Any]) -> str:
    if res.get("status") != "ok":
        return f"# {company} 估值\n\n模型被阻断：\n" + "\n".join(f"- {e}" for e in res.get("errors", [])) + "\n"
    vr = res["value_range"]
    price = res.get("current_price")
    L = [f"# {company} DCF 估值（FCFF）", "",
         f"- 估值基准日：{plan['meta']['valuation_date']}；货币单位：{plan['meta']['units']}",
         f"- 模型状态：`{res['model_status']}`（筛选级：假设来自分析师估计，需复核）",
         f"- **每股价值区间：{vr['low']:.2f} – {vr['high']:.2f} 元，基准 {vr['base']:.2f} 元**"
         + (f"；参考股价 {price:.2f} 元，基准情景空间 {(vr['base'] / price - 1) * 100:+.1f}%" if price else ""), "",
         "## 一、事实：历史基数（来自财报抽取）", "", "| 项目 | 2024 实际（百万元） |", "|---|---|"]
    h = plan["historicals"]
    for k, name in [("revenue", "营业收入"), ("ebit", "EBIT（剔除投资收益与公允价值变动）"), ("da", "折旧摊销"),
                    ("capex", "资本开支"),
                    ("net_working_capital", "营运资本"), ("change_nwc", "营运资本变动"), ("unlevered_fcf", "无杠杆自由现金流")]:
        L.append(f"| {name} | {h[k]:,.1f} |")
    hr = res.get("historical_ratios") or {}
    L += ["", "历史比率：" + "，".join(f"{k} {v * 100:.1f}%" for k, v in hr.items() if v is not None), "",
          "## 二、推论：三情景估值", "",
          "各情景的收入、EBIT、折旧摊销、资本开支、营运资本与税率取自三表模型同一情景的输出（见第五节），"
          "DCF 只做折现、终值与股权桥。"
          + (f"逐期核对最大偏差 {res['three_statement_tie']['max_abs_diff_mm']:.2e} 百万元"
             f"（{'✅ 一致' if res['three_statement_tie']['status'] == 'pass' else '❌ 不一致'}）。"
             if res.get("three_statement_tie") else ""), "",
          "| 情景 | WACC | 永续增长 | EV（百万元） | 股权价值（百万元） | 每股价值（元） | 终值占比 | 隐含EV/EBITDA |",
          "|---|---|---|---|---|---|---|---|"]
    for s in res["scenarios"]:
        L.append(f"| {s['scenario_cn']} | {s['wacc'] * 100:.2f}% | {s['terminal_growth'] * 100:.1f}% | "
                 f"{s['enterprise_value_mm']:,.0f} | {s['equity_value_mm']:,.0f} | **{s['value_per_share']:.2f}** | "
                 f"{s['tv_percent_ev'] * 100:.1f}% | {s['implied_exit_ebitda']:.1f}x |")
    L += [""] + [f"- **{s['scenario_cn']}**：{s['description']}" for s in res["scenarios"]]

    g = res["sensitivities"][0]
    L += ["", f"## 三、敏感性分析：{g['name']}（每股价值，元）", "",
          "| WACC 变动 \\ 永续增长变动 | " + " | ".join(f"{y * 100:+.1f}%" for y in g["y_values"]) + " |",
          "|---|" + "---|" * len(g["y_values"])]
    for x, row in zip(g["x_values"], g["matrix"]):
        L.append(f"| {x * 100:+.1f}% | " + " | ".join("—" if v is None else f"{v:.2f}" for v in row) + " |")
    L += ["", "其余敏感性矩阵（WACC×退出倍数、收入增速×利润率）见 model.xlsx。", "",
          "## 四、观点：主要假设、适用范围与风险", ""]
    for k, v in (assumptions.get("rationale") or {}).items():
        L.append(f"- **{k}**：{v}")
    L += ["", "**模型口径说明（推论/简化）**", ""] + [f"- {n['item']}：{n['detail']}" for n in notes]
    L += ["", "**模型检查**", ""] + [f"- ⚠️ {w}" for w in res["checks"].get("warnings") or []] + \
         [f"- ❌ {w}" for w in res["checks"].get("hard_failures") or []]
    L += ["", "> 适用范围：本估值为基于公开财报与显性假设的筛选级测算，终值占比较高，结论对 WACC 与永续增长率敏感；"
              "不构成投资建议。"]
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ 研报核查
def render_check(report_name: str, result: dict[str, Any]) -> str:
    s = result["summary"]
    L = [f"# 研报核查报告：{report_name}", "",
         f"- 可核验断言 {s['claims']} 条：❌ 错误 {s['errors']}，✅ 正确 {s['verified_correct']}，⚪ 无法核实 {s['unverifiable']}",
         "- 分类：" + "，".join(f"{k} {v}" for k, v in s["by_verdict"].items()), "",
         "## 一、错误清单与修改建议", "",
         "| # | 位置 | 原文 | 结论 | 财报真值 | 修改建议 | 来源 |", "|---|---|---|---|---|---|---|"]
    errs = [f for f in result["findings"] if f["verdict"] not in ("正确", "无法核实")]
    for f in errs:
        L.append(f"| {f['claim_id']} | p.{f['location'].get('page')} | {f['quote']} | **{f['verdict']}** | "
                 f"{f['truth_display']} | {f['suggestion']} | {'；'.join(loc(e) for e in f['evidence'])} |")
    if not errs:
        L.append("| — | — | 未发现错误 | — | — | — | — |")
    L += ["", "## 二、全部断言核查明细", "", "| # | 指标 | 期间 | 类型 | 研报值 | 结论 | 说明 |", "|---|---|---|---|---|---|---|"]
    for f in result["findings"]:
        L.append(f"| {f['claim_id']} | {f['metric_name']} | {f['period']} | {f['claim_type']} | {f['raw_value']}{f['unit']} | "
                 f"{f['verdict']} | {f['explanation']} |")
    L += ["", "> 容差按研报数字的展示精度计算；预测性表述与缺少真值的断言判为“无法核实”，不计入错误。"]
    return "\n".join(L) + "\n"


# ------------------------------------------------------------------ 新增模块渲染
SKEW_CN = {"underwriteable upside": "可承接的上行空间", "optical upside / needs proof": "表面上行、待验证",
           "negative skew": "负偏度", "balanced / watchlist": "均衡/观察", "input required": "缺少输入"}
ACTION_CN = {"add / press if evidence confirms": "证据确认后加仓", "hold / wait for proof": "持有等待验证",
             "trim / exit unless thesis is re-underwritten": "除非重新论证逻辑，否则减仓/退出",
             "watchlist / re-underwrite": "观察/重新论证", "input required": "缺少输入"}


COL_CN = {"scenario": "情景", "price_target": "目标价", "return_vs_share_price": "较现价", "expected_return_vs_hurdle": "超额于门槛",
          "downside_upside_ratio": "下行/上行比", "break_even_probability": "盈亏平衡概率", "skew_label": "偏度判断",
          "action_rule": "行动规则", "probability": "概率", "multiple": "倍数", "ev_ebitda_implied_price": "EV/EBITDA 隐含股价",
          "pe_implied_price": "P/E 隐含股价", "eps_revision": "EPS 修正", "multiple_change": "倍数变化", "revised_eps": "修正后 EPS",
          "revised_multiple": "修正后倍数", "implied_price": "隐含股价", "revenue_shock": "收入冲击", "margin_shock": "利润率冲击",
          "revenue_delta": "收入变动", "profit_impact": "EBIT 影响", "stress_case": "压力情景", "stressed_fcf": "压力 FCF",
          "liquidity_after_12m_maturities": "扣除 12 月到期后流动性", "minimum_liquidity": "最低流动性",
          "liquidity_headroom": "流动性余量", "debt_to_ebitda": "债务/EBITDA", "trigger": "触发条件", "threshold": "阈值",
          "monitoring_cadence": "跟踪频率", "next_step": "下一步", "source_or_owner": "来源"}
SCEN_CN2 = {"upside": "乐观", "base": "基准", "downside": "悲观", "probability_weighted": "概率加权"}


def _mm(v: float | None, d: int = 1) -> str:
    return "—" if v is None else f"{v:,.{d}f}"


def render_earnings(res: dict[str, Any]) -> str:
    L = ["", "## 五、业绩变化归因", ""]
    b = res.get("profit_bridge")
    if b:
        L += [f"### 利润变动归因桥（{b['base_period']} → {b['period']}，归母净利润，百万元）", "",
              f"归母净利润 {b['np_parent_start'] / 1e6:,.1f} → {b['np_parent_end'] / 1e6:,.1f}，变动 **{b['delta'] / 1e6:+,.1f}**；"
              f"逐项加总闭合误差 {b['closure_error']:.2e} 元。", "",
              "| 驱动项 | 贡献（百万元） | 占变动比例 | 口径 |", "|---|---|---|---|"]
        for it in b["items"]:
            sh = "—" if it["share_of_change"] is None else f"{it['share_of_change'] * 100:+.0f}%"
            L.append(f"| {it['item']} | {it['value'] / 1e6:+,.1f} | {sh} | {it['formula']} |")
        L += ["", f"- **推论**：影响最大的三项为 {'、'.join(b['drivers_ranked'])}。"]
        if b.get("non_recurring_share_of_delta") is not None:
            L.append(f"- **推论**：非经常性损益变动 {b['non_recurring_delta'] / 1e6:+,.1f} 百万元，相当于归母净利润变动的 "
                     f"{b['non_recurring_share_of_delta'] * 100:.0f}%"
                     + ("，剔除后经营性利润实际下降。" if b["non_recurring_share_of_delta"] > 1 else "。"))
    if res.get("beat_miss") and any(r["consensus"] is not None for r in res["beat_miss"]):
        L += ["", "### 实际 vs 预期", "", "| 指标 | 实际 | 一致预期 | 差异 | 内部预期 | 差异 | 来源 |", "|---|---|---|---|---|---|---|"]
        for r in res["beat_miss"]:
            d = 2 if "每股" in r["metric_cn"] else 1
            pc = lambda x: "—" if x is None else f"{x * 100:+.1f}%"  # noqa: E731
            L.append(f"| {r['metric_cn']} | {_mm(r['reported'], d)} | {_mm(r['consensus'], d)} | {pc(r['surprise_cons'])} | "
                     f"{_mm(r['internal'], d)} | {pc(r['surprise_int'])} | {r['source_tag']} |")
    if res.get("guidance"):
        L += ["", "### 实际 vs 业绩预告", "", "| 指标 | 预告区间 | 中值 | 一致预期 | 实际 | 位置 | 来源 |", "|---|---|---|---|---|---|---|"]
        for g in res["guidance"]:
            L.append(f"| {g['metric_cn']} | {_mm(g['low'])} – {_mm(g['high'])} | {_mm(g['midpoint'])} | {_mm(g['consensus'])} | "
                     f"{_mm(g['actual'])} | **{g['position'] or '—'}** | {g['source_tag']} |")
    for q in res.get("eps_quality", []):
        L += ["", "### EPS 质量筛查", "", f"- 基本每股收益 {q['eps']:.2f} 元，扣非每股收益 "
              f"{_mm(q['adjusted_eps'], 2)} 元",
              f"- 结论：**{q['status']}**。{q['read_through']}"]
    for lim in res.get("limitations", []):
        L.append(f"- 限制：{lim}")
    return "\n".join(L) + "\n"


def render_three_statement(res: dict[str, Any], notes: list[dict[str, Any]]) -> str:
    L = ["", "## 五、三表联动预测（基准情景，百万元）", "",
         f"模型状态：`{res['model_status']}`；硬性失败 {len(res['hard_failures'])} 项，警告 {len(res['warnings'])} 项。", ""]
    for name, st in res["statements"].items():
        L += [f"### {name}", "", "| 项目 | " + " | ".join(st["periods"]) + " |", "|---|" + "---|" * len(st["periods"])]
        for r in st["rows"]:
            L.append(f"| {r['name']} | " + " | ".join(_mm(v) for v in r["values"]) + " |")
        L.append("")
    L += ["### 勾稽检查", "", "| 检查项 | 最大误差 | 结果 |", "|---|---|---|"]
    L += [f"| {c['check']} | {c['max_abs_error']:.2e} | {'✅' if c['status'] == 'pass' else '❌'} |" for c in res["integrity"]]
    L += ["", "### 情景汇总", "", "| 情景 | 期末收入 | 期末 EBITDA | 期末 FCF | 期末现金 | 期末有息负债 | 峰值净杠杆 |", "|---|---|---|---|---|---|---|"]
    cn = {"base": "基准", "downside": "悲观", "upside": "乐观"}
    for k, s in res["scenario_summary"].items():
        L.append(f"| {cn.get(k, k)} | {_mm(s['final_revenue'])} | {_mm(s['final_ebitda'])} | {_mm(s['final_fcf'])} | "
                 f"{_mm(s['ending_cash'])} | {_mm(s['ending_debt'])} | {s['peak_net_leverage']:.2f}x |")
    for w in res["warnings"] + res["hard_failures"]:
        L.append(f"- ⚠️ {w.get('code')}：{w.get('message')}")
    L += [""] + [f"- {n['item']}：{n['detail']}" for n in notes]
    return "\n".join(L) + "\n"


def render_scenarios(res: dict[str, Any]) -> str:
    L = ["", "## 六、情景偏度与多维敏感性", "", f"就绪度：`{res['readiness']['model_status']}`", ""]
    for tb in res["tables"]:
        rows = tb["rows"]
        if not rows:
            continue
        cols = [c for c in tb["columns"] if c not in ("source_id", "source_posture", "as_of_date", "rationale",
                                                     "implication", "method_note", "flowthrough_note", "probability_check",
                                                     "probability_sum", "required_return")]
        L += [f"### {tb['name_cn']}", "", "| " + " | ".join(COL_CN.get(c, c) for c in cols) + " |", "|" + "---|" * len(cols)]
        for r in rows:
            vals = [r.get(c, "") for c in cols]
            vals = [SCEN_CN2.get(v, SKEW_CN.get(v, ACTION_CN.get(v, v))) if isinstance(v, str) else v for v in vals]
            L.append("| " + " | ".join(str(v) for v in vals) + " |")
        if tb["name"] == "equity_liquidity_downside":
            L += ["", "> 注：原脚本按 FCF ×(1+冲击) 计算，当 FCF 为负时冲击方向与直觉相反（负冲击反而改善），解读时请注意。"]
        L.append("")
    return "\n".join(L) + "\n"


def render_comps(res: dict[str, Any]) -> str:
    L = ["", "## 七、可比公司估值（相对估值）", "",
         f"核心同业 {res['core_peer_count']} 家，状态 `{res['status']}`。", "",
         "| 代码 | 公司 | 分组 | EV（百万元） | EV/收入 | EV/EBITDA | EV/EBIT | P/E（LTM） | P/E（NTM） |",
         "|---|---|---|---|---|---|---|---|---|"]
    fx = lambda v: "—" if v is None else (v if isinstance(v, str) else f"{v:.1f}x")  # noqa: E731
    for r in res["rows"]:
        L.append(f"| {r['ticker']} | {r['company']} | {r['peer_tier']} | {_mm(r['ev'], 0)} | {fx(r['ev_revenue'])} | "
                 f"{fx(r['ev_ebitda'])} | {fx(r['ev_ebit'])} | {fx(r['pe_ltm'])} | {fx(r['pe_ntm'])} |")
    L += ["", "| 倍数 | 核心 P25 | 核心中位数 | 核心 P75 | 目标公司 | 相对核心中位数 | IQR 离群值 |", "|---|---|---|---|---|---|---|"]
    for s in res["stats"].values():
        q = s["core"]
        prem = "—" if s["premium_vs_core_median"] is None else f"{s['premium_vs_core_median'] * 100:+.1f}%"
        L.append(f"| {s['name']} | {fx(q['p25'])} | {fx(q['median'])} | {fx(q['p75'])} | {fx(s['target'])} | {prem} | "
                 f"{'、'.join(s['outliers']) or '无'} |")
    L += ["", "| 方法 | P25 隐含股价 | 中位数隐含股价 | P75 隐含股价 |", "|---|---|---|---|"]
    for r in res["implied"]:
        L.append(f"| {r['multiple']} | {_mm(r['p25'], 2)} | {_mm(r['median'], 2)} | {_mm(r['p75'], 2)} |")
    if res.get("margins"):
        pc = lambda v: "—" if v is None else (v if isinstance(v, str) else f"{v * 100:.1f}%")  # noqa: E731
        L += ["", "**利润率对比**（核心同业；目标公司 EBIT 为剔除投资收益与公允价值变动后的经营性口径）", "",
              "| 利润率 | 核心 P25 | 核心中位数 | 核心 P75 | 目标公司 | 相对核心中位数 |", "|---|---|---|---|---|---|"]
        for m in res["margins"].values():
            q = m["core"]
            d = "—" if m["diff_vs_core_median"] is None else f"{m['diff_vs_core_median'] * 100:+.1f}pp"
            L.append(f"| {m['name']} | {pc(q['p25'])} | {pc(q['median'])} | {pc(q['p75'])} | {pc(m['target'])} | {d} |")
    if res["range"]:
        L += ["", f"- **相对估值区间：{res['range']['low']:.2f} – {res['range']['high']:.2f} 元（中值 {res['range']['mid']:.2f} 元）**"]
    c = res.get("dcf_cross_check")
    if c:
        L.append(f"- 交叉验证：DCF 基准 {c['dcf_base']:.2f} 元，较相对估值中值 {c['dcf_vs_comps_mid'] * 100:+.1f}%；"
                 f"两种方法区间{'有' if c['ranges_overlap'] else '无'}重叠。")
    for e in res["excluded"]:
        L.append(f"- 剔除 {e['company']}（{e['ticker']}）：{e['reason']}")
    L.append("- 口径：P25/P75 使用核心同业并剔除 IQR 离群值；分母 ≤ 0 记 NM；次要同业仅作参照。")
    return "\n".join(L) + "\n"
