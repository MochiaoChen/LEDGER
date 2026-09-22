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
    for k, name in [("revenue", "营业收入"), ("ebit", "EBIT（近似）"), ("da", "折旧摊销"), ("capex", "资本开支"),
                    ("net_working_capital", "营运资本"), ("change_nwc", "营运资本变动"), ("unlevered_fcf", "无杠杆自由现金流")]:
        L.append(f"| {name} | {h[k]:,.1f} |")
    hr = res.get("historical_ratios") or {}
    L += ["", "历史比率：" + "，".join(f"{k} {v * 100:.1f}%" for k, v in hr.items() if v is not None), "",
          "## 二、推论：三情景估值", "",
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
