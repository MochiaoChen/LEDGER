"""研报评测命令行。

  python -m finagent.evaluation run     --workspace <工作区>                       # 评测流水线工作区的当前产物
  python -m finagent.evaluation run     --company 宁德时代 --run-dir runs/<id> --work data/extractions/宁德时代_2025
  python -m finagent.evaluation score   --result eval/results/<目录> [--rubric 改过权重的标准]   # 不重跑评审，只重算分
  python -m finagent.evaluation compare --result <A> --result <B> [--out 对比.md]
  python -m finagent.evaluation pack    --result <A> --result <B> --out <文件夹>   # 质检查看包：PDF + 评分标准 + 打分结果 + index.html
  python -m finagent.evaluation review-docs --pack eval/review_pack/v0 --out eval/review_pack/demo  # 独立人工质检页

run 的结果目录：checks.json（程序判定）、judgments.json（评审判定）、score.json、scorecard.md（逐条表）、
issues.json / issues.md（未通过条目转成的问题单，不含条目原文与分值，供 refine loop 回传给生成与复核）。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.config import PROJECT_ROOT
from . import judge
from .checks import run_checks
from .rubric import Bundle, bundle_from_workspace, load_rubric, score, scorecard_markdown

RESULTS = PROJECT_ROOT / "eval" / "results"


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def issues_from(sc: dict[str, Any]) -> list[dict[str, Any]]:
    """未通过的正向条目与命中的负向条目 → 问题单。只写理由与证据，不写条目标题、判定标准与分值（评分标准对生成方不可见）。"""
    out = []
    for r in sc["items"]:
        failed = r["passed"] if r["layer"] == "N" else not r["passed"]
        if not failed:
            continue
        severity = "blocker" if r["layer"] in ("L0", "N") else "major" if r["points"] >= 4 else "minor"
        out.append({"id": f"I{len(out) + 1:02d}", "route": r["route"], "stage": r["stage"], "severity": severity,
                    "description": r["reason"], "evidence": r["evidence"]})
    return out


def issues_markdown(issues: list[dict[str, Any]], route: str | None = None) -> str:
    rows = [i for i in issues if route is None or i["route"] == route]
    lines = ["# 质检问题单", "", "逐条处理；处理不了的（需要补数据、改假设）写进 report/review.md 并说明原因。", ""]
    for i in rows:
        lines.append(f"- **{i['id']}**（{i['severity']}，阶段 {i['stage']}）{i['description']}"
                     + (f"\n  - 证据：{i['evidence']}" if i["evidence"] else ""))
    return "\n".join(lines) + "\n"


def evaluate(b: Bundle, out: Path, *, rubric_path: str | Path | None = None, model: str | None = None,
             use_judge: bool = True, blind_dir: Path | None = None, echo: bool = True) -> dict[str, Any]:
    """程序检查 + 盲评 + 计分，结果写进 out。返回 score。"""
    rubric = load_rubric(rubric_path)
    out.mkdir(parents=True, exist_ok=True)
    _write(out / "bundle.json", {**b.describe(), "rubric": str(rubric_path or "default"),
                                 "evaluated_at": datetime.now().isoformat(timespec="seconds")})
    results = run_checks(rubric, b)
    _write(out / "checks.json", results)
    problems: list[str] = []
    if use_judge:
        blind = blind_dir or judge.default_root() / f"{b.company}_{datetime.now():%Y%m%d-%H%M%S}"
        judge.prepare(b, rubric, blind)
        _write(out / "judge_run.json", {**judge.run_session(blind, model, echo), "blind_dir": str(blind)})
        if (blind / "judgments.json").is_file():
            shutil.copy2(blind / "judgments.json", out / "judgments.json")
        shutil.copy2(blind / "judge.jsonl", out / "judge.jsonl")
    if (out / "judgments.json").is_file():
        judged, problems = judge.read_judgments(out / "judgments.json", rubric)
        results.update(judged)
    return rescore(out, rubric, problems)


def rescore(out: Path, rubric: dict[str, Any], problems: list[str] | None = None) -> dict[str, Any]:
    results = json.loads((out / "checks.json").read_text(encoding="utf-8"))
    if (out / "judgments.json").is_file():
        judged, found = judge.read_judgments(out / "judgments.json", rubric)
        results.update(judged)
        problems = found if problems is None else problems
    sc = score(rubric, results)
    sc["judge_problems"] = problems or []
    if (out / "judgments.json").is_file():
        sc["judge_summary"] = json.loads((out / "judgments.json").read_text(encoding="utf-8")).get("summary", "")
    company = json.loads((out / "bundle.json").read_text(encoding="utf-8"))["company"]
    _write(out / "score.json", sc)
    md = scorecard_markdown(company, sc)
    if sc.get("judge_summary"):
        md += f"\n## 评审总评\n\n{sc['judge_summary']}\n"
    if sc["judge_problems"]:
        md += "\n## 评审输出问题\n\n" + "\n".join(f"- {p}" for p in sc["judge_problems"]) + "\n"
    (out / "scorecard.md").write_text(md, encoding="utf-8")
    issues = issues_from(sc)
    _write(out / "issues.json", issues)
    (out / "issues.md").write_text(issues_markdown(issues), encoding="utf-8")
    return sc


def compare_markdown(dirs: list[Path]) -> str:
    cols = [(d, json.loads((d / "score.json").read_text(encoding="utf-8")),
             json.loads((d / "bundle.json").read_text(encoding="utf-8"))["company"]) for d in dirs]
    lines = ["| 条目 | " + " | ".join(c for _, _, c in cols) + " |", "|---|" + "---:|" * len(cols)]
    lines.append("| **总分** | " + " | ".join(f"**{s['total']}**" for _, s, _ in cols) + " |")
    for k in ("L1", "L2", "L3"):
        lines.append(f"| {k} | " + " | ".join(f"{s['layers'][k]['earned']:g}/{s['layers'][k]['possible']:g}"
                                             for _, s, _ in cols) + " |")
    lines.append("| 扣分 | " + " | ".join(f"{s['deduction']:g}" for _, s, _ in cols) + " |")
    for i, r in enumerate(cols[0][1]["items"]):
        marks = []
        for _, s, _ in cols:
            x = s["items"][i]
            marks.append(("命中" if x["passed"] else "—") if x["layer"] == "N" else ("✓" if x["passed"] else "✗"))
        lines.append(f"| {r['id']} {r['title']} | " + " | ".join(marks) + " |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="finagent.evaluation", description="研报评测")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--workspace", help="流水线工作区")
    r.add_argument("--company")
    r.add_argument("--run-dir", help="估值运行目录")
    r.add_argument("--work", help="抽取目录 data/extractions/<公司>_<年度>")
    r.add_argument("--rubric", help="评分标准，默认 eval/rubrics/report_v0.json")
    r.add_argument("--model", help=f"评审模型，默认 {judge.QC_MODEL}（环境变量 FINAGENT_QC_MODEL）")
    r.add_argument("--no-judge", action="store_true", help="只跑程序检查")
    r.add_argument("--out", help="结果目录，默认 eval/results/<公司>_<时间>")
    s = sub.add_parser("score")
    s.add_argument("--result", required=True)
    s.add_argument("--rubric")
    c = sub.add_parser("compare")
    c.add_argument("--result", action="append", required=True)
    c.add_argument("--out")
    k = sub.add_parser("pack")
    k.add_argument("--result", action="append", required=True)
    k.add_argument("--out", required=True)
    k.add_argument("--rubric")
    k.add_argument("--title", default="研报质检")
    d = sub.add_parser("review-docs", help="从已封存查看包生成逐公司人工质检页；不重跑评审")
    d.add_argument("--pack", default=str(PROJECT_ROOT / "eval" / "review_pack" / "v0"))
    d.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    if args.cmd == "run":
        if args.workspace:
            b = bundle_from_workspace(Path(args.workspace).expanduser().resolve())
        elif args.company and args.run_dir and args.work:
            b = Bundle(args.company, Path(args.run_dir).resolve(), Path(args.work).resolve())
        else:
            ap.error("run 需要 --workspace，或同时给 --company --run-dir --work")
        out = Path(args.out) if args.out else RESULTS / f"{b.company}_{datetime.now():%Y%m%d-%H%M%S}"
        sc = evaluate(b, out, rubric_path=args.rubric, model=args.model, use_judge=not args.no_judge)
    elif args.cmd == "pack":
        from .pack import build_pack
        print(build_pack([Path(d) for d in args.result], Path(args.out), args.rubric, args.title))
        return 0
    elif args.cmd == "review-docs":
        from .review_docs import build_review_docs
        for path in build_review_docs(Path(args.pack), Path(args.out)):
            print(path)
        return 0
    elif args.cmd == "score":
        out = Path(args.result)
        sc = rescore(out, load_rubric(args.rubric))
    else:
        text = compare_markdown([Path(d) for d in args.result])
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
        print(text)
        return 0
    print(f"\n总分 {sc['total']}（{'达到' if sc['deliverable'] else '未达'}交付标准）→ {out / 'scorecard.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
