"""三条任务流水线（赛题 2 / 4 / 5）与 Agent 可调用的 Tool 注册。

    财报 ──parse──▶ extract ──▶ analyze ──▶ 财报分析报告           （赛题2）
                                  │
                                  ├──▶ build_plan ──▶ DCF ──▶ 估值报告  （赛题4）
                                  │
    研报 ──parse──▶ claims ──────┴──▶ verify ──▶ 核查报告          （赛题5）

分析结果（含派生指标）形成“真值表”，同时服务估值与核查，保证三个任务口径一致。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .core import tracing
from .core.llm import LLMClient, LLMError
from .core.orchestrator import Pipeline
from .core.tools import registry
from .output import report as R
from .output.xlsx import write_xlsx
from .parsing.document import load_document
from .prompts import load_prompt
from .tasks.financials.analyze import analyze
from .tasks.financials.extract import extract_financials
from .tasks.report_check.claims import extract_claims
from .tasks.report_check.verify import verify_claims
from .tasks.valuation.build_plan import build_plan
from .tasks.valuation.run import run_dcf, workbook_sheets


# ------------------------------------------------------------------ 公共步骤
def _write(ctx: dict[str, Any], name: str, content: str | dict | list) -> None:
    tr = tracing.current()
    if tr is None:
        return
    if isinstance(content, str):
        tr.write_artifact(name, content)
    else:
        tr.write_json(name, content)


def commentary(company: str, analysis: dict[str, Any], llm: LLMClient | None) -> dict[str, Any] | None:
    """LLM 解读 + 数字护栏：解读中每个数字都必须出现在输入数据里。"""
    if llm is None or not llm.enabled:
        return None
    payload = {"company": company, "period": analysis["period"],
               "changes": [{k: r.get(k) for k in ("metric", "value", "yoy_pct", "yoy_change_pp")} for r in analysis["changes"]],
               "signals": [{k: s[k] for k in ("id", "title", "fact", "inference")} for s in analysis["signals"]]}
    data_text = json.dumps(payload, ensure_ascii=False)
    try:
        msg = llm.chat([{"role": "system", "content": load_prompt("analysis_commentary")},
                        {"role": "user", "content": data_text}], purpose="analysis_commentary")
    except LLMError as exc:
        tracing.log("commentary_failed", error=str(exc))
        return None
    text = msg.get("content") or ""
    allowed = set(re.findall(r"\d+(?:\.\d+)?", data_text.replace(",", "")))
    # 允许年份与序号类小整数
    nums = [n for n in re.findall(r"\d+(?:\.\d+)?", text.replace(",", "")) if not re.fullmatch(r"20\d{2}|\d", n)]
    unverified = sorted({n for n in nums if n not in allowed and not any(a.startswith(n) for a in allowed)})
    tracing.log("number_guard", checked=len(nums), unverified=unverified)
    return {"text": text, "model": llm.s.llm_model, "unverified_numbers": unverified}


# ------------------------------------------------------------------ 赛题2
financials_pipeline = Pipeline("financials")


@financials_pipeline.step("parse", "doc")
def _p_parse(ctx: dict[str, Any]):
    return load_document(ctx["input"])


@financials_pipeline.step("extract", "extract")
def _p_extract(ctx: dict[str, Any]):
    out = extract_financials(ctx["doc"], fiscal_year=ctx.get("fiscal_year"), llm=ctx.get("llm"),
                             llm_mode=ctx.get("llm_extract", "fallback"))
    _write(ctx, "financials/facts.json", out)
    _write(ctx, "financials/facts.csv", R.to_csv(out["facts"], ["metric_id", "metric_name", "period", "value", "raw", "unit",
                                                               "label", "method", "confidence", "source"]))
    return out


@financials_pipeline.step("analyze", "analysis")
def _p_analyze(ctx: dict[str, Any]):
    out = analyze(ctx["extract"]["facts"], period=ctx.get("period"), doc=ctx["doc"],
                  extract_issues=ctx["extract"]["issues"])
    _write(ctx, "financials/analysis.json", out)
    return out


@financials_pipeline.step("report", "financials_report")
def _p_report(ctx: dict[str, Any]):
    com = commentary(ctx["company"], ctx["analysis"], ctx.get("llm"))
    md = R.render_financials(ctx["company"], ctx["extract"], ctx["analysis"], com)
    _write(ctx, "financials/report.md", md)
    return {"commentary": com is not None}


# ------------------------------------------------------------------ 赛题4
valuation_pipeline = Pipeline("valuation")


@valuation_pipeline.step("build_plan", "plan")
def _v_plan(ctx: dict[str, Any]):
    raw = tracing.read_file(ctx["assumptions"])
    ctx["assumptions_data"] = json.loads(raw.decode("utf-8"))
    plan, notes = build_plan(ctx["extract"]["facts"], ctx["assumptions_data"], company=ctx["company"],
                             period=ctx["analysis"]["period"], source_name=Path(ctx["input"]).name)
    ctx["plan_notes"] = notes
    _write(ctx, "valuation/plan.json", plan)
    return plan


@valuation_pipeline.step("dcf", "valuation")
def _v_dcf(ctx: dict[str, Any]):
    res = run_dcf(ctx["plan"], ctx["assumptions_data"].get("current_price"))
    _write(ctx, "valuation/valuation.json", res)
    if res.get("status") == "ok" and tracing.current() is not None:
        path = tracing.current().dir / "valuation" / "model.xlsx"
        write_xlsx(path, workbook_sheets(ctx["plan"], res))
        tracing.current().register_artifact(path)
    _write(ctx, "valuation/report.md",
           R.render_valuation(ctx["company"], ctx["plan"], res, ctx["plan_notes"], ctx["assumptions_data"]))
    return res


# ------------------------------------------------------------------ 赛题5
check_pipeline = Pipeline("report_check")


@check_pipeline.step("parse_report", "report_doc")
def _c_parse(ctx: dict[str, Any]):
    return load_document(ctx["report"])


@check_pipeline.step("claims", "claims")
def _c_claims(ctx: dict[str, Any]):
    out = extract_claims(ctx["report_doc"], default_year=ctx.get("fiscal_year"), llm=ctx.get("llm"))
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


# ------------------------------------------------------------------ 入口
def run(task: str, ctx: dict[str, Any]) -> dict[str, Any]:
    """task: financials | valuation | check | all"""
    financials_pipeline.run(ctx)
    if task in ("valuation", "all"):
        valuation_pipeline.run(ctx)
    if task in ("check", "all"):
        check_pipeline.run(ctx)
    return ctx


# ------------------------------------------------------------------ Agent 工具
_STATE: dict[str, Any] = {}


@registry.register("analyze_financial_report", "解析财报文件，抽取财务指标，计算同比/环比、勾稽校验与异常信号。",
                   {"type": "object", "properties": {
                       "path": {"type": "string", "description": "财报文件路径（PDF/MD）"},
                       "fiscal_year": {"type": "integer"}, "company": {"type": "string"}},
                    "required": ["path", "fiscal_year"]})
def tool_analyze(path: str, fiscal_year: int, company: str = "目标公司") -> dict[str, Any]:
    ctx = {"input": path, "fiscal_year": fiscal_year, "company": company, "llm": _STATE.get("llm")}
    financials_pipeline.run(ctx)
    _STATE["ctx"] = ctx
    a = ctx["analysis"]
    return {"period": a["period"], "changes": a["changes"], "tieouts": [{k: c.get(k) for k in ("check", "status")} for c in a["tieouts"]],
            "signals": a["signals"]}


@registry.register("run_dcf_valuation", "基于已分析的财报与估值假设文件运行 DCF 三情景估值与敏感性分析（需先调用 analyze_financial_report）。",
                   {"type": "object", "properties": {"assumptions_path": {"type": "string"}},
                    "required": ["assumptions_path"]})
def tool_valuation(assumptions_path: str) -> dict[str, Any]:
    ctx = _STATE["ctx"]
    ctx["assumptions"] = assumptions_path
    valuation_pipeline.run(ctx)
    v = ctx["valuation"]
    return {k: v.get(k) for k in ("status", "model_status", "value_range", "scenarios", "checks")}


@registry.register("check_research_report", "将研报草稿中的数字断言与已分析财报逐条核对，输出错误与修改建议（需先调用 analyze_financial_report）。",
                   {"type": "object", "properties": {"report_path": {"type": "string"}}, "required": ["report_path"]})
def tool_check(report_path: str) -> dict[str, Any]:
    ctx = _STATE["ctx"]
    ctx["report"] = report_path
    check_pipeline.run(ctx)
    c = ctx["check"]
    return {"summary": c["summary"],
            "errors": [{k: f[k] for k in ("claim_id", "quote", "verdict", "truth_display", "suggestion")}
                       for f in c["findings"] if f["verdict"] not in ("正确", "无法核实")]}


def bind_llm(llm: LLMClient | None) -> None:
    _STATE["llm"] = llm
