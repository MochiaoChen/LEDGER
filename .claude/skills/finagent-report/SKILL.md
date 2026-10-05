---
name: finagent-report
description: 为 A 股公司生成卖方体例的年报点评暨深度研究 PDF（25～30 页、60 个以上图表）：在 finagent-research 跑完抽取与估值之后，补抄年报经营数据、写分析文稿并过数字护栏，再用 reportkit 排版成带目录、图表目录和免责声明的 PDF。用户要为某家公司出“研报 / 深度报告 / 年报点评 PDF”时使用。
---

# FinAgent 研报生成（深度报告）

**新公司建议走流水线**：在仓库里运行 `python -m finagent.report_pipeline build --company <公司> --year <年度>`
搭隔离工作区（只含两个 skill、引擎和该公司年报），在工作区里按其 CLAUDE.md 分阶段执行，`status` 查闸门，完成后 `collect`
收回仓库。你若已在工作区内（根目录有 `sample.json`），以工作区 CLAUDE.md 为准，下文提到的茅台样例不在工作区里。

前置：已按 `finagent-research` 完成抽取、校验和估值，有一个运行目录 `runs/<run_id>/`（含 `valuation/`）。
没有的话先跑那个 skill。数字规则、版式细节的完整规范见
`.claude/skills/finagent-research/references/html-report.md` 与 `writing.md`，本 skill 讲怎么把一份报告做出来。

样例：贵州茅台 `data/extractions/贵州茅台_2025/report/`（`build_report.py` + `narrative.md`；它早于本 skill，没有 framework.md），
产物 `runs/20260929-145916-valuation/report/贵州茅台0929.pdf`（21 页、56 个图表）。

## 一、不可协商的约束

这些是比赛规则和可追溯性的底线，违反就返工：

1. **数字只来自运行产物。** 正文数字必须过 `guard`；图表数字由脚本从产物 JSON 读出，脚本只做单位换算与格式化。
   增速、占比、差值、单价这类派生数**不要自己算**（包括心算约数，如“约三倍”“超过四成”），写成 extras 的 `ratios`
   让程序算（`op: growth / diff`，见 extraction.md）。
2. **年报之外的信息要检索、登记、标明来源，不能凭记忆。** 行业数据、排名、价格、竞争对手、年报后的事件，
   用 WebSearch / WebFetch 现查，登记进 `research/sources.json`，正文句末加 `[S编号]`（方法见 `references/research.md`）。
   股价是外部数据，估值参数是分析师假设，在出现处注明。
3. **措辞区分事实、推论、观点**：事实直接陈述；推论用“主要系”“反映”；观点用“我们认为”“我们预计”。
   公司没披露、产物也算不出的判断（“行业最强”“首次”），要么找数据支撑，要么改成观点措辞，要么删掉。
4. **写给投资者看，不是写给审核者看。** 不写否定对照（“不是……而是”“而非”）、自证圆场（“佐证”“与……一致”
   “年报未披露”“属分析师假设”）、程序口吻（“程序预测”）和口语套话（“不过”“具体来看”），规则与改写示例见
   `writing.md`。拿不准但重要的内容写进 `report/review.md` 复核清单，不进正文；拿不准又不重要的不写。
   文稿写完后由独立会话按 `finagent-review` skill 复核改写（只改措辞与结构，数字锁保证不碰数字）。
5. **评级取程序结果**（`forecast_summary.rating`），不自己定。“不构成投资建议”只出现在免责声明里。
6. **字体与免责声明共用**：正文固定 10.5pt，Times New Roman + 楷体；表格、图表的数字用 Helvetica，汉字用楷体。
   免责声明用 `reportkit/disclaimer.md`，不要逐份改写。交付前确认 PDF 里没有意外嵌入其他中文字体。
   配色统一用红色主题（`core.py` 颜色常量 + `report.css`），不再提供主题切换；公司脚本画图取 `core` 的颜色常量，不写死色值。

## 二、交给你判断的部分

模板和茅台样例是参考，不是清单。每家公司的投资逻辑不同，你应该：

- **先找故事，再定结构。** 通读年报的管理层讨论与分析、经营性信息和附注，回答三个问题：这家公司今年最重要的变化是什么？
  变化背后的业务驱动是什么？驱动明年还会不会延续？章节标题、顺序和篇幅都围绕这条主线安排。
- **分析框架自己推导。** 本 skill 不预设任何行业该看什么。读完年报，按 `references/analysis.md` 的方法推导这家公司的
  收入与利润驱动、领先指标和预测参数，写成 `framework.md`。茅台的框架只是推导示例，不是模板。
- **章节自己取舍。** `references/sections.md` 列的是报告里常见的章节和现成图表，按框架增删、合并、重排、新增。
- **图表服务论点。** 每张图都要支撑正文里的一个判断，没有判断的图不放。reportkit 原语不够用就在公司脚本里画，
  也可以往 reportkit 加通用原语（同时保证茅台样例还能跑）。
- **补哪些年报表格由你决定**：以 framework.md 的驱动清单为准。
- **年报点评 + 深度研究，25～30 页。** 年报点评约占 1/3（业绩、盈利、资产负债与现金流、年报之后的最新进展）；
  深度研究约占 2/3（行业空间、竞争对标、核心竞争力、3～5 个深度专题、预期差、估值交叉验证），正文不少于 15,000 字、
  图表不少于 60 个。联网是为了把研究做深：每个深度专题多来源交叉、多环定量推导，而不是摘几条新闻点评。
  内容不够时回去补深度调研，不要缩短篇幅，也不要用重复的图表和空话凑页数。
- **排版要好看。** 这份报告要给人看：基于 `templates/build_report.py` 写公司定制脚本，参考 `templates/examples/`
  三份 20 页级样例的配图密度与写法；表格的同比、变动列用 `chg()` 涨跌双色；逐页检查留白、重叠与孤立标题。
- **遇到规范没覆盖的情况**，按“可追溯、不误导、读者友好”三条原则自己处理，并在交付说明里告诉用户你怎么做的。

## 三、流程

每家公司的文件放在 `data/extractions/<公司>_<年度>/report/`。

0. **先搜集最新信息。** 动笔之前，按 `references/research.md` 第一部分联网搜齐年报之后的定期报告、行情、卖方预期、
   可比公司、行业、竞争与近期事件，写成资料包 `research/dossier.md`（流水线里由独立的研究助理会话完成）。
   后面的框架、预测、估值和文稿都建立在资料包之上。
1. **读年报、推导框架。** 先读资料包，再通读管理层讨论与分析、经营性信息和相关附注，按 `references/analysis.md` 写出
   `framework.md`：投资主线（3～4 条核心观点，也是首页“投资要点”和第 1 节的骨架；每条过 analysis.md“投资主线写到什么程度”六项）、驱动清单（年报位置 → extras →
   报告章节 → 预测参数）、披露局限、章节结构。
2. **补充调研。** 资料包没回答、框架又需要的问题，按 framework.md 的外部调研清单逐题联网检索，追加到 `research/sources.json`，
   `PY -m finagent verify-sources --sources .../research/sources.json` 到 `ok: true`（见 `references/research.md` 第二部分）。
3. **补数据。** 按驱动清单把要用的表格逐格抄进 `extras.json`（原文写法、带页码），派生比率写进 `ratios`，行和比率可加 `alias`
   （正文里的简称）。`PY -m finagent verify-extra ...` 到 `ok: true`，再重跑 `valuation --extras ...` 生成新的运行目录。
4. **写文稿**（`narrative.md`，从 `templates/narrative.md` 复制）。先写完全部分析，再排版。写完跑
   `PY -m finagent guard --run-dir runs/<run_id> --text narrative.md --sources ../research/sources.json`，
   直到 `ok: true`（数字与外部来源）；护栏不认识的正确表述，
   先检查措辞（见下面“常见坑”），确属护栏局限再考虑给 extras 行加 alias 或改进 guard。
   过了护栏还要自查：数字配对的指标和期间对不对，推论有没有超出披露。
   然后交给 **finagent-review**（另开会话最好）：备份初稿、编辑改写、数字锁 `numlock`、重跑 guard。
5. **写编排脚本**（从 `templates/build_report.py` 复制）。标准图表直接调用 reportkit；公司专属图表从 `run.cell()` /
   `run.ratios` 取数后调用原语。关键假设表的“依据”列要写明对应正文第几节。
6. **渲染与自检。** `PY data/extractions/<公司>_<年度>/report/build_report.py --run-dir runs/<run_id>`，
   脚本会两遍打印（回填目录页码），输出逐页预览和每 8 页一张的缩略图 `preview/sheet*.png`。
   公共渲染器打印前检查 A4 版心溢出、正文 10.5pt 和图表加载，打印后在 PDF 正文原文中实测字号；
   通过才替换 PDF，并写 `report/render_check.json`（绑定 HTML、PDF 与排版代码的哈希）。失败时修表头换行、
   表格宽度或改整栏；不要缩小正文、设置 zoom/transform，或用裁切隐藏溢出。流水线排版闸门核对这份凭证。
   先看缩略图找大块留白、孤立标题、只溢出一两行的页；再逐页看图表文字是否重叠、数字是否清楚。
   留白多时：缩小图高、调整图文顺序、给长表格加 `cls="split"` 允许跨页。
7. **交付。** 确认 `report/review.md` 复核清单已写（finagent-review 产出），
   `Config.output_name` 设成用户要的文件名（如“贵州茅台0929.pdf”）。向用户报告：PDF 路径、页数与图表数、
   核心结论、哪些输入是假设或外部数据、复核清单。

## 四、reportkit 速查

在公司脚本开头把 `.claude/skills/finagent-report` 加进 `sys.path`，然后 `from reportkit import charts as C, tables as T`。

| 模块 | 内容 |
|---|---|
| `core` | `Run`（`v(指标, 期间)`、`cell(表, 行, 列)`、`ratios`、`rows(表)`、`has(表…)`、`yoy(指标)`）；格式化 `yi / pct / pp / num / mm`；`md / md_parts`（按 `### ` 拆块）；配色常量 |
| `charts` 标准图 | `cover` `history` `quality` `quarterly` `cash_quarterly` `bridge` `segment_forecast` `margins` `scenarios` `ev_bridge` `football`（参数 `run, out`，传给 `doc.img(C.xxx, 宽度mm)`） |
| `charts` 原语 | `grouped`（分组柱，可标同比）`stacked`（堆叠柱）`signed`（正负柱）`hbars`（横条）`donuts`（环形）`progress`（进度条）`panels`（并排小柱）`composition`（单根构成条）；非数据图 `timeline`（时间轴）`flow`（产业链/链条示意）；返回 SVG 文件名，用 `doc.img(文件名, 宽度)` 嵌入 |
| `tables` 标准表 | `forecast` `three_year` `core` `quarterly` `balance` `assumptions` `segment_forecast` `wacc` `fcff` `scenario_table` `sensitivity(i)` `comps` `comps_implied` `nonop`；文字对比表 `text_table`；拼装工具 `table / tr / td / grp` |
| `layout` | `Config`（公司、代码、行业、日期、`side_rows`、`method_note`、`output_name`）；`Doc`（`fig` 自动编号、`img`、`h2`）；`two`（半栏并排）；`valuation_ranges(doc)`（估值区间图 + 产物里全部敏感性矩阵；有 `--peers` 时追加可比公司表）；`appendix`（报表预测、方法说明、免责声明）；`main(CFG, body)` |

半栏图宽 83mm、通栏 172mm。`doc.fig(标题, 内容, 注释, cls, src)`：注释追加在“资料来源”后，`src` 换成外部资料的发布方与 `[S编号]`；`cls="split"` 允许长表跨页，
`cls="half"` 占半栏宽。

数字精度按数量级自动取（`core.dec`）：金额或每股价值 ≥ 100 取整，否则两位小数，低价股、小公司不会被取整。
缺数据时标准部件整块跳过：没有分季度数据、没有分部预测（`run.seg` 为空）、没有可比公司时，模板里对应图表不出现。

**环境**：打印 PDF 需要 Chrome / Chromium / Edge，自动在常见路径和 PATH 里找，也可设 `FINAGENT_CHROME`。
非 macOS 环境字体回退到 Arial / KaiTi（Windows）或 Noto（Linux），交付前看 `preview` 里打印的嵌入字体。

**改 reportkit 之后必须跑** `PY -m pytest -q tests/test_report_kit.py`：它在茅台（经营数据最全）、样例星河智造
（有负债、有可比公司、低价股、无分部预测）和人为构造的亏损公司（无分季度、无可比公司）上各渲染一遍。
新公司暴露出 reportkit 的问题时，修在 reportkit 里并往这个测试加一个同类情形，不要只在公司脚本里绕过去。

## 五、常见坑（茅台样例踩过的）

- **汇总数的构成写错**（最严重的一次）：正文把股权价值桥的加回 1,789.15 亿元写成“拆出资金、货币资金等”，把扣减
  95.55 亿元写成“财务公司吸收的存款”；实际加回 = 货币资金 + 非经营性资产净额（已扣吸收存款），扣减 = 少数股东权益 +
  租赁等债务。数字都过了 guard，归属全错，读者对不上附表。**写任何汇总数的构成之前，先在产物里把它拆开**
  （估值桥看 `plan.json` 的 `ev_to_equity_bridge`、利润归因看 `earnings.json`）；同一数字在正文与图表、附录出现时，
  自查要把它们放在一起对账。报告里用 `layout.equity_bridge(doc)` 展示逐项估值桥，让读者也能对账。
- **心算取整出错**：Q2 环比 −23.3445% 心算写成 23.35%，guard 拦下。所有派生数都让程序算，照产物的展示值抄。
- **guard 读不懂“由 X 升至 Y”**：会把 X 当成本期值。写成“销售费用率 4.30%，上年为 3.30%”。
- **分部数字被当成公司整体**：“i茅台平台收入 130.31 亿元”会被当成营业收入核对。句中要点名分部（行名或 alias），
  季度数字写全“2025 年第四季度”，利润归因写“毛利率效应拖累 12.69 亿元”（归因项名称）。
- **估值产物单位是百万元**：正文写亿元即可，guard 已按 ×1e6 核对；WACC 参数取自 `plan.json`。
- **图例压住标注**：图例统一放图下方（原语已处理）；横轴标签长就用 `\n` 换行。
- **目录页码对不上**：标题里的全角符号在不同字体下抽出的字符不同，定位只比对文字与数字（已处理）；
  若提示“目录未定位”，检查标题是否太短或重复。
- **分部预测的单价单位**：引擎按“收入（百万元）÷ 销量 × 100”算单价，单位是“万元/<销量单位>”（茅台是万元/吨）。
  销量单位很大或很小时显示值可能不直观；`T.segment_forecast(run, volume_unit=, price_unit=, price_label=)` 与
  `T.assumptions(run, BASIS, price_label=)` 按公司写单位和名称。正文要用别的单价口径，在 extras 里写比率并给 `scale`。
- **可比公司倍数可能是字符串**：亏损或分母为负时 comps.json 里是 `"NM"`，自写表格也要能显示非数字。
- **页面大块留白**：成对的半栏图放不下会整体挪页。先看缩略图，再调图高或顺序。

## 六、文件

```
.claude/skills/finagent-report/
  SKILL.md                     本文件
  reportkit/                   共用代码：core / charts / tables / layout / render / render_probe.js / report.css / disclaimer.md
  templates/build_report.py    编排脚本模板（标准章节已接好，公司专属部分留 TODO）
  templates/narrative.md       文稿模板（分节与写作提示）
  references/analysis.md       从年报推导分析框架的方法（framework.md 写法；茅台推导示例）
  references/sections.md       常见章节、现成图表（含非数据图表）、需要的数据
  references/research.md       联网调研：先搜集（七个类别、资料包、可比公司表）、后补充；sources.json 登记与引用
```
