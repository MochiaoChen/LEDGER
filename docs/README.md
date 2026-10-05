# 文档索引

| 文档 | 内容 | 状态 |
|---|---|---|
| [architecture.md](architecture.md) | 系统架构：计算引擎、角色说明、多 Agent 编排（隔离工作区、五个无头 Claude Code 会话、11 道闸门）、质检循环、追踪与复现 | **以此为准** |
| [eval-dataset-collection.md](eval-dataset-collection.md) | 评测集收集清单（年报季报、卖方研报人工埋错） | 进行中 |
| [design/](design/) | 设计过程记录（按日期） | 历史记录 |

`design/` 下的文档记录当时的讨论与方案，其中提到的 DeepSeek 执行器、程序内调用国产模型的 Agent 版本、Codex 执行器
均已删除；现行架构只有“多 Agent + 无头 Claude Code + 确定性计算引擎”一条路线，以 [architecture.md](architecture.md) 为准。
