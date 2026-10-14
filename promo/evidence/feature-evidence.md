# 卖点证据

所有上屏数字由 `tools/gen_data.py` 从仓库与工作区产物读出，或调用引擎函数得到，写入 `src/data/data.json`；没有手写的数字。
工作区：`~/finagent-samples/中际旭创_2025`（2026-10-03 建，仓库提交 c131c2c）。

| 镜头 | 主张 | 状态 | 来源 | 演示范围与限制 |
|---|---|---|---|---|
| hook | 研报正文 20,291 字、650 个带单位的数字；无出处数字 0 | 已实现 | `narrative.md` 经 `finagent/output/numlock._tokens` 统计；`commentary_guard.json` 的 `unverified_numbers` | 650 是复核改写后的数；“带单位的数字”按数字锁的口径（年份、一位序号不计） |
| brand / rule | 模型只读、抄、写、判断，计算由确定性 Python 完成 | 已实现 | `CLAUDE.md` 设计规范 1；`docs/architecture.md` | “约三倍”的例子出自设计规范原文，画面里被挡回是示意，不是某次运行的日志 |
| cmd | 一条命令建隔离工作区，依次起五个无头会话 | 已实现 | `finagent/report_pipeline.py`；`.pipeline/agent_runs.json` 的角色与模型 | 命令按 CLAUDE.md 的模板代入本工作区的公司、年度、股价；终端输出是按事实排的示意，不是原始回显 |
| search | 研究助理 29 次检索、41 次抓取、506 秒；51 个来源、184 条带数字摘句、核对问题 0 | 已实现 | 见 `session-research.md`；`research/sources.json`；`finagent.output.sources.verify_sources` 的返回值 | 事件流只压缩了时间，文字来自原始记录（长行截断）；闸门 1 的文字是 `status` 原文 |
| read | 模型把数字原样抄进 facts.json，带页码；共 98 条 | 已实现 | `facts.json`；年报第 94 页原图（pdftoppm 渲染）；单元格位置由 pdfplumber 取 | 第二条（2024 年营业收入）是同一格式的同表事实 |
| code | `find_evidence` 按数字边界在所写页码查找；原样命中、改一位拒收、只给整数部分拒收 | 已实现 | `finagent/tasks/financials/external.py:40-65`；三次调用的结果由 gen_data.py 实际调用引擎得到（命中 c0351；两次 None） | “改一位”是为演示构造的输入，画面上已标“演示”；拒收文字按 `_to_fact` 的格式生成 |
| truth | 真值表是唯一数据来源；98 条入账、拒收 0、冲突 0、8 项勾稽通过；同比由程序算；异常信号把事实与推论分开 | 已实现 | `facts.verified.json`；`analysis.json` 的 `truth_table`、`changes`、`tieouts`、`signals` | 本次运行规则通道没有参与比对（`rule_facts: 0`），所以片中不讲“双通道比对” |
| depth | 15 个驱动、4 个深度专题由分析师会话推导；研报含产业链图；专题调研补充 16 个问题、共 51 个来源 | 已实现 | `report/framework.md` 的“驱动清单”“深度专题”；`runs/…/report/charts/chain.svg`（reportkit `C.flow` 生成，原样上镜）；`status` 第 3、4 行 | 驱动标签去掉了括号里的单位说明；“不预设行业框架”出自 CLAUDE.md 设计规范 11 |
| compute | 三情景 DCF、敏感性、WACC；工作簿 15 张表 865 条公式 | 已实现 | `valuation/valuation.json`；`valuation/model.xlsx`（公式由脚本从 xlsx 的 XML 里数出） | 估值是系统输出示例，画面标“不构成投资建议”；不展示评级 |
| write | guard 核对出处：无出处数字 0、指标期间不符 0、外部数字缺引用 0 | 已实现 | `commentary_guard.json`；`narrative.md` 两段原文；`sources.json` 的来源信息 | 右栏“数字 → 来源编号”的配对规则是“数字后面最近的编号”，是为画面做的简化 |
| review | 数字锁：665 → 650，新增 0 | 已实现 | `finagent/output/numlock.py:29`；`numlock(draft, final)` 的返回值；改写前后真实句对 | 句对是从两稿里按“数字相同、措辞不同”筛出来的一对 |
| layout | 30 页、68 个图表；11 道闸门全部通过 | 已实现 | `中际旭创1003.pdf` 逐页渲染；`status` 原文 | 页面缩略图看不清正文，只交代规模 |
| qc | 四层 40 条评分项（程序判 18、盲评 22），总分 90；三个版本 46～49 → 74/67 → 90/88；重复盲评逐条一致 86%～91%、总分极差 7～8 | 已实现 | `eval/results/*/score.json`；`eval/calibration/summary.json` | 版本对比是单次盲评，评分标准 v0；重复盲评的三次总分是 85/80/78 与 80/88/83，和单次的 90/88 不是同一次 |
| check | 纠错核查判断错误类型；注入实验 1,334 条断言、754 条含错，召回 100%、误报 0、类型判对 99.5% | 已实现 | `runs/20261013-160800-all/check/findings.json`；`paper/techreport/sections/13_experiments.tex` 表 exp-tol | 草稿是仓库里的虚构公司样例；注入实验只衡量核对与诊断，不含从文本里抽断言 |
| trace | 终端界面可回看闸门、真值表、追溯、会话 | 已实现 | `finagent_tui/app.py`；`tools/tui_shot.py` 导出的 SVG | 10 次会话、144 分钟、825 轮含返工与失败的会话 |
