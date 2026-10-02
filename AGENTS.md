# AGENTS.md

本仓库的开发指南、比赛约束与设计规范写在 [CLAUDE.md](CLAUDE.md)，对所有 AI 工具同样适用，先完整读它。

skill 全文在 `.claude/skills/`，`.agents/skills/` 下是给 Codex 等工具的入口（由
`python -m finagent.report_pipeline sync-skills` 生成，不要手改）。为新公司出研报、或让多个模型对比测评时，
用 `finagent-pipeline` skill：在隔离工作区里执行，不要在本仓库里直接写研报。
