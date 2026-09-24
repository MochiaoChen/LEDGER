# 第三方组件说明

## 1. Public Equity Investing 插件（参照其计算规则自研实现，不包含其代码）

| 项目 | 内容 |
|---|---|
| 来源 | OpenAI Public Equity Investing 插件 0.1.31 |
| 许可证 | 原插件标注为 **Proprietary – Internal Use Only** |
| 本仓库包含的原插件代码 | **无**。早期版本通过 `third_party/` 原样引入并调用，现已全部删除，改为自研实现 |
| 仍参照的内容 | 下表所列引擎的计算口径、判定阈值、输出字段名与英文代码值（如 `input required`、`senior-review-ready`），以保证改造前后结果一致 |

| 参照的原插件引擎 | 本项目自研实现 | 一致性校验 |
|---|---|---|
| `three-statement-model-builder/scripts/skill_core.py`（三表联动、营运资本、PP&E、债务与现金归集、勾稽、情景与敏感性、模型状态判定） | `finagent/tasks/valuation/ts_engine.py` | 浮点逐位相等 |
| `scenario-sensitivity-generator/scripts/materialize_public_equity_sensitivities.py`（三情景目标价与偏度、倍数/EPS/KPI/流动性敏感性、跟踪触发表、就绪度） | `finagent/tasks/valuation/scenario_tables.py` | 输出逐字节相等 |
| `earnings-deep-dive/scripts/run_plan.py`（beat/miss、业绩预告中值对比、EPS 质量筛查规则） | `finagent/tasks/financials/earnings.py` | 逐字段相等 |
| `dcf-model-builder/scripts/skill_core.py`（FCFF DCF） | `finagent/tasks/valuation/dcf.py` | 相对误差 < 1e-9 |
| `comps-valuation/references/*.md`（EV 桥、倍数配对、NM、IQR 离群值、P25/P75 区间） | `finagent/tasks/valuation/comps.py` | — |
| `comps-valuation/scripts/create_comps_template.py`（英文 comps 公式模板） | 未沿用模板；`comps.write_formula_workbook` 另行生成中文公式工作簿，数值与 `comps.json` 一致 | 公式独立重算与缓存值相等 |

校验方式：
- `tests/golden/`：改造前用原插件引擎跑样例得到的产物快照；`tests/test_golden.py` 要求自研实现的产物与之完全相等（无需原插件即可运行）。
- `tests/test_parity_reference.py`：本地存在原插件时（`FINAGENT_REFERENCE_PLUGIN`），用样例、边界值和数百组随机输入逐项对照；找不到原插件时跳过。

## 2. 开源依赖

| 名称 | 版本 | 许可证 | 使用范围 |
|---|---|---|---|
| pdfplumber | ≥0.11 | MIT | PDF 文本与表格抽取 |
| pytest | ≥8.0 | MIT | 测试 |

`finagent/` 其余部分仅使用 Python 标准库（含 xlsx 写出）。

## 3. 大语言模型

| 名称 | 调用方式 | 使用范围 |
|---|---|---|
| 见 `.env`（如 deepseek-chat / qwen-plus / glm-4-plus） | OpenAI 兼容 Chat Completions API | 非标准表格抽取补漏、研报断言抽取补漏、分析文字解读、Agent 规划 |

## 4. 自主开发部分

`finagent/` 下全部代码均为自主开发：编排与追踪（core）、LLM 客户端、文档解析、A 股指标字典与抽取、财务分析与异常信号、
利润变动归因桥、业绩预期对比、DCF 引擎、三表联动引擎、情景敏感性表格、相对估值与公式工作簿、研报核查、报告与 xlsx 输出、评测与测试。
其中第 1 节所列模块的计算规则参照原插件，如实标注于此。
