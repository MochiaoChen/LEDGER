"""研报生成流水线：为一家公司搭建隔离工作区（sample），让模型在里面直接产出研报。

  python -m finagent.report_pipeline build     --company 恒瑞医药 --year 2025 [--tag opus] [--price 45.6 --price-source "..."]
  python -m finagent.report_pipeline run       --workspace <工作区> --agent claude|codex [--model ...] [--dry-run]
  python -m finagent.report_pipeline status    [--workspace <工作区>]           # 阶段闸门（工作区内可省略参数）
  python -m finagent.report_pipeline collect   --workspace <工作区> [--label Opus]  # 产物收回仓库
  python -m finagent.report_pipeline refine    --workspace <工作区> [--max-rounds 3]  # 生成 → 复核 → 质检循环，达标才交付
  python -m finagent.report_pipeline scorecard --workspace <A> --workspace <B>   # 测评：多个工作区并排比较
  python -m finagent.report_pipeline sync-skills                                 # 更新仓库 .agents/skills 入口

工作区只放两个 skill、计算引擎、这一家公司的年报和外部输入，目录结构与仓库一致（skill 里的相对路径照常可用），
不含其他公司的抽取文件、文稿、历史运行和交付物，也不在仓库目录树内（避免模型读到仓库或上级目录的
CLAUDE.md、原插件代码）。工作区说明写在 AGENTS.md（Codex 等直接读，CLAUDE.md 引用它），按阶段写明该读什么、
不该读什么，`status` 逐阶段核对闸门。skill 全文在 .claude/skills/，.agents/skills/ 下是指向它的入口。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .core.config import PROJECT_ROOT

SKILLS = ("finagent-research", "finagent-report", "finagent-review")
# 引擎里与研报无关的模块不进工作区
# evaluation 是质检（评分标准与评审提示），对生成方不可见
ENGINE_EXCLUDE = {"__pycache__", "evaluation"}
# skill 文档引用的格式样例（虚构公司，只作字段格式参考）
FORMAT_SAMPLES = ("data/samples/valuation_assumptions.json", "data/samples/peers.csv")
META = "sample.json"
STATE_DIR = ".pipeline"
AGENT_SKILLS = Path(".agents") / "skills"  # Codex 等读 .agents/skills 与 AGENTS.md
# Claude 执行时的默认分工：生成用 Opus，复核与质检用 Sonnet
PY_WRAPPER = "py.cmd" if os.name == "nt" else "./py"
GEN_MODEL = os.getenv("FINAGENT_GEN_MODEL", "claude-opus-5-5")
QC_MODEL = os.getenv("FINAGENT_QC_MODEL", "claude-sonnet-5-5")
# 资料搜集会话：先于一切分析，联网把年报之后的最新信息搜齐，写成资料包交给写作会话
RESEARCH_PROMPT = ("你是本工作区的研究助理，只做 AGENTS.md 阶段 1（资料搜集）：先读 "
                   ".claude/skills/finagent-report/references/research.md 第一部分，用 WebSearch / WebFetch 把年报之后的"
                   "最新信息搜齐，登记 sources.json 并写资料包 dossier.md。不做财务抽取、不写分析框架。"
                   f"结束运行 {PY_WRAPPER} -m finagent.report_pipeline status，阶段 1 通过后停止并汇报。"
                   f"命令直接以 {PY_WRAPPER} 开头，不加 cd、不串联。")
TASK_PROMPT = ("按本工作区 AGENTS.md 的流水线完成研报阶段 2～8（阶段 1 资料搜集已由研究助理完成，先读它写的 dossier.md）："
               f"每个阶段结束运行 {PY_WRAPPER} -m finagent.report_pipeline status，"
               f"文稿 guard 通过后停止并汇报（阶段 9 起由独立的复核会话完成）。命令直接以 {PY_WRAPPER} 开头，不加 cd、不串联。")
# 复核会话：不继承写作会话的上下文，以编辑身份读稿（finagent-review skill），再完成排版与交付
REVIEW_PROMPT = ("你是本工作区研报的复核编辑，没有参与写作。先读 .claude/skills/finagent-review/SKILL.md，"
                 f"按它完成 AGENTS.md 阶段 9（复核改写），再完成阶段 10～11；每个阶段结束运行 "
                 f"{PY_WRAPPER} -m finagent.report_pipeline status，全部闸门通过后停止并汇报。命令直接以 {PY_WRAPPER} 开头，不加 cd、不串联。")


# 工作区内允许的操作。未被信任的目录里 Claude Code 会忽略 settings.json 的 allow（deny 照常生效），
# 所以无头执行时同一份清单再经 --allowedTools 传入，不去改用户的全局信任配置
# 规则用通配写法：旧式 `前缀:*` 只在词边界匹配，`data/extractions/:*` 匹配不到 `data/extractions/<公司>/...`。
# 模板不用 cp 从 .claude/ 复制（Claude Code 会拒绝从配置目录复制），改用 report_pipeline template。
ALLOWED_TOOLS = (f"Bash({PY_WRAPPER} -m finagent *)", f"Bash({PY_WRAPPER} -m finagent.report_pipeline *)",
                 f"Bash({PY_WRAPPER} data/extractions/*)", f"Bash({PY_WRAPPER} -c *)",
                 "Bash(cp data/extractions/*)", "Bash(ls *)", "Bash(mkdir -p data/*)",
                 "Read", "Write(./data/**)", "Edit(./data/**)", "WebSearch", "WebFetch")
# 资料搜集闸门：各类别都要覆盖、检索量下限、近 RECENT_DAYS 天内发布的来源下限；补充调研的问题数下限
MIN_COLLECT_QUERIES, MIN_RECENT_SOURCES, RECENT_DAYS, MIN_FOLLOWUP = 20, 3, 90, 3


def agent_command(agent: str, model: str | None = None, prompt: str = TASK_PROMPT) -> list[str]:
    """无头执行命令。输出都是 JSONL 事件流，存进 .pipeline/agents/ 供测评读取用量。"""
    if agent == "claude":
        return ["claude", "-p", prompt, "--permission-mode", "acceptEdits",
                "--allowedTools", *ALLOWED_TOOLS, "--output-format", "stream-json", "--verbose",
                *(["--model", model] if model else [])]
    if agent == "codex":
        # 工作区不是 git 仓库；workspace-write 沙箱只允许写工作区与临时目录
        # tools.web_search 打开 Codex 的联网检索（外部调研阶段需要）
        return ["codex", "exec", "--full-auto", "--skip-git-repo-check", "--json", "-c", "tools.web_search=true",
                *(["-m", model] if model else []), prompt]
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
            "created_at": datetime.now().isoformat(timespec="seconds"), "as_of": f"{datetime.now():%Y-%m-%d}"}
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
    (ws / "REVIEW.md").write_text(REVIEW_PROMPT + "\n", encoding="utf-8")
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
    # report/resources/ 是年报原件；不能写成 report/**，否则会连带拦住 data/extractions/<公司>/report/（框架与文稿）
    locked = ("finagent/**", ".claude/**", ".agents/**", "report/resources/**", META, "py", "py.cmd", "CLAUDE.md", "AGENTS.md")
    return {"permissions": {
        "allow": list(ALLOWED_TOOLS),
        "deny": [f"Read(/{fence}/**)",
                 *(f"{tool}(./{p})" for p in locked for tool in ("Edit", "Write"))]}}


# ------------------------------------------------------------------ 工作区说明（CLAUDE.md）
def render_guide(meta: dict[str, Any]) -> str:
    c, y, key, py, pdf = meta["company"], meta["year"], meta["key"], "./py", meta["pdf"]
    work = f"data/extractions/{key}"
    market = meta["inputs"].get("market")
    price_line = (f"`inputs/market.json`：当前股价 {market['current_price']} 元，来源：{market['price_source']}"
                  f"（外部数据，写进假设文件的 `current_price` / `price_source`）"
                  if market else "**未提供股价。** 资料搜集阶段检索最近一个交易日收盘价，登记进 `sources.json`"
                  "（摘句含价格与日期），`price_source` 写“<发布方> <日期> 收盘，[S编号]”；查不到就停下写进交付说明，不能凭记忆填。")
    peers_line = ("`inputs/peers.csv`：可比公司（外部数据），估值命令加 `--peers inputs/peers.csv`"
                  if "peers" in meta["inputs"] else "未提供可比公司，不做相对估值。")
    source_line = ("已核验（`manifest.json` 有记录，SHA-256 一致）" if meta["verified_source"]
                   else "**未核验来源**（项目成员提供，官方链接与版本未核对），交付说明里要写明")
    if "招股" in Path(pdf).name:
        source_line += ("。**这是招股说明书，不是年报**：财务数据在“财务会计信息与管理层分析”一节，单位多为万元，"
                        "报告期为最近三年；公司是否已上市、最新股价与上市后的定期报告以资料搜集结果为准")
    return f"""# {c} {y} 年报深度研报 · 工作区流水线

本工作区由 `python -m finagent.report_pipeline build` 生成，只为 **{c} {y}** 一家公司出一份卖方体例深度研报（PDF）
和估值模型（xlsx）。按下面的阶段顺序做，每个阶段结束运行一次状态检查：

```bash
{py} -m finagent.report_pipeline status
```

它逐项核对闸门并告诉你下一步做什么、读哪份文档。上下文被压缩或中途接手时，**先跑 status，不要重读已完成阶段的文件**。

下文 `PY` = macOS/Linux 的 `./py`，Windows 的 `py.cmd`（均包装本机 Python）。**当前目录就是工作区**：命令直接以 `./py` 开头，
不要加 `cd`、不要写绝对路径、不要用 `&&` / 管道串联多条命令，否则无头执行时权限匹配不上会被拒。
在 Windows 上执行本页示例命令时，把 `./py` 替换成 `py.cmd`。

## 输入

| 文件 | 说明 |
|---|---|
| `{pdf}` | 年报原件，{source_line} |
| `{Path(pdf).parent.as_posix()}/locate.json` | 关键页定位（已跑好），先看它再按页读 PDF |
| {"`inputs/market.json`" if market else "—"} | {price_line} |
| {"`inputs/peers.csv`" if "peers" in meta["inputs"] else "—"} | {peers_line} |

skill 全文在 `.claude/skills/`（`.agents/skills/` 下只是指向它的入口），下文的 skill 文档路径都相对 `.claude/skills/`。

你的全部产出写在 `{work}/`（资料包、抽取、假设、框架、外部调研、文稿、编排脚本、复核清单、交付说明），程序运行目录在 `runs/`。

## 先搜集、后分析：年报之外的信息必须联网检索，不能用记忆

今天是 {meta.get("as_of") or meta["created_at"][:10]}，年报反映的是过去。**动笔分析之前先把最新信息搜齐**（阶段 1，由研究助理会话完成）：
年报之后的定期报告与业绩、股价与市值、卖方一致预期、可比公司估值、行业景气、竞争格局、近三个月的公司事件。
搜到的东西写进 `{work}/research/dossier.md`（资料包）与 `{work}/research/sources.json`，后面的分析框架、预测假设、
估值和文稿都要建立在资料包之上：例如最新半年报已经披露，预测首年就要与之衔接，不能只外推年报。

行业规模与增速、竞争格局与排名、产品价格与行业价格指数、同行数据、年报披露日之后的公司公告与事件、政策……
这些年报里没有的内容，**一律用 WebSearch / WebFetch 现查**，登记进 `{work}/research/sources.json` 才能写进研报。
你记忆里的数字和事件可能过时或记错，即使你很确定，也先去搜；搜不到的不写。

- 检索什么：阶段 1 按 `finagent-report/references/research.md` 第一部分的类别搜集；阶段 4 按 framework.md 的“外部调研清单”补充检索。
- 来源优先级：交易所与公司公告 > 政府与行业协会统计 > 知名研究机构与行业数据商 > 主流财经媒体；自媒体、论坛不用。
- 正文引用外部数字或判断时，句末加 `[S编号]`（guard 会核对外部数字带没带编号）；排名、份额、“龙头”“领先”这类判断没有来源就删掉。

## 文风由独立复核会话把关

写作前读 `finagent-research/references/writing.md`（分析链条、改写示例、优秀研报学习记录）。文稿写完、guard 通过后，
**由另一个会话按 `finagent-review` skill 做复核与可读性改写**（阶段 9）：它没有参与写作，以读者的眼光通读全文，
删去自证、圆场和机器腔，只删改措辞、不碰数字（数字锁）。执行写作的会话做到阶段 8 就停下。

**拿不准的内容怎么处理**：能自己判断的直接判断；拿不准又不重要的不写；拿不准但影响结论的（口径疑问、
外部数据矛盾、关键假设缺依据），写进 `{work}/report/review.md` 复核清单交给人工核对，**不要写进正文**。

## 读取边界（防止上下文浪费和信息污染）

- **不读**：`finagent/` 引擎源码（用命令和 `schema`，不看实现）、`data/samples/` 以外的样例（这里也没有）、
  `runs/` 下 JSON 的全文（用 `PY -c` 取需要的字段，或在编排脚本里用 `reportkit.core.Run` 读）、
  `preview/` 以外的渲染中间文件。工作区之外的任何目录都不要读。
- **skill 文档按阶段读**（见下表），不要一开始全部读完。skill 里提到的茅台样例、`tests/`、`data/extractions/贵州茅台_2025/`
  不在本工作区，不用找；`references/claims.md`、`commentary.md` 与本任务无关（不核查研报草稿，解读即研报正文）。
- **PDF 按页读**，每次不超过 20 页，只读 `locate.json` 的 `suggested_reads`、管理层讨论与分析、framework 需要的附注页。
  已抄进 facts / extras 的页不要再读。
- **不改** `finagent/`、`.claude/`、`report/`：引擎或 reportkit 不够用时，在公司编排脚本里绕开，并在交付说明里写明需要仓库改什么。

## 阶段

| # | 阶段 | 做什么 | 这时才读 | 闸门（status 检查） |
|---|---|---|---|---|
| 1 | 资料搜集（研究助理会话） | 先读年报首页与管理层讨论与分析的目录了解公司，再按 research.md 第一部分的七个类别联网搜集，登记 `{work}/research/sources.json`（问题标 `phase: collect` 与 `category`），写资料包 `{work}/research/dossier.md`；可比公司倍数齐全时按 `data/samples/peers.csv` 的列写 `{work}/research/peers.csv`；`PY -m finagent verify-sources --sources {work}/research/sources.json` | `finagent-report/references/research.md` 第一部分 | dossier.md 存在；verify-sources 为 `ok: true`；七个类别都覆盖；资料搜集检索 ≥ {MIN_COLLECT_QUERIES} 次；近 {RECENT_DAYS} 天内发布的来源 ≥ {MIN_RECENT_SOURCES} 个。**研究助理会话到此停止** |
| 2 | 财务抽取 | 先读 dossier.md。按 locate 读三大报表、主要会计数据、分季度、股本页，写 `{work}/facts.json` | `finagent-research/SKILL.md` 第 1–3 步，`references/extraction.md` | `PY -m finagent verify-facts --input {pdf} --year {y} --facts {work}/facts.json` 为 `ok: true` |
| 3 | 分析框架 | 通读管理层讨论与分析，结合 dossier.md 写 `{work}/report/framework.md`（投资主线、驱动清单、年报之后的变化、外部调研清单、披露局限、章节结构） | `finagent-report/SKILL.md` 一～三，`references/analysis.md` | 文件存在，含“外部调研清单” |
| 4 | 补充调研 | 资料包没回答、框架又需要的问题，按外部调研清单逐题检索，追加到同一个 sources.json（`phase: followup`）；verify-sources | `finagent-report/references/research.md` 第二部分 | verify-sources 为 `ok: true`，补充问题 ≥ {MIN_FOLLOWUP} 个 |
| 5 | 经营数据 | 按驱动清单逐格抄表到 `{work}/extras.json`，派生比率写 `ratios` | `references/extraction.md`“补充表格” | `PY -m finagent verify-extra --input {pdf} --extras {work}/extras.json` 为 `ok: true` |
| 6 | 估值假设 | 起草 `{work}/valuation_assumptions.json`：`status` 写明“观点/假设”，股价取 `inputs/market.json`（没有则取资料搜集登记的最新收盘价），每项假设写依据；**预测首年要与资料包里年报之后的最新业绩衔接**，依据里引用 `[S编号]` | `finagent-research/SKILL.md` 第 5 步“估值口径”，`data/samples/valuation_assumptions.json`（格式） | 文件存在，有 `current_price` 与 `price_source`，依据中引用了资料搜集的 `[S编号]` |
| 7 | 估值运行 | `PY -m finagent valuation --input {pdf} --year {y} --company {c} --assumptions {work}/valuation_assumptions.json --facts {work}/facts.json --extras {work}/extras.json --llm off`{" --peers inputs/peers.csv" if "peers" in meta["inputs"] else f" --peers {work}/research/peers.csv（资料搜集写了可比公司表时）"} | — | 最新运行目录成功，且晚于 facts / extras / 假设 / 可比公司表的修改，并带上了它们 |
| 8 | 文稿 | `PY -m finagent.report_pipeline template narrative.md {work}/report/narrative.md`，写完全部分析，年报之后的最新进展要写进去；`PY -m finagent guard --run-dir runs/<run_id> --text {work}/report/narrative.md --sources {work}/research/sources.json` | `references/sections.md`，`finagent-research/references/writing.md` | 最新运行目录的 guard 为 `ok: true`（数字与外部来源），且核对的就是当前文稿。**写作会话到此停止** |
| 9 | 复核改写（独立会话） | 按 `finagent-review` skill：备份初稿为 `{work}/report/narrative.draft.md`，以编辑身份通读改写，写 `{work}/report/edit_log.md` 与复核清单 `{work}/report/review.md`；`PY -m finagent numlock --before {work}/report/narrative.draft.md --after {work}/report/narrative.md`，再重跑阶段 8 的 guard | `finagent-review/SKILL.md` | 三个文件都存在，数字锁通过，guard 对改写稿通过 |
| 10 | 排版 | `PY -m finagent.report_pipeline template build_report.py {work}/report/build_report.py`，`Config.output_name` 设为 `{c}{datetime.now():%m%d}.pdf`；`PY {work}/report/build_report.py --run-dir runs/<run_id>`，看 `preview/sheet*.png` 自检 | `finagent-research/references/html-report.md` | PDF 晚于文稿和编排脚本 |
| 11 | 交付说明 | 写 `{work}/report/delivery.md`：PDF 路径、页数与图表数、核心结论、评级（取程序结果）、哪些是假设或外部数据、复核清单要点 | — | 文件存在 |

改了前面阶段的文件（如补抄 extras），status 会把后面的阶段标为过期：重跑估值、guard、排版。

## 底线（违反就返工）

1. 你不做算术：增速、占比、差值、估值都由程序算，正文照产物展示值抄。
2. 每个数字来自年报原文（带页码）、运行产物或 `sources.json` 登记的外部资料；正文必须过 guard。
   年报之外的事实不凭记忆写，先检索、登记、再引用。
3. 估值参数是你起草的观点/假设，必须标明；股价是外部数据，必须注明来源；评级取 `forecast_summary.rating`。
4. 校验 3 轮仍不过的问题不硬改数字，写进交付说明。
5. 研究助理会话只做阶段 1；写作会话做阶段 2～8；复核会话做阶段 9～11，全部闸门通过后停止，汇报 status 输出和交付说明，不要做额外的事。
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
    """verify-extra 结果按 extras、年报与校验代码的哈希缓存：三者都没变才复用，避免每次 status 都重新解析整份 PDF。"""
    import hashlib
    from .parsing import document
    from .tasks.financials import external, extras as extra_module

    cache = ws / STATE_DIR / "extras_check.json"
    digest = _sha256(extras)
    code_hash = hashlib.sha256(b"".join(Path(p).read_bytes() for p in
                                    (document.__file__, external.__file__, extra_module.__file__, __file__))).hexdigest()
    if (cache.is_file() and (c := _load(cache)).get("sha256") == digest
            and c.get("pdf_sha256") == meta["pdf_sha256"] and c.get("verifier_sha256") == code_hash):
        return c
    res = extra_module.verify_extras(document.load_document(str(ws / meta["pdf"])), _load(extras))
    out = {"sha256": digest, "pdf_sha256": meta["pdf_sha256"], "verifier_sha256": code_hash,
           "ok": not res["rejected"], "rejected": len(res["rejected"]),
           "tables": len(res["tables"]),
           "cells": sum(1 for t in res["tables"] for row in t["rows"] for v in row["values"] if v is not None)}
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def status(ws: Path) -> dict[str, Any]:
    meta = _load(ws / META)
    c, y, work = meta["company"], meta["year"], f"data/extractions/{meta['key']}"
    w = ws / work
    facts, verified, extras = w / "facts.json", w / "facts.verified.json", w / "extras.json"
    assumptions, framework = w / "valuation_assumptions.json", w / "report" / "framework.md"
    narrative, script, delivery = w / "report" / "narrative.md", w / "report" / "build_report.py", w / "report" / "delivery.md"
    sources, review = w / "research" / "sources.json", w / "report" / "review.md"
    draft, edit_log = w / "report" / "narrative.draft.md", w / "report" / "edit_log.md"
    dossier, peers_csv = w / "research" / "dossier.md", w / "research" / "peers.csv"
    stages: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str, todo: str) -> bool:
        stages.append({"stage": name, "ok": ok, "detail": detail, "next": "" if ok else todo})
        return ok

    from .output.sources import coverage, verify_sources
    src_data = _load(sources) if sources.is_file() else {}
    vs = verify_sources(src_data) if src_data else None
    cov = coverage(src_data, meta.get("as_of") or meta["created_at"][:10], RECENT_DAYS) if src_data else None
    # 1 资料搜集（先搜集、后分析）
    if not sources.is_file() or not dossier.is_file():
        add("1 资料搜集", False, "缺 " + "、".join(p.name for p in (sources, dossier) if not p.is_file()),
            "读 finagent-report/references/research.md 第一部分，按七个类别联网搜集，登记 sources.json、写 dossier.md")
    else:
        short = []
        if cov["missing"]:
            short.append("未覆盖 " + "、".join(cov["missing"]))
        if cov["n_collect_queries"] < MIN_COLLECT_QUERIES:
            short.append(f"检索 {cov['n_collect_queries']} 次 < {MIN_COLLECT_QUERIES}")
        if len(cov["recent"]) < MIN_RECENT_SOURCES:
            short.append(f"近 {RECENT_DAYS} 天来源 {len(cov['recent'])} 个 < {MIN_RECENT_SOURCES}")
        if not vs["ok"]:
            short.append(f"verify-sources {len(vs['problems'])} 处问题")
        add("1 资料搜集", not short, f"{cov['n_collect']} 个问题、{cov['n_collect_queries']} 次检索、"
            f"近 {RECENT_DAYS} 天来源 {len(cov['recent'])} 个" + ("；" + "；".join(short) if short else ""),
            "补齐：" + "；".join(short) if short else "")
    # 2 财务抽取
    if not facts.is_file():
        add("2 财务抽取", False, "facts.json 不存在",
            "读 finagent-research/SKILL.md 第 1–3 步与 references/extraction.md，按 locate.json 读页抽取")
    elif not verified.is_file() or _mtime(verified) < _mtime(facts):
        add("2 财务抽取", False, "facts.json 修改后未重新校验", "运行 verify-facts")
    else:
        chk = _load(verified).get("check", {})
        add("2 财务抽取", bool(chk.get("ok")),
            f"rejected {len(chk.get('rejected', []))}，conflicts {len(chk.get('conflicts', []))}，"
            f"勾稽失败 {len(chk.get('tieout_failures', []))}", "按 verify-facts 输出回原文修正（最多 3 轮）")
    # 3 分析框架
    fw_text = framework.read_text(encoding="utf-8") if framework.is_file() else ""
    add("3 分析框架", "外部调研清单" in fw_text,
        "framework.md " + ("已写" if "外部调研清单" in fw_text else "缺“外部调研清单”" if fw_text else "不存在"),
        "读 finagent-report/SKILL.md 一～三与 references/analysis.md，通读管理层讨论与分析后写 framework.md")
    # 4 补充调研（框架之后，针对资料包没回答的问题）
    if vs is None:
        add("4 补充调研", False, "research/sources.json 不存在", "先完成资料搜集")
    else:
        stale = _mtime(sources) < _mtime(framework)
        few = cov["n_followup"] < MIN_FOLLOWUP
        add("4 补充调研", vs["ok"] and not few and not stale,
            f"补充问题 {cov['n_followup']} 个，共 {vs['n_sources']} 个来源"
            + ("（不足）" if few else "") + ("（早于 framework.md，未按外部调研清单补查）" if stale else ""),
            "按 framework.md 的外部调研清单补充检索，问题标 phase: followup，追加进 sources.json")
    # 5 经营数据
    if not extras.is_file():
        add("5 经营数据", False, "extras.json 不存在", "按 framework.md 驱动清单抄表，读 extraction.md“补充表格”")
    else:
        ec = _extras_check(ws, meta, extras)
        add("5 经营数据", ec["ok"], f"{ec['tables']} 张表，拒收 {ec['rejected']} 格", "运行 verify-extra 并修正拒收项")
    # 6 估值假设
    if not assumptions.is_file():
        add("6 估值假设", False, "valuation_assumptions.json 不存在", "读 SKILL.md 第 5 步估值口径，按样例格式起草")
    else:
        a = _load(assumptions)
        miss = [k for k in ("current_price", "price_source") if a.get(k) in (None, "")]
        if not re.search(r"\[S\d+\]", assumptions.read_text(encoding="utf-8")):
            miss.append("依据中的资料搜集引用 [S编号]")
        add("6 估值假设", not miss, "缺 " + "、".join(miss) if miss else "已起草，依据引用了资料包",
            "股价取 inputs/market.json 或资料搜集登记的收盘价；预测首年与年报之后的最新业绩衔接，依据里写 [S编号]")
    # 7 估值运行
    run, man = _latest_run(ws, work)
    inputs_mtime = max(_mtime(facts), _mtime(extras), _mtime(assumptions), _mtime(peers_csv))
    if run is None:
        add("7 估值运行", False, "没有成功的 valuation 运行", "按 AGENTS.md 阶段 7 的命令运行")
    else:
        started = datetime.fromisoformat(man["started_at"]).timestamp()
        argv = man["config"]["argv"]
        stale = started < inputs_mtime
        no_extras = extras.is_file() and not _has_arg(argv, f"{work}/extras.json")
        no_peers = (peers_csv.is_file() and "peers" not in meta["inputs"]
                    and not _has_arg(argv, f"{work}/research/peers.csv"))
        add("7 估值运行", not (stale or no_extras or no_peers), f"runs/{run.name}"
            + ("（早于输入文件修改，已过期）" if stale else "") + ("（未带 --extras）" if no_extras else "")
            + ("（未带资料搜集的可比公司表 --peers）" if no_peers else ""),
            "重跑估值，后续阶段都用新的运行目录")
    # 8 文稿
    if not narrative.is_file() or run is None:
        add("8 文稿", False, "narrative.md 不存在" if not narrative.is_file() else "缺运行目录",
            "复制 templates/narrative.md，读 references/sections.md 与 writing.md 后写作")
    else:
        g, cm = run / "commentary_guard.json", run / "commentary.md"
        same = cm.is_file() and cm.read_text(encoding="utf-8") == narrative.read_text(encoding="utf-8")
        gr = _load(g) if g.is_file() else {}
        with_sources = bool(gr.get("sources")) or not sources.is_file()
        ok = gr.get("ok") and same and with_sources and _mtime(g) >= _mtime(sources)
        detail = ("guard 通过" if ok else "guard 未通过" if gr and same
                  else f"当前文稿未对 runs/{run.name} 跑 guard")
        if gr and same and not with_sources:
            detail = "guard 未带 --sources"
        add("8 文稿", bool(ok), detail, f"PY -m finagent guard --run-dir runs/{run.name} --text {work}/report/narrative.md"
            f" --sources {work}/research/sources.json")
    # 9 复核改写（独立会话）
    missing = [p.name for p in (draft, edit_log, review) if not p.is_file()]
    if missing:
        add("9 复核改写", False, "缺 " + "、".join(missing),
            "另开会话（REVIEW.md），按 finagent-review skill 复核改写")
    else:
        from .output.numlock import numlock
        lock = numlock(draft.read_text(encoding="utf-8"), narrative.read_text(encoding="utf-8"))
        add("9 复核改写", lock["ok"], f"数字锁{'通过' if lock['ok'] else '未通过'}，删去数字 {lock['removed']} 个"
            + (f"，新增 {'、'.join(lock['added'] + lock['new_sources'])}" if not lock["ok"] else ""),
            f"改写不得新增或改动数字：PY -m finagent numlock --before {work}/report/narrative.draft.md "
            f"--after {work}/report/narrative.md")
    # 10 排版
    pdf = run / "report" / "report.pdf" if run else None
    if pdf is None or not pdf.is_file():
        add("10 排版", False, "PDF 不存在", "复制 templates/build_report.py，读 references/html-report.md，渲染后看 preview")
    else:
        fresh = _mtime(pdf) >= max(_mtime(narrative), _mtime(script))
        named = [p.name for p in pdf.parent.glob("*.pdf") if p.name != "report.pdf"]
        add("10 排版", fresh and bool(named), f"runs/{run.name}/report/{named[0] if named else 'report.pdf'}"
            + ("" if fresh else "（早于文稿或脚本修改）") + ("" if named else "（未设 output_name）"),
            "重新渲染；Config.output_name 设为公司名+日期")
    # 11 交付说明
    add("11 交付说明", delivery.is_file(), "delivery.md " + ("已写" if delivery.is_file() else "不存在"),
        "写交付说明：结论、评级、假设与外部数据、复核清单要点")

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
            review = src_work / "report" / "review.md"
            if review.is_file():
                shutil.copy2(review, dst / "复核清单.md")
            out["delivery"] = str(dst.relative_to(root))
    return out


# ------------------------------------------------------------------ run（无头）
RESEARCH_STAGES = 1  # 阶段 1 由研究助理会话完成（先搜集、后分析）
WRITE_STAGES = 8  # 阶段 2～8 由写作会话完成，之后交给独立的复核会话


def _research_done(ws: Path) -> bool:
    return all(st["ok"] for st in status(ws)["stages"][:RESEARCH_STAGES])


def _writing_done(ws: Path) -> bool:
    return all(st["ok"] for st in status(ws)["stages"][:WRITE_STAGES])


def _role_model(agent: str, role: str, model: str | None, review_model: str | None = None) -> str | None:
    """Claude 默认分工：写作用 GEN_MODEL，复核用 QC_MODEL；显式指定的模型优先。其他 agent 用其默认模型。"""
    if role in ("research", "write"):
        return model or (GEN_MODEL if agent == "claude" else None)
    return review_model or model or (QC_MODEL if agent == "claude" else None)


def run_agent(ws: Path, agent: str, model: str | None = None, review_model: str | None = None) -> int:
    """无头执行三个会话，彼此不继承上下文：研究助理（阶段 1 资料搜集）→ 写作（阶段 2～8）→ 复核（阶段 9～11）。
    已完成的部分不重跑。"""
    code = 0
    if not _research_done(ws):
        code = _session(ws, agent, _role_model(agent, "research", model), "research", RESEARCH_PROMPT)
        if not _research_done(ws):
            print("资料搜集未通过，不进入写作会话；运行 status 查看缺什么。")
            return code or 1
    if not _writing_done(ws):
        code = _session(ws, agent, _role_model(agent, "write", model), "write", TASK_PROMPT)
        if not _writing_done(ws):
            print("写作阶段未全部通过，不进入复核会话；运行 status 查看卡在哪一步。")
            return code or 1
    if not status(ws)["done"]:
        code = _session(ws, agent, _role_model(agent, "review", model, review_model), "review", REVIEW_PROMPT)
    return code


def _session(ws: Path, agent: str, model: str | None, role: str, prompt: str) -> int:
    """在工作区里无头执行一个会话；事件流原样存 .pipeline/agents/<时间>-<agent>-<role>.jsonl，运行记录追加到 agent_runs.json。"""
    cmd = agent_command(agent, model, prompt)
    if shutil.which(cmd[0]) is None:
        raise SystemExit(f"找不到 {cmd[0]} 命令行，先安装并登录")
    logs = ws / STATE_DIR / "agents"
    logs.mkdir(parents=True, exist_ok=True)
    started = datetime.now()
    log = logs / f"{started:%Y%m%d-%H%M%S}-{agent}-{role}.jsonl"
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
    record = {"agent": agent, "model": model, "role": role, "started_at": started.isoformat(timespec="seconds"),
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
    return {**out, **tokens}


# ------------------------------------------------------------------ refine（生成 → 复核 → 质检循环）
FIX_PROMPT = ("上一轮质检发现了需要回到写作阶段处理的问题，见 {issues}。按本工作区 AGENTS.md 修改对应阶段的产物"
              "（需要补数据、改假设就重跑估值，文稿改完重跑 guard）；处理不了的写进 {work}/report/review.md 并说明原因。"
              "阶段 1～8 全部通过后停止并汇报，阶段 9 起由复核会话完成。命令直接以 ./py 开头，不加 cd、不串联。")
REVISE_PROMPT = ("你是本工作区研报的复核编辑，没有参与写作。先读 .claude/skills/finagent-review/SKILL.md，再读质检问题单 "
                 "{issues} 逐条处理：只改措辞、结构与编排，数字锁照常（{work}/report/narrative.draft.md 是初稿，不要覆盖）；"
                 "需要补数字或改结论的写进 {work}/report/review.md。改完重跑 guard 与数字锁，重新渲染 PDF（阶段 10），"
                 "更新交付说明（阶段 11）；每个阶段结束运行 ./py -m finagent.report_pipeline status，全部闸门通过后停止。"
                 "命令直接以 ./py 开头，不加 cd、不串联。")
SNAPSHOT_FILES = ("narrative.md", "narrative.draft.md", "edit_log.md", "review.md", "delivery.md")


def _rounds_dir(ws: Path) -> Path:
    return ws / STATE_DIR / "rounds"


def _snapshot(ws: Path, n: int) -> dict[str, Any]:
    """本轮交付物存档（文稿、复核文件、PDF），供回滚到最佳一轮。"""
    meta, st = _load(ws / META), status(ws)
    report = ws / "data" / "extractions" / meta["key"] / "report"
    snap = _rounds_dir(ws) / str(n) / "snapshot"
    snap.mkdir(parents=True, exist_ok=True)
    for name in SNAPSHOT_FILES:
        if (report / name).is_file():
            shutil.copy2(report / name, snap / name)
    pdfs = []
    if st["run_dir"] and (ws / st["run_dir"] / "report").is_dir():
        for pdf in (ws / st["run_dir"] / "report").glob("*.pdf"):
            shutil.copy2(pdf, snap / pdf.name)
            pdfs.append(pdf.name)
    return {"run_dir": st["run_dir"], "pdfs": pdfs,
            "narrative_sha256": _sha256(report / "narrative.md") if (report / "narrative.md").is_file() else None}


def _restore(ws: Path, n: int, info: dict[str, Any]) -> bool:
    """回滚到第 n 轮。估值运行目录变了（中间重跑过估值）就不回滚，只在 loop.json 里指明最佳一轮。"""
    st = status(ws)
    if st["run_dir"] != info["run_dir"]:
        return False
    meta = _load(ws / META)
    report = ws / "data" / "extractions" / meta["key"] / "report"
    snap = _rounds_dir(ws) / str(n) / "snapshot"
    for name in SNAPSHOT_FILES:
        if (snap / name).is_file():
            shutil.copy2(snap / name, report / name)
    for name in info["pdfs"]:  # PDF 最后复制，保持“PDF 晚于文稿”
        shutil.copy2(snap / name, ws / info["run_dir"] / "report" / name)
    return True


def _stop_reason(rounds: list[dict[str, Any]], max_rounds: int, min_gain: float) -> str | None:
    last = rounds[-1]
    if last["deliverable"]:
        return "达到交付标准"
    if len(rounds) >= max_rounds:
        return f"达到最大轮数 {max_rounds}"
    totals = [r["total"] for r in rounds]
    if len(totals) >= 3 and totals[-1] - totals[-2] < min_gain and totals[-2] - totals[-3] < min_gain:
        return f"连续两轮提升不足 {min_gain} 分"
    if not last["issues"]["generator"] and not last["issues"]["reviewer"]:
        return "没有可回传的问题"
    return None


def refine(ws: Path, *, max_rounds: int = 3, min_gain: float = 2.0, gen_model: str | None = None,
           qc_model: str | None = None, rubric: str | None = None) -> dict[str, Any]:
    """多 Agent 循环：Generator（写作会话）→ Reviewer（复核会话）→ Evaluator（盲评会话）。
    三者都是独立的 Claude Code 会话，只靠文件交接。未达交付标准时，问题单按路由回传：
    数据与假设类回到 Generator（重跑写作阶段，复核从头再来），措辞与结构类交给 Reviewer 修订。
    每轮存档；结束时回滚到得分最高的一轮。问题单只含理由与证据，评分标准对生成方不可见。"""
    from .evaluation import judge
    from .evaluation.__main__ import evaluate, issues_markdown
    from .evaluation.rubric import bundle_from_workspace

    gen_model, qc_model = gen_model or GEN_MODEL, qc_model or QC_MODEL
    meta = _load(ws / META)
    work = f"data/extractions/{meta['key']}"
    # 评测结果（含条目与分值）放在工作区之外，生成方读不到；回传给它的只有问题单
    eroot = judge.default_root() / ws.name
    eroot.mkdir(parents=True, exist_ok=True)
    path = eroot / "loop.json"
    state = _load(path) if path.is_file() else {"rounds": [], "best": None, "stopped": None}
    state.update(max_rounds=max_rounds, min_gain=min_gain, gen_model=gen_model, qc_model=qc_model)
    if state["rounds"] and (reason := _stop_reason(state["rounds"], max_rounds, min_gain)):
        state["stopped"] = reason
        return state

    for n in range(len(state["rounds"]) + 1, max_rounds + 1):
        if n == 1:
            run_agent(ws, "claude", gen_model, qc_model)
        else:
            prev = _rounds_dir(ws) / str(n - 1)
            prev.mkdir(parents=True, exist_ok=True)
            issues = json.loads((eroot / f"r{n - 1}" / "eval" / "issues.json").read_text(encoding="utf-8"))
            to_gen = [i for i in issues if i["route"] == "generator"]
            to_rev = [i for i in issues if i["route"] == "reviewer"]
            rev_file = prev / "issues-reviewer.md"
            rev_file.write_text(issues_markdown(to_rev), encoding="utf-8")
            rev_rel = rev_file.relative_to(ws).as_posix()
            if to_gen:
                gen_file = prev / "issues-generator.md"
                gen_file.write_text(issues_markdown(to_gen), encoding="utf-8")
                for name in ("narrative.draft.md", "edit_log.md"):  # 文稿要重写，复核从头再来
                    (ws / work / "report" / name).unlink(missing_ok=True)
                _session(ws, "claude", gen_model, "fix",
                         FIX_PROMPT.format(issues=gen_file.relative_to(ws).as_posix(), work=work))
                if _writing_done(ws):
                    prompt = REVIEW_PROMPT + (f"另读质检问题单 {rev_rel} 逐条处理。" if to_rev else "")
                    _session(ws, "claude", qc_model, "review", prompt)
            else:
                _session(ws, "claude", qc_model, "revise", REVISE_PROMPT.format(issues=rev_rel, work=work))

        rdir = eroot / f"r{n}"
        st = status(ws)
        if not st["done"]:  # 交付物不全时盲评没有意义：停下，把卡住的闸门交给人
            state["stopped"] = f"第 {n} 轮闸门未通过：{st['next']}"
            print(state["stopped"])
            break
        sc = evaluate(bundle_from_workspace(ws), rdir / "eval", rubric_path=rubric, model=qc_model,
                      blind_dir=rdir / "blind")
        issues = json.loads((rdir / "eval" / "issues.json").read_text(encoding="utf-8"))
        state["rounds"].append({
            "round": n, "total": sc["total"], "deliverable": sc["deliverable"],
            "not_deliverable_reasons": sc["not_deliverable_reasons"],
            "stages_passed": sum(s["ok"] for s in st["stages"]),
            "issues": {r: sum(i["route"] == r for i in issues) for r in ("generator", "reviewer")},
            "snapshot": _snapshot(ws, n), "finished_at": datetime.now().isoformat(timespec="seconds")})
        state["best"] = max(state["rounds"], key=lambda r: r["total"])["round"]
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"第 {n} 轮：总分 {sc['total']}，{'达到' if sc['deliverable'] else '未达'}交付标准")
        if reason := _stop_reason(state["rounds"], max_rounds, min_gain):
            state["stopped"] = reason
            break

    if not state["rounds"]:
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return state
    best = next(r for r in state["rounds"] if r["round"] == state["best"])
    last = state["rounds"][-1]
    if best is not last:
        state["restored"] = _restore(ws, best["round"], best["snapshot"])
    if not best["deliverable"]:  # 未达标也交付最佳版本，未解决的问题交给人工
        review = ws / work / "report" / "review.md"
        issues_md = (eroot / f"r{best['round']}" / "eval" / "issues.md").read_text(encoding="utf-8")
        with review.open("a", encoding="utf-8") as f:
            f.write(f"\n\n## 质检循环未达交付标准（最佳第 {best['round']} 轮，总分 {best['total']}）\n\n"
                    + issues_md.split("\n", 4)[-1])
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    return state


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
    if (work / "research" / "sources.json").is_file():
        from .output.sources import verify_sources
        sc = verify_sources(_load(work / "research" / "sources.json"))
        row.update(web_queries=sc["n_queries"], web_sources=sc["n_sources"])
    if (work / "report" / "narrative.md").is_file():
        text = (work / "report" / "narrative.md").read_text(encoding="utf-8")
        row["narrative_chars"] = len(re.sub(r"\s|<!--.*?-->", "", text, flags=re.S))
        draft = work / "report" / "narrative.draft.md"
        if draft.is_file():  # 复核会话删改的篇幅：初稿与终稿字数差
            row["draft_chars"] = len(re.sub(r"\s|<!--.*?-->", "", draft.read_text(encoding="utf-8"), flags=re.S))
        row["citations"] = len(set(re.findall(r"\[S\d+\]", text)))
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


SCORE_COLUMNS = [("workspace", "工作区"), ("agent", "执行"), ("model", "模型"), ("stages_passed", "闸门/11"),
                 ("facts", "财务事实"), ("extras_cells", "经营数据格"), ("valuation_runs", "估值运行次数"),
                 ("web_queries", "检索次数"), ("web_sources", "外部来源"), ("citations", "正文引用来源"),
                 ("guard_ok", "guard"), ("draft_chars", "初稿字数"), ("narrative_chars", "终稿字数"), ("pages", "页数"), ("figures", "图表"),
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


TEMPLATES = Path(".claude") / "skills" / "finagent-report" / "templates"


def copy_template(ws: Path, name: str, dest: str, *, force: bool = False) -> Path:
    """把 finagent-report 的模板复制到工作区 data/ 下（模型不能用 cp 从 .claude/ 复制）。已存在不覆盖。"""
    src = ws / TEMPLATES / name
    if not src.is_file() or src.parent.resolve() != (ws / TEMPLATES).resolve():
        raise SystemExit(f"没有模板 {name}；可用：{'、'.join(sorted(p.name for p in (ws / TEMPLATES).iterdir()))}")
    target = (ws / dest).resolve()
    if (ws / "data").resolve() not in target.parents:
        raise SystemExit("模板只能复制到 data/ 下")
    if target.exists() and not force:
        raise SystemExit(f"{dest} 已存在，未覆盖（确需重来加 --force）")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
    return target


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
    for name in ("status", "run", "collect", "refine"):
        p = sub.add_parser(name)
        p.add_argument("--workspace", help="工作区目录（在工作区内运行可省略）")
        if name == "status":
            p.add_argument("--json", action="store_true")
        if name == "run":
            p.add_argument("--agent", choices=["claude", "codex"], default="claude")
            p.add_argument("--model", help=f"透传给 agent 的模型名；Claude 默认写作 {GEN_MODEL}、复核 {QC_MODEL}")
            p.add_argument("--review-model", help="复核会话单独指定模型")
            p.add_argument("--dry-run", action="store_true", help="只打印命令")
        if name == "collect":
            p.add_argument("--label", help="交付目录后缀，默认取工作区 tag")
            p.add_argument("--overwrite", action="store_true", help="覆盖仓库里已有的同名抽取目录")
            p.add_argument("--delivery-only", action="store_true", help="只收 PDF 与模型（测评对照时用，不覆盖抽取文件）")
            p.add_argument("--force", action="store_true", help="闸门未通过也收回")
        if name == "refine":
            p.add_argument("--max-rounds", type=int, default=3)
            p.add_argument("--min-gain", type=float, default=2.0, help="连续两轮提升都低于此分数即停止")
            p.add_argument("--gen-model", help=f"生成模型，默认 {GEN_MODEL}（FINAGENT_GEN_MODEL）")
            p.add_argument("--qc-model", help=f"复核与质检模型，默认 {QC_MODEL}（FINAGENT_QC_MODEL）")
            p.add_argument("--rubric", help="评分标准，默认 eval/rubrics/report_v0.json")
    sc = sub.add_parser("scorecard", help="测评：多个工作区并排比较")
    sc.add_argument("--workspace", action="append", required=True, help="可多次指定")
    sc.add_argument("--json", action="store_true")
    sc.add_argument("--out", help="Markdown 表格另存路径")
    sub.add_parser("sync-skills", help="按 .claude/skills 更新仓库 .agents/skills 入口（Codex 等用）")
    tp = sub.add_parser("template", help="工作区内：把 finagent-report 模板复制到 data/ 下")
    tp.add_argument("name", help="模板文件名，如 narrative.md、build_report.py")
    tp.add_argument("dest", help="目标路径（相对工作区，须在 data/ 下）")
    tp.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "build":
        _in_workspace("build")
        ws = build(args.company, args.year, Path(args.dest).expanduser() if args.dest else None, pdf=args.pdf,
                   price=args.price, price_source=args.price_source, price_date=args.price_date, peers=args.peers,
                   tag=args.tag, allow_unverified=args.allow_unverified, force=args.force)
        print(f"工作区：{ws}")
        print("下一步：python -m finagent.report_pipeline run --agent claude --workspace "
              + json.dumps(str(ws), ensure_ascii=False)
              + "（或在 Claude Code / Codex 中打开该目录，把 TASK.md 的内容作为第一条消息；"
              "写作完成后另开一个新会话，把 REVIEW.md 的内容作为第一条消息）")
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
    if args.cmd == "template":
        print(copy_template(_workspace(None), args.name, args.dest, force=args.force))
        return 0
    ws = _workspace(args.workspace)
    if args.cmd == "status":
        res = status(ws)
        print(json.dumps(res, ensure_ascii=False, indent=2)) if args.json else _print_status(res)
        return 0 if res["done"] else 1
    if args.cmd == "run":
        _in_workspace("run")
        for role, key, prompt in (("写作会话", "write", TASK_PROMPT), ("复核会话", "review", REVIEW_PROMPT)):
            cmd = agent_command(args.agent, _role_model(args.agent, key, args.model, args.review_model), prompt)
            print(f"# {role}\ncd " + json.dumps(str(ws), ensure_ascii=False) + " && "
                  + " ".join(json.dumps(x, ensure_ascii=False) for x in cmd))
        return 0 if args.dry_run else run_agent(ws, args.agent, args.model, args.review_model)
    if args.cmd == "refine":
        _in_workspace("refine")
        state = refine(ws, max_rounds=args.max_rounds, min_gain=args.min_gain, gen_model=args.gen_model,
                       qc_model=args.qc_model, rubric=args.rubric)
        print(json.dumps({k: state.get(k) for k in ("best", "stopped", "restored")}
                         | {"rounds": [{k: r[k] for k in ("round", "total", "deliverable", "issues")}
                                       for r in state["rounds"]]}, ensure_ascii=False, indent=2))
        return 0
    _in_workspace("collect")
    label = args.label if args.label is not None else (_load(ws / META).get("tag") or "")
    print(json.dumps(collect(ws, label=label, overwrite=args.overwrite, force=args.force,
                             delivery_only=args.delivery_only), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
