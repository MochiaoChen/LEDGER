"""评分标准读取、评测对象定位与计分。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.config import PROJECT_ROOT

DEFAULT_RUBRIC = PROJECT_ROOT / "eval" / "rubrics" / "report_v1.json"
LAYERS = ("L0", "L1", "L2", "L3", "N")


@dataclass
class Bundle:
    """一份待评测的研报：估值运行目录 + 抽取目录（data/extractions/<公司>_<年度>）。"""
    company: str
    run: Path
    work: Path

    @property
    def narrative(self) -> Path:
        return self.work / "report" / "narrative.md"

    @property
    def draft(self) -> Path:
        return self.work / "report" / "narrative.draft.md"

    @property
    def review(self) -> Path:
        return self.work / "report" / "review.md"

    @property
    def sources(self) -> Path:
        return self.work / "research" / "sources.json"

    @property
    def pdf(self) -> Path | None:
        """交付 PDF：优先取设了 output_name 的命名版。"""
        d = self.run / "report"
        named = sorted(p for p in d.glob("*.pdf") if p.name != "report.pdf") if d.is_dir() else []
        if named:
            return named[-1]
        return d / "report.pdf" if (d / "report.pdf").is_file() else None

    def describe(self) -> dict[str, Any]:
        return {"company": self.company, "run": str(self.run), "work": str(self.work),
                "pdf": str(self.pdf) if self.pdf else None}


def bundle_from_workspace(ws: Path) -> Bundle:
    from ..report_pipeline import META, status

    meta = json.loads((ws / META).read_text(encoding="utf-8"))
    run = status(ws)["run_dir"]
    if not run:
        raise SystemExit(f"{ws} 还没有估值运行目录，无法评测")
    return Bundle(meta["company"], ws / run, ws / "data" / "extractions" / meta["key"])


def load_rubric(path: str | Path | None = None) -> dict[str, Any]:
    rubric = json.loads(Path(path or DEFAULT_RUBRIC).read_text(encoding="utf-8"))
    ids = [it["id"] for it in rubric["items"]]
    if len(set(ids)) != len(ids):
        raise ValueError("评分标准条目 id 重复")
    for it in rubric["items"]:
        if it["layer"] not in LAYERS:
            raise ValueError(f"{it['id']}: 未知层级 {it['layer']}")
        if it["judge"] == "program" and not it.get("check"):
            raise ValueError(f"{it['id']}: 程序条目缺 check")
        if it["layer"] == "N" and it.get("points", 0) > 0:
            raise ValueError(f"{it['id']}: 负向条目分值须 ≤ 0")
    return rubric


def judge_items(rubric: dict[str, Any]) -> list[dict[str, Any]]:
    """交给评审模型的条目：只给 id、标题、判定标准与反例，不给分值与层级权重。"""
    keep = ("id", "title", "criterion", "fail_examples")
    return [{k: it[k] for k in keep if k in it} | {"negative": it["layer"] == "N"}
            for it in rubric["items"] if it["judge"] == "llm"]


def score(rubric: dict[str, Any], results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """results: {item_id: {passed, evidence, reason/detail}}。负向条目 passed=True 表示“命中”（扣分）。
    缺判定的条目按未通过（负向条目按未命中）计，并列入 missing。"""
    layers = {k: {"name": rubric["layers"][k], "earned": 0.0, "possible": 0.0} for k in LAYERS}
    rows, caps, missing, gate_fail = [], [], [], []
    deduction = 0.0
    for it in rubric["items"]:
        r = results.get(it["id"])
        if r is None:
            missing.append(it["id"])
        hit = bool(r and r.get("passed"))
        pts = float(it.get("points", 0))
        lay = layers[it["layer"]]
        if it["layer"] == "N":
            got = pts if hit else 0.0
            deduction += got
            if hit and it.get("cap") is not None:
                caps.append((it["cap"], it["id"]))
        else:
            got = pts if hit else 0.0
            lay["possible"] += pts
            if it["layer"] == "L0" and not hit:
                gate_fail.append(it["id"])
        lay["earned"] += got
        rows.append({"id": it["id"], "layer": it["layer"], "title": it["title"], "judge": it["judge"],
                     "points": pts, "passed": hit, "got": got, "route": it.get("route"), "stage": it.get("stage"),
                     "evidence": (r or {}).get("evidence", ""),
                     "reason": (r or {}).get("reason") or (r or {}).get("detail") or ("缺判定" if r is None else "")})
    deduction = max(deduction, float(rubric.get("negative_floor", -100)))
    positive = sum(layers[k]["earned"] for k in ("L1", "L2", "L3"))
    raw = max(0.0, positive + deduction)
    if gate_fail:
        caps.append((rubric["gate_cap"], "L0：" + "、".join(gate_fail)))
    total = min([raw] + [c for c, _ in caps])
    d = rubric.get("delivery", {})
    reasons = []
    if gate_fail:
        reasons.append("硬闸门未通过：" + "、".join(gate_fail))
    if total < d.get("total", 0):
        reasons.append(f"总分 {total:.1f} < {d['total']}")
    for k, ratio in d.get("layer_ratio", {}).items():
        lay = layers[k]
        if lay["possible"] and lay["earned"] / lay["possible"] < ratio:
            reasons.append(f"{k} 得分率 {lay['earned'] / lay['possible']:.0%} < {ratio:.0%}")
    hits = [r["id"] for r in rows if r["layer"] == "N" and r["passed"]]
    if hits and not d.get("allow_negative", False):
        reasons.append("命中负向条目：" + "、".join(hits))
    return {"rubric": rubric["version"], "total": round(total, 2), "raw": round(raw, 2),
            "deduction": round(deduction, 2), "caps": [{"cap": c, "by": by} for c, by in caps],
            "layers": layers, "deliverable": not reasons, "not_deliverable_reasons": reasons,
            "missing": missing, "items": rows}


def scorecard_markdown(company: str, sc: dict[str, Any]) -> str:
    """逐条评分表：给人看松紧、调权重用。"""
    lines = [f"# {company} 研报评测（{sc['rubric']}）", "",
             f"**总分 {sc['total']}**（正向 {sc['raw'] - sc['deduction']:.1f}，扣分 {sc['deduction']:.1f}"
             + (f"，封顶 {min(c['cap'] for c in sc['caps'])}：{'；'.join(c['by'] for c in sc['caps'])}" if sc["caps"] else "")
             + f"）· {'达到交付标准' if sc['deliverable'] else '未达交付标准'}", ""]
    if sc["not_deliverable_reasons"]:
        lines += ["未达标原因：" + "；".join(sc["not_deliverable_reasons"]), ""]
    lines += ["| 层 | 名称 | 得分 | 满分 |", "|---|---|---:|---:|"]
    for k, lay in sc["layers"].items():
        lines.append(f"| {k} | {lay['name']} | {lay['earned']:g} | {lay['possible']:g} |")
    lines += ["", "| 条目 | 判定 | 分值 | 结果 | 理由 | 证据 |", "|---|---|---:|---|---|---|"]
    for r in sc["items"]:
        mark = ("命中" if r["passed"] else "未命中") if r["layer"] == "N" else ("✓" if r["passed"] else "✗")
        cell = lambda s: str(s).replace("|", "／").replace("\n", " ")[:220]
        lines.append(f"| {r['id']} {r['title']} | {'程序' if r['judge'] == 'program' else '评审'} | {r['points']:g} "
                     f"| {mark} | {cell(r['reason'])} | {cell(r['evidence'])} |")
    return "\n".join(lines) + "\n"
