# PR：提交宁德时代/招商轮船 sandbox 测评、估值 Excel 与研报审阅修订版

## 背景与范围

把两家公司的年报、原版 Skill、纯净首轮过程、第二阶段估值运行、Excel、初版及审阅修订版研报一并保存到仓库 `sandbox/`，供负责人复现与审阅。该 PR 基于最新 `main`；只新增 sandbox 内容，并对报告封面实际/预测图例做通用代码修正。未改动原有估值假设、三表计算引擎或现存研报事实表。

## 两个阶段必须区分

1. **纯净首轮**：输入仅为宁德时代、招商轮船 2025 年报及仓库原版 `finagent-research`、`finagent-report` Skill。Skill 副本在 `sandbox/skills/`，交互记录和核验数据在 `sandbox/results/`。因未确认估值假设与参考股价，模型在估值前停止，**这阶段没有 Excel/PDF**；见 `sandbox/results/首轮测评结果.md`。
2. **补充输入阶段**：使用仓库已有、标为分析师观点的估值假设，补充同一年报的核验事实和经营数据，再输入外部参考股价，运行三表和 DCF。最终运行目录为宁德时代 `sandbox/phase2/runs/20261002-003730-valuation/`、招商轮船 `sandbox/phase2/runs/20261002-005015-valuation/`。DeepSeek API 使用 `deepseek-flash`（thinking/high）生成研究文字；事实校验、估值、Excel、图表和 PDF 排版由程序完成。随后又对正文作编辑修订，不能把最终 PDF 说成 DeepSeek 原样输出。

## 审阅入口

| 公司 | 估值 Excel | 最新研报 PDF | 运行结果 |
| --- | --- | --- | --- |
| 宁德时代 | `sandbox/phase2/deliverables/宁德时代/sheet.xlsx` | `sandbox/phase2/revision/deliverables/宁德时代/宁德时代_研报_审阅修订版.pdf`（16 页、38 图） | `sandbox/phase2/runs/20261002-003730-valuation/` |
| 招商轮船 | `sandbox/phase2/deliverables/招商轮船/sheet.xlsx` | `sandbox/phase2/revision/deliverables/招商轮船/招商轮船_研报_审阅修订版.pdf`（14 页、31 图） | `sandbox/phase2/runs/20261002-005015-valuation/` |

初版 PDF 保留于 `sandbox/phase2/deliverables/*/report.pdf` 及 `sandbox/phase2/revision/original/`，便于比较。修订对照与结果限制分别见 `sandbox/phase2/revision/修订与复核说明.md`、`sandbox/phase2/revision/重要待复核事项.md`。

## 本次报告质量修订

- 把封面图的实际收入、实际归母净利、预测收入、预测归母净利分别标注；预测期用浅金/浅蓝，解释 A/E 年份。
- 封面结论由经营、利润、现金流等关键数字支撑；删除正文中的程序自证、无信息量的否定句式与口语化套话。
- 图表由宁德时代 62 缩至 38、招商轮船 48 缩至 31；保留与经营及估值判断直接相关的图。
- 对可能改变预测、DCF 和评级的未决事项集中列出，供负责人 double check；正文不拿“年报佐证”之类过程语言圆场。

## 验证

- 两家公司最终三表勾稽失败数均为 0；DCF 标记为 `screen-grade`，没有伪称可直接用于投资决策。
- 两份编辑修订正文运行 `finagent guard`，均为 `ok: true`、`unverified_numbers=[]`、`mismatched_claims=[]`。
- Excel ZIP 完整性检查通过；最终 PDF 已逐页渲染、检查页数和嵌入字体。
- `tests/test_report_kit.py`、`tests/test_pipeline.py`、`tests/test_quarterly_ebit.py`：25 passed；测试环境仍有 Matplotlib 中文字体缺字警告，PDF 逐页预览未见该问题。
- 已排除 `.DS_Store`、API 响应缓存、页面预览缓存与重复的 `sandbox/sandbox/`；没有把 `.env` 或 API Key 提交。原始过程记录与必要运行产物保留在 sandbox。

## 请求负责人重点审阅

本地事实输入主要基于 2025 年报，尚未并入 2026 年随后披露的定期报告。请先更新事实基期和参考股价，再重点核查宁德时代受限资金/库存与利润路径、招商轮船分船型运价/毛利率及租赁和长期股权投资的估值桥，最后复核终值敏感性和评级。**在这些事项确认之前，两份报告仅为内部研究稿，不宜对外发布。**
