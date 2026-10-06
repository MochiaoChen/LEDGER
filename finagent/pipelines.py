"""计算引擎的三条任务流水线（财报分析 / 估值建模 / 纠错核查）。不调用模型：模型会话写下的抽取、经营数据、断言文件由这里校验后接入。

    财报 ──parse──▶ extract ──▶ analyze ──▶ 财报分析报告           （财报分析）
                                  │
                                  ├──▶ 三表模型 ──▶ build_plan ──▶ DCF ──▶ 估值报告  （估值建模）
                                  │
    研报 ──parse──▶ claims ──────┴──▶ verify ──▶ 核查报告          （纠错核查）

分析结果（含派生指标）形成“真值表”，同时服务估值与核查，保证三个任务口径一致。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .core import tracing
from .core.orchestrator import Pipeline
from .output import report as R
from .output.xlsx import write_xlsx
from .parsing.document import load_document
from .tasks.financials import earnings as earnings_mod
from .tasks.financials.analyze import analyze
from .tasks.financials.external import ingest
from .tasks.financials.extract import extract_financials
from .tasks.financials.extras import verify_extras
from .tasks.report_check import consistency as consistency_mod
from .tasks.report_check.claims import extract_claims, ingest_claims
from .tasks.report_check.verify import verify_claims
from .tasks.valuation.build_plan import build_plan, resolve_non_operating_items
from .tasks.valuation import comps as comps_mod
from .tasks.valuation import forecast_summary as forecast_mod
from .tasks.valuation import reverse_dcf as reverse_mod
from .tasks.valuation import segment_forecast as segment_mod
from .tasks.valuation import scenarios as scenarios_mod
from .tasks.valuation import three_statement as ts_mod
from .tasks.valuation.run import run_dcf
from .tasks.valuation.workbook import model_sheets


# ------------------------------------------------------------------ 公共步骤
def _write(ctx: dict[str, Any], name: str, content: str | dict | list) -> None:
    tr = tracing.current()
    if tr is None:
        return
    if isinstance(content, str):
        tr.write_artifact(name, content)
    else:
        tr.write_json(name, content)


# ------------------------------------------------------------------ 财报分析
financials_pipeline = Pipeline("financials")


@financials_pipeline.step("parse", "doc")
def _p_parse(ctx: dict[str, Any]):
    return load_document(ctx["input"])


@financials_pipeline.step("extract", "extract")
def _p_extract(ctx: dict[str, Any]):
    if ctx.get("facts_file"):  # 分析师会话读 PDF 的抽取结果，经证据校验并与规则通道比对
        payload = json.loads(tracing.read_file(ctx["facts_file"]).decode("utf-8"))
        _write(ctx, "financials/skill_extraction.json", payload)
        out = ingest(ctx["doc"], payload, fiscal_year=ctx.get("fiscal_year"),
                     supplements=[load_document(x) for x in ctx.get("supplements") or []])
    else:  # 没有模型抽取文件时只走规则通道（样例回归与引擎测试）
        out = extract_financials(ctx["doc"], fiscal_year=ctx.get("fiscal_year"))
    _write(ctx, "financials/facts.json", out)
    _write(ctx, "financials/facts.csv", R.to_csv(out["facts"], ["metric_id", "metric_name", "period", "value", "raw", "unit",
                                                               "label", "method", "confidence", "source"]))
    return out


@financials_pipeline.step("analyze", "analysis")
def _p_analyze(ctx: dict[str, Any]):
    out = analyze(ctx["extract"]["facts"], period=ctx.get("period"), doc=ctx["doc"],
                  extract_issues=ctx["extract"]["issues"])
    _write(ctx, "financials/analysis.json", out)
    if ctx.get("facts_file"):
        extraction = ctx["extract"]
        conflicts = [i for i in extraction["issues"] if i["type"] in
                     ("同一指标多处取值不一致", "规则与LLM抽取不一致")]
        failed_tieouts = [t for t in out["tieouts"] if t["status"] == "fail"]
        blocking_missing = [m for m in extraction["missing"] if m["blocking"]]
        if extraction["rejected"] or conflicts or failed_tieouts or blocking_missing:
            raise ValueError("模型抽取未通过校验，请先运行 verify-facts 并处理拒收、冲突、勾稽失败和核心缺失项")
    return out


@financials_pipeline.step("extras", "extras")
def _p_extras(ctx: dict[str, Any]):
    """经营数据补充表格：逐格核对原文，拒收即停止（与抽取校验同一标准）。"""
    if not ctx.get("extras_file"):
        return None
    payload = json.loads(tracing.read_file(ctx["extras_file"]).decode("utf-8"))
    out = verify_extras(ctx["doc"], payload, ctx["analysis"]["truth_table"])
    if out["rejected"]:
        raise ValueError(f"补充表格有 {len(out['rejected'])} 个数字未通过原文核对，请先运行 verify-extra")
    _write(ctx, "financials/extras.json", out)
    return out


@financials_pipeline.step("earnings", "earnings")
def _p_earnings(ctx: dict[str, Any]):
    a = ctx["analysis"]
    s1 = next((s for s in a["signals"] if s["id"] == "S1"), None)
    cells = {(c["metric_id"], c["period"]): c["value"] for c in a["truth_table"]}
    nr, npp = cells.get(("non_recurring", a["period"])), cells.get(("np_parent", a["period"]))
    share = nr / npp * 100 if nr is not None and npp else None
    out = earnings_mod.run(a["truth_table"], a["period"], estimates_path=ctx.get("estimates"),
                           guidance_path=ctx.get("guidance"), nonrec_share=share if s1 or share else None)
    _write(ctx, "financials/earnings.json", out)
    return out


@financials_pipeline.step("report", "financials_report")
def _p_report(ctx: dict[str, Any]):
    md = R.render_financials(ctx["company"], ctx["extract"], ctx["analysis"]) + R.render_earnings(ctx["earnings"])
    _write(ctx, "financials/report.md", md)
    return {"report": "financials/report.md"}


# ------------------------------------------------------------------ 估值建模
valuation_pipeline = Pipeline("valuation")


# 三表模型先行：DCF 的各情景经营预测取自三表模型输出（见 build_plan / run_dcf 的一致性核对）
@valuation_pipeline.step("three_statement", "three_statement")
def _v_three_statement(ctx: dict[str, Any]):
    raw = tracing.read_file(ctx["assumptions"])
    ctx["assumptions_data"] = json.loads(raw.decode("utf-8"))
    spec = ctx["assumptions_data"].get("segment_forecast")
    if spec:  # 分部驱动：产品量价 → 收入增速、毛利率、经营费用率（覆盖假设文件中的对应向量）
        if not ctx.get("extras"):
            raise ValueError("假设文件含 segment_forecast，需要 --extras 提供分部经营数据")
        n = len(ctx["assumptions_data"]["scenarios"]["base"]["revenue_growth"])
        seg = segment_mod.build(spec, ctx["extras"], ctx["analysis"]["truth_table"], ctx["analysis"]["period"], n)
        segment_mod.apply(ctx["assumptions_data"], seg)
        ctx["segment_forecast"] = seg
        _write(ctx, "valuation/segment_forecast.json", seg)
    non_op = ctx["assumptions_data"].get("non_operating_assets")
    if isinstance(non_op, list):  # 明细写法：逐项核对原文后由程序加总（百万元）
        resolved = resolve_non_operating_items(non_op, ctx.get("doc"))
        ctx["assumptions_data"]["non_operating_assets"] = resolved["total_mm"]
        ctx["assumptions_data"]["non_operating_items"] = resolved["items"]
        _write(ctx, "valuation/non_operating_assets.json", resolved)
    plan, notes = ts_mod.build_plan(ctx["analysis"]["truth_table"], ctx["assumptions_data"], company=ctx["company"],
                                    period=ctx["analysis"]["period"])
    ctx["three_statement_notes"] = notes
    ctx["three_statement_plan"] = plan
    _write(ctx, "valuation/three_statement_plan.json", plan)
    out = ts_mod.run(plan)
    _write(ctx, "valuation/three_statement.json", out)
    ctx["three_statement_detail"] = ts_mod.detail(plan)
    _write(ctx, "valuation/three_statement_detail.json", ctx["three_statement_detail"])
    return out


@valuation_pipeline.step("build_plan", "plan")
def _v_plan(ctx: dict[str, Any]):
    plan, notes = build_plan(ctx["analysis"]["truth_table"], ctx["assumptions_data"], company=ctx["company"],
                             period=ctx["analysis"]["period"], source_name=Path(ctx["input"]).name,
                             three_statement=ctx["three_statement"])
    ctx["plan_notes"] = notes
    _write(ctx, "valuation/plan.json", plan)
    return plan


@valuation_pipeline.step("dcf", "valuation")
def _v_dcf(ctx: dict[str, Any]):
    res = run_dcf(ctx["plan"], ctx["assumptions_data"].get("current_price"), ctx["three_statement"]["dcf_drivers"])
    _write(ctx, "valuation/valuation.json", res)
    return res


@valuation_pipeline.step("reverse_dcf", "reverse_dcf")
def _v_reverse_dcf(ctx: dict[str, Any]):
    """参考股价隐含的收入增速、利润率、折现率与终值参数（逐个单独求解）。"""
    if ctx["valuation"].get("status") != "ok" or not ctx["assumptions_data"].get("current_price"):
        return None
    hist = reverse_mod.history(ctx["analysis"]["truth_table"], ctx["analysis"]["period"])
    out = reverse_mod.run(ctx["plan"], ctx["valuation"], ctx["assumptions_data"]["current_price"], hist)
    _write(ctx, "valuation/reverse_dcf.json", out)
    return out


@valuation_pipeline.step("scenarios", "scenarios")
def _v_scenarios(ctx: dict[str, Any]):
    if ctx["valuation"].get("status") != "ok":
        return None
    payload = scenarios_mod.build_payload(ctx["analysis"]["truth_table"], ctx["analysis"]["period"], ctx["valuation"],
                                          ctx["plan"], ctx["assumptions_data"], ctx["analysis"]["signals"])
    out = scenarios_mod.run(payload)
    _write(ctx, "valuation/scenarios.json", out)
    return out


@valuation_pipeline.step("forecast_summary", "forecast_summary")
def _v_forecast_summary(ctx: dict[str, Any]):
    out = forecast_mod.build(ctx["analysis"]["truth_table"], ctx["analysis"]["period"], ctx.get("three_statement"),
                             ctx["assumptions_data"], ctx.get("valuation"))
    _write(ctx, "valuation/forecast_summary.json", out)
    return out


@valuation_pipeline.step("comps", "comps")
def _v_comps(ctx: dict[str, Any]):
    if not ctx.get("peers"):
        return None
    target = comps_mod.target_row(ctx["analysis"]["truth_table"], ctx["analysis"]["period"], ctx["plan"], ctx["company"],
                                  ctx["assumptions_data"])
    peers = comps_mod.load_peers(ctx["peers"])
    out = comps_mod.run(peers, target, ctx["valuation"].get("value_range"))
    _write(ctx, "valuation/comps.json", out)
    tr = tracing.current()
    if tr is not None:
        path = tr.dir / "valuation" / "comps_formula_workbook.xlsx"
        comps_mod.write_formula_workbook(path, out, "CNY", ctx["assumptions_data"]["valuation_date"])
        tr.register_artifact(path)
    return out


@valuation_pipeline.step("valuation_report", "valuation_report")
def _v_report(ctx: dict[str, Any]):
    res = ctx["valuation"]
    md = R.render_valuation(ctx["company"], ctx["plan"], res, ctx["plan_notes"], ctx["assumptions_data"])
    if ctx.get("three_statement"):
        md += R.render_three_statement(ctx["three_statement"], ctx["three_statement_notes"])
    if ctx.get("scenarios"):
        md += R.render_scenarios(ctx["scenarios"])
    if ctx.get("comps"):
        md += R.render_comps(ctx["comps"])
    if ctx.get("reverse_dcf"):
        md += R.render_reverse_dcf(ctx["reverse_dcf"])
    _write(ctx, "valuation/report.md", md)
    if res.get("status") == "ok" and tracing.current() is not None:
        sheets = model_sheets(ctx["company"], ctx["plan"], res, ctx.get("three_statement"), ctx.get("comps"),
                              analysis=ctx.get("analysis"), three_statement_plan=ctx.get("three_statement_plan"),
                              non_operating_items=ctx["assumptions_data"].get("non_operating_items"),
                              forecast_summary=ctx.get("forecast_summary"), extras=ctx.get("extras"),
                              three_statement_detail=ctx.get("three_statement_detail"),
                              segment_forecast=ctx.get("segment_forecast"))
        path = tracing.current().dir / "valuation" / "model.xlsx"
        write_xlsx(path, sheets)
        tracing.current().register_artifact(path)
    return {"sections": [k for k in ("three_statement", "scenarios", "comps") if ctx.get(k)]}


# ------------------------------------------------------------------ 纠错核查
check_pipeline = Pipeline("report_check")


@check_pipeline.step("parse_report", "report_doc")
def _c_parse(ctx: dict[str, Any]):
    return load_document(ctx["report"])


@check_pipeline.step("claims", "claims")
def _c_claims(ctx: dict[str, Any]):
    if ctx.get("claims_file"):  # 模型会话拆出的断言，引用须为原文片段
        payload = json.loads(tracing.read_file(ctx["claims_file"]).decode("utf-8"))
        _write(ctx, "check/skill_claims.json", payload)
        out, rejected = ingest_claims(ctx["report_doc"], payload, ctx.get("fiscal_year"))
        if rejected:
            _write(ctx, "check/claims_rejected.json", rejected)
    else:
        out = extract_claims(ctx["report_doc"], default_year=ctx.get("fiscal_year"))
    _write(ctx, "check/claims.json", out)
    return out


@check_pipeline.step("verify", "check")
def _c_verify(ctx: dict[str, Any]):
    out = verify_claims(ctx["claims"], ctx["analysis"]["truth_table"])
    _write(ctx, "check/findings.json", out)
    _write(ctx, "check/findings.csv", R.to_csv(out["findings"], [
        "claim_id", "metric_name", "period", "claim_type", "raw_value", "unit", "quote", "verdict",
        "truth_display", "explanation", "suggestion", "location"]))
    _write(ctx, "check/report.md", R.render_check(Path(ctx["report"]).name, out))
    return out


@check_pipeline.step("consistency", "consistency")
def _c_consistency(ctx: dict[str, Any]):
    """研报内部一致性（不依赖真值表）：评级、各情景每股价值、预测年度公司整体收入与利润前后不一。"""
    year = ctx.get("fiscal_year") or int(str(ctx["analysis"]["period"])[:4])
    if str(ctx["report"]).lower().endswith(".md"):
        text, pages = tracing.read_file(ctx["report"]).decode("utf-8"), None
    else:  # PDF 等：按文本块拼接，行号换算回页码
        lines, pages = [], []
        for ch in ctx["report_doc"].texts():
            for ln in ch.text.splitlines():
                lines.append(ln)
                pages.append(ch.page)
        text = "\n".join(lines)
    out = consistency_mod.check(text, year)
    for f in out["findings"]:
        for m in f["mentions"]:
            m["page"] = pages[m["line"] - 1] if pages else None
    _write(ctx, "check/consistency.json", out)
    _write(ctx, "check/report.md", R.render_check(Path(ctx["report"]).name, ctx["check"])
           + R.render_consistency(out, pages is not None))
    return out


# ------------------------------------------------------------------ 入口
def run(task: str, ctx: dict[str, Any]) -> dict[str, Any]:
    """task: financials | valuation | check | all"""
    financials_pipeline.run(ctx)
    if task in ("valuation", "all"):
        valuation_pipeline.run(ctx)
    if task in ("check", "all"):
        check_pipeline.run(ctx)
    return ctx
