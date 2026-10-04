"""产物目录：找出本机的研报工作区、运行目录与评测结果，读成统一结构。

命令行 `finagent ls` 与终端界面 `finagent tui` 共用；只读文件、不改任何东西。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .core.config import PROJECT_ROOT

RUNS = PROJECT_ROOT / "runs"
RESULTS = PROJECT_ROOT / "eval" / "results"
CALIBRATION = PROJECT_ROOT / "eval" / "calibration"


def load(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


@dataclass
class Subject:
    """界面上可以选中的一项：一个估值运行目录，可选地属于某个研报工作区。"""
    kind: str  # workspace | run
    title: str
    run: Path | None
    workspace: Path | None = None
    company: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return str(self.workspace or self.run)


def workspaces(root: Path | None = None) -> list[Subject]:
    from .report_pipeline import META, default_dest

    root = root or default_dest()
    out = []
    for ws in sorted(root.glob("*")) if root.is_dir() else []:
        meta = load(ws / META)
        if not isinstance(meta, dict):
            continue
        run = _latest_run(ws / "runs")
        out.append(Subject("workspace", f"{meta.get('company', ws.name)} {meta.get('year', '')}".strip(), run, ws,
                           meta.get("company", ""), meta))
    return out


def runs(root: Path = RUNS, limit: int = 20) -> list[Subject]:
    """仓库内含财务分析产物的运行目录（新的在前）。"""
    found = [d for d in sorted(root.glob("*"), reverse=True)
             if (d / "financials" / "analysis.json").is_file() and not d.name.endswith("-eval")]  # 样例评测的运行不列
    out = []
    for d in found[:limit]:
        m = load(d / "manifest.json", {}) or {}
        company = _company_of(d, m)
        out.append(Subject("run", f"{d.name}", d, None, company, m))
    return out


def _latest_run(d: Path) -> Path | None:
    cands = [p for p in sorted(d.glob("*")) if (p / "financials" / "analysis.json").is_file()] if d.is_dir() else []
    return cands[-1] if cands else None


def _company_of(run: Path, manifest: dict[str, Any]) -> str:
    argv = (manifest.get("config") or {}).get("argv") or []
    if "--company" in argv and argv.index("--company") + 1 < len(argv):
        return argv[argv.index("--company") + 1]
    return ""


# ------------------------------------------------------------------ 读取单个对象


def gates(s: Subject) -> dict[str, Any] | None:
    if not s.workspace:
        return None
    from .report_pipeline import status

    try:
        return status(s.workspace)
    except (SystemExit, Exception):  # noqa: BLE001  工作区不完整时界面照常显示其余内容
        return None


def analysis(s: Subject) -> dict[str, Any]:
    return load(s.run / "financials" / "analysis.json", {}) if s.run else {}


def valuation(s: Subject) -> dict[str, Any]:
    if not s.run:
        return {}
    v = load(s.run / "valuation" / "valuation.json", {}) or {}
    f = load(s.run / "valuation" / "forecast_summary.json", {}) or {}
    return {**v, "rating": (f.get("rating") or {})} if v else {}


def events(s: Subject) -> list[dict[str, Any]]:
    path = s.run / "events.jsonl" if s.run else None
    if not path or not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def agent_runs(s: Subject) -> list[dict[str, Any]]:
    if not s.workspace:
        return []
    return load(s.workspace / ".pipeline" / "agent_runs.json", []) or []


def agent_log(s: Subject, rel: str, limit: int = 400) -> list[str]:
    """Agent 事件流的一行摘要（与 report_pipeline 终端输出一致）。"""
    from .report_pipeline import _event_brief

    path = (s.workspace / rel) if s.workspace else None
    if not path or not path.is_file():
        return []
    lines = [b.rstrip("\n") for ln in path.read_text(encoding="utf-8").splitlines() for b in [_event_brief(ln)] if b.strip()]
    return lines[-limit:]


def scores(s: Subject) -> list[dict[str, Any]]:
    """与该对象相关的评测结果（新的在后）：refine 各轮、eval/results 与 eval/calibration 中评的是它的那些。"""
    found: list[tuple[str, Path]] = []
    if s.workspace:
        for d in sorted((s.workspace / ".pipeline" / "rounds").glob("*")):
            if (d / "score.json").is_file():
                found.append((f"refine 第 {d.name} 轮", d))
    target = str(s.run) if s.run else None
    for base in (RESULTS, CALIBRATION):
        for score in sorted(base.rglob("score.json")) if base.is_dir() else []:
            b = load(score.parent / "bundle.json", {}) or {}
            if target and b.get("run") == target:
                found.append((str(score.parent.relative_to(PROJECT_ROOT)), score.parent))
    out = []
    for label, d in found:
        sc = load(d / "score.json")
        if isinstance(sc, dict):
            when = (load(d / "bundle.json", {}) or {}).get("evaluated_at") or ""
            out.append({"label": label, "dir": d, "evaluated_at": when, **sc})
    return sorted(out, key=lambda x: x["evaluated_at"])


def pdf(s: Subject) -> Path | None:
    d = s.run / "report" if s.run else None
    if not d or not d.is_dir():
        return None
    named = sorted(p for p in d.glob("*.pdf") if p.name != "report.pdf")
    return named[-1] if named else (d / "report.pdf" if (d / "report.pdf").is_file() else None)


def workbook(s: Subject) -> Path | None:
    p = s.run / "valuation" / "model.xlsx" if s.run else None
    return p if p and p.is_file() else None
