# 第三方组件说明

## 1. Public Equity Investing 插件（原样引入，未修改）

| 项目 | 内容 |
|---|---|
| 位置 | `third_party/public_equity_investing/`（保留原目录结构） |
| 来源 | Public Equity Investing 插件（见该目录下 `README.md`） |
| 许可证 | 原插件标注为 **Proprietary – Internal Use Only**（见 `third_party/public_equity_investing/LICENSE.txt`），**不得对外再分发**；本仓库为私有仓库 |
| 修改情况 | 未修改任何文件，由 `finagent/vendor.py` 按文件路径加载 |

| 原插件模块 | 在本项目中的用途 | 调用位置 |
|---|---|---|
| `skills/three-statement-model-builder/scripts/skill_core.py`、`validate_plan.py` | 三表联动预测：利润表/资产负债表/现金流量表、营运资本、PP&E、债务与现金归集、勾稽检查、情景与敏感性 | `finagent/tasks/valuation/three_statement.py` |
| `skills/scenario-sensitivity-generator/scripts/materialize_public_equity_sensitivities.py` | 三情景目标价与偏度、盈亏平衡概率、倍数/EPS/KPI/流动性敏感性、跟踪触发表、就绪度判定 | `finagent/tasks/valuation/scenarios.py` |
| `skills/comps-valuation/scripts/create_comps_template.py` | 生成带公式的 comps Excel 工作簿（需 XlsxWriter） | `finagent/tasks/valuation/comps.py` |
| `skills/comps-valuation/references/*.md` | 相对估值计算规则（EV 桥、倍数配对、NM、IQR 离群值、P25/P75 区间），据此实现计算 | `finagent/tasks/valuation/comps.py` |
| `skills/earnings-deep-dive/scripts/run_plan.py` 及 `utils/` | 实际 vs 预期（beat/miss）、业绩预告中值对比、EPS 质量筛查规则 | `finagent/tasks/financials/earnings.py` |
| `skills/dcf-model-builder/scripts/skill_core.py` | 作为参照实现，测试中与自研 `dcf.py` 逐项对比（误差 < 1e-9） | `tests/test_new_modules.py` |
| `shared/` | 原插件公共模块，供上述脚本内部导入 | — |

## 2. 开源依赖

| 名称 | 版本 | 许可证 | 使用范围 |
|---|---|---|---|
| pandas | ≥2.0 | BSD-3-Clause | 业绩深度分析（原插件 run_plan.py 依赖） |
| openpyxl | ≥3.0.10 | MIT | 原插件 Excel 读写 |
| XlsxWriter | ≥3.0 | BSD-2-Clause | 原插件 comps 公式工作簿 |
| pdfplumber | ≥0.11 | MIT | PDF 文本与表格抽取 |
| pytest | ≥8.0 | MIT | 测试 |

## 3. 大语言模型

| 名称 | 调用方式 | 使用范围 |
|---|---|---|
| 见 `.env`（如 deepseek-chat / qwen-plus / glm-4-plus） | OpenAI 兼容 Chat Completions API | 非标准表格抽取补漏、研报断言抽取补漏、分析文字解读、Agent 规划 |

## 4. 自主开发部分

`finagent/` 下除 `vendor.py` 加载的原插件代码外均为自主开发：编排与追踪（core）、LLM 客户端、文档解析、A 股指标字典与抽取、
财务分析与异常信号、利润变动归因桥、DCF 引擎（`dcf.py`）、A 股口径到原插件引擎的映射层、相对估值计算、研报核查、报告与 xlsx 输出、评测与测试。
