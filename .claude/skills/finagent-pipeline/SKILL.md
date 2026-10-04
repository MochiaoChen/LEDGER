---
name: finagent-pipeline
description: 研报生成流水线与模型测评入口：为一家 A 股公司搭隔离工作区，交给无头 Claude Code 或 Codex 按阶段产出深度研报 PDF 与估值模型，查闸门、收回仓库；也可让多个模型各跑同一家公司并出对比表。用户要“给某公司出研报 / 跑研报流水线 / 让 Claude 和 Codex 比一比 / 测评研报生成”时使用。
---

# FinAgent 研报流水线（入口）

本 skill 不自己写研报，只负责编排：搭工作区 → 交给执行模型 → 查闸门 → 收回 → 测评。
研报怎么写在工作区里的 `finagent-research`、`finagent-report` 两个 skill 和工作区 `AGENTS.md` 里，**你不需要读它们**。

在仓库根目录执行命令。`PY` 为仓库虚拟环境的解释器（macOS / Linux `.venv/bin/python`）。

## 为什么要隔离工作区

仓库里有其他公司的抽取、文稿、交付物和对照稿，上级目录还有原插件代码。模型在仓库里直接写研报，会把这些读进上下文：
浪费上下文，也会照抄别家的分析框架。工作区只有两个 skill、计算引擎、这一家公司的年报和人给的外部输入，
建在仓库目录树之外。

## 一、出一份研报

### 1. 确认输入（问用户，不要自己找或编）

| 输入 | 必需 | 说明 |
|---|---|---|
| 公司、年度 | 是 | 年报默认取 `report/resources/<公司>/` 下的 PDF，也可 `--pdf` 指定 |
| 当前股价与来源 | 估值需要 | 外部数据，`--price` 与 `--price-source` 必须同时给；没有就不给，执行模型会在资料搜集阶段联网检索收盘价并登记来源 |
| 可比公司 CSV | 否 | `--peers`，格式见 `data/samples/peers.csv` |
| 未核验来源 | — | 年报不在 `report/resources/manifest.json` 里时，需用户同意后加 `--allow-unverified` |

### 2. 搭工作区

```bash
PY -m finagent.report_pipeline build --company <公司> --year <年度> --price <股价> --price-source "<来源>" [--tag <标签>]
```

默认建在 `~/finagent-samples/<公司>_<年度>[_<标签>]`（`--dest` 可改，不能在仓库目录树内）。

### 3. 执行

**默认交给无头执行**（干净上下文，你只看结果）：

```bash
PY -m finagent.report_pipeline run --workspace <工作区> --agent claude
```

`--agent codex` 用 Codex CLI（需已安装登录）；`--model` 透传模型名。Claude 默认分工：写作会话用 Opus（`FINAGENT_GEN_MODEL`），
复核会话用 Sonnet（`FINAGENT_QC_MODEL`）。一份研报通常要跑很久，放后台执行，
不要轮询，结束后再看。事件流存在工作区 `.pipeline/agents/`，用量记在 `.pipeline/agent_runs.json`。

**要质检达标再交付时用 `refine`**（多 Agent 循环）：

```bash
PY -m finagent.report_pipeline refine --workspace <工作区> [--max-rounds 3]
```

生成（Opus）→ 复核（Sonnet）→ 盲评质检（Sonnet，在工作区之外的目录里只看交付物，按 `eval/rubrics/report_v0.json` 打分）。
未达交付标准时把问题单按路由回传：数据与假设类回到写作会话，措辞与结构类交给复核会话；达标、满轮数或连续两轮提升不足即停止，
回滚到得分最高的一轮，未解决的问题追加进 `review.md`。评分结果与 `loop.json` 在 `~/finagent-evals/<工作区名>/`，
**不要把评分标准或分数告诉工作区里的会话**。

也可以由人在 Claude Code 或 Codex 里直接打开工作区目录，把 `TASK.md` 的内容作为第一条消息。
**不要在当前会话里自己进入工作区写研报**：你的上下文已经有仓库内容，正是隔离要避免的。

### 4. 查闸门

```bash
PY -m finagent.report_pipeline status --workspace <工作区>
```

11 个阶段：**资料搜集**（先搜集、后分析：联网搜齐年报之后的最新业绩、行情、卖方预期、可比公司、行业、竞争、近期事件，
写资料包 `research/dossier.md`）→ 财务抽取 → 分析框架 → 补充调研 → 经营数据 → 估值假设（须引用资料包）→ 估值运行 →
文稿（guard：数字与外部来源）→ 复核改写 → 排版 → 交付说明。`run` 依次起三个**互不继承上下文**的会话：
研究助理（Opus，阶段 1）→ 写作（Opus，阶段 2～8）→ 复核（Sonnet，`finagent-review` skill：编辑身份通读改写、数字锁、
`review.md` 复核清单，并完成排版与交付）。
未全部通过时，把 `下一步` 和工作区 `data/extractions/<公司>_<年度>/report/delivery.md`（如有）转告用户，
由用户决定是再 `run` 一次（会接着已完成的阶段做）还是人工介入。不要绕过闸门。

### 5. 收回仓库

```bash
PY -m finagent.report_pipeline collect --workspace <工作区> [--label Opus]
```

抽取、外部调研与文稿 → `data/extractions/<公司>_<年度>/`，运行目录 → `runs/`，PDF、模型与复核清单 → `report/交付/<MMDD> <公司> <标签>/`。
仓库已有同名抽取目录时需用户确认后加 `--overwrite`。收回后按仓库 CLAUDE.md 跑测试；是否提交由用户决定。

向用户汇报：交付目录、页数与图表数、评级与估值区间（取 `scorecard`）、哪些是假设或外部数据、`delivery.md` 里的未解决问题，以及复核清单（`复核清单.md`）里需要人工核对的事项。

## 二、测评：多个模型跑同一家公司

1. 每个执行方各搭一个工作区，输入完全相同，只换 `--tag`：

   ```bash
   PY -m finagent.report_pipeline build --company <公司> --year <年度> --price <股价> --price-source "<来源>" --tag opus
   ```

   ```bash
   PY -m finagent.report_pipeline build --company <公司> --year <年度> --price <股价> --price-source "<来源>" --tag codex
   ```

2. 分别 `run --agent claude` / `run --agent codex`（可同时在后台跑）。
3. 出对比表：

   ```bash
   PY -m finagent.report_pipeline scorecard --workspace <工作区A> --workspace <工作区B> --out <对比.md>
   ```

   列出闸门通过数、财务事实与经营数据规模、估值迭代次数、检索次数与外部来源数、正文引用来源数、guard、
   初稿与终稿字数（复核会话删改了多少）、页数、图表数、评级、DCF 基准值、
   耗时、token 与费用。
4. 收回交付物做人工对比：`collect --delivery-only`（只收 PDF 与模型，不覆盖抽取文件），交付目录按标签区分。

解读对比表时注意：

- 这些都是客观计数，**不代表研报质量**。篇幅、图表多不等于分析好；分析深度、论证是否成立要人读 PDF 判断。
- 输入（年报、股价、可比公司）必须相同，否则估值结论不可比。
- 评级和 DCF 不同，通常来自执行模型起草的估值假设不同：对比两边的 `valuation_assumptions.json`，不要直接说谁对。
- 未通过全部闸门的一方，其后续指标不可信，对比表里会列出卡在哪一步。

## 文件

```
finagent/report_pipeline.py      build / run / refine / status / collect / scorecard / sync-skills
finagent/evaluation/             研报质检：程序检查 + 盲评会话 + 计分（python -m finagent.evaluation run / score / compare）
eval/rubrics/                    评分标准与说明（不进工作区）
工作区/AGENTS.md                 分阶段说明（CLAUDE.md 只引用它），读取边界、闸门
工作区/.claude/settings.json     Claude Code 权限：禁读仓库与上级目录，禁改引擎与 skill（Codex 靠自身沙箱）
.agents/skills/                  Codex 等的 skill 入口，正文指向 .claude/skills/；改 skill 描述后跑 sync-skills
```
