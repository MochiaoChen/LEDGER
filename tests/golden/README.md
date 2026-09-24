# 金标准快照（原插件引擎产出）

本目录下的 JSON 是 2026-09-24 用**原 Public Equity Investing 插件引擎**（改造前的 `vendor.load` 版本）
跑样例数据得到的产物，命令：

```bash
python -m finagent all --input data/samples/annual_report_2024.md --year 2024 --company 星河智造 --assumptions data/samples/valuation_assumptions.json --report data/samples/research_draft.md --peers data/samples/peers.csv --estimates data/samples/estimates.csv --guidance data/samples/guidance.csv --llm off
```

`tests/test_golden.py` 要求自研引擎的产物与这些文件**完全相等**（逐字段、浮点逐位），
即使不再保留原插件代码，也能持续校验“改造后效果与原来一致”。

除非有意修改计算口径，否则不要重新生成这些文件；如需修改，请在 PR 中说明差异原因。
