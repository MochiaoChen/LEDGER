"""校准评测器：评审模型的判定到底可不可信。

三组证据，各自回答一个问题：

1. 稳定性（stability）：同一份研报重复盲评 k 次，逐条判定是否一致、总分波动多大。
2. 劣化命中（degrade）：对一份合格研报按确定性规则制造已知缺陷（删交叉验证、删预期差、风险泛化、
   删跟踪指标、插入无来源数字、制造前后矛盾、注入机器腔），重新排版、重新盲评，看对应条目是否判出问题，
   以及其余条目是否被连带改判（与重复评审本身的波动对比）。缺陷是程序造的，“该判不通过”是已知真值。
3. 人工一致（human）：人工质检页导出的 JSON，逐条对比人工结论与评审判定。注意人工只复核了评审判
   “不通过”的条目（selection_policy=model_flagged_only），只能算出“判不通过”的精确率，算不出漏判率；
   漏判由第 2 组的劣化命中补上。

  python -m finagent.evaluation.calibrate run   --workspace ~/finagent-samples/宇树科技_2025 [--repeats 3] [--jobs 4]
  python -m finagent.evaluation.calibrate human --qc <人工质检.json> ... [--rubric-from eval/results/v0_贵州茅台]
  python -m finagent.evaluation.calibrate report  # 汇总 eval/calibration/ 下全部结果 → report.md / summary.json

变体工作区与盲评目录建在 ~/finagent-evals/calibration/（仓库之外）；判定结果存 eval/calibration/<公司>/<变体>/。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from ..core.config import PROJECT_ROOT
from . import judge
from .rubric import bundle_from_workspace, load_rubric

OUT = PROJECT_ROOT / "eval" / "calibration"
SECTION_RE = re.compile(r"<!-- section: (\w+) -->")

# ------------------------------------------------------------------ 劣化算子（只改 narrative.md，确定性）


def _sections(text: str) -> list[tuple[str, int, int]]:
    """[(节名, 正文起点, 正文终点)]：正文是本节标记之后、下一个标记之前的文字。"""
    marks = list(SECTION_RE.finditer(text))
    return [(m.group(1), m.end(), marks[i + 1].start() if i + 1 < len(marks) else len(text))
            for i, m in enumerate(marks)]


def _replace_section(text: str, name: str, body: str) -> str:
    for sec, a, b in reversed(_sections(text)):
        if sec == name:
            text = text[:a] + "\n" + body + "\n\n" + text[b:]
    return text


def _drop_headings(text: str, pattern: str) -> str:
    """删掉标题匹配 pattern 的 ### 小节（到下一个 ### 或节标记为止）。"""
    out, skip = [], False
    for line in text.splitlines(keepends=True):
        if line.startswith("### "):
            skip = bool(re.search(pattern, line))
        elif SECTION_RE.search(line):
            skip = False
        if not skip:
            out.append(line)
    return "".join(out)


def _hollow_sections_titled(text: str, prefix: str, pattern: str) -> str:
    """掏空整节：节名以 prefix 开头、且节内第一个 ### 标题匹配 pattern（如“股价隐含了什么”的深度专题）。
    保留标题与段落数（排版脚本按段落位置取内容），正文段落与列表项换成“本段从略。”。"""
    for sec, a, b in reversed(_sections(text)):
        first = re.search(r"^### (.+)$", text[a:b], re.M)
        if sec.startswith(prefix) and first and re.search(pattern, first.group(1)):
            lines = []
            for line in text[a:b].splitlines(keepends=True):
                if line.strip() and not line.startswith(("#", "|", "<!--")):
                    line = ("- " if line.startswith("- ") else "") + "本段从略。\n"
                lines.append(line)
            text = text[:a] + "".join(lines) + text[b:]
    return text


def _paragraphs(text: str, every: int, edit: Callable[[str], str], skip=("title", "subtitle", "summary")) -> str:
    """对正文段落（非标题、非列表、非表格）每隔 every 段做一次 edit。"""
    out, n, cur = [], 0, ""
    for line in text.splitlines(keepends=True):
        m = SECTION_RE.search(line)
        if m:
            cur = m.group(1)
        plain = line.strip() and not line.startswith(("#", "-", "|", "<!--", "*")) and cur not in skip
        if plain:
            n += 1
            if n % every == 0:
                line = edit(line.rstrip("\n")) + "\n"
        out.append(line)
    return "".join(out)


_FLIP = {"卖出": "买入", "减持": "增持", "买入": "卖出", "增持": "减持", "持有": "买入", "中性": "买入"}


def _flip_rating(text: str) -> str:
    """只改摘要里的评级词，正文与推荐段保持原样 → 前后矛盾。"""
    for sec, a, b in _sections(text):
        if sec == "summary":
            body = re.sub(r"给予“(\w+)”评级", lambda m: f"给予“{_FLIP.get(m.group(1), '买入')}”评级", text[a:b], count=1)
            return text[:a] + body + text[b:]
    return text


def _insert_unsourced(text: str) -> str:
    claim = ("**市场空间测算。** 据行业测算，2030 年全球市场规模将达到 4,800 亿元，2025—2030 年复合增速约 62%，"
             "其中中国市场占比约 45%，公司有望占据其中 18% 的份额。")
    for sec, a, b in _sections(text):
        if sec == "deep_industry":
            body = text[a:b]
            m = re.search(r"\n\n(?=\*\*)", body)  # 第一段之后
            at = a + (m.start() if m else 0)
            return text[:at] + "\n\n" + claim + text[at:]
    return text


GENERIC_RISKS = "- 宏观经济波动风险。\n- 行业竞争加剧风险。\n- 政策变化风险。\n- 技术迭代风险。"

DEGRADATIONS: dict[str, dict[str, Any]] = {
    "no_cross_check": {"targets": ["L2-09"], "desc": "删掉相对估值与交叉验证小节",
                       "op": lambda t: _drop_headings(t, r"交叉验证|相对估值")},
    "no_expectation_gap": {"targets": ["L2-02"], "desc": "删掉市场关注问题、预期差与“股价隐含”专题",
                           "op": lambda t: _replace_section(
                               _hollow_sections_titled(_drop_headings(t, r"市场关注|预期差"), "deep_topic", r"隐含"),
                               "deep_expectations", "")},
    "generic_risks": {"targets": ["L2-11"], "desc": "风险提示换成不对应任何假设的通用模板",
                      "op": lambda t: re.sub(r"\*\*风险提示：\*\*[^\n]*", "**风险提示：** 宏观经济波动；行业竞争加剧；政策变化；技术迭代。",
                                             _replace_section(t, "risks", GENERIC_RISKS))},
    "no_tracking": {"targets": ["L2-12"], "desc": "删掉跟踪指标与结论失效条件",
                    "op": lambda t: _replace_section(t, "tracking", "")},
    "unsourced_number": {"targets": ["N-01"], "desc": "行业部分插入一段无来源的市场规模与份额数字",
                         "op": _insert_unsourced},
    "contradiction": {"targets": ["N-02"], "desc": "只把摘要里的评级改成相反方向，正文不变",
                      "op": _flip_rating},
    "machine_tone": {"targets": ["L3-04"], "desc": "每两段注入一次程序口吻（“根据程序计算结果”“已通过数字护栏校验”）",
                     "op": lambda t: _paragraphs(t, 2, lambda s: "根据程序计算结果，" + s + "（以上数据已通过数字护栏校验，由模型自动生成。）")},
}


def degrade(text: str, kind: str) -> str:
    out = DEGRADATIONS[kind]["op"](text)
    if out == text:
        raise ValueError(f"劣化 {kind} 没有改动文稿（找不到对应小节），换一家公司或补算子")
    return out


# ------------------------------------------------------------------ 运行


def _work_root() -> Path:
    return judge.default_root() / "calibration"


def _render(ws: Path, work: Path, run: Path) -> None:
    script = work / "report" / "build_report.py"
    py = ws / "py"
    cmd = [str(py) if py.is_file() else sys.executable, str(script.relative_to(ws)), "--run-dir", str(run.relative_to(ws))]
    proc = subprocess.run(cmd, cwd=ws, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"重新排版失败（{ws.name}）：{proc.stderr[-800:]}")


def prepare_variant(src: Path, kind: str, rep: int) -> tuple[Any, Path]:
    """复制工作区 → 改文稿 → 重新排版。clean 变体不改文稿、不重排。返回 (Bundle, 盲评目录)。"""
    b0 = bundle_from_workspace(src)
    name = kind if kind != "clean" else f"clean{rep}"
    base = _work_root() / b0.company / name
    if kind == "clean":
        return b0, base / "blind"
    ws = base / "ws"
    if ws.exists():
        shutil.rmtree(ws)
    shutil.copytree(src, ws, symlinks=True, ignore=shutil.ignore_patterns("__pycache__", "mpl"))
    b = bundle_from_workspace(ws)
    b.narrative.write_text(degrade(b.narrative.read_text(encoding="utf-8"), kind), encoding="utf-8")
    _render(ws, b.work, b.run)
    return b, base / "blind"


def run(src: Path, kinds: list[str], repeats: int, jobs: int, rubric: str | None, model: str | None) -> list[Path]:
    from .__main__ import evaluate

    plan = [("clean", i + 1) for i in range(repeats)] + [(k, 1) for k in kinds]
    company = bundle_from_workspace(src).company

    def one(task: tuple[str, int]) -> Path:
        kind, rep = task
        name = kind if kind != "clean" else f"clean{rep}"
        out = OUT / company / name
        if (out / "judgments.json").is_file():
            print(f"[{name}] 已有结果，跳过", flush=True)
            return out
        try:
            b, blind = prepare_variant(src, kind, rep)
        except (RuntimeError, ValueError) as e:
            print(f"[{name}] 跳过：{e}", flush=True)
            return out
        print(f"[{name}] 盲评开始", flush=True)
        sc = evaluate(b, out, rubric_path=rubric, model=model, blind_dir=blind, echo=False)
        if sc["judge_problems"]:  # 评审没跑完（额度、网络）：结果作废，删掉以便重跑
            shutil.rmtree(out)
            print(f"[{name}] 评审未完成，结果作废：{'；'.join(sc['judge_problems'])}", flush=True)
            return out
        meta = {"kind": kind, "rep": rep, "targets": DEGRADATIONS.get(kind, {}).get("targets", []),
                "desc": DEGRADATIONS.get(kind, {}).get("desc", "原稿")}
        (out / "variant.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{name}] 完成，总分 {sc['total']}", flush=True)
        return out

    with ThreadPoolExecutor(max_workers=jobs) as ex:
        return list(ex.map(one, plan))


# ------------------------------------------------------------------ 汇总


def _verdicts(out: Path) -> dict[str, bool]:
    """{条目: 是否“判出问题”}：正向条目未通过、负向条目命中都算判出问题。只取评审条目。"""
    sc = json.loads((out / "score.json").read_text(encoding="utf-8"))
    flagged = {}
    for r in sc["items"]:
        if r.get("judge") == "llm" or r["layer"] in ("L2", "L3", "N"):
            flagged[r["id"]] = bool(r["passed"]) if r["layer"] == "N" else not r["passed"]
    return flagged


def _total(out: Path) -> float:
    return json.loads((out / "score.json").read_text(encoding="utf-8"))["total"]


def summarize_company(d: Path) -> dict[str, Any] | None:
    runs = {p.name: p for p in sorted(d.iterdir()) if (p / "score.json").is_file()
            and not json.loads((p / "score.json").read_text(encoding="utf-8")).get("judge_problems")}
    cleans = [runs[k] for k in runs if k.startswith("clean")]
    if not cleans:
        return None
    cv = [_verdicts(p) for p in cleans]
    items = sorted(cv[0])
    majority = {i: Counter(v[i] for v in cv).most_common(1)[0][0] for i in items}
    unanimous = [i for i in items if len({v[i] for v in cv}) == 1]
    pair_flip = []  # 两两比较的逐条不一致率：重复评审自身的噪声
    for x in range(len(cv)):
        for y in range(x + 1, len(cv)):
            pair_flip.append(sum(cv[x][i] != cv[y][i] for i in items) / len(items))
    totals = [_total(p) for p in cleans]
    stability = {"runs": len(cleans), "items": len(items), "unanimous": len(unanimous),
                 "agreement": round(len(unanimous) / len(items), 3),
                 "pairwise_flip_rate": round(sum(pair_flip) / len(pair_flip), 3) if pair_flip else None,
                 "totals": totals, "total_range": round(max(totals) - min(totals), 1),
                 "unstable_items": [i for i in items if i not in unanimous]}
    variants = []
    for name, p in runs.items():
        if name.startswith("clean") or not (p / "variant.json").is_file():
            continue
        meta = json.loads((p / "variant.json").read_text(encoding="utf-8"))
        v = _verdicts(p)
        hits = {t: v.get(t, False) for t in meta["targets"]}
        base_flagged = {t: majority.get(t, False) for t in meta["targets"]}
        collateral = [i for i in items if i not in meta["targets"] and v[i] != majority[i]]
        variants.append({"variant": name, "desc": meta["desc"], "targets": meta["targets"],
                         "clean_flagged": base_flagged, "hit": hits,
                         "valid": not any(base_flagged.values()),  # 原稿已被判出该问题时，命中不说明问题
                         "collateral": collateral, "collateral_rate": round(len(collateral) / len(items), 3),
                         "total": _total(p), "clean_total_mean": round(sum(totals) / len(totals), 1)})
    valid = [x for x in variants if x["valid"]]
    hit = sum(all(x["hit"].values()) for x in valid)
    return {"company": d.name, "stability": stability, "variants": variants,
            "detection": {"valid": len(valid), "hit": hit, "rate": round(hit / len(valid), 3) if valid else None}}


def human_agreement(qc_files: list[Path]) -> dict[str, Any]:
    """人工质检导出 → 评审“判出问题”的精确率。统计评审判出问题的条目（人工未下结论的记待查）与人工主动复核的条目。"""
    rows, per_company = [], {}
    for f in qc_files:
        d = json.loads(f.read_text(encoding="utf-8"))
        session = d["review_sessions"][-1]
        c = Counter()
        for it in session["items"]:
            if it["layer"] not in ("L2", "L3", "N"):  # L0/L1 由程序判，不是评审模型的判定
                continue
            if not (it.get("human_reviewed") or it.get("model_flagged")):  # 评审判通过、人工未看的条目不计
                continue
            verdict = it["human_verdict"] if it["human_verdict"] in ("confirmed_issue", "false_alarm") else "pending"
            c[verdict] += 1
            rows.append({"company": d["company"], "item": it["item_id"], "judge_flagged": it.get("model_flagged"),
                         "human": verdict, "reason": (it.get("feedback") or {}).get("reason", "")})
        per_company[d["company"]] = {"rubric": d["rubric_version"], "policy": d["selection_policy"],
                                     "reviewer": session.get("reviewer"), **dict(c)}
    confirmed = sum(r["human"] == "confirmed_issue" for r in rows)
    false_alarm = [r for r in rows if r["human"] == "false_alarm"]
    pending = sum(r["human"] == "pending" for r in rows)
    decided = confirmed + len(false_alarm)
    return {"per_company": per_company, "reviewed": len(rows), "confirmed": confirmed,
            "false_alarm": len(false_alarm), "pending": pending,
            "precision": round(confirmed / decided, 3) if decided else None,
            "false_alarm_items": false_alarm, "rows": rows}


def report() -> Path:
    companies = [s for d in sorted(OUT.iterdir()) if d.is_dir() and d.name != "human"
                 for s in [summarize_company(d)] if s]
    human_files = sorted((OUT / "human").glob("*.json")) if (OUT / "human").is_dir() else []
    human = human_agreement(human_files) if human_files else None
    summary = {"companies": companies, "human": human}
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "report.md").write_text(_markdown(summary), encoding="utf-8")
    return OUT / "report.md"


def _markdown(s: dict[str, Any]) -> str:
    L = ["# 评审模型校准报告", "",
         "评审（Sonnet 盲评）判的是 L2 分析质量、L3 表达与合规和负向条目；L0/L1 由程序判，不在此列。", ""]
    if s["companies"]:
        L += ["## 1. 稳定性：同一份研报重复盲评", "",
              "| 公司 | 次数 | 逐条全一致 | 两两不一致率 | 总分 | 极差 | 不稳定条目 |", "|---|---:|---:|---:|---|---:|---|"]
        for c in s["companies"]:
            st = c["stability"]
            L.append(f"| {c['company']} | {st['runs']} | {st['unanimous']}/{st['items']}（{st['agreement']:.0%}） | "
                     f"{st['pairwise_flip_rate'] if st['pairwise_flip_rate'] is not None else '—'} | "
                     f"{' / '.join(f'{t:g}' for t in st['totals'])} | {st['total_range']:g} | "
                     f"{'、'.join(st['unstable_items']) or '无'} |")
        L += ["", "## 2. 劣化命中：程序制造已知缺陷，看评审能否判出", "",
              "“原稿已判出”的变体不计入命中率（原稿就被判有该问题，命中不说明评审灵敏）。连带改判 = 非目标条目与原稿多数判定不同，"
              "应与第 1 节的两两不一致率相当。", "",
              "| 公司 | 变体 | 制造的缺陷 | 目标条目 | 原稿判定 | 劣化稿判出 | 连带改判 | 总分（原稿均值 → 劣化） |",
              "|---|---|---|---|---|---|---|---|"]
        for c in s["companies"]:
            for v in c["variants"]:
                L.append(f"| {c['company']} | {v['variant']} | {v['desc']} | {'、'.join(v['targets'])} | "
                         f"{'已判出' if any(v['clean_flagged'].values()) else '未判出'} | "
                         f"{'✓' if all(v['hit'].values()) else '✗'} | {len(v['collateral'])}（{'、'.join(v['collateral']) or '—'}） | "
                         f"{v['clean_total_mean']:g} → {v['total']:g} |")
        L += [""] + [f"- {c['company']}：有效变体 {c['detection']['valid']} 个，判出 {c['detection']['hit']} 个"
                     + (f"（{c['detection']['rate']:.0%}）" if c['detection']['rate'] is not None else "") for c in s["companies"]]
    h = s.get("human")
    if h:
        L += ["", "## 3. 人工一致：评审判出的问题，人工是否认同", "",
              "人工质检只复核评审判“不通过”的条目（model_flagged_only），所以这里只有“判出问题”的精确率；"
              "评审判“通过”的条目是否漏判，见第 2 节。", "",
              "| 公司 | 评分标准 | 复核人 | 确认 | 误报 | 待查 |", "|---|---|---|---:|---:|---:|"]
        for name, c in h["per_company"].items():
            L.append(f"| {name} | {c['rubric']} | {c['reviewer']} | {c.get('confirmed_issue', 0)} | {c.get('false_alarm', 0)} | "
                     f"{c.get('pending', 0)} |")
        L += ["", f"合计 {h['reviewed']} 条：确认 {h['confirmed']}、误报 {h['false_alarm']}、待查 {h['pending']}；"
              f"判出问题的精确率 {h['precision']:.0%}（不含待查）。", "", "误报条目与处理："]
        L += [f"- {r['company']} {r['item']}：{r['reason'] or '（未写理由）'}" for r in h["false_alarm_items"]]
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="finagent.evaluation.calibrate", description="评审模型校准")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--workspace", required=True, help="一份已交付、质检合格的研报工作区")
    r.add_argument("--variants", default=",".join(DEGRADATIONS), help="逗号分隔，默认全部")
    r.add_argument("--repeats", type=int, default=3, help="原稿重复盲评次数")
    r.add_argument("--jobs", type=int, default=4)
    r.add_argument("--rubric")
    r.add_argument("--model")
    h = sub.add_parser("human")
    h.add_argument("--qc", action="append", required=True, help="人工质检页导出的 JSON，可多次给")
    sub.add_parser("report")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        kinds = [k for k in args.variants.split(",") if k]
        unknown = set(kinds) - set(DEGRADATIONS)
        if unknown:
            ap.error(f"未知劣化：{'、'.join(sorted(unknown))}")
        run(Path(args.workspace).expanduser().resolve(), kinds, args.repeats, args.jobs, args.rubric, args.model)
    elif args.cmd == "human":
        dest = OUT / "human"
        dest.mkdir(parents=True, exist_ok=True)
        for f in args.qc:
            d = json.loads(Path(f).read_text(encoding="utf-8"))
            shutil.copy2(f, dest / f"{d['company']}_{d['rubric_version']}.json")
    print(report())
    return 0


if __name__ == "__main__":
    sys.exit(main())
