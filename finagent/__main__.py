"""命令行入口。

  python -m finagent financials --input 年报.pdf --year 2024 --company 公司名
  python -m finagent valuation  --input 年报.pdf --year 2024 --assumptions 假设.json
  python -m finagent check      --input 年报.pdf --year 2024 --report 研报草稿.md
  python -m finagent all        --input ... --assumptions ... --report ...
  python -m finagent ask "分析这份年报并估值" （Agent 模式，需配置 LLM）

通用参数：--llm {live,replay,off}  --llm-extract {fallback,all,off}

Skill 版本（Claude Code 读 PDF，本程序负责定位、校验与计算，见 .claude/skills/finagent-research）：
  python -m finagent locate       --input 年报.pdf               # 关键页定位
  python -m finagent schema                                        # 可抽取指标清单
  python -m finagent verify-facts --input 年报.pdf --year 2024 --facts extracted.json
  python -m finagent all ... --facts extracted.json [--claims claims.json]
  python -m finagent guard        --run-dir runs/<id> --text 解读.md  # 解读数字护栏
"""

from __future__ import annotations

import argparse
import json
import sys

from pathlib import Path

from .core.config import get_settings
from .core.llm import LLMClient
from .core.orchestrator import Agent
from .core.tracing import RunTracer
from . import pipelines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="finagent", description="金融投研智能体")
    ap.add_argument("task", choices=["financials", "valuation", "check", "all", "ask",
                                     "locate", "schema", "verify-facts", "guard"])
    ap.add_argument("instruction", nargs="?", help="ask 模式的自然语言指令")
    ap.add_argument("--input", help="财报文件（PDF / MD）")
    ap.add_argument("--year", type=int, help="主报告期年份，如 2024")
    ap.add_argument("--period", help="分析期间，默认自动识别（如 2024 / 2024Q3）")
    ap.add_argument("--company", default="目标公司")
    ap.add_argument("--assumptions", help="估值假设 JSON")
    ap.add_argument("--report", help="待核查研报草稿（PDF / MD）")
    ap.add_argument("--peers", help="可比公司 CSV（可选，启用相对估值）")
    ap.add_argument("--estimates", help="一致预期/内部预期 CSV（可选，启用超预期分析）")
    ap.add_argument("--guidance", help="业绩预告 CSV（可选）")
    ap.add_argument("--llm", choices=["live", "replay", "off"], help="覆盖 LLM_MODE")
    ap.add_argument("--llm-extract", default="fallback", choices=["fallback", "all", "off"])
    ap.add_argument("--runs-dir")
    ap.add_argument("--facts", help="Skill 版本：外部模型抽取的财务数据 JSON")
    ap.add_argument("--claims", help="Skill 版本：外部模型拆出的研报断言 JSON")
    ap.add_argument("--out", help="verify-facts 校验结果输出路径")
    ap.add_argument("--run-dir", help="guard：已完成的运行目录")
    ap.add_argument("--text", help="guard：待检查的文字解读（Markdown）")
    args = ap.parse_args(argv)

    if args.task in HELPERS:
        return HELPERS[args.task](args, ap)

    settings = get_settings(llm_mode=args.llm, runs_dir=args.runs_dir)
    llm = LLMClient(settings) if settings.llm_enabled else None
    config = {**settings.public(), "task": args.task, "llm_extract": args.llm_extract,
              "extraction": "skill" if args.facts else "agent",
              "argv": sys.argv[1:] if argv is None else argv}

    with RunTracer(args.task, settings.runs_dir, config) as tr:
        if args.task == "ask":
            if llm is None:
                print("Agent 模式需要配置 LLM（LLM_API_KEY 或 --llm replay）", file=sys.stderr)
                return 2
            pipelines.bind_llm(llm)
            res = Agent(pipelines.registry, llm).run(args.instruction or "")
            tr.write_json("agent_transcript.json", res["messages"])
            tr.write_artifact("answer.md", res["answer"] or "")
            print(res["answer"])
        else:
            need = {"valuation": ["assumptions"], "check": ["report"], "all": ["assumptions", "report"]}
            missing = [k for k in ["input", *need.get(args.task, [])] if not getattr(args, k)]
            if missing:
                ap.error("缺少参数：" + ", ".join("--" + m for m in missing))
            ctx = {"input": args.input, "fiscal_year": args.year, "period": args.period, "company": args.company,
                   "assumptions": args.assumptions, "report": args.report, "llm": llm,
                   "peers": args.peers, "estimates": args.estimates, "guidance": args.guidance,
                   "llm_extract": args.llm_extract, "facts_file": args.facts, "claims_file": args.claims}
            pipelines.run(args.task, ctx)
            summary = {"run_dir": str(tr.dir), "financials": ctx["analysis"]["summary"]}
            if "valuation" in ctx:
                summary["valuation"] = {"model_status": ctx["valuation"].get("model_status"),
                                        "value_range": ctx["valuation"].get("value_range")}
            if ctx.get("comps") and ctx["comps"].get("range"):
                summary["comps_range"] = ctx["comps"]["range"]
            if ctx.get("three_statement"):
                summary["three_statement"] = {"model_status": ctx["three_statement"]["model_status"],
                                              "integrity_all_pass": all(c["status"] == "pass" for c in ctx["three_statement"]["integrity"])}
            if "check" in ctx:
                summary["check"] = ctx["check"]["summary"]
            tr.write_json("summary.json", summary)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


# ------------------------------------------------------------------ Skill 版本辅助命令（不生成运行目录）
def _need(ap: argparse.ArgumentParser, args: argparse.Namespace, *names: str) -> None:
    missing = [n for n in names if not getattr(args, n.replace("-", "_"))]
    if missing:
        ap.error("缺少参数：" + ", ".join("--" + m for m in missing))


def _print(obj: object) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_locate(args: argparse.Namespace, ap: argparse.ArgumentParser) -> int:
    from .parsing.document import load_document
    from .parsing.locate import locate, pdf_page_count

    _need(ap, args, "input")
    _print(locate(load_document(args.input), pdf_page_count(args.input)))
    return 0


def cmd_schema(args: argparse.Namespace, ap: argparse.ArgumentParser) -> int:
    from .tasks.financials.external import CORE_METRICS, metric_catalog
    from .tasks.financials.schema import METRICS

    _print({"facts": metric_catalog(), "core_metrics": CORE_METRICS,
             "claim_metrics": [{"metric_id": m.id, "name": m.name, "aliases": list(m.claim_aliases)}
                               for m in METRICS if m.claim_aliases]})
    return 0


def cmd_verify_facts(args: argparse.Namespace, ap: argparse.ArgumentParser) -> int:
    """预检：校验外部抽取结果，列出被拒绝、冲突、缺失与勾稽失败项；有阻断问题时返回 1。"""
    from .parsing.document import load_document
    from .tasks.financials.analyze import analyze
    from .tasks.financials.external import ingest

    _need(ap, args, "input", "facts")
    doc = load_document(args.input)
    res = ingest(doc, json.loads(Path(args.facts).read_text(encoding="utf-8")), fiscal_year=args.year)
    tieouts = []
    if res["facts"]:
        a = analyze(res["facts"], period=args.period, doc=doc, extract_issues=res["issues"])
        tieouts = [t for t in a["tieouts"] if t["status"] == "fail"]
    conflicts = [i for i in res["issues"] if i["type"] in ("同一指标多处取值不一致", "规则与LLM抽取不一致")]
    blocking = [m for m in res["missing"] if m["blocking"]]
    report = {"ok": not (res["rejected"] or conflicts or tieouts or blocking),
              "stats": res["stats"], "rejected": res["rejected"], "conflicts": conflicts,
              "tieout_failures": tieouts, "missing": res["missing"]}
    out = Path(args.out or Path(args.facts).with_suffix(".verified.json"))
    out.write_text(json.dumps({**res, "check": report}, ensure_ascii=False, indent=2), encoding="utf-8")
    _print({**report, "verified_file": str(out)})
    return 0 if report["ok"] else 1


def cmd_guard(args: argparse.Namespace, ap: argparse.ArgumentParser) -> int:
    """解读数字护栏（见 output/guard.py）：
    1. 每个数字按单位与展示精度，必须出自本次运行的结论性产物；
    2. 能识别的“指标 + 数字”表述，用研报核查引擎按指标与期间核对真值表。"""
    from .output.guard import check_binding, check_text, truth_values

    _need(ap, args, "run-dir", "text")
    run = Path(args.run_dir)
    text = Path(args.text).read_text(encoding="utf-8")
    unverified = check_text(text, truth_values(run))
    mismatched = check_binding(text, run)
    result = {"ok": not (unverified or mismatched), "unverified_numbers": unverified,
              "mismatched_claims": mismatched, "text": str(args.text)}
    (run / "commentary.md").write_text(text, encoding="utf-8")
    (run / "commentary_guard.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    _print(result)
    return 0 if result["ok"] else 1


HELPERS = {"locate": cmd_locate, "schema": cmd_schema, "verify-facts": cmd_verify_facts, "guard": cmd_guard}


if __name__ == "__main__":
    raise SystemExit(main())
