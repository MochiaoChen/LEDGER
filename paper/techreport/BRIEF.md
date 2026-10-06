# 技术报告写作总则（所有 subagent 必读）

## 任务
为 FinAgent（2026 北京市大学生金融 AI 竞赛，选题 2 财报分析 / 4 估值建模 / 5 研报纠错）写一份**完整、超长、顶会体例（NeurIPS/ICLR 风格）的中文技术报告**。
目标读者：懂 ML/LLM 系统、也懂基本公司金融的评委。全书预计 120+ 页，你负责其中若干章节。

## 硬规则
1. **只依据源码、skill、docs、测试、eval/ 与 runs/ 等产物来写。严禁打开或参考 `paper/sections/`、`paper/main.tex`（旧稿，用户明确不要参考）。**
   仓库根目录：`/Users/mochiaochen/Desktop/OpenAI fin/public-equity-investing/contest`。先读根目录 `CLAUDE.md` 与 `docs/architecture.md` 了解全貌，再精读你负责模块的**全部源码**。
2. 只写你被分配的文件（`paper/techreport/sections/XX_*.tex`），不要改其他文件；不要改仓库代码；不要 git commit。
3. 写完用 `bash paper/techreport/check.sh sections/XX_name.tex` 编译检查（在 paper/techreport 目录下执行），必须 OK 无错误；尽量消除大的 Overfull。
4. 中文撰写，重要术语首次出现标英文，如“真值表（truth table）”。标识符/文件名用 `\code{}`、`\file{}`（下划线要转义 `\_`）。
5. 不要写 `\documentclass`、`\usepackage`、`\begin{document}`；宏都在 `macros.tex`（请先读它和 `neurips_cn.sty`）。
   可用：`\sysname`、`\code`、`\file`、`designbox{标题}`、`tradeoff`、`insight`、`failcase` 盒子、`definition/proposition/invariant/example` 环境、
   `algorithm` + `algpseudocodex`（`\begin{algorithmic}[1] \State \If \For \Function` 等）、`lstlisting`（只放 ASCII 代码/JSON，中文注释会出问题——如需中文，用 `\texttt` 表格或 verbatim 前先测试）、
   TikZ（样式 `prog` 蓝=确定性程序、`agent` 橙=模型会话、`gate` 红=闸门、`file`、`arr`、`darr`）、pgfplots、booktabs/tabularx/longtable/multirow。
   如需额外宏，请在章节文件内用唯一前缀定义（如 `\newcommand{\valX}`），避免冲突。
6. **标签规范**：节 `sec:<key>`（如 `sec:valuation`、`sec:val-dcf`），图 `fig:<key>-...`，表 `tab:<key>-...`，式 `eq:<key>-...`，算法 `alg:<key>-...`。
   各章的节标签（可跨章 \ref）：sec:intro, sec:related, sec:problem, sec:principles, sec:arch, sec:extract, sec:analysis, sec:valuation,
   sec:reportcheck, sec:guards, sec:pipeline, sec:eval, sec:exp, sec:discussion, sec:limits, sec:conclusion；附录 app:repro, app:rubric, app:gates, app:schemas, app:degrade, app:prompts, app:thirdparty。
7. **记号统一**（第 3 节定义，你直接用）：年报 $\Doc$、页集合 $\Pages$、事实 $f=(m,k,v,u,\Src)$（指标 $m\in\Metrics$、期间 $k\in\Periods$、数值 $v$、单位 $u$、来源 $\Src=(\text{source},\text{page},\text{chunk\_id},\text{row},\text{col})$）、
   真值表 $\Truth$、研报断言集 $\Claims$、外部来源登记 $\Sources$、文稿 $\Narr$、本次运行结论性产物 $\Art$、闸门 $\Gate_i$；`\halfulp`、`\yoy`、`\qoq`。
8. **引用**：先看 `paper/techreport/refs.bib` 已有条目并优先引用。可新增**真实存在**的文献（你确信存在、元数据准确），写到 `paper/techreport/bib/<你的章节号>.bib`，key 用 `作者姓年份关键词` 风格；不要编造文献。
9. **编造许可**：用户允许“有的内容可以编造”（如缺失的实验数字、消融结果、成本统计、案例细节）。规则：**凡是仓库里查不到依据的数字或事实，一律用 `\fab{...}` 包起来**（草稿里会标橙，便于团队之后核实/替换）。仓库里能查到的真实数字不要包。编造要合理、内部自洽、与真实数字量级一致，不能与仓库真实数据矛盾。
10. **风格**：像顶会论文但长得多、细得多。每个设计都要讲清：动机（遇到的真实问题）→ 形式化定义/算法（公式、伪代码）→ 实现要点（指到具体模块/函数）→ 正确性或性质论证 → **权衡（trade-off，用 `tradeoff` 盒子，讲考虑过的替代方案及为什么不选）** → 失败案例/边界情况 → 小结。
    多画 TikZ 结构图/流程图，多用表格；写公式时给变量含义。突出创新点。避免空话、营销腔、“不是…而是…”式机器腔、过度排比。论证要具体到机制。
11. 篇幅：你负责的每一章目标 **12～25 页**（即每个 .tex 约 700～1500 行）。宁可详尽。
12. 完成后回复：写了哪些文件、页数、主要小节标题列表、用了哪些 `\fab`（简述）、新增了哪些 bib key、引用的跨章标签。
