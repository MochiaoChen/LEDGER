"""评测脚本：字段抽取准确率（赛题2）+ 研报纠错的准确率/召回率/误报（赛题5）。

    python eval/run_eval.py            # 计算引擎规则通道，不调用模型
结果写入 runs/<run_id>/eval_result.json，并打印汇总。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from finagent import pipelines  # noqa: E402
from finagent.core.config import get_settings  # noqa: E402
from finagent.core.tracing import RunTracer  # noqa: E402
from finagent.tasks.report_check.verify import ERROR_VERDICTS  # noqa: E402


def eval_extraction(facts: list[dict], gold: dict) -> dict:
    got = {f"{f['metric_id']}|{f['period']}": f["value"] for f in facts}
    rows, correct = [], 0
    for key, exp in gold["facts"].items():
        v = got.get(key)
        ok = v is not None and math.isclose(v, exp, rel_tol=1e-9, abs_tol=1e-6)
        correct += ok
        rows.append({"key": key, "expected": exp, "got": v, "ok": ok})
    return {"fields": len(rows), "correct": correct, "accuracy": correct / len(rows), "detail": rows}


def eval_check(findings: list[dict], labels: dict) -> dict:
    matched: set[str] = set()
    detail = []
    tp = type_ok = 0
    for lab in labels["errors"]:
        cand = [f for f in findings if lab["match"] in f["quote"] and f["claim_type"] == lab["claim_type"]]
        f = cand[0] if cand else None
        if f is not None:
            matched.add(f["claim_id"])
        detected = f is not None and f["verdict"] in ERROR_VERDICTS
        tp += detected
        type_ok += detected and f["verdict"] == lab["verdict"]
        detail.append({"id": lab["id"], "expected": lab["verdict"], "got": f["verdict"] if f else None,
                       "detected": detected})
    fps = [f for f in findings if f["verdict"] in ERROR_VERDICTS and f["claim_id"] not in matched]
    flagged = tp + len(fps)
    return {"labeled_errors": len(labels["errors"]), "true_positive": tp, "false_positive": len(fps),
            "precision": tp / flagged if flagged else 1.0, "recall": tp / len(labels["errors"]),
            "type_accuracy": type_ok / tp if tp else 0.0, "detail": detail,
            "false_positive_detail": [{k: f[k] for k in ("claim_id", "quote", "verdict")} for f in fps]}


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    gold = json.loads((ROOT / "eval/gold_financials.json").read_text(encoding="utf-8"))
    labels = json.loads((ROOT / "eval/labels.json").read_text(encoding="utf-8"))
    settings = get_settings()
    with RunTracer("eval", settings.runs_dir, settings.public()) as tr:
        ctx = {"input": str(ROOT / gold["document"]), "fiscal_year": gold["fiscal_year"], "company": "样例公司",
               "report": str(ROOT / labels["report"])}
        pipelines.run("check", ctx)
        result = {"extraction": eval_extraction(ctx["extract"]["facts"], gold),
                  "report_check": eval_check(ctx["check"]["findings"], labels)}
        tr.write_json("eval_result.json", result)
    e, c = result["extraction"], result["report_check"]
    print(f"[抽取] 字段准确率 {e['accuracy']:.1%}（{e['correct']}/{e['fields']}）")
    print(f"[核查] 召回率 {c['recall']:.1%}  准确率 {c['precision']:.1%}  误报 {c['false_positive']}  "
          f"错误类型准确率 {c['type_accuracy']:.1%}")
    for d in c["detail"]:
        print(f"   {d['id']}: 期望 {d['expected']:<5} 实际 {d['got']}")
    print(f"结果：{tr.dir / 'eval_result.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
