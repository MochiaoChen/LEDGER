# 前端选型：TUI 还是网站

> 2026-10-04 · 调研结论，待拍板。初赛截止 2026-10-18，决赛 11 月底（现场演示 + 答辩）。

## 0. 结论

**先做 TUI，用 Textual（Python）。** 同一套代码用 `textual serve` 就能在浏览器里打开，决赛要网页演示时不用重写。
Streamlit / FastAPI + React 的网站推迟到决赛之后再看是否需要。

理由：

1. **跟流水线的形态对得上。** 一次研报生成要 30～60 分钟、三个 Agent 会话，状态全部落在工作区文件里
   （`.pipeline/`、`runs/`、`eval/`）。前端只是这些文件的“看板”，不需要服务端、数据库和任务队列；TUI 直接读文件即可，
   评审在自己机器上 `python -m finagent.tui` 就能看。网站需要先起后端、处理长任务和 SSE 推送，工作量大一档。
2. **同一种语言。** Textual 是 Python，能直接调用 `report_pipeline.status()`、`evaluation.rubric.score()` 这些函数，
   不用再包一层 API。Ink（Claude Code 用的 React 终端框架）、Bubble Tea（Go）、Ratatui（Rust）都要换语言。
3. **演示效果。** 初赛视频里，一个全屏终端看板（闸门时间线、三个 Agent 的实时事件流、refine 每轮分数、
   点一个数字跳到年报第几页）比滚动的日志好看得多，也比套模板的网页更“工程感”。
4. **一码两用。** Textual 的应用可以用 `textual serve` 发布成网页（浏览器里渲染同一个 TUI），决赛现场投屏、
   给评委发链接都可以。

## 1. 候选方案对比

| 方案 | 语言 | 优点 | 缺点 | 适合 |
|---|---|---|---|---|
| Rich（只做美化输出） | Python | 半天就能做：进度条、表格、彩色闸门状态 | 不能交互，不能翻看产物 | 作为 CLI 输出的底线改进 |
| **Textual** | Python | 完整 TUI：多屏、表格、树、日志流、键盘鼠标；CJK 宽字符处理好；可 `textual serve` 发布到浏览器 | 终端里不能内嵌 PDF / 图表图片（只能调系统查看器，或用文本图） | **推荐** |
| Ink | TypeScript/React | Claude Code 同款 | 换语言，要包一层 API | 不选 |
| Bubble Tea / Ratatui | Go / Rust | 性能好、好看 | 换语言 | 不选 |
| Streamlit | Python | 网页、能嵌 PDF 和图表、写得快 | 长任务和实时事件流别扭（脚本每次交互整页重跑）；样式模板化 | 决赛后如需网页再考虑 |
| FastAPI + React | Python + TS | 最灵活、最像产品 | 工作量最大，两套代码 | 不在比赛周期内 |

## 2. TUI 设计草案

入口：`python -m finagent.tui [--workspace <工作区>]`。放在 `finagent/tui/` 还是独立目录待定：`finagent/` 约定只用标准库，
Textual 是第三方依赖，建议放 `apps/tui/`，在 `requirements.txt` 标为可选，并登记 `THIRD_PARTY.md`（Textual，MIT）。

| 屏 | 内容 | 数据来源 |
|---|---|---|
| 任务 | 工作区列表（公司、阶段、最近分数、是否达交付标准）；新建任务（公司、年度、股价与来源） | `report_pipeline build/status`、`eval/results/` |
| 运行看板 | 10 道闸门时间线（通过 / 未通过 / 过期）；Generator / Reviewer / Evaluator 三栏实时事件流；refine 每轮总分折线 | `.pipeline/`、`.pipeline/agents/*.jsonl`、`loop.json` |
| 真值表 | 抽取指标 × 期间表格；选中一个数显示来源（文件、页码、表、行列、是否续表）、双通道是否一致、勾稽结果 | `facts.verified.json`、`analysis.json` |
| 估值 | DCF 三情景、敏感性矩阵、股权价值桥；“打开 model.xlsx / 研报 PDF”调系统程序 | `runs/<id>/valuation/` |
| 评测 | L0～L3 与负向条目逐条：判定、证据、理由；多份研报并排对比 | `eval/results/*/score.json` |
| 追溯回放 | 按时间顺序回放 trace：读了哪些文件（哈希）、调用了哪些工具、写了哪些产物 | `runs/<id>/trace.jsonl` |

初赛视频建议只录“运行看板 → 真值表点数字回溯 → 评测逐条”这三屏。

## 3. 工作量与排期

| 事项 | 估计 |
|---|---|
| 任务 + 运行看板（读文件、定时刷新、事件流） | 1.5 天 |
| 真值表 + 来源定位 | 1 天 |
| 估值 + 评测两屏 | 1 天 |
| 追溯回放 | 0.5 天 |
| `textual serve` 网页发布、录屏调样式 | 0.5 天 |

约 4～5 天。若初赛前时间紧，先做“运行看板 + 真值表 + 评测”三屏供录视频。

## 4. 待拍板

1. 是否按上面的方案做 Textual TUI（还是只做 Rich 美化 CLI）。
2. 目录放 `apps/tui/` 还是 `finagent/tui/`（后者要放宽“只用标准库”的约定）。
3. 初赛前做到哪几屏。
