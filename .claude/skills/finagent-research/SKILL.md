---
name: finagent-research
description: A 股上市公司投研（Skill 版本）：直接读年报/季报 PDF 抽取财务数据，经程序校验后完成财报分析（含单季拆分）、三表驱动的 DCF/可比公司估值与研报纠错。用户给出 A 股年报或季报（PDF），要求分析财报、估值、核查研报草稿，或提到 FinAgent / 赛题 2、4、5 时使用。
---

# FinAgent 投研（Skill 版本）

本仓库有两个版本，计算引擎共用：

- **Agent 版本**：`python -m finagent all|ask`，程序调用国产大模型 API（DeepSeek 等）抽取与规划。
- **Skill 版本（本文件）**：由你（Claude Code 中的模型）直接读 PDF 抽取数字、拆研报断言、写解读；
  程序负责定位关键页、校验每个数字、做全部计算与出报告。

## 铁律

1. **你不做算术。** 同比、比率、估值、勾稽全部由程序计算。你只读原文、抄数字、写文字。
2. **每个数字都来自原文。** 抄录时保留原文写法（千分位、小数位、括号负数），写明页码；程序会逐字核对，
   找不到就拒收。不要凭记忆或推算补数。
3. **只取合并报表。** 年报同时有“合并”和“母公司”两套报表，科目名几乎相同，只能取“合并”。
4. **不静默取舍。** 程序报告的冲突、缺失、勾稽失败，要么回原文修正，要么如实写进交付说明。
5. **估值假设不自己编。** 没有假设文件就问用户；用户要你起草时，必须标明“观点/假设”，并请用户确认后再跑。

## 准备

在仓库根目录执行命令。Python 用 `.venv/bin/python`（不存在时用 `python3`，并先
`pip install -r requirements.txt`）。下文写作 `PY`。

每家公司建一个工作目录 `data/extractions/<公司>_<年度>/`，抽取文件放这里并随代码提交，
评审无需模型即可从这些文件复现全部结果。

## 流程

### 1. 定位关键页

```bash
PY -m finagent locate --input <年报.pdf>
```

输出 `suggested_reads`（建议读的页码范围）、`parent_only_pages`（母公司报表页，注意避开）、
`unit_hints`（各页单位）、`no_text_layer_pages`（扫描页）。若关键章节没找到，用 Grep/Read 在目录页里找页码。
`sections.quarterly` 是年报“分季度主要财务指标”页，单季数据要一并抄。

**同时有季报时**（用户要单季数据，或给了一季报/半年报/三季报）：年报作 `--input`，季报对每份也跑一次 `locate`，
抽取时条目写 `source_file`，后续命令都加 `--supplement <季报>`（可多次）。单季由程序拆分：
Q4 = 全年 − 前三季度累计，Q3 = 前三季度 − 半年度，Q2 = 半年度 − 一季度，写法见 extraction.md“季度数据”。

### 2. 读页并抽取

用 Read 工具按页读 PDF（`pages` 参数，每次不超过 20 页），只读 `suggested_reads` 及必要的相邻页。
指标清单与字段要求见 [references/extraction.md](references/extraction.md)（也可运行 `PY -m finagent schema`）。

把结果写成 `data/extractions/<公司>_<年度>/facts.json`。本期和上期（比较期）两列都要抄。

### 3. 校验与修正（循环，最多 3 轮）

```bash
PY -m finagent verify-facts --input <年报.pdf> --year <年度> --facts data/extractions/<公司>_<年度>/facts.json [--supplement <季报.pdf>]
```

返回 `ok: true` 才能继续。否则按输出逐项处理：

| 输出 | 含义 | 处理 |
|---|---|---|
| `rejected` | 数字没在所写页码的原文里找到 / 字段不合法 / 非合并口径 / `source_file` 未传入 | 回到该页核对：页码、数字写法、单位、是否误取母公司报表；季报条目检查 `source_file` 与 `--supplement` |
| `conflicts` | 同一指标两处取值不同，或与程序规则通道结果不同 | 回原文确认哪个对；确属原文不一致的，保留并在交付说明中写明 |
| `tieout_failures` | 勾稽不平（资产≠负债+权益、第四季度≠全年−前三季度等） | 通常是抄错一位、期间列看反，或把累计数当成单季，回表核对 |
| `missing` 且 `blocking: true` | 本期核心指标缺失 | 去对应报表补抄；财报确实没有的写明原因 |

3 轮后仍未解决的问题，不要硬改数字，如实写进交付说明。

### 4. 研报断言（有研报草稿时）

读研报草稿，把可核验的数字断言写成 `data/extractions/<公司>_<年度>/claims.json`，
字段见 [references/claims.md](references/claims.md)。你只负责拆句和标注，对错由程序判断。

### 5. 运行计算与报告

```bash
PY -m finagent all --input <年报.pdf> --year <年度> --company <公司> \
  --assumptions <假设.json> --report <研报草稿> \
  --facts data/extractions/<公司>_<年度>/facts.json --claims data/extractions/<公司>_<年度>/claims.json \
  [--supplement <季报.pdf>] --llm off
```

可选：`--peers`、`--estimates`、`--guidance`（格式见 `data/samples/`）。只做财报分析用 `financials`，
不核查研报时去掉 `--report/--claims` 并改用 `valuation`。命令会打印运行目录 `runs/<run_id>/`。
要分析单季（如第四季度）加 `--period 2024Q4`，同比、环比按单季计算。

估值口径（写解读、起草假设文件时要知道）：

- 程序先跑三表模型，**DCF 的收入、EBIT、折旧摊销、资本开支、营运资本和税率都取自三表模型同一情景**。
  假设文件的情景只需要 `revenue_growth`、`capex_percent_revenue`、`terminal_growth_rate`、`wacc_adjustment`；
  利润率、周转天数的情景差异写在 `three_statement.gross_margin_shift` / `ar_days_shift`（样例见
  `data/samples/valuation_assumptions.json`）。旧文件里的 `ebit_margin` 等字段会被忽略，报告里有提示。
- EBIT = 利润总额 + 财务费用 − 投资收益 − 公允价值变动收益。剔除的投资类资产应在假设文件 `non_operating_assets`
  中加回，未设置时报告会提示“每股价值偏保守”。
- comps 工作簿（`valuation/comps_formula_workbook.xlsx`）有“利润率对比”页，可用来解释目标公司倍数的溢价/折价。
- `valuation/model.xlsx` 与 comps 工作簿按投行模型排版（输入蓝、公式黑、跨表引用绿，千分位括号负数，期间横排）。
  新增或修改工作表必须遵守 [references/workbook.md](references/workbook.md)，交付前在 Excel 中打开自查。

### 6. 写解读并过数字护栏

读 `runs/<run_id>/` 下的 `financials/report.md`、`financials/analysis.json`、`valuation/report.md`、
`check/report.md`，写一段中文解读（结构与要求见 [references/commentary.md](references/commentary.md)），存为文件后：

```bash
PY -m finagent guard --run-dir runs/<run_id> --text <解读.md>
```

`guard` 做两道检查，`ok: true` 才算通过：

- `unverified_numbers`：数字按单位和展示精度（“58.62 亿元”对应真值 ÷1e8 保留两位）在本次运行的结论性产物里
  找不到出处。改成产物里的数字，或删掉。研报草稿里的数字不算出处。
- `mismatched_claims`：能识别的“指标 + 数字”表述（如“营业成本 35.22 亿元”）按指标和期间核对真值表后不符，
  附正确值与原因（口径/期间/单位/数值）。按正确值改写。

护栏只能核对程序能识别的表述，不能替代你对“数字配对了正确的指标和期间”的自查。通过后解读会存入运行目录的
`commentary.md`。

### 7. 交付

向用户汇报：运行目录、核心结论（营收/利润变化、主要异常信号、估值区间、研报错误条数）、
未解决的校验问题，以及抽取文件路径。说明结论“不构成投资建议”。
