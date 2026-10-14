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
| `scenario-sensitivity-generator/references/target-backsolve-rubric.md`（“股价隐含了什么”、反解目标所需路径、可行性分档的思路） | `finagent/tasks/valuation/reverse_dcf.py`：自研单变量反向 DCF（网格扫描 + 二分求解），分档改为按基准假设与历史区间判定，未沿用原分档文字 | 仅借方法，无口径复刻；`tests/test_reverse_dcf.py` 代回正向 DCF 校验 |
| `deck-report-qc/references/extraction-and-tieout.md`、`issue-taxonomy.md`（重复数字对账：实体、口径、期间、单位、情景都相同才算矛盾；证据强度分级） | `finagent/tasks/report_check/consistency.py`：自研研报内部一致性检查（评级、各情景每股价值、预测年度公司整体收入与利润），用于评分标准 N-02、guard 与研报纠错核查；比较范围与判定规则自定，未使用原脚本 | 仅借方法；`tests/test_consistency.py` |
| `initiating-coverage/references/thesis-framework.md`、`pm-md-standards.md`；`thesis-tracker/references/workflow-core.md`（论点质量要求、分歧表、确认 / 预警 / 证伪三档阈值、公司判断与股价判断分开） | `.claude/skills/finagent-report/references/analysis.md`“投资主线写到什么程度”、`sections.md` 跟踪一节：中文自写的写作要求，未搬原文与行业模板，不含买方仓位操作建议 | 文档，无计算 |
| `model-audit-tieout/references/formula-and-workbook-controls.md`（跨期公式一致性、公式内写死数字、易变函数） | `finagent/evaluation/workbook_audit.py` 的 `formula_controls`：自研只读检查，跨期只抓“孤岛”列，写死数字按约定常数白名单识别，未使用原脚本 | 仅借方法；`tests/test_workbook_audit.py` |
| `financials-normalizer/references/normalization-schema.md`、`source-protocol.md`（证据标签：报告披露、计算、管理层表述、假设、外部估计等） | `finagent/output/guard.py` 的 `tagged_truth_values` / `classify_text`：按产物文件与抽取方式给数字定出处类型，并归入赛题要求的事实 / 推论 / 观点；标签体系自定（中文五类），未使用原脚本 | 仅借方法；`tests/test_provenance.py` |

校验方式：
- `tests/golden/`：改造前用原插件引擎跑样例得到的产物快照；`tests/test_golden.py` 要求自研实现的产物与之完全相等（无需原插件即可运行）。
  2026-09-28 因有意修改口径（EBIT 剔除投资收益与公允价值变动、三表经营费用改为轧差、DCF 由三表驱动、comps 增加利润率）
  重新生成了快照；各引擎本身未改，仍由 `test_parity_reference.py` 与原插件逐项对照。
- `tests/test_parity_reference.py`：本地存在原插件时（`FINAGENT_REFERENCE_PLUGIN`），用样例、边界值和数百组随机输入逐项对照；找不到原插件时跳过。

## 2. 开源依赖

| 名称 | 版本 | 许可证 | 使用范围 |
|---|---|---|---|
| pdfplumber | ≥0.11 | MIT | PDF 文本与表格抽取 |
| pytest | ≥8.0 | MIT | 测试 |
| fpdf2 | 2.8 | LGPL-3.0 | 仅开发时：`data/samples/build_pdf.py` 生成样例 PDF，不是运行依赖 |
| Textual | ≥1.0（开发时 8.2.8） | MIT | 仅终端界面 `finagent_tui/`（`finagent tui`），可选；`finagent/` 引擎不依赖 |
| Rich | 随 Textual 安装（开发时 15.0.0） | MIT | 终端界面中的表格、文本渲染 |

宣传片工程 `promo/`（与 `video/` 是两套独立的宣传片工程，互不依赖）：

| 名称 | 版本 | 许可证 | 来源 | 使用范围 |
|---|---|---|---|---|
| 归藏 product video skill 起步工程 | 提交 18842e0 | AGPL-3.0 | https://github.com/op7418/guizang-product-video-skill | `promo/` 的构建与逐帧渲染脚本（`build.mjs`、`render.mjs`、`stills.mjs`、`server.mjs`、`cover.mjs`、`src/engine.js`、`src/film-store.js`、`src/kit/` 中的 cursor / interact / measure / text）与 11 个内置音效 `promo/assets/sfx/*.wav`；混音与交付检查脚本（`mix_audio.py`、`check_delivery.py`、`sfx_landmarks.py`）运行时从该仓库调用，不随源码分发。许可证与说明见 `promo/LICENSE`、`promo/NOTICE.md` |
| React / ReactDOM | 19.2.3 | MIT | npm | 宣传片画面组件 |
| GSAP | 3.15.0 | GSAP Standard License（免费使用） | npm | 缓动函数 |
| esbuild | 0.27.3 | MIT | npm | 打包画面代码 |
| Playwright | 1.58.1 | Apache-2.0 | npm | 无头浏览器逐帧截图 |
| Three.js | 0.186.1 | MIT | npm | 起步工程自带依赖，本片未使用 |
| NumPy / SciPy | `uv run --with` 临时安装 | BSD-3-Clause | PyPI | 配乐与键入声合成（`tools/score.py`、`tools/make_typing.py`） |
| Maple Mono NF CN | 7.9 | SIL OFL 1.1 | https://github.com/subframe7536/maple-font | 英文与代码字体；文件不入库 |
| ElevenLabs TTS / 语音转写 | eleven_v4、scribe_v1（2026-10） | ElevenLabs 服务条款（免费套餐） | API | 旁白试听版（自带音色 Brian）；生成的音频不入库 |

`promo/` 的画面与配乐由 `promo/src/`、`promo/tools/` 下的代码生成；`typing-*.wav` 由 `tools/make_typing.py` 合成；中文字体 Noto Sans SC 取自 `video/film/fonts/`（OFL 1.1）。
片中出现的年报页面、研报页面与终端界面截图，均来自本仓库与工作区的真实产物（中际旭创 2025 年年度报告为公开披露文件）。

样例 PDF（`data/samples/annual_report_2024.pdf`）内嵌 macOS 系统字体 Arial Unicode 的字形子集，仅用于显示样例数据。

`finagent/` 其余部分仅使用 Python 标准库（含 xlsx 写出）；终端界面单独成包 `finagent_tui/`。

## 3. 大语言模型与执行器

| 名称 | 调用方式 | 使用范围 |
|---|---|---|
| Claude（Anthropic）：生成侧默认 Claude Opus 5.5，复核与盲评默认 Claude Sonnet 5.5 | 无头 Claude Code（`claude -p --output-format stream-json`），由 `finagent/report_pipeline.py` 逐角色启动 | 研究助理联网检索与登记来源；分析师读年报 PDF 抽取数字、拆研报断言、起草估值假设；主笔写文稿；复核编辑改写；排版设计师写排版脚本；盲评质检员逐条评审。所有计算、校验与计分由本项目代码完成 |
| Claude Code（Anthropic） | 外部命令行工具，用户自行安装与登录，不随源码分发 | 多 Agent 执行器（harness） |

## 4. 自主开发部分

`finagent/` 下全部代码均为自主开发：编排与追踪（core）、多 Agent 编排器（report_pipeline）、文档解析、A 股指标字典与抽取、财务分析与异常信号、
利润变动归因桥、业绩预期对比、DCF 引擎、三表联动引擎、情景敏感性表格、相对估值与公式工作簿、研报核查、报告与 xlsx 输出、评测与测试。
其中第 1 节所列模块的计算规则参照原插件，如实标注于此。
