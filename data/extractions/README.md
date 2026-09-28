# 模型抽取结果（Skill 版本）

Skill 版本中，Claude Code 里的模型读年报 PDF 后写出的抽取文件放在这里，**随代码提交**：

```
data/extractions/<公司>_<年度>/
  facts.json    财务数据（格式见 .claude/skills/finagent-research/references/extraction.md）
  claims.json   研报断言（格式见 .claude/skills/finagent-research/references/claims.md）
```

评审复现不需要调用任何模型：用这些文件加 `--facts` / `--claims` 重跑 `python -m finagent all ...`，
程序会重新做逐字证据校验、规则通道交叉比对与全部计算，结果与提交时一致。
