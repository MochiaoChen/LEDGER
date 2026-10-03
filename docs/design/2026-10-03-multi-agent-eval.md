# FinAgent 下一阶段设计：评测体系 · Multi-Agent · Harness · 前端

> 2026-10-03 · v2：已按拍板结果实现 v0（见第 6、7 节）。初赛截止 2026-10-18，决赛 11 月底。

## 0. 一页结论

| 模块 | 方案 | 初赛前要做到 |
|---|---|---|
| 评测体系 | 两条思路合成一套四层 Rubric：L0 硬闸门（程序）→ L1 数据闭合（程序）→ L2 分析质量（Sonnet 二元判定）→ L3 表达与合规（Sonnet）。思路一按卖方研报体例用模型知识拆解 | **已实现**：`eval/rubrics/report_v0.json` + `finagent/evaluation/`，三家公司各评一遍 |
| Multi-Agent | 编排器用确定性 Python，三个 Claude Code 会话：Generator（Opus 5.5）/ Reviewer（Sonnet）/ Evaluator（Sonnet），只通过文件交接 | **已实现**：`report_pipeline refine`，用模拟会话测过路由与回滚，尚未真跑一整轮 |
| Harness | 只用 Claude Code（`claude -p` 无头），走本机订阅；PR #16 的 DeepSeek 执行器不作默认。提交用的简版配置包后面再弄 | **已实现**：`scripts/setup.sh` / `setup.ps1` + `python -m finagent.doctor` |
| 前端 | FastAPI 薄后端包 CLI + SSE 推事件流；前端先 Streamlit 出演示，再换 React | 只出架构，不写代码（决赛前做） |

## 1. 评测体系

### 1.1 边界

- 不使用之前那套“拆解参考研报提取关键点”的方法与材料（NDA）。沿用的只是通用骨架：**Rubric 逐条二元判定 → 程序计分 → 校准评测器本身**。
- 评测对象是我们流水线产出的**完整交付物**：研报 PDF/`narrative.md`、`model.xlsx`、真值表、`sources.json`、`review.md`。
- 定位是内部质控与模型对比，不作为选题 7 的参赛内容（CLAUDE.md 选题范围不变）。

### 1.2 思路一：从已有研报拆“好研报关心什么”

目标是得到一份**行业无关**的“研报关心的核心问题”题库，而不是对着某篇参考研报逐条对答案。

做法：

1. **选样**：10～15 篇公开的 A 股深度报告，覆盖消费、制造、周期、医药、科技至少 5 个行业、3 家以上券商。只读不入库（版权），仓库里只存我们拆出来的结构化结果。
2. **按段落问“这一段在回答什么问题”**：Claude 逐段标注 `{问题, 证据类型(数据/图表/类比/管理层表述), 是否定量链条, 位置}`。问题写成通用形式，例如“核心驱动的量价拆分是什么”，不写“白酒吨价”。
3. **聚类成题库**：跨报告合并同义问题，统计出现频次（几篇报告问了）和篇幅占比。
4. **转成 Rubric 条目**：高频且决定结论的问题进 L2；每条改写成可二元判定的形式，并写清“通过 / 不通过”的判定标准与示例。
5. **权重**：频次 × 对结论的重要性（人工定 1/2/3 档），归一化到 L2 总分。

预期得到的核心问题（基于卖方研报常规体例的先验，待样本验证）：

| 维度 | 研报通常回答的问题 |
|---|---|
| 投资逻辑 | 一句话核心结论是什么；与市场分歧在哪里（预期差） |
| 商业模式 | 卖什么、卖给谁、靠什么赚钱、竞争壁垒 |
| 驱动拆解 | 收入/利润由哪几个驱动决定；量、价、结构各贡献多少 |
| 行业与竞争 | 供需格局、周期位置、份额变化，均有外部来源 |
| 盈利预测 | 关键假设逐项给出依据；与历史、指引、一致预期对比 |
| 估值 | 方法与公司特征匹配；至少一种交叉验证；目标价/评级可由模型复算 |
| 风险与催化 | 风险具体到哪个假设、影响多大；结论失效的条件 |

### 1.3 思路二：从投研工作流推出“数据闭合”Rubric

把我们的工作流 `年报 → 抽取 → 真值表 → 经营数据 → 预测 → 三表 → DCF/comps → 文稿 → 排版` 每一次交接都看成一个“闭合点”：上游的数在下游必须找得到、对得上、口径一致。大部分可由程序判，现有工具直接复用。

| 闭合点 | 检查 | 实现 |
|---|---|---|
| 年报 → 真值表 | 抽取数字逐字可定位，三表勾稽通过 | `verify-facts`（已有） |
| 真值表 → 历史分析 | 同比/环比/单季拆分由程序算，与年报一致 | `analyze()`（已有） |
| 经营数据 → 预测 | 分部预测的历史期合计等于报表收入 | 新增：分部合计 vs 营业收入 |
| 预测 → 三表 | 资产负债表平衡、现金流与现金余额衔接、留存收益滚动 | `ts_engine` 逐期核对（已有，接入计分） |
| 三表 → DCF | FCFF 各项取自三表；EV → 股权价值桥逐项可加总 | 新增：桥表加总 = 文中股权价值 |
| 估值 → 结论 | 目标价 = 股权价值 / 股本；评级与上行空间阈值一致 | 新增：评级规则复算 |
| 产物 → 正文 | 正文数字都能在产物或 `[S编号]` 找到 | `guard`（已有） |
| 正文 ↔ 图表 ↔ 附录 | 同一个数在三处一致；聚合数的构成描述与拆分表一致 | 新增：跨位置一致性扫描 |
| 外部信息 | 外部数字都带来源、来源可访问、检索量达标 | `verify-sources`（已有） |
| 复核改写 | 改写前后数字集合不增不改 | `numlock`（已有） |
| 时点 | 股价、外部数据的日期不晚于报告日；无未来信息 | 新增：日期扫描 |

### 1.4 合成：四层 Rubric 与计分

| 层 | 内容 | 判定者 | 分值 | 规则 |
|---|---|---|---|---|
| L0 硬闸门 | 10 道流水线闸门、guard、numlock、免责声明、来源 | 程序 | 不计分 | 任一失败 → 不可交付，总分封顶 40 |
| L1 数据闭合 | 1.3 的闭合点 | 程序为主 | 35 | 每条二元；单位/期间/口径错按严重度扣分 |
| L2 分析质量 | 1.2 题库 | Judge | 45 | 二元判定 + 证据原文 + 理由 |
| L3 表达与合规 | 故事线、事实/推论/观点区分、风险提示、可读性、机器腔 | Judge | 20 | 二元判定 |

计分全部在 Python 里做，Judge 只输出 `{item_id, passed, evidence, reason}`。另设负向条目（编造数据、来源与结论不符、评级与估值矛盾），命中即扣分并封顶（例如编造外部数据封顶 60）。

条目示例（v0 共约 40 条，细节进 `eval/rubrics/report_v0.json`）：

- L1-07 股权价值桥：EV 加回项与扣减项逐项列示，加总等于正文股权价值（容差按展示精度）。
- L2-03 驱动拆解：至少一个核心驱动给出 ≥2 环定量推导（外部驱动 → 公司量价 → 收入/利润）。
- L2-11 估值交叉验证：除主方法外至少一种方法交叉验证，并解释差异来源。
- L3-02 风险具体：每条主要风险能对应到某个预测假设，并给出方向或敏感性。

### 1.5 校准评测器

评测器本身要先过关，才能拿它驱动 refine loop。（v0 暂不做下列长校准，先评一遍看松紧，见第 6 节。）

1. **稳定性**：同一份报告评 3 次，逐条一致率 ≥ 90%，总分极差 ≤ 5。
2. **区分度**：Opus 交付稿 > DeepSeek 初稿 > 劣化稿，顺序必须稳定。
3. **劣化命中**：用赛题 5 的埋错能力自动造劣化稿（改单位、换期间、删交叉验证、删风险对应、插无来源断言），对应条目的命中率 ≥ 80%。
4. **人工一致**：每家公司抽 10 条，人工判与 Judge 判对比，不一致的条目改写判定标准。

## 2. Multi-Agent 系统

### 2.1 角色与上下文隔离

| 角色 | 是什么 | 能看到 | 不能看到 | 产出 |
|---|---|---|---|---|
| Orchestrator | Python 状态机（`report_pipeline` 扩展），不是 LLM | 全部状态文件 | — | 调度、轮次、版本、停止判定 |
| Generator | 独立 Claude Code 会话 | 年报、skills、工作区 | Rubric、评测结果原文 | 阶段 1～7 产物 |
| Reviewer | 独立会话，finagent-review skill | 文稿、产物、上一轮问题单 | 写作过程、Rubric 原文 | 改写稿（过 numlock）、`review.md`、问题路由 |
| Evaluator | 独立会话，盲评 | 交付物 + Rubric + 证据包 | 写作/复核日志、模型名 | `eval/score.json`、逐条证据 |

隔离方式：每个 Agent 是一次独立的 `claude -p` 会话，**只通过文件交接**，不共享对话。Evaluator 在单独复制出的只读目录里跑，只放交付物，从物理上看不到过程文件。Agent 内部可以再用 Claude Code subagent 并行（比如外部调研多题并行），但三个主角色之间不用 subagent，避免父会话把上下文摘要带过去。

### 2.2 Refine loop

```
Generator(1–7) → L0 闸门 ──失败──→ Generator 修复（现有逻辑）
        │通过
        ▼
   Reviewer(8) → 排版(9) → Evaluator ──达标──→ 交付(10)
        ▲                     │未达标
        │                     ▼
        └── 问题单路由 ←── Orchestrator 判停
             ├ 文字/结构问题 → Reviewer 改写
             └ 数据/假设问题 → Generator 从对应阶段重跑（下游闸门自动失效）
```

要点：

- **交付标准**：L0 全过；总分 ≥ 75；L1 ≥ 80% 得分率；L2、L3 各 ≥ 60%；无未关闭的负向条目。数字待校准后定。
- **停止条件**：达标；或满 3 轮；或连续 2 轮总分提升 < 2；或出现回归（自动回滚到最佳版本）。未达标也交付最佳版本，但标“未达交付标准”，问题单进 `review.md` 给人工。
- **防应试**：Rubric 分两半，“反馈集”转成问题单给 Reviewer/Generator（只给问题描述与证据，不给条目原文和分值），“留出集”只用于最终计分。两者分数差距过大说明在应试。
- **数字锁贯穿**：Reviewer 每轮改写都过 numlock；需要补数字的问题一律路由回 Generator，走真值表与 guard。

### 2.3 交接文件（契约）

- `.pipeline/loop.json`：轮次、每轮分数、最佳版本、停止原因。
- `.pipeline/rounds/<n>/issues.json`：`{id, layer, severity, route: reviewer|generator, stage, description, evidence}`。
- `.pipeline/rounds/<n>/score.json`：逐条判定与总分。
- 每轮交付物快照（`narrative.md`、PDF、`model.xlsx` 的哈希），便于回滚与追溯。

### 2.4 模型分工（已定）

全部用 Claude：生成用 Opus 5.5，复核与质检用 Sonnet。评审会话看不到生成模型名与写作过程，减轻自偏好。

## 3. Harness 与部署

### 3.1 选择

- Harness 统一用 Claude Code：`claude -p --output-format stream-json`，现有 `run --agent claude` 已跑通。
- PR #16 的 DeepSeek 执行器（`deepseek_agent.py` 等）保留在仓库，不作为默认路径，不再投入。
- （暂缓，提交时再定）“简版 Claude Code”提交的是**配置包**：`.claude/skills/`、`.claude/agents/`（三个角色定义）、`.claude/settings.json`（工具白名单）、`CLAUDE.md`。Claude Code 本体不能随源码分发，运行说明里写安装命令；在 `THIRD_PARTY.md` 登记为外部依赖。

### 3.2 启动脚本

`scripts/setup.sh`（macOS/Linux）与 `scripts/setup.ps1`（Windows）做这几件事：

1. 检查 Python ≥ 3.12，建 `.venv`，`pip install -r requirements.txt`。
2. 检查 Node ≥ 18 与 `claude` 命令；缺失时提示 `npm install -g @anthropic-ai/claude-code`。
3. `.env` 不存在就从 `.env.example` 复制，逐项提示填写。
4. 检查 Chrome/Chromium（HTML → PDF，可用 `FINAGENT_CHROME` 指定）与中文字体。
5. 最后跑 `python -m finagent.doctor`：逐项打勾，并用最小请求验证每个 key 可用（不打印 key）。

`.env` 需要的变量：

| 变量 | 用途 | 必填 |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude Code 无头执行（也可用 `claude login` 订阅登录代替） | 二选一 |
| `ANTHROPIC_BASE_URL` | 走代理/网关时 | 否 |
| `FINAGENT_GEN_MODEL` | 生成模型，默认 `claude-opus-5-5` | 否 |
| `FINAGENT_QC_MODEL` | 复核与质检模型，默认 `claude-sonnet-5-5` | 否 |
| `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` / `LLM_MODE` | Agent 版本（已有） | Agent 版本必填 |
| `FINAGENT_CHROME` | 浏览器路径 | 否 |

评审复现：`LLM_MODE=replay` 可离线复现 Agent 版本；研报流水线的 Claude 事件流已存在 `.pipeline/agents/*.jsonl`，提交时一并附上。

## 4. 前端架构（构想）

```
浏览器 ── React/Streamlit
   │  REST + SSE
FastAPI ── 任务队列（单机：每个任务一个子进程）
   │
report_pipeline（build / refine / status / collect / scorecard）  ← 与 CLI 同一套函数
   │
工作区（文件即状态） + runs/（产物与 trace）
```

- **原则**：前端不重写逻辑，后端只是 CLI 的薄包装；状态全在工作区文件里，前端刷新即可恢复。
- **页面**：新建任务（上传年报、公司、股价与来源）→ 运行看板（10 道闸门时间线、三个 Agent 的实时事件流、loop 每轮分数曲线）→ 产物（PDF 预览、Excel 下载、点数字跳原文页）→ 评测（逐条判定与证据、多模型对比表）→ 人工复核（`review.md` 清单逐项勾选）。
- **节奏**：决赛演示前先用 Streamlit 出可运行原型；时间够再换 React。

## 5. 排期（到初赛）

| 日期 | 事项 |
|---|---|
| 10-04 ～ 10-06 | Rubric v0（L0/L1 程序检查 + L2/L3 条目）、计分程序、Judge 调用 |
| 10-06 ～ 10-09 | `refine` loop、问题单路由、版本快照与回滚；`.claude/agents/` 三个角色 |
| 10-08 ～ 10-10 | setup 脚本、`doctor`、`.env.example` 更新、运行说明 |
| 10-10 ～ 10-13 | 三家公司校准（稳定性 / 区分度 / 劣化命中）；思路一题库（拿到样本研报后） |
| 10-14 ～ 10-17 | 计划书与 5 分钟视频素材（loop 分数曲线是很好的展示点） |
| 初赛后 | 前端；扩充评测集 |

## 6. 已拍板（2026-10-03）

1. 全部用 Claude：生成 Opus 5.5，复核与质检 Sonnet，走订阅。
2. 思路一不找样本研报，先用模型知识拆框架（拆解表见 `eval/rubrics/README.md`）。
3. 评分标准对生成方不可见：工作区不复制 `finagent/evaluation/`，评分结果放在工作区之外，回传的问题单只含理由与证据。
4. 不做三遍稳定性校准；先评一遍看松紧，由用户调分。
5. 简版 Claude Code 提交件暂不处理。

## 7. v0 实现与首轮结果

| 模块 | 位置 |
|---|---|
| 评分标准与拆解说明 | `eval/rubrics/report_v0.json`、`eval/rubrics/README.md` |
| 程序检查、盲评、计分 | `finagent/evaluation/`（`run` / `score` / `compare`） |
| 多 Agent 循环 | `finagent/report_pipeline.py` 的 `refine` |
| 环境 | `scripts/setup.sh`、`scripts/setup.ps1`、`finagent/doctor.py`、`.env.example` |
| 测试 | `tests/test_evaluation.py`（全量 120 个通过） |

三家 Opus 交付稿各评一遍（Sonnet 盲评，每家约 3 分钟、约 1 美元等值用量）：

| | 贵州茅台 | 宁德时代 | 招商轮船 |
|---|---:|---:|---:|
| 总分 | 48 | 49 | 46 |
| L1 数据闭合 | 26/35 | 26/35 | 21/35 |
| L2 分析质量 | 19/45 | 15/45 | 21/45 |
| L3 表达与合规 | 11/20 | 8/20 | 12/20 |
| 扣分 | −8 | 0 | −8 |

逐条结果见 `eval/results/v0_compare.md` 与各公司 `scorecard.md`。
