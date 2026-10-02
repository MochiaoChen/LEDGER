"""研报生成流水线：为一家公司搭建隔离工作区（sample），让模型在里面直接产出研报。

  python -m finagent.report_pipeline build     --company 恒瑞医药 --year 2025 [--tag opus] [--price 45.6 --price-source "..."]
  python -m finagent.report_pipeline run       --workspace <工作区> --agent claude|codex|deepseek [--model ...] [--dry-run]
  python -m finagent.report_pipeline status    [--workspace <工作区>]           # 阶段闸门（工作区内可省略参数）
  python -m finagent.report_pipeline collect   --workspace <工作区> [--label Opus]  # 产物收回仓库
  python -m finagent.report_pipeline scorecard --workspace <A> --workspace <B>   # 测评：多个工作区并排比较
  python -m finagent.report_pipeline sync-skills                                 # 更新仓库 .agents/skills 入口

工作区只放两个 skill、计算引擎、这一家公司的年报和外部输入，目录结构与仓库一致（skill 里的相对路径照常可用），
不含其他公司的抽取文件、文稿、历史运行和交付物，也不在仓库目录树内（避免模型读到仓库或上级目录的
CLAUDE.md、原插件代码）。工作区说明写在 AGENTS.md（Codex 等直接读，CLAUDE.md 引用它），按阶段写明该读什么、
不该读什么，`status` 逐阶段核对闸门。skill 全文在 .claude/skills/，.agents/skills/ 下是指向它的入口。
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from .core.config import PROJECT_ROOT

SKILLS = ("finagent-research", "finagent-report")
# 引擎里与研报无关的模块不进工作区
ENGINE_EXCLUDE = {"__pycache__", "deepseek_harness.py"}
# skill 文档引用的格式样例（虚构公司，只作字段格式参考）
FORMAT_SAMPLES = ("data/samples/valuation_assumptions.json", "data/samples/peers.csv")
META = "sample.json"
STATE_DIR = ".pipeline"
AGENT_SKILLS = Path(".agents") / "skills"  # Codex 等读 .agents/skills 与 AGENTS.md
PY_WRAPPER = "py.cmd" if os.name == "nt" else "./py"
TASK_PROMPT = (f"按本工作区 AGENTS.md 的流水线完成研报：每个阶段结束运行 {PY_WRAPPER} -m finagent.report_pipeline status，"
               f"全部闸门通过后停止并汇报。命令直接以 {PY_WRAPPER} 开头，不加 cd、不串联。")


# 工作区内允许的操作。未被信任的目录里 Claude Code 会忽略 settings.json 的 allow（deny 照常生效），
# 所以无头执行时同一份清单再经 --allowedTools 传入，不去改用户的全局信任配置
ALLOWED_TOOLS = (f"Bash({PY_WRAPPER} -m finagent:*)", f"Bash({PY_WRAPPER} -m finagent.report_pipeline status:*)",
                 f"Bash({PY_WRAPPER} data/extractions/:*)", f"Bash({PY_WRAPPER} -c:*)",
                 "Bash(cp .claude/skills/finagent-report/templates/:*)", "Bash(ls:*)", "Bash(mkdir -p data/:*)",
                 "Read", "Write(./data/**)", "Edit(./data/**)")


def agent_command(agent: str, model: str | None = None, *, python: str | None = None) -> list[str]:
    """无头执行命令。输出都是 JSONL 事件流，存进 .pipeline/agents/ 供测评读取用量。"""
    if agent == "claude":
        return ["claude", "-p", TASK_PROMPT, "--permission-mode", "acceptEdits",
                "--allowedTools", *ALLOWED_TOOLS, "--output-format", "stream-json", "--verbose",
                *(["--model", model] if model else [])]
    if agent == "codex":
        # 工作区不是 git 仓库；workspace-write 沙箱只允许写工作区与临时目录
        return ["codex", "exec", "--full-auto", "--skip-git-repo-check", "--json",
                *(["-m", model] if model else []), TASK_PROMPT]
    if agent == "deepseek":
        return [python or sys.executable, "-m", "finagent.deepseek_agent",
                *(["--model", model] if model else [])]
    raise SystemExit(f"不支持的 agent：{agent}")


def default_dest() -> Path:
    return Path(os.getenv("FINAGENT_SAMPLES_DIR") or Path.home() / "finagent-samples")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _ignore(names: set[str]):
    return lambda _dir, files: [f for f in files if f in names or f.endswith(".pyc")]


def _frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    return dict(line.split(": ", 1) for line in m.group(1).splitlines() if ": " in line) if m else {}


def skill_stub(name: str, root: Path) -> str:
    """.agents/skills/<name>/SKILL.md：与 .claude/skills 同名同描述，正文只指向全文，避免两份内容漂移。"""
    fm = _frontmatter((root / ".claude" / "skills" / name / "SKILL.md").read_text(encoding="utf-8"))
    return (f"---\nname: {fm['name']}\ndescription: {fm['description']}\n---\n\n"
            f"# {fm['name']}\n\n本 skill 的全文与配套文件在 `.claude/skills/{name}/`（相对仓库或工作区根目录）。"
            f"先完整读 `.claude/skills/{name}/SKILL.md`，按其中的流程执行：文中 `references/`、`templates/`、`reportkit/` "
            f"等链接相对该目录，命令和 `data/`、`runs/` 等路径相对根目录。\n")


def sync_agent_skills(root: Path, names: tuple[str, ...] | None = None) -> list[Path]:
    names = names or tuple(sorted(p.name for p in (root / ".claude" / "skills").iterdir()
                                  if (p / "SKILL.md").is_file()))
    out = []
    for name in names:
        path = root / AGENT_SKILLS / name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(skill_stub(name, root), encoding="utf-8")
        out.append(path)
    return out


# ------------------------------------------------------------------ 来源
def resolve_source(company: str, pdf: str | None = None, root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """找到公司的年报：优先已核验清单（manifest.json），其次 report/resources/<公司>/ 下唯一的 PDF。"""
    resources = root / "report" / "resources"
    manifest = json.loads((resources / "manifest.json").read_text(encoding="utf-8"))
    record = next((r for r in manifest["reports"] if r["short_name"] == company), None)
    if pdf:
        path = Path(pdf).resolve()
    elif record:
        path = resources / record["path"]
    else:
        found = sorted((resources / company).glob("*.pdf")) if (resources / company).is_dir() else []
        if len(found) != 1:
            raise SystemExit(f"report/resources/{company}/ 下应有且仅有一份 PDF（找到 {len(found)} 份），请用 --pdf 指定")
        path = found[0]
    if not path.is_file():
        raise SystemExit(f"找不到年报：{path}")
    digest = _sha256(path)
    verified = bool(record) and (resources / record["path"]).resolve() == path.resolve()
    if verified and digest != record["sha256"]:
        raise SystemExit(f"{company} 年报 SHA-256 与 manifest.json 不符")
    return {"path": path, "sha256": digest, "verified": verified,
            "ticker": record["ticker"] if verified else None,
            "exchange": record["exchange"] if verified else None}


def _check_location(ws: Path, root: Path) -> None:
    """工作区不能在仓库或其上级目录树内：Claude Code / Codex 会沿父目录加载 CLAUDE.md / AGENTS.md，上级目录还有原插件代码。"""
    ws = ws.resolve()
    fence = root.resolve().parent
    if ws == fence or fence in ws.parents:
        raise SystemExit(f"工作区不能放在 {fence} 之下（会读到仓库与原插件内容），请换 --dest")
    home = Path.home().resolve()
    for p in ws.parents:
        hit = [n for n in ("CLAUDE.md", "AGENTS.md") if (p / n).exists()]
        if p != home and hit:
            raise SystemExit(f"上级目录 {p} 有 {hit[0]}，会被加载进模型上下文，请换 --dest")


# ------------------------------------------------------------------ build
def build(company: str, year: int, dest: Path | None = None, *, pdf: str | None = None,
          price: float | None = None, price_source: str | None = None, price_date: str | None = None,
          peers: str | None = None, tag: str | None = None, allow_unverified: bool = False,
          force: bool = False, root: Path = PROJECT_ROOT) -> Path:
    src = resolve_source(company, pdf, root)
    if not src["verified"] and not allow_unverified:
        raise SystemExit(f"{src['path'].name} 不在已核验清单 manifest.json 中（来源/版本未核对）。"
                         "确认可以使用后加 --allow-unverified")
    if price is not None and not price_source:
        raise SystemExit("--price 是外部数据，必须同时给 --price-source")
    key = f"{company}_{year}"
    # 同一公司要让不同模型各跑一遍时用 tag 区分工作区；抽取目录名仍是 <公司>_<年度>
    ws = (dest or default_dest()) / (f"{key}_{tag}" if tag else key)
    _check_location(ws, root)
    if ws.exists():
        if not force:
            raise SystemExit(f"工作区已存在：{ws}（--force 重建，会删除其中全部内容）")
        shutil.rmtree(ws)
    ws.mkdir(parents=True)

    for name in SKILLS:
        shutil.copytree(root / ".claude" / "skills" / name, ws / ".claude" / "skills" / name,
                        ignore=_ignore({"__pycache__"}))
    for name in SKILLS:
        (ws / AGENT_SKILLS / name).mkdir(parents=True)
        (ws / AGENT_SKILLS / name / "SKILL.md").write_text(skill_stub(name, root), encoding="utf-8")
    shutil.copytree(root / "finagent", ws / "finagent", ignore=_ignore(ENGINE_EXCLUDE))
    shutil.copy2(root / "requirements.txt", ws / "requirements.txt")
    for rel in FORMAT_SAMPLES:
        (ws / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, ws / rel)

    # 年报放在与仓库相同的相对路径，运行记录里的 argv 收回仓库后仍可复现
    pdf_rel = Path("report") / "resources" / company / src["path"].name
    (ws / pdf_rel).parent.mkdir(parents=True)
    shutil.copy2(src["path"], ws / pdf_rel)
    locate = src["path"].parent / "locate.json"
    if locate.is_file() and src["verified"]:
        shutil.copy2(locate, ws / pdf_rel.parent / "locate.json")
    else:
        out = subprocess.run([sys.executable, "-m", "finagent", "locate", "--input", str(pdf_rel)],
                             cwd=ws, capture_output=True, text=True, encoding="utf-8")
        if out.returncode != 0:
            raise SystemExit("locate 失败：\n" + out.stderr)
        (ws / pdf_rel.parent / "locate.json").write_text(out.stdout, encoding="utf-8")

    inputs: dict[str, Any] = {}
    if price is not None:
        inputs["market"] = {"current_price": price, "price_source": price_source, "price_date": price_date}
        (ws / "inputs").mkdir(exist_ok=True)
        (ws / "inputs" / "market.json").write_text(json.dumps(inputs["market"], ensure_ascii=False, indent=2),
                                                    encoding="utf-8")
    if peers:
        (ws / "inputs").mkdir(exist_ok=True)
        shutil.copy2(peers, ws / "inputs" / "peers.csv")
        inputs["peers"] = "inputs/peers.csv"
    (ws / "data" / "extractions" / key / "report").mkdir(parents=True)
    (ws / "runs").mkdir()

    meta = {"company": company, "year": year, "key": key, "pdf": pdf_rel.as_posix(),
            "pdf_sha256": src["sha256"], "verified_source": src["verified"], "ticker": src["ticker"],
            "exchange": src["exchange"], "tag": tag, "inputs": inputs, "python": sys.executable,
            "repo": str(root.resolve()), "repo_commit": _git_head(root),
            "created_at": datetime.now().isoformat(timespec="seconds")}
    (ws / META).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    # 解释器包一层 ./py：命令短，路径里的空格也不影响 Bash 权限前缀匹配；
    # matplotlib 缓存放进工作区，Codex 等沙箱只允许写工作区时也能画图
    (ws / "py").write_text("#!/bin/sh\n" 'HERE="$(cd "$(dirname "$0")" && pwd)"\n'
                           'export MPLCONFIGDIR="$HERE/.pipeline/mpl"\n'
                           f'exec "{sys.executable}" "$@"\n', encoding="utf-8")
    (ws / "py").chmod(0o755)
    # Windows cmd.exe / PowerShell 不识别无扩展名的 POSIX 包装器。
    (ws / "py.cmd").write_text(
        "@echo off\r\n"
        "set \"MPLCONFIGDIR=%~dp0.pipeline\\mpl\"\r\n"
        f'"{sys.executable}" %*\r\n', encoding="utf-8")
    (ws / "AGENTS.md").write_text(render_guide(meta), encoding="utf-8")
    (ws / "CLAUDE.md").write_text("@AGENTS.md\n", encoding="utf-8")
    (ws / "TASK.md").write_text(TASK_PROMPT + "\n", encoding="utf-8")
    (ws / ".claude" / "settings.json").write_text(
        json.dumps(settings(meta, root), ensure_ascii=False, indent=2), encoding="utf-8")
    return ws


def _git_head(root: Path) -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def settings(meta: dict[str, Any], root: Path) -> dict[str, Any]:
    """工作区权限：引擎与 skill 只读；仓库及其上级目录（原插件、其他公司产物）不可读。"""
    fence = root.resolve().parent.as_posix()
    locked = ("finagent/**", ".claude/**", ".agents/**", "report/**", META, "py", "py.cmd", "CLAUDE.md", "AGENTS.md")
    return {"permissions": {
        "allow": list(ALLOWED_TOOLS),
        "deny": [f"Read(/{fence}/**)", "WebFetch", "WebSearch",
                 *(f"{tool}(./{p})" for p in locked for tool in ("Edit", "Write"))]}}


# ------------------------------------------------------------------ 工作区说明（CLAUDE.md）
def render_guide(meta: dict[str, Any]) -> str:
    c, y, key, py, pdf = meta["company"], meta["year"], meta["key"], "./py", meta["pdf"]
    work = f"data/extractions/{key}"
    market = meta["inputs"].get("market")
    price_line = (f"`inputs/market.json`：当前股价 {market['current_price']} 元，来源：{market['price_source']}"
                  f"（外部数据，写进假设文件的 `current_price` / `price_source`）"
                  if market else "**未提供股价。** 估值阶段停下，在交付说明里写明缺股价，不要自己找或编。")
    peers_line = ("`inputs/peers.csv`：可比公司（外部数据），估值命令加 `--peers inputs/peers.csv`"
                  if "peers" in meta["inputs"] else "未提供可比公司，不做相对估值。")
    source_line = ("已核验（`manifest.json` 有记录，SHA-256 一致）" if meta["verified_source"]
                   else "**未核验来源**（项目成员提供，官方链接与版本未核对），交付说明里要写明")
    return f"""# {c} {y} 年报深度研报 · 工作区流水线

本工作区由 `python -m finagent.report_pipeline build` 生成，只为 **{c} {y}** 一家公司出一份卖方体例深度研报（PDF）
和估值模型（xlsx）。按下面的阶段顺序做，每个阶段结束运行一次状态检查：

```bash
{py} -m finagent.report_pipeline status
```

它逐项核对闸门并告诉你下一步做什么、读哪份文档。上下文被压缩或中途接手时，**先跑 status，不要重读已完成阶段的文件**。

下文 `PY` = macOS/Linux 的 `./py`，Windows 的 `py.cmd`（均包装本机 Python）。DeepSeek harness
通过受限工具执行，不自行拼 shell 命令。**当前目录就是工作区**：命令直接以 `./py` 开头，
不要加 `cd`、不要写绝对路径、不要用 `&&` / 管道串联多条命令，否则无头执行时权限匹配不上会被拒。
在 Windows 上执行本页示例命令时，把 `./py` 替换成 `py.cmd`。

## 输入（只有这些）

| 文件 | 说明 |
|---|---|
| `{pdf}` | 年报原件，{source_line} |
| `{Path(pdf).parent.as_posix()}/locate.json` | 关键页定位（已跑好），先看它再按页读 PDF |
| {"`inputs/market.json`" if market else "—"} | {price_line} |
| {"`inputs/peers.csv`" if "peers" in meta["inputs"] else "—"} | {peers_line} |

skill 全文在 `.claude/skills/`（`.agents/skills/` 下只是指向它的入口），下文的 skill 文档路径都相对 `.claude/skills/`。

你的全部产出写在 `{work}/`（抽取、假设、框架、文稿、编排脚本、交付说明），程序运行目录在 `runs/`。

## 读取边界（防止上下文浪费和信息污染）

- **不读**：`finagent/` 引擎源码（用命令和 `schema`，不看实现）、`data/samples/` 以外的样例（这里也没有）、
  `runs/` 下 JSON 的全文（用 `PY -c` 取需要的字段，或在编排脚本里用 `reportkit.core.Run` 读）、
  `preview/` 以外的渲染中间文件。工作区之外的任何目录都不要读，也不要联网查公司信息：本报告只用年报和上面的输入。
- **skill 文档按阶段读**（见下表），不要一开始全部读完。skill 里提到的茅台样例、`tests/`、`data/extractions/贵州茅台_2025/`
  不在本工作区，不用找；`references/claims.md`、`commentary.md` 与本任务无关（不核查研报草稿，解读即研报正文）。
- **PDF 按页读**，每次不超过 20 页，只读 `locate.json` 的 `suggested_reads`、管理层讨论与分析、framework 需要的附注页。
  已抄进 facts / extras 的页不要再读。
- **不改** `finagent/`、`.claude/`、`report/`：引擎或 reportkit 不够用时，在公司编排脚本里绕开，并在交付说明里写明需要仓库改什么。

## 阶段

| # | 阶段 | 做什么 | 这时才读 | 闸门（status 检查） |
|---|---|---|---|---|
| 1 | 财务抽取 | 按 locate 读三大报表、最近三年主要会计数据、分季度、股本页，写 `{work}/facts.json`；同一指标/期间只留一条 | `finagent-research/SKILL.md` 第 1–3 步，`references/extraction.md` | `verify-facts` 为 `ok: true`，且最近三年收入、归母、经营现金流、总资产、基本 EPS 无缺项/重复 |
| 2 | 分析框架 | 通读管理层讨论与分析，写 `{work}/report/framework.md`（投资主线、驱动清单、披露局限、章节结构） | `finagent-report/SKILL.md` 一～三，`references/analysis.md` | 文件存在且不是模板 |
| 3 | 经营数据 | 按驱动清单逐格抄表到 `{work}/extras.json`，派生比率写 `ratios` | `references/extraction.md`“补充表格” | `PY -m finagent verify-extra --input {pdf} --extras {work}/extras.json` 为 `ok: true` |
| 4 | 估值假设 | 起草 `{work}/valuation_assumptions.json`：`status` 写明“观点/假设”，股价取 `inputs/market.json`，每项假设写依据 | `finagent-research/SKILL.md` 第 5 步“估值口径”，`data/samples/valuation_assumptions.json`（格式） | 文件存在，有 `current_price` 与 `price_source` |
| 5 | 估值运行 | `PY -m finagent valuation --input {pdf} --year {y} --company {c} --assumptions {work}/valuation_assumptions.json --facts {work}/facts.json --extras {work}/extras.json --llm off`{" --peers inputs/peers.csv" if "peers" in meta["inputs"] else ""} | — | 最新运行目录成功，且晚于 facts / extras / 假设的修改 |
| 6 | 文稿 | `cp .claude/skills/finagent-report/templates/narrative.md {work}/report/narrative.md`，写完全部分析；`PY -m finagent guard --run-dir runs/<run_id> --text {work}/report/narrative.md` | `references/sections.md`，`finagent-research/references/writing.md` | 最新运行目录的 guard 为 `ok: true`，核对的是当前文稿，且文稿检查无内部流程话术、占位符或冗余否定句式 |
| 7 | 排版 | `cp .claude/skills/finagent-report/templates/build_report.py {work}/report/build_report.py`，`Config.output_name` 设为 `{c}{datetime.now():%m%d}.pdf`；`PY {work}/report/build_report.py --run-dir runs/<run_id>`，看 `preview/sheet*.png` 自检 | `finagent-research/references/html-report.md` | PDF 晚于文稿和编排脚本 |
| 8 | 交付说明 | 写 `{work}/report/delivery.md`：PDF 路径、页数与图表数、核心结论、评级（取程序结果）、哪些是假设或外部数据、未解决的校验问题 | — | 文件存在 |

改了前面阶段的文件（如补抄 extras），status 会把后面的阶段标为过期：重跑估值、guard、排版。

## 底线（违反就返工）

1. 你不做算术：增速、占比、差值、估值都由程序算，正文照产物展示值抄。
2. 每个数字来自年报原文（带页码）或运行产物；正文必须过 guard。
3. 估值参数是你起草的观点/假设，必须标明；股价是外部数据，必须注明来源；评级取 `forecast_summary.rating`。
4. 给投资研究读者写结论：先给 2–3 环关键数字的推导，再写判断；行业分母和公司口径不一致时不能推出份额变化。
   不写“程序归因”“模型状态”等内部流程，不用“不是……而是……”“而非”凑转折，不把现金或分红宣称为估值下限。
   拿不准且非关键的内容删去；关键但证据不足的判断放在交付说明的待核清单，不在正文自我辩解。
5. 校验 3 轮仍不过的问题不硬改数字，写进交付说明。
6. 全部闸门通过后停止，汇报 status 输出和交付说明，不要做额外的事。
"""


# ------------------------------------------------------------------ status
def _mtime(path: Path) -> float:
    return path.stat().st_mtime if path.exists() else 0.0


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_run(ws: Path, work: str) -> tuple[Path | None, dict | None]:
    """最新一次用本工作区 facts 跑成功的 valuation / all 运行。"""
    best = None
    for d in sorted((ws / "runs").glob("*"), reverse=True):
        m = d / "manifest.json"
        if not m.is_file():
            continue
        man = _load(m)
        argv = man.get("config", {}).get("argv", [])
        if man.get("status") == "ok" and man.get("task") in ("valuation", "all") and _has_arg(argv, f"{work}/facts.json"):
            best = (d, man)
            break
    return best or (None, None)


def _has_arg(argv: list[str], rel: str) -> bool:
    return any(Path(a).as_posix().removeprefix("./") == rel for a in argv)


def _extras_check(ws: Path, meta: dict, extras: Path) -> dict:
    """verify-extra 结果按 extras 内容哈希缓存，避免每次 status 都重新解析整份 PDF。"""
    cache = ws / STATE_DIR / "extras_check.json"
    digest = _sha256(extras)
    if cache.is_file() and (c := _load(cache)).get("sha256") == digest:
        return c
    from .parsing.document import load_document
    from .tasks.financials.extras import verify_extras

    res = verify_extras(load_document(str(ws / meta["pdf"])), _load(extras))
    out = {"sha256": digest, "ok": not res["rejected"], "rejected": len(res["rejected"]),
           "tables": len(res["tables"]),
           "cells": sum(1 for t in res["tables"] for row in t["rows"] for v in row["values"] if v is not None)}
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _facts_quality(path: Path, year: int) -> dict[str, Any]:
    """抽取完整性下限：防止 verify-facts 只验证已有数字，却放过漏抄与重复条目。"""
    data = _load(path)
    entries = data.get("facts") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return {"ok": False, "missing": ["facts 数组"], "duplicates": []}
    pairs = [(str(item.get("metric_id")), str(item.get("period"))) for item in entries if isinstance(item, dict)]
    counts = Counter(pairs)
    duplicates = sorted(f"{metric}/{period}" for (metric, period), n in counts.items() if n > 1)
    # A 股年报“主要会计数据和财务指标”覆盖最近三年；这些是三表、盈利质量与报告首页的最低输入。
    core = ("revenue", "np_parent", "ocf", "total_assets", "eps_basic")
    missing = sorted(f"{metric}/{period}" for period in range(year - 2, year + 1)
                     for metric in core if (metric, str(period)) not in counts)
    return {"ok": not (missing or duplicates), "missing": missing, "duplicates": duplicates}


def _narrative_quality(path: Path) -> dict[str, Any]:
    """机械拦截已知劣质写法；不代替事实与投资判断审核。"""
    body = path.read_text(encoding="utf-8")
    checks = {
        "内部流程话术": r"程序(?:未|据|归因|评级)|按程序|模型状态|senior-review-ready|screen-grade",
        "冗余否定句式": r"不是[^。；\n]{0,60}而是|而非|而不是",
        "未完成占位符": r"(?i:TODO|TBD|FIXME)|待(?:核查|补充|确认|完善)",
        "无依据的保底表述": r"(?:估值|股价)(?:的)?下限|构成估值的下限",
    }
    issues: list[str] = []
    for label, pattern in checks.items():
        for match in list(re.finditer(pattern, body))[:5]:
            line = body.count("\n", 0, match.start()) + 1
            issues.append(f"{label} L{line}: {match.group(0)}")
    return {"ok": not issues, "issues": issues}


def _xlsx_valid(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 1000:
        return False
    try:
        with zipfile.ZipFile(path) as package:
            return "xl/workbook.xml" in package.namelist() and package.testzip() is None
    except (OSError, zipfile.BadZipFile):
        return False


def _pdf_valid(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size < 1000:
        return False
    try:
        import pdfplumber
        from pdfplumber.utils.exceptions import PdfminerException
        with pdfplumber.open(path) as doc:
            return bool(doc.pages) and bool((doc.pages[0].extract_text() or "").strip())
    except (OSError, ValueError, TypeError, PdfminerException):
        return False


def status(ws: Path) -> dict[str, Any]:
    meta = _load(ws / META)
    c, y, work = meta["company"], meta["year"], f"data/extractions/{meta['key']}"
    w = ws / work
    facts, verified, extras = w / "facts.json", w / "facts.verified.json", w / "extras.json"
    assumptions, framework = w / "valuation_assumptions.json", w / "report" / "framework.md"
    narrative, script, delivery = w / "report" / "narrative.md", w / "report" / "build_report.py", w / "report" / "delivery.md"
    stages: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str, todo: str) -> bool:
        stages.append({"stage": name, "ok": ok, "detail": detail, "next": "" if ok else todo})
        return ok

    # 1 财务抽取
    if not facts.is_file():
        add("1 财务抽取", False, "facts.json 不存在",
            "读 finagent-research/SKILL.md 第 1–3 步与 references/extraction.md，按 locate.json 读页抽取")
    elif not verified.is_file() or _mtime(verified) < _mtime(facts):
        add("1 财务抽取", False, "facts.json 修改后未重新校验", "运行 verify-facts")
    else:
        chk = _load(verified).get("check", {})
        fq = _facts_quality(facts, y)
        add("1 财务抽取", bool(chk.get("ok")) and fq["ok"],
            f"rejected {len(chk.get('rejected', []))}，conflicts {len(chk.get('conflicts', []))}，"
            f"勾稽失败 {len(chk.get('tieout_failures', []))}，"
            f"三年核心缺项 {len(fq['missing'])}，重复条目 {len(fq['duplicates'])}",
            "按 verify-facts 与三年核心完整性清单回原文修正："
            + ", ".join((fq["missing"] + fq["duplicates"])[:12]))
    # 2 分析框架
    add("2 分析框架", framework.is_file() and framework.stat().st_size > 0,
        "framework.md " + ("已写" if framework.is_file() else "不存在"),
        "读 finagent-report/SKILL.md 一～三与 references/analysis.md，通读管理层讨论与分析后写 framework.md")
    # 3 经营数据
    if not extras.is_file():
        add("3 经营数据", False, "extras.json 不存在", "按 framework.md 驱动清单抄表，读 extraction.md“补充表格”")
    else:
        ec = _extras_check(ws, meta, extras)
        add("3 经营数据", ec["ok"], f"{ec['tables']} 张表，拒收 {ec['rejected']} 格", "运行 verify-extra 并修正拒收项")
    # 4 估值假设
    market = ws / "inputs" / "market.json"
    if not assumptions.is_file():
        add("4 估值假设", False, "valuation_assumptions.json 不存在", "读 SKILL.md 第 5 步估值口径，按样例格式起草")
    else:
        a = _load(assumptions)
        market_data = _load(market) if market.is_file() else {}
        miss = [k for k in ("current_price", "price_source") if a.get(k) in (None, "")]
        mismatch = [k for k in ("current_price", "price_source") if market_data and a.get(k) != market_data.get(k)]
        if market_data.get("price_date") and a.get("valuation_date") != market_data["price_date"]:
            mismatch.append("valuation_date")
        add("4 估值假设", not (miss or mismatch or not market_data),
            "缺行情输入" if not market_data else "缺 " + "、".join(miss) if miss else
            "与 inputs/market.json 不一致：" + "、".join(mismatch) if mismatch else "已核对行情来源与日期",
            "股价取 inputs/market.json；没有就停下并写进交付说明")
    # 5 估值运行
    run, man = _latest_run(ws, work)
    inputs_mtime = max(_mtime(facts), _mtime(extras), _mtime(assumptions))
    if run is None:
        add("5 估值运行", False, "没有成功的 valuation 运行", "按 CLAUDE.md 阶段 5 的命令运行")
    else:
        started = datetime.fromisoformat(man["started_at"]).timestamp()
        argv = man["config"]["argv"]
        stale = started < inputs_mtime
        no_extras = extras.is_file() and not _has_arg(argv, f"{work}/extras.json")
        model_ok = _xlsx_valid(run / "valuation" / "model.xlsx")
        add("5 估值运行", not (stale or no_extras) and model_ok, f"runs/{run.name}"
            + ("（早于输入文件修改，已过期）" if stale else "") + ("（未带 --extras）" if no_extras else "")
            + ("（估值 Excel 缺失或损坏）" if not model_ok else ""),
            "重跑估值，后续阶段都用新的运行目录")
    # 6 文稿
    if not narrative.is_file() or run is None:
        add("6 文稿", False, "narrative.md 不存在" if not narrative.is_file() else "缺运行目录",
            "复制 templates/narrative.md，读 references/sections.md 与 writing.md 后写作")
    else:
        g, cm = run / "commentary_guard.json", run / "commentary.md"
        same = cm.is_file() and cm.read_text(encoding="utf-8") == narrative.read_text(encoding="utf-8")
        quality = _narrative_quality(narrative)
        ok = g.is_file() and _load(g).get("ok") and same and quality["ok"]
        detail = ("guard 与文稿检查通过" if ok else "文稿检查未通过：" + "；".join(quality["issues"][:8])
                  if g.is_file() and _load(g).get("ok") and same and not quality["ok"] else "guard 未通过" if g.is_file() and same
                  else f"当前文稿未对 runs/{run.name} 跑 guard")
        add("6 文稿", bool(ok), detail, f"PY -m finagent guard --run-dir runs/{run.name} --text {work}/report/narrative.md")
    # 7 排版
    pdf = run / "report" / "report.pdf" if run else None
    if pdf is None or not pdf.is_file():
        add("7 排版", False, "PDF 不存在", "复制 templates/build_report.py，读 references/html-report.md，渲染后看 preview")
    else:
        fresh = _mtime(pdf) >= max(_mtime(narrative), _mtime(script))
        named = [p.name for p in pdf.parent.glob("*.pdf") if p.name != "report.pdf"]
        readable = _pdf_valid(pdf)
        add("7 排版", fresh and bool(named) and readable, f"runs/{run.name}/report/{named[0] if named else 'report.pdf'}"
            + ("" if fresh else "（早于文稿或脚本修改）") + ("" if named else "（未设 output_name）")
            + ("" if readable else "（PDF 损坏或首页无文本）"),
            "重新渲染；Config.output_name 设为公司名+日期")
    # 8 交付说明
    add("8 交付说明", delivery.is_file(), "delivery.md " + ("已写" if delivery.is_file() else "不存在"),
        "写交付说明：结论、评级、假设与外部数据、未解决问题")

    # 前一阶段未过，后面的“通过”不可信
    blocked = False
    for s in stages:
        if blocked and s["ok"]:
            s["ok"], s["detail"], s["next"] = False, s["detail"] + "（前序阶段未通过）", "先完成前序阶段"
        blocked = blocked or not s["ok"]
    nxt = next((s for s in stages if not s["ok"]), None)
    return {"company": c, "year": y, "workspace": str(ws), "run_dir": f"runs/{run.name}" if run else None,
            "done": nxt is None, "next": f"{nxt['stage']}：{nxt['next']}" if nxt else "全部闸门通过",
            "stages": stages}


def _print_status(res: dict[str, Any]) -> None:
    print(f"{res['company']} {res['year']}  工作区 {res['workspace']}")
    for s in res["stages"]:
        print(f"  [{'✓' if s['ok'] else ' '}] {s['stage']:<8} {s['detail']}")
    print(f"运行目录：{res['run_dir'] or '—'}")
    print(f"下一步：{res['next']}")


# ------------------------------------------------------------------ collect
def collect(ws: Path, *, label: str = "", overwrite: bool = False, force: bool = False,
            delivery_only: bool = False, root: Path = PROJECT_ROOT) -> dict[str, Any]:
    """产物收回仓库：抽取与文稿 → data/extractions/，运行目录 → runs/，PDF 与模型 → report/交付/。"""
    res = status(ws)
    if not res["done"] and not force:
        raise SystemExit(f"闸门未全部通过（{res['next']}），--force 可强制收回")
    meta = _load(ws / META)
    key = meta["key"]
    src_work, dst_work = ws / "data" / "extractions" / key, root / "data" / "extractions" / key
    if dst_work.exists() and not (overwrite or delivery_only):
        raise SystemExit(f"{dst_work} 已存在，确认覆盖加 --overwrite（测评对照只收交付物用 --delivery-only）")
    out: dict[str, Any] = {}
    if not delivery_only:
        if dst_work.exists():
            shutil.rmtree(dst_work)
        shutil.copytree(src_work, dst_work, ignore=_ignore({"__pycache__"}))
        out["extractions"] = str(dst_work.relative_to(root))
    if res["run_dir"]:
        run = ws / res["run_dir"]
        dst_run = root / "runs" / run.name
        if not dst_run.exists():
            shutil.copytree(run, dst_run)
        out["run_dir"] = str(dst_run.relative_to(root))
        pdf, xlsx = run / "report" / "report.pdf", run / "valuation" / "model.xlsx"
        if pdf.is_file():
            name = " ".join(x for x in (datetime.now().strftime("%m%d"), meta["company"], label) if x)
            dst = root / "report" / "交付" / name
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copy2(pdf, dst / "report.pdf")
            if xlsx.is_file():
                shutil.copy2(xlsx, dst / "sheet.xlsx")
            out["delivery"] = str(dst.relative_to(root))
    return out


# ------------------------------------------------------------------ run（无头）
def run_agent(ws: Path, agent: str, model: str | None = None) -> int:
    """在工作区里无头执行；事件流原样存 .pipeline/agents/<时间>-<agent>.jsonl，运行记录追加到 agent_runs.json。"""
    cmd = agent_command(agent, model, python=_load(ws / META)["python"])
    if shutil.which(cmd[0]) is None:
        raise SystemExit(f"找不到 {cmd[0]} 命令行，先安装并登录")
    logs = ws / STATE_DIR / "agents"
    logs.mkdir(parents=True, exist_ok=True)
    started = datetime.now()
    log = logs / f"{started:%Y%m%d-%H%M%S}-{agent}.jsonl"
    with log.open("w", encoding="utf-8") as f:
        proc = subprocess.Popen(cmd, cwd=ws, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace")
        try:
            for line in proc.stdout:  # 边跑边落盘，中途中断也有记录
                f.write(line)
                f.flush()
                print(_event_brief(line), end="", flush=True)
            code = proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            code = 130
            print("[中断] 已停止执行模型，工作区进度保留\n", flush=True)
    record = {"agent": agent, "model": model or ("deepseek-flash" if agent == "deepseek" else None),
              "started_at": started.isoformat(timespec="seconds"),
              "elapsed_sec": round((datetime.now() - started).total_seconds(), 1), "exit_code": code,
              "log": log.relative_to(ws).as_posix(), **_usage(log, agent)}
    runs = ws / STATE_DIR / "agent_runs.json"
    history = _load(runs) if runs.is_file() else []
    runs.write_text(json.dumps([*history, record], ensure_ascii=False, indent=2), encoding="utf-8")
    return code


def _event_brief(line: str) -> str:
    """事件流只在终端打印一行摘要，完整内容在日志里。"""
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        return line
    kind = ev.get("type", "")
    if kind == "result":
        return f"[完成] {str(ev.get('result', ''))[:400]}\n"
    if kind == "assistant":
        texts = [c.get("text", "") for c in ev.get("message", {}).get("content", []) if c.get("type") == "text"]
        return "".join(f"· {t.strip()[:200]}\n" for t in texts if t.strip())
    if kind == "item.completed" and ev.get("item", {}).get("type") == "agent_message":
        return f"· {ev['item'].get('text', '').strip()[:200]}\n"
    if kind == "deepseek.stage":
        return f"· {ev.get('stage', '')}：{ev.get('detail', '')[:200]}\n"
    if kind == "deepseek.error":
        return f"[错误] {ev.get('detail', '')[:300]}\n"
    return ""


def _usage(log: Path, agent: str) -> dict[str, Any]:
    """从事件流取用量：Claude 的 result 事件有轮数与费用，Codex 的 turn.completed 有 token 数。"""
    out: dict[str, Any] = {}
    tokens = {"input_tokens": 0, "output_tokens": 0}
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if agent == "claude" and ev.get("type") == "result":
            out.update(turns=ev.get("num_turns"), cost_usd=ev.get("total_cost_usd"))
            u = ev.get("usage") or {}
            tokens = {"input_tokens": u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                      + u.get("cache_creation_input_tokens", 0), "output_tokens": u.get("output_tokens", 0)}
        if agent == "codex" and ev.get("type") == "turn.completed":
            u = ev.get("usage") or {}
            tokens["input_tokens"] += u.get("input_tokens", 0)
            tokens["output_tokens"] += u.get("output_tokens", 0)
        if agent == "deepseek" and ev.get("type") == "deepseek.usage":
            u = ev.get("usage") or {}
            tokens["input_tokens"] += u.get("prompt_tokens", 0)
            tokens["output_tokens"] += u.get("completion_tokens", 0)
    return {**out, **tokens}


# ------------------------------------------------------------------ scorecard（测评）
def scorecard(ws: Path) -> dict[str, Any]:
    """一个工作区的客观指标：闸门、抽取规模、迭代次数、研报篇幅、估值结论、模型用量。不打总分。"""
    meta, res = _load(ws / META), status(ws)
    work = ws / "data" / "extractions" / meta["key"]
    row: dict[str, Any] = {"workspace": ws.name, "company": meta["company"], "tag": meta.get("tag"),
                           "stages_passed": sum(s["ok"] for s in res["stages"]), "done": res["done"],
                           "next": None if res["done"] else res["next"]}
    runs = ws / STATE_DIR / "agent_runs.json"
    if runs.is_file() and (history := _load(runs)):
        last = history[-1]
        row.update(agent=last["agent"], model=last.get("model"), agent_runs=len(history),
                   elapsed_min=round(sum(r["elapsed_sec"] for r in history) / 60, 1),
                   cost_usd=round(sum(r.get("cost_usd") or 0 for r in history), 2) or None,
                   input_tokens=sum(r.get("input_tokens", 0) for r in history),
                   output_tokens=sum(r.get("output_tokens", 0) for r in history))
    if (work / "facts.verified.json").is_file():
        row["facts"] = _load(work / "facts.verified.json").get("check", {}).get("stats", {}).get("merged")
    if (ws / STATE_DIR / "extras_check.json").is_file():
        ec = _load(ws / STATE_DIR / "extras_check.json")
        row.update(extras_tables=ec["tables"], extras_cells=ec.get("cells"))
    row["valuation_runs"] = sum(1 for d in (ws / "runs").glob("*-valuation") if (d / "summary.json").is_file())
    if (work / "report" / "narrative.md").is_file():
        row["narrative_chars"] = len(re.sub(r"\s|<!--.*?-->", "", (work / "report" / "narrative.md").read_text(encoding="utf-8"), flags=re.S))
    if res["run_dir"]:
        run = ws / res["run_dir"]
        g = run / "commentary_guard.json"
        row["guard_ok"] = bool(g.is_file() and _load(g).get("ok"))
        fs = run / "valuation" / "forecast_summary.json"
        if fs.is_file():
            row["rating"] = (_load(fs).get("rating") or {}).get("rating")
        vr = (_load(run / "summary.json").get("valuation") or {}).get("value_range") or {}
        row["dcf_base"] = round(vr["base"], 2) if vr.get("base") is not None else None
        html_path = run / "report" / "report.html"
        if html_path.is_file():
            row["figures"] = len(re.findall(r'fno">图表 \d+', html_path.read_text(encoding="utf-8")))
            row["pages"] = len(list((run / "report" / "preview").glob("page*.png"))) or None
    return row


SCORE_COLUMNS = [("workspace", "工作区"), ("agent", "执行"), ("model", "模型"), ("stages_passed", "闸门/8"),
                 ("facts", "财务事实"), ("extras_cells", "经营数据格"), ("valuation_runs", "估值运行次数"),
                 ("guard_ok", "guard"), ("narrative_chars", "正文字数"), ("pages", "页数"), ("figures", "图表"),
                 ("rating", "评级"), ("dcf_base", "DCF 基准（元/股）"), ("elapsed_min", "耗时（分）"),
                 ("cost_usd", "费用（美元）"), ("input_tokens", "输入 token"), ("output_tokens", "输出 token")]


def scorecard_markdown(rows: list[dict[str, Any]]) -> str:
    def cell(v: Any) -> str:
        return "—" if v is None else ("✓" if v is True else "✗" if v is False else f"{v:,}" if isinstance(v, int) else str(v))
    lines = ["| " + " | ".join(t for _, t in SCORE_COLUMNS) + " |", "|" + "---|" * len(SCORE_COLUMNS)]
    lines += ["| " + " | ".join(cell(r.get(k)) for k, _ in SCORE_COLUMNS) + " |" for r in rows]
    unfinished = [f"- {r['workspace']}：{r['next']}" for r in rows if not r["done"]]
    note = ("\n\n指标都是客观计数，不代表研报质量高低；正文分析深度、论证是否成立需要人工阅读 PDF 判断。"
            "费用只有 Claude 的事件流提供。")
    return "\n".join(lines) + ("\n\n未完成：\n" + "\n".join(unfinished) if unfinished else "") + note + "\n"


def _workspace(arg: str | None) -> Path:
    ws = Path(arg).expanduser().resolve() if arg else PROJECT_ROOT
    if not (ws / META).is_file():
        raise SystemExit(f"{ws} 不是研报工作区（缺 {META}），用 --workspace 指定")
    return ws


def _in_workspace(cmd: str) -> None:
    if (PROJECT_ROOT / META).is_file():
        raise SystemExit(f"当前在工作区内，{cmd} 要在仓库里运行")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="finagent.report_pipeline", description="研报生成流水线（隔离工作区）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="搭建工作区")
    b.add_argument("--company", required=True)
    b.add_argument("--year", type=int, required=True)
    b.add_argument("--dest", help="工作区父目录，默认 ~/finagent-samples（或 FINAGENT_SAMPLES_DIR）")
    b.add_argument("--tag", help="工作区后缀；同一公司让不同模型各跑一遍时区分，如 opus / codex")
    b.add_argument("--pdf", help="年报路径，默认按 report/resources/ 查找")
    b.add_argument("--price", type=float, help="当前股价（元，外部数据）")
    b.add_argument("--price-source", help="股价来源（必填，若给 --price）")
    b.add_argument("--price-date", help="股价日期")
    b.add_argument("--peers", help="可比公司 CSV（外部数据）")
    b.add_argument("--allow-unverified", action="store_true", help="允许使用未进 manifest.json 的年报")
    b.add_argument("--force", action="store_true", help="工作区已存在时删除重建")
    for name in ("status", "run", "collect"):
        p = sub.add_parser(name)
        p.add_argument("--workspace", help="工作区目录（在工作区内运行可省略）")
        if name == "status":
            p.add_argument("--json", action="store_true")
        if name == "run":
            p.add_argument("--agent", choices=["claude", "codex", "deepseek"], default="claude")
            p.add_argument("--model", help="透传给 agent 的模型名")
            p.add_argument("--dry-run", action="store_true", help="只打印命令")
        if name == "collect":
            p.add_argument("--label", help="交付目录后缀，默认取工作区 tag")
            p.add_argument("--overwrite", action="store_true", help="覆盖仓库里已有的同名抽取目录")
            p.add_argument("--delivery-only", action="store_true", help="只收 PDF 与模型（测评对照时用，不覆盖抽取文件）")
            p.add_argument("--force", action="store_true", help="闸门未通过也收回")
    sc = sub.add_parser("scorecard", help="测评：多个工作区并排比较")
    sc.add_argument("--workspace", action="append", required=True, help="可多次指定")
    sc.add_argument("--json", action="store_true")
    sc.add_argument("--out", help="Markdown 表格另存路径")
    sub.add_parser("sync-skills", help="按 .claude/skills 更新仓库 .agents/skills 入口（Codex 等用）")
    args = ap.parse_args(argv)

    if args.cmd == "build":
        _in_workspace("build")
        ws = build(args.company, args.year, Path(args.dest).expanduser() if args.dest else None, pdf=args.pdf,
                   price=args.price, price_source=args.price_source, price_date=args.price_date, peers=args.peers,
                   tag=args.tag, allow_unverified=args.allow_unverified, force=args.force)
        print(f"工作区：{ws}")
        print("下一步：python -m finagent.report_pipeline run --agent claude|codex|deepseek --workspace "
              + json.dumps(str(ws), ensure_ascii=False)
              + "（或在 Claude Code / Codex 中打开该目录，把 TASK.md 的内容作为第一条消息）")
        return 0
    if args.cmd == "sync-skills":
        _in_workspace("sync-skills")
        for path in sync_agent_skills(PROJECT_ROOT):
            print(path.relative_to(PROJECT_ROOT))
        return 0
    if args.cmd == "scorecard":
        rows = [scorecard(_workspace(w)) for w in args.workspace]
        text = json.dumps(rows, ensure_ascii=False, indent=2) if args.json else scorecard_markdown(rows)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
        print(text)
        return 0
    ws = _workspace(args.workspace)
    if args.cmd == "status":
        res = status(ws)
        print(json.dumps(res, ensure_ascii=False, indent=2)) if args.json else _print_status(res)
        return 0 if res["done"] else 1
    if args.cmd == "run":
        _in_workspace("run")
        cmd = agent_command(args.agent, args.model, python=_load(ws / META)["python"])
        print("cd " + json.dumps(str(ws), ensure_ascii=False) + " && "
              + " ".join(json.dumps(x, ensure_ascii=False) for x in cmd))
        return 0 if args.dry_run else run_agent(ws, args.agent, args.model)
    _in_workspace("collect")
    label = args.label if args.label is not None else (_load(ws / META).get("tag") or "")
    print(json.dumps(collect(ws, label=label, overwrite=args.overwrite, force=args.force,
                             delivery_only=args.delivery_only), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
