"""盲评会话：在仓库与工作区之外搭一个只含交付物的目录，起独立的 Claude Code 会话逐条评审。

评审模型看不到写作与复核过程、模型名和分值，只看到：研报 PDF、文稿、估值产物、外部来源登记、人工复核清单，
以及评审条目（id、标题、判定标准、反例）。输出 judgments.json，由 rubric.score 计分。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.config import PROJECT_ROOT
from ..report_pipeline import QC_MODEL
from .rubric import Bundle, judge_items

MODEL_FILES = ("valuation.json", "forecast_summary.json", "segment_forecast.json", "scenarios.json",
               "non_operating_assets.json", "comps.json")
ALLOWED_TOOLS = ("Read(./**)", "Glob", "Grep", "Write(./judgments.json)")
PROMPT = "按本目录 CLAUDE.md 评审这份研报，把结果写进 judgments.json 后停止。"

GUIDE = """# 研报评审

你是研究所的质控评审，独立评审一份 A 股公司深度研报。你没有参与写作，也不知道是谁写的。
读者是买方基金经理：要的是判断和支撑判断的证据。

## 材料（只读本目录）

- `deliverable/report.pdf`：交付的研报 PDF（含图表、附录、免责声明）。页数较多时分批读，每次不超过 20 页。
- `deliverable/narrative.md`：研报正文文稿（与 PDF 正文同源，便于检索原文）。
- `deliverable/model/`：估值模型产物（DCF、盈利预测、分部预测、股权价值桥的加回项拆分等），单位见各文件。
- `deliverable/sources.json`：外部资料登记，正文 `[S编号]` 对应这里的条目（可能不存在）。
- `deliverable/review.md`：作者留给人工的复核清单（可能不存在）。
- `rubric.json`：评审条目。

数字与年报是否一致、三表是否勾稽、估值算术是否正确，已由程序另行核对，**你不必复算**；你判断的是分析是否成立、
论证是否充分、表达是否合格。不要联网，不要读本目录以外的文件。

## 判定规则

1. 对 `rubric.json` 的每一条都给出判定，不能遗漏。
2. 二元判定：完全满足判定标准才算通过；**拿不准时判不通过**，并在 reason 写明缺什么。
3. `negative: true` 的条目是负向条目：`passed: true` 表示**命中**（报告犯了这个错），没有发现就判 false。
4. evidence 摘录报告原文（不超过 80 字），并标位置（章节名或 PDF 页码）；没有可摘的写“无”。
5. reason 一两句话，说清为什么通过或不通过；不通过时写出读者需要、但报告没给的东西。

## 输出

写 `judgments.json`（UTF-8，合法 JSON）：

```json
{"items": [{"id": "L2-01", "passed": true, "evidence": "……（摘要页）", "reason": "……"}],
 "summary": "三五句话：这篇报告最强和最弱的地方"}
```
"""


def default_root() -> Path:
    return Path(os.getenv("FINAGENT_EVAL_DIR") or Path.home() / "finagent-evals")


def prepare(b: Bundle, rubric: dict[str, Any], dest: Path) -> Path:
    """搭盲评目录。目录必须在仓库之外：Claude Code 会沿父目录加载 CLAUDE.md。"""
    from ..report_pipeline import _check_location

    _check_location(dest, PROJECT_ROOT)
    if dest.exists():
        shutil.rmtree(dest)
    (dest / "deliverable" / "model").mkdir(parents=True)
    if b.pdf:
        shutil.copy2(b.pdf, dest / "deliverable" / "report.pdf")
    if b.narrative.is_file():
        shutil.copy2(b.narrative, dest / "deliverable" / "narrative.md")
    for name in MODEL_FILES:
        if (b.run / "valuation" / name).is_file():
            shutil.copy2(b.run / "valuation" / name, dest / "deliverable" / "model" / name)
    for src in (b.sources, b.review):
        if src.is_file():
            shutil.copy2(src, dest / "deliverable" / src.name)
    (dest / "rubric.json").write_text(json.dumps(judge_items(rubric), ensure_ascii=False, indent=2), encoding="utf-8")
    (dest / "CLAUDE.md").write_text(GUIDE, encoding="utf-8")
    return dest


def command(model: str | None = None) -> list[str]:
    return ["claude", "-p", PROMPT, "--model", model or QC_MODEL, "--permission-mode", "acceptEdits",
            "--allowedTools", *ALLOWED_TOOLS, "--output-format", "stream-json", "--verbose"]


def run_session(dest: Path, model: str | None = None, echo: bool = True) -> dict[str, Any]:
    """执行盲评会话；事件流存 judge.jsonl。返回运行记录（耗时、用量、退出码）。"""
    from ..report_pipeline import _event_brief, _usage

    cmd = command(model)
    if shutil.which(cmd[0]) is None:
        raise SystemExit("找不到 claude 命令行，先安装并登录（见 scripts/setup.sh）")
    started = datetime.now()
    log = dest / "judge.jsonl"
    with log.open("w", encoding="utf-8") as f:
        proc = subprocess.Popen(cmd, cwd=dest, stdout=subprocess.PIPE, text=True, encoding="utf-8")
        for line in proc.stdout:
            f.write(line)
            f.flush()
            if echo:
                print(_event_brief(line), end="", flush=True)
        code = proc.wait()
    return {"model": model or QC_MODEL, "exit_code": code, "started_at": started.isoformat(timespec="seconds"),
            "elapsed_sec": round((datetime.now() - started).total_seconds(), 1), **_usage(log, "claude")}


def read_judgments(path: Path, rubric: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """读 judgments.json，返回 ({id: 判定}, 问题列表)。非评审条目、重复与格式错误记为问题，不进计分。"""
    if not path.is_file():
        return {}, ["评审未写出 judgments.json"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {}, [f"judgments.json 不是合法 JSON：{e}"]
    wanted = {it["id"] for it in rubric["items"] if it["judge"] == "llm"}
    out: dict[str, dict[str, Any]] = {}
    problems = []
    for it in data.get("items", []):
        iid = it.get("id")
        if iid not in wanted:
            problems.append(f"多余条目 {iid}")
        elif iid in out:
            problems.append(f"重复条目 {iid}")
        elif not isinstance(it.get("passed"), bool):
            problems.append(f"{iid}: passed 不是布尔值")
        else:
            out[iid] = {"passed": it["passed"], "evidence": str(it.get("evidence", "")), "reason": str(it.get("reason", ""))}
    problems += [f"缺条目 {i}" for i in sorted(wanted - set(out))]
    return out, problems
