---
name: finagent-pipeline
description: 研报生成流水线与模型测评入口：为一家 A 股公司搭隔离工作区，交给 Claude Code、Codex 或 DeepSeek 按阶段产出深度研报 PDF 与估值模型，查闸门、收回仓库；也可让多个模型各跑同一家公司并出对比表。用户要“给某公司出研报 / 跑研报流水线 / 测评研报生成”时使用。
---

# finagent-pipeline

本 skill 的全文与配套文件在 `.claude/skills/finagent-pipeline/`（相对仓库或工作区根目录）。先完整读 `.claude/skills/finagent-pipeline/SKILL.md`，按其中的流程执行：文中 `references/`、`templates/`、`reportkit/` 等链接相对该目录，命令和 `data/`、`runs/` 等路径相对根目录。
