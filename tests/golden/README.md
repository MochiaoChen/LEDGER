# 金标准快照（原插件引擎产出）

本目录下的 JSON 是 2026-09-24 用**原 Public Equity Investing 插件引擎**（改造前的 `vendor.load` 版本）
跑样例数据得到的产物，命令：

```bash
python -m finagent all --input data/samples/annual_report_2024.md --year 2024 --company 星河智造 --assumptions data/samples/valuation_assumptions.json --report data/samples/research_draft.md --peers data/samples/peers.csv --estimates data/samples/estimates.csv --guidance data/samples/guidance.csv
```

`tests/test_golden.py` 要求自研引擎的产物与这些文件**完全相等**（逐字段、浮点逐位），
即使不再保留原插件代码，也能持续校验“改造后效果与原来一致”。

除非有意修改计算口径，否则不要重新生成这些文件；如需修改，请在 PR 中说明差异原因。

## 变更记录

- 2026-09-28：有意修改口径后重新生成（引擎代码未改，`test_parity_reference.py` 仍与原插件逐项一致）。
  - `three_statement.json`：历史 EBIT 改为利润总额 + 财务费用 − 投资收益 − 公允价值变动收益，经营费用改为轧差项
    （原“销售+管理+研发”未扣除已计入成本费用的折旧摊销，EBIT 被重复扣减）；新增 `dcf_drivers`；样例假设文件新增悲观/乐观情景的
    毛利率与应收天数调整。
  - `scenarios.json`：DCF 改由三表模型驱动后三情景目标价变化。
  - `comps.json`：目标公司 EBIT/EBITDA 口径变化；新增逐家利润率与 `margins` 统计。
  - `earnings.json`：数值不变，样例年报新增第 7 页分季度表后 chunk 编号后移。
