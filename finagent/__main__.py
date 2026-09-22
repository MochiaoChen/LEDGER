"""命令行入口。

  python -m finagent financials --input 年报.pdf --year 2024 --company 公司名
  python -m finagent valuation  --input 年报.pdf --year 2024 --assumptions 假设.json
  python -m finagent check      --input 年报.pdf --year 2024 --report 研报草稿.md
  python -m finagent all        --input ... --assumptions ... --report ...
  python -m finagent ask "分析这份年报并估值" （Agent 模式，需配置 LLM）

通用参数：--llm {live,replay,off}  --llm-extract {fallback,all,off}
"""

from __future__ import annotations

import argparse
import json
import sys

from .core.config import get_settings
from .core.llm import LLMClient
from .core.orchestrator import Agent
from .core.tracing import RunTracer
from . import pipelines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="finagent", description="金融投研智能体")
    ap.add_argument("task", choices=["financials", "valuation", "check", "all", "ask"])
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
    args = ap.parse_args(argv)

    settings = get_settings(llm_mode=args.llm, runs_dir=args.runs_dir)
    llm = LLMClient(settings) if settings.llm_enabled else None
    config = {**settings.public(), "task": args.task, "llm_extract": args.llm_extract,
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
                   "llm_extract": args.llm_extract}
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


if __name__ == "__main__":
    raise SystemExit(main())
