# CLAUDE.md — LEDGER 开发指南（给 Agent 看）

本仓库是 **2026 北京市大学生金融人工智能竞赛**（主题：金融投研智能体构建）的参赛作品。
系统正式名 **LEDGER**（**L**LM-driven **E**quity Research with **D**eterministic **G**rounding, **E**valuation and **R**eporting）；
GitHub 仓库已改名 LEDGER；Python 包名与命令行仍为 `finagent`，不要为改名去动标识符。
公开仓库：https://github.com/MochiaoChen/LEDGER

## 我们选了什么

三个主选题、三个子选题，共用同一个数据底座（真值表）：

| 层级 | 选题 | 做什么 | 代码 |
|---|---|---|---|
| 主选题 | 财报分析 | 抽取 A 股财报指标、同比/环比、单季拆分、勾稽校验、异常信号、利润变动归因、实际 vs 一致预期/业绩预告、EPS 质量 | `finagent/tasks/financials/` |
| 主选题 | 自动化估值建模 | 分部预测 → 三表联动 → FCFF DCF 三情景 + 敏感性、反向 DCF、可比公司、程序评级、公式联动工作簿 | `finagent/tasks/valuation/` |
| 主选题 | 研究报告质量评估 | 四层评分标准（L0 硬闸门 / L1 数据闭合 / L2 分析质量 / L3 表达合规 / 负向）、程序检查 + 盲评、程序计分、评审校准、`refine` 闭环 | `finagent/evaluation/`、`report_pipeline refine` |
| 子选题 | 数据提取 | 模型读 PDF 抄数 + 逐字证据校验 + 规则通道交叉（稀疏网格、跨页续表、科目折行）；经营数据表逐格回查 | `finagent/parsing/`、`tasks/financials/{extract,external,extras}.py` |
| 子选题 | 产业链分析 | 资料搜集（行业、竞争、可比公司）→ 分析框架的驱动链 → 深度专题；产业链图；外部数字带 `[S编号]` 过 guard | `.claude/skills/finagent-report/`（`references/research.md`、reportkit `C.flow`） |
| 子选题 | 研究报告纠错核查 | 抽研报数字断言，与财报真值逐条核对，判断错误类型并给修改建议；研报内部一致性 | `finagent/tasks/report_check/` |

**不做**：其他选题。除非用户明确要求，不要往其他方向扩展。

## 系统架构（只有这一条路线）

**多 Agent 系统，harness 是无头 Claude Code。**

- **编排器** `finagent/report_pipeline.py`（确定性 Python，不是模型）：`build` 在仓库目录树之外为单家公司搭隔离工作区；
  `run` 依次起五个无头 Claude Code 会话（`claude -p --output-format stream-json`）；`status` 判 11 道闸门；
  `refine` 加盲评与问题单路由；`collect` 收回产物；`scorecard` 多工作区对比。
- **五个生产角色**（每个一次独立会话，不共享上下文，只靠工作区文件交接）：研究助理（阶段 1，Opus）→ 分析师（2～7，Opus）
  → 主笔（8，Opus）→ 复核编辑（9，Sonnet）→ 排版设计师（10～11，Opus）。另有**盲评质检员**（Sonnet），
  在仓库与工作区之外只含交付物的目录里评审。模型由 `FINAGENT_GEN_MODEL` / `FINAGENT_QC_MODEL` 配置。
- **角色说明**：`.claude/skills/` 四个 skill（`finagent-pipeline` 编排入口、`finagent-research` 分析师、
  `finagent-report` 研究助理 / 主笔 / 排版、`finagent-review` 复核编辑）+ 编排器生成的工作区 `CLAUDE.md`（11 阶段、读取边界、闸门）。
- **计算引擎** `finagent/`（除 `evaluation/`）：**不调用任何模型**。模型会话写下 `facts.json`、`extras.json`、`sources.json`、
  `claims.json`、`valuation_assumptions.json`、`narrative.md`，引擎负责 `locate` 定位、`verify-facts` / `verify-extra` /
  `verify-sources` 校验、全部计算、`guard` 护栏与 `numlock` 数字锁。没有模型抽取文件时引擎只走规则通道（样例回归与测试用）。
- **质检** `finagent/evaluation/`：程序检查（L0/L1）+ 盲评（L2/L3/负向）+ 计分 + 评审校准。工作区不复制它，评分标准对生成方不可见。

历史上曾有“程序内调用国产模型 API”的 Agent 版本（`ask`、`--llm`）和 Codex 执行器，已删除，不要重新引入。

架构说明见 `docs/architecture.md`；计划书见 `paper/`；完整技术报告（长版）见 `paper/techreport/`。

## 比赛硬约束（违反即扣分或失格）

- 至少一个 LLM 作核心推理引擎（大赛写的是优先国产模型；**已拍板全部用 Claude**，计划书里说明理由）。
- 输出必须是**结构化数据、表格或报告**，不能只有对话记录。
- 全程记录文件访问、工具调用、计算过程，做到**可追溯、可复现**。
- 提交**完整源码**、依赖文件和运行说明，评审要能复现。
- 第三方代码必须在 `THIRD_PARTY.md` 如实列明名称、版本、来源、许可证、使用范围，**不得冒充自研**。
- 估值和投资判断必须写明假设、适用范围、风险，并**区分事实、推论与观点**。

## 设计规范（不要破坏）

1. **LLM 不做算术。** 模型只负责读、抄、写、判断。所有数值计算都用确定性 Python 完成，连“约三倍”这类约数也不许心算。
2. **每个数字可追溯。** 抽取结果必须带 `source = {source, page, chunk_id, row, col}`。模型抄的数字必须在所写页码的原文中
   按数字边界找到，否则拒收（`external.find_evidence`）；外部来源的摘句必须包含所登记的数字（`output/sources.py`）。
3. **双通道不静默取舍。** 模型抽取与规则通道结果不一致时，记为 issue 并阻断估值，不要偷偷选一个（`extract.merge`）。
4. **一张真值表。** `analyze()` 产出的 `truth_table` 是估值和纠错的唯一数据来源。不要在下游重新抽取或重算基础数字。
5. **所有文件读取走 `tracing.read_file()`**，所有产物走 `tracer.write_artifact()` / `write_json()`，这样才会记录哈希。
   引擎步骤用 `Pipeline.step` 注册，工具函数用 `@tracing.traced`。会话事件流存工作区 `.pipeline/agents/`。
6. **单位约定**：财务事实内部统一用**元**；估值模块（DCF、三表、comps）用**百万元**，每股用**元**；比率存百分数值（14.49 表示 14.49%）。
7. **误报控制优先于召回。** 纠错容差按研报数字的展示精度算（`half_ulp`）；预测性表述和缺少真值的断言判“无法核实”，
   不计为错误；错误类型（单位/期间/口径/方向）必须找到精确匹配才下结论。
8. **报告结构**：事实 → 推论 → 观点；估值报告必须写假设、口径简化说明和“不构成投资建议”。
9. **模型输出加护栏**：文稿过 `guard`（出处、指标绑定、外部数字带 `[S编号]`）；任何让模型改写报告的环节都必须过 `numlock`。
10. **会话隔离**：角色之间不共享上下文；工作区在仓库之外；评分标准与完整评测结果不进入工作区，回传的问题单只含理由与证据。
11. **不预设行业框架**：skill 只给方法与约束，驱动由模型从年报与资料包推导。**文风不做程序拦截**（用户明确反对），交给复核编辑。

## 第三方代码规则

- 仓库**不包含** OpenAI Public Equity Investing 插件代码，不要重新引入。本地参考副本 `reference/openai-pei/` 不入库。
- 原插件引擎已自研替代：`ts_engine.py`（三表）、`scenario_tables.py`（情景表）、`earnings.py`（beat/miss、预告、EPS 质量）、
  `dcf.py`、`comps.py`（含公式工作簿）。计算口径与原插件保持一致，参照关系如实写在 `THIRD_PARTY.md`。
- 一致性护栏：`tests/test_golden.py`（对比 `tests/golden/` 原引擎快照，必须完全相等）；
  `tests/test_parity_reference.py`（本地有原插件时逐项对照，`FINAGENT_REFERENCE_PLUGIN` 或仓库上级目录）。
- 有意修改计算口径时，同步更新 golden 快照并在 PR 中说明差异原因。

## 已知问题（改动相关代码时注意）

- 流动性压力测试沿用原插件口径 FCF×(1+冲击)，FCF 为负时方向相反；为保持一致未改，报告里已注明。
- EBIT = 利润总额 + 财务费用 − 投资收益 − 公允价值变动收益；资产处置收益、其他收益、减值、营业外收支仍在 EBIT 内。
  剔除的投资类资产需在假设文件 `non_operating_assets` 加回，未设置时报告提示估值偏保守。
- 三表模型的经营费用是轧差项（毛利 − EBIT − 折旧摊销），保证历史期 EBIT 与 DCF 同口径；
  DCF 情景向量全部取自三表模型，假设文件里的 `ebit_margin` 等字段不再生效。
- 三表模型期初留存收益置 0，权益合并列示，只影响列示，不影响勾稽。
- 规则通道不识别季报表头（“本报告期 / 年初至报告期末”会被当成年度），所以季报（`--supplement`）只接模型抽取，规则通道不参与比对。
- 规则通道未取到：股本变动表、政府补助口径、部分扣非季度别名。扫描页直接拒收，不做 OCR。
- 样例数据全部为虚构，内部完全自洽，真实数据效果会明显下降。

## 进展（截至 2026-10-05）

- 财报分析、估值建模、纠错核查端到端跑通；引擎自研替代原插件，产出一致（PR #1）。
- 模型读 PDF + 程序校验计算（PR #3）；季报单季拆分与分季度勾稽；EBIT 口径、三表驱动 DCF、comps 利润率对比、投行排版 Excel。
- 真实年报：茅台、宁德、招商、中际旭创、宇树科技（招股书）；稀疏网格、跨页续表、科目折行处理后，三家 314 个核验值规则通道取到 293 个，错配 0。
- 研报流水线：隔离工作区、五会话、11 道闸门，先搜集后分析、深度专题调研；reportkit 排版（25～32 页、≥ 60 图表）。
- 质检：评分标准 v0 → v1（人工质检调整）→ v2（数字前后矛盾改程序判）；`refine` 闭环；评审校准
  （重复盲评逐条一致 86%～91%、总分极差 7～8；判出问题人工精确率 84%；整节删除类劣化判出率低，原因是劣化不彻底）。
- v0 三家（旧流程）46～49 分；中际旭创、宇树科技 v1 74 / 67 → v2 90 / 88（评分标准 v0、单次盲评）。
- 反向 DCF、研报内部一致性检查、工作簿公式审计、数字出处分类（事实 / 推论 / 观点）。
- 统一命令行 `finagent`、终端界面 `finagent_tui/`。
- 2026-10-05 清理：删除程序内 LLM 客户端、`ask` 工具循环、prompt 模板、`--llm` 参数与 Codex 执行器，只保留无头 Claude Code 一条路线。
- 164 个测试通过（本地无原插件时跳过 5 个逐项对照测试）。

**按优先级待做**：
1. **计划书**（论文体例，`paper/`，XeLaTeX + ctex）；项目名已定为 LEDGER。完整技术报告 `paper/techreport/`（`bash build.sh`），其中橙色 `\fab{}` 为待核实内容。
2. **评测集**：清单见 `docs/eval-dataset-collection.md`（约 15 家年报季报 + 卖方研报人工埋错），团队收集中。
3. 改进劣化算子（跨全文删除并同步删图表），做资料搜集 / 复核会话 / 深度专题三项消融。
4. 规则通道识别季报表头；研报写作待优秀研报样例（`references/exemplars/`）到位后提炼分析逻辑。
5. **前端**：网页前端由其他成员负责；终端界面后续补运行中实时刷新。

**截止日期**：**2026-10-18** 初赛提交（计划书 PDF + ≤5 分钟 MP4 视频）；11 月底决赛（现场演示 + 答辩，需可运行原型和现场样例数据）。

## 常用命令

```bash
python -m finagent all --input data/samples/annual_report_2024.md --year 2024 --company 星河智造 --assumptions data/samples/valuation_assumptions.json --report data/samples/research_draft.md --peers data/samples/peers.csv --estimates data/samples/estimates.csv --guidance data/samples/guidance.csv
```

```bash
python -m finagent.report_pipeline build --company <公司> --year 2025 --price <股价> --price-source "<来源>"
```

```bash
python -m finagent.report_pipeline refine --workspace <工作区>
```

```bash
python -m finagent.evaluation run --workspace <工作区>
```

```bash
python -m pytest -q tests
```

```bash
python eval/run_eval.py
```

- 环境：Python 3.12；`.venv/` 不入库。macOS / Linux 解释器为 `.venv/bin/python`，Windows 为
  `.venv\\Scripts\\python.exe`；也可激活虚拟环境后统一使用 `python`。
- 改完代码必须跑测试和评测。样例评测指标下降视为回归。
- 改样例年报要改 `data/samples/build_samples.py` 再重新生成（同时生成样例三季报），并同步更新 `eval/gold_financials.json`、
  `eval/labels.json`、样例 PDF（`build_pdf.py`）和 `data/extractions/` 下的抽取文件。

## 代码风格

- 注释、docstring、报告、错误信息用**中文**；标识符用英文。
- `finagent/` 只用标准库（pdfplumber 仅用于 PDF 解析）；终端界面在 `finagent_tui/`，可选依赖。
- 跟随周边代码的写法和注释密度；新功能配测试。
- Git：分支 `main`，提交信息结尾加 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`；未经用户要求不要 push。
