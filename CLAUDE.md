# CLAUDE.md — FinAgent 开发指南（给 Agent 看）

本仓库是 **2026 北京市大学生金融人工智能竞赛**（主题：金融投研智能体构建）的参赛作品。
私有仓库：https://github.com/MochiaoChen/finagent

## 我们选了什么

竞赛共 7 个选题，我们做 **2、4、5**，三者共用同一个数据底座：

| 选题 | 做什么 | 代码 |
|---|---|---|
| 2 财报分析 | 抽取 A 股财报指标、同比/环比、勾稽校验、异常信号、利润变动归因、实际 vs 一致预期/业绩预告、EPS 质量 | `finagent/tasks/financials/` |
| 4 估值建模 | DCF（FCFF）三情景 + 敏感性、三表联动预测、可比公司相对估值、情景偏度 | `finagent/tasks/valuation/` |
| 5 研报纠错 | 抽研报数字断言，与财报真值逐条核对，判断错误类型并给修改建议 | `finagent/tasks/report_check/` |

**不做**：选题 1、3、6、7。除非用户明确要求，不要往这些方向扩展。

## 两个版本（共用计算引擎）

- **Agent 版本**：`python -m finagent all|ask`，程序内调用国产大模型 API 抽取、规划。
- **Skill 版本**：`.claude/skills/finagent-research/`，Claude Code 读 PDF 抽取、拆断言、写解读；程序负责
  `locate` 定位、`verify-facts` 逐字校验、`all --facts/--claims` 计算、`guard` 解读护栏。抽取文件存 `data/extractions/`。
- 两版在样例上产出逐项一致（`tests/test_skill.py`）；改共用代码时两版都要回归。
- 季报（`--supplement` + 条目 `source_file`）目前只有 Skill 版本支持；Agent 版本仍只读单份报告，待改。

## 比赛硬约束（违反即扣分或失格）

- 至少一个 LLM 作核心推理引擎，**优先国产模型**（DeepSeek / 千问 / 智谱，走 OpenAI 兼容接口）。
- 输出必须是**结构化数据、表格或报告**，不能只有对话记录。
- 全程记录文件访问、工具调用、计算过程，做到**可追溯、可复现**。
- 提交**完整源码**、依赖文件和运行说明，评审要能复现。
- 第三方代码必须在 `THIRD_PARTY.md` 如实列明名称、版本、来源、许可证、使用范围，**不得冒充自研**。
- 估值和投资判断必须写明假设、适用范围、风险，并**区分事实、推论与观点**。

## 当前路线（截至 2026-09-28）

**已完成**：
- 三个选题端到端跑通；样例数据上抽取准确率、纠错召回率/准确率均为 100%（样例是自造的，不代表真实效果）。
- 去除对 OpenAI 插件的依赖，引擎全部自研，与原引擎产出一致（PR #1）。
- Skill 版本：Claude Code 读 PDF + 程序校验计算，与 Agent 版本产出一致；样例 PDF 端到端跑通（PR #3）。
- 季报单季拆分（Q2 = H1 − Q1，Q3 = Q1-3 − H1，Q4 = 全年 − Q1-3）与分季度勾稽；Skill 版本支持年报 + 季报。
- EBIT 剔除投资收益与公允价值变动；DCF 由三表模型驱动（逐期一致性核对）；comps 工作簿补利润率对比页。
- Excel 产物按投行模型排版（`output/xlsx.py` 样式层，规范见 skill 的 `references/workbook.md`）。
- 70 个测试通过；Skill 抽取的阻断问题会在估值前停止流水线，所有下游共用分析真值表。

**按优先级待做**：
1. **真实 A 股年报联调**（两个版本都要测）：跨页表格、合并单元格、版式差异；扫描页目前直接拒收，不做 OCR。
   这项最影响真实效果，还没做过。
2. **导师风格改写**（已和用户讨论过，放在 `tasks/report_check/` 下）：喂导师点评 → 提炼风格档案 → 代码做格式合规检查 → LLM 一键改写 → **数字锁**（改写前后断言必须完全一致，否则拒绝输出）。
3. 扩充评测集：10～20 份真实财报 + 人工埋错研报。
4. Streamlit Web 界面 + 运行日志回放。
5. Agent 版本接入真实国产模型跑 `--llm live`，并把 `.cache/llm/` 提交进仓库供评审 replay。
6. Agent 版本跟进 Skill 版本：多文件输入（季报）、规则通道识别季报表头“本报告期/年初至报告期末”
   （现在会被当成年度，所以没有对季报开放）、`prompts/extract_financials.md` 补投资收益与公允价值变动收益。

**截止日期**：**2026-10-18** 初赛提交（计划书 PDF + ≤5 分钟 MP4 视频）；11 月底决赛（现场演示 + 答辩，需可运行原型和现场样例数据）。

## 设计规范（不要破坏）

1. **LLM 不做算术。** LLM 只负责理解文本、抽取补漏、写文字解读、Agent 规划。所有数值计算都用确定性 Python 完成。
2. **每个数字可追溯。** 抽取结果必须带 `source = {source, page, chunk_id, row, col}`。LLM 抽出的数字必须能在原文 chunk 里找到，否则丢弃（`extract._validate_llm_item`）。
3. **双通道不静默取舍。** 规则通道和 LLM 通道结果不一致时，记为 issue 交人工复核，不要偷偷选一个。
4. **一张真值表。** `analyze()` 产出的 `truth_table` 是估值和纠错的唯一数据来源。不要在下游重新抽取或重算基础数字。
5. **所有文件读取走 `tracing.read_file()`**，所有产物走 `tracer.write_artifact()` / `write_json()`，这样才会记录哈希。新步骤用 `Pipeline.step` 注册，工具函数用 `@tracing.traced`。
6. **单位约定**：财务事实内部统一用**元**；估值模块（DCF、三表、comps）用**百万元**，每股用**元**；比率存百分数值（14.49 表示 14.49%）。
7. **误报控制优先于召回。** 纠错容差按研报数字的展示精度算（`half_ulp`）；预测性表述和缺少真值的断言判"无法核实"，不计为错误；错误类型（单位/期间/口径）必须找到精确匹配才下结论。
8. **报告结构**：事实 → 推论 → 观点；报告中每个数字都附来源定位；估值报告必须写假设、口径简化说明和"不构成投资建议"。
9. **LLM 输出加护栏**：文字解读过数字护栏（`pipelines.commentary`）；以后任何让 LLM 改写报告的功能都必须加数字锁。

## 第三方代码规则

- 仓库**不再包含** OpenAI Public Equity Investing 插件代码（原 `third_party/` 与 `vendor.py` 已删除），不要重新引入。
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
- 样例数据全部为虚构，内部完全自洽，真实数据效果会明显下降。

## 常用命令

```bash
.venv/bin/python -m finagent all --input data/samples/annual_report_2024.md --year 2024 --company 星河智造 --assumptions data/samples/valuation_assumptions.json --report data/samples/research_draft.md --peers data/samples/peers.csv --estimates data/samples/estimates.csv --guidance data/samples/guidance.csv --llm off
```

```bash
.venv/bin/python -m pytest -q tests
```

```bash
.venv/bin/python eval/run_eval.py
```

- 环境：`uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt`（Python 3.12；`.venv/` 不入库）。
- 改完代码必须跑测试和评测。样例评测指标下降视为回归。
- 改样例年报要改 `data/samples/build_samples.py` 再重新生成（同时生成样例三季报），并同步更新 `eval/gold_financials.json`、
  `eval/labels.json`、样例 PDF（`build_pdf.py`）和 `data/extractions/` 下的抽取文件。

## 代码风格

- 注释、docstring、报告、错误信息用**中文**；标识符用英文。
- `finagent/` 只用标准库（pdfplumber 仅用于 PDF 解析）。
- 跟随周边代码的写法和注释密度；新功能配测试。
- Git：分支 `main`，提交信息结尾加 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`；未经用户要求不要 push。
