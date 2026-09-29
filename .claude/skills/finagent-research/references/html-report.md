# 研报（HTML → PDF）规范

交付物是**卖方研报级别**的报告（年报点评 / 深度报告），读者是投资者，不是程序的运行记录：
校验过程、运行命令、异常信号清单这些放附录“数据说明”，正文只写研究结论和支撑数据。
你写文字、设计图表和版式，用 Python 画图、生成 HTML，再用无头 Chrome 打印成 PDF。
**版式是你的，数字是程序的**：报告里的每个数字都来自本次运行的产物。

## 文件与分工

```
data/extractions/<公司>_<年度>/report/
  build_report.py      # 你写：读运行目录 JSON → 画图 → 渲染 HTML（随代码提交，评审可复现）
  narrative.md         # 你写：各节文字，先过 guard
runs/<run_id>/report/  # build_report.py 的输出
  charts/*.svg  report.html  report.pdf  preview/*.png（自检用）
```

运行方式固定为 `PY data/extractions/<公司>_<年度>/report/build_report.py --run-dir runs/<run_id>`，
换一次运行只需改 `--run-dir`。

## 数字规则（与铁律一致）

1. **表格和图里的数字由脚本从产物 JSON 读出**：`financials/analysis.json`（`truth_table`、`changes`、
   `quarterly`、`tieouts`）、`financials/earnings.json`（利润归因桥）、`financials/extras.json`（经营数据与吨价、
   占比等程序算出的比率，来自 `--extras`）、`valuation/forecast_summary.json`（盈利预测表与市场数据：总市值、P/E、P/B）、
   `valuation/valuation.json`、`valuation/three_statement.json`（附录财务报表预测）、`valuation/non_operating_assets.json`。
   不要在脚本里手写数字常量（刻度、字号、颜色等版式参数除外）。
2. 脚本只做**单位换算与格式化**（元 → 亿元、小数 → 百分数、保留位数），不计算新的比率、增速、合计。
   需要的派生值产物里没有时，要么不放，要么先改程序让它成为产物。
3. **正文文字写在 `narrative.md` 里，先过护栏**：`PY -m finagent guard --run-dir runs/<run_id> --text <narrative.md>`，
   `ok: true` 后才能渲染。写法同 [commentary.md](commentary.md)：事实 / 推论 / 观点分开，数字配指标与期间。
4. 不是来自本次年报的输入（股价、估值假设）要在出现处注明来源和“假设/外部数据”。
5. 不写投资评级（买入/增持等）和操作建议；估值结论用“每股价值区间 / 相对参考股价的空间”表述，
   程序产物里的“行动规则”等字段不放进研报。

`narrative.md` 用 `<!-- section: 名称 -->` 分节（如 `summary`、`performance`、`attribution`、`cashflow`、
`valuation`、`risks`），脚本按节取用，用标准库把 Markdown 段落、列表、`**加粗**` 转成 HTML 即可。

## 报告结构（A4 纵向，参照卖方年报点评）

**首页**（一页放完；放不下就精简要点，预测表不能挤到第二页）：

- 抬头：日期；公司（代码）与行业；右侧 FinAgent 字标（不得使用任何券商名称或标识）。
- 主标题两个短语、中间空格（“主品稳守基本盘　渠道改革穿越调整期”），下一行“——公司 年度 年报点评”，右侧“公司点评”，
  下方蓝色粗线。标题与小标题用楷体加粗。
- 左栏“投资要点”：每段“● 加粗小标题。”接正文——事件、业务结构、渠道、盈利能力、现金流与股东回报、
  **盈利预测及投资建议**（核心逻辑 → 预测 → 估值 → 评级）、风险提示。
- 右侧栏：投资评级（程序给出）、DCF 每股价值与区间、基本数据（股价、股本、市值、每股净资产、P/B、P/E、资产负债率、
  每股派息，表注写股价日期）、营收与归母净利润实际 + 预测小图（图例区分预测值）。
- 底部通栏“盈利预测与估值”：两个实际年度 + 三个预测年度的收入、增速、归母净利润、增速、EPS、P/E。

**正文**（章节标题写结论）：

| 章节 | 必备图表 |
|---|---|
| 1 业绩回顾 | 分季度收入与利润图；主要财务指标表（含费用率与同比） |
| 2 分产品与渠道 | 分产品收入与毛利率图；渠道结构图；主营构成表；量价拆分表；渠道、产能、库存 |
| 3 盈利能力 | 利润变动归因瀑布图；毛利率与费用率变化 |
| 4 现金流与股东回报 | 分季度经营现金流 vs 归母净利润；合同负债、存货、分红率 |
| 5 盈利预测与估值 | 关键假设（与第 2～4 节的业务变化逐条对应）；分部收入预测表；盈利预测表；三情景驱动与估值；每股价值区间图；敏感性 |
| 6 投资建议 | 核心逻辑 + 估值 + 评级（评级取程序结果） |
| 7 风险提示 | 与假设对应的风险 |
| 附录 | 财务报表预测（含现金分红）；股权桥调整项；估值方法说明；数据来源与方法；内容说明；投资评级说明；免责声明 |

- 图表统一“图表 N：标题”，图下“资料来源：公司公告，FinAgent”；正文与图注不写页码（页码在估值模型“历史财务”“经营数据”页）。
- 不用事实/推论/观点彩色标签；按 writing.md 用措辞区分，附录“内容说明”交代口径。
- 页眉：公司、代码、报告名；页脚：“请阅读最后一页的免责声明”和页码；“不构成投资建议”只在免责声明出现。

## 深度报告（约 20 页）

用户要深度报告时，先写完分析文稿、过 `guard`，再做排版：

1. **先补数据**：年报里的成本构成、采购、费用与税金明细、存货构成、区域、子公司、产能与在建项目、现金流项目、
   分红回购、股东与员工等表格抄进 `extras.json`（逐格核对）；增速、占比、差值写成 `ratios`（`op: growth/diff`），不自己算。
2. **文稿结构**：投资逻辑（核心观点 + 市场关注问题）→ 公司概况与行业 → 业绩 → 产品与产能 → 渠道与区域 → 盈利能力 →
   资产负债与现金流 → 股东回报 → 盈利预测（假设逐条对应前文）→ 估值 → 投资建议 → 风险。每节用 `### 小标题`
   分成若干块，脚本在块之间插图表（`md_parts`）。
3. **排版**：首页后加目录与图表目录，页码两遍生成（先打印一次按标题与“图表 N”定位页码，再回填）；图表自动编号；
   半栏图两两并排，长表格加 `split` 允许跨页（表头重复）；图例放在图下方，避免与数值标注重叠。
4. **自检**：除逐页看图外，先拼一张缩略图总览（每页 0.4 倍）找大块留白、孤立标题与单独一行溢出的页面。

完整流程、共用代码（reportkit）和模板见 **finagent-report** skill（`.claude/skills/finagent-report/`）。
茅台样例：`data/extractions/贵州茅台_2025/report/`（`build_report.py` 只含公司专属图表与编排，`narrative.md` 为文稿）。

## 字体（中英文分开指定）

字体栈把**西文字体放前面、中文字体放后面**：英文字母和数字用西文字体，汉字自动回退到中文字体。
各平台都列上，打印成 PDF 后字体会嵌入，评审换机器看 PDF 不受影响。

```css
--serif: "Times New Roman", "Times", "Kaiti SC", "STKaiti", "KaiTi", "楷体", "KaiTi_GB2312", serif;  /* 正文：Times New Roman + 楷体 */
--sans:  "Helvetica Neue", "Arial", "PingFang SC", "Source Han Sans SC", "Noto Sans CJK SC",
         "Microsoft YaHei", sans-serif;                                   /* 标题、表格、图注、侧栏 */
```

- 正文五号字（10.5pt），西文与数字用 Times New Roman、汉字用楷体，行高约 1.6、两端对齐（首页投资要点同样 10.5pt）；表格与侧栏 8.5～9pt 无衬线；图注与来源 7.5pt 灰色。
- 表格数字右对齐并开 `font-variant-numeric: tabular-nums`，同列保留相同小数位；负数用“-”，不用括号。
- 中文用全角标点；数字与中文单位之间空一格（`1,688.38 亿元`）；英文缩写（DCF、WACC、EBIT）保持半角。
- 加 `line-break: strict`（避免行首标点）、`orphans: 3; widows: 3`。
- 不引用网络字体（离线可复现）。

## 图表（matplotlib → SVG）

- `matplotlib.use("Agg")`，`rcParams["font.family"] = ["Helvetica Neue", "PingFang SC"]`（西文在前，中文回退；
  非 macOS 换成 Arial / Noto Sans CJK SC），`rcParams["svg.fonttype"] = "path"`（文字转曲，避免缺字），
  `axes.unicode_minus = False`。画完检查图中汉字没有变成方框。
- 尺寸按版心定：通栏宽 170mm、半栏 82mm；图内字号 7.5～9pt，与正文协调。
- 统一配色（全文一致）：主色藏青 `#1B365D`，辅色 `#8A9BB0`，强调/负向 `#B5482F`，合计/中性 `#7F8C9A`，
  网格线 `#E5E7EB`。颜色含义写进图例；如用红绿表示涨跌，按 A 股惯例红涨绿跌。
- 去掉上、右边框；只留浅色水平网格；柱状图 8 根以内直接标数值，不再重复坐标轴刻度。
- 图标题写结论（如“四季度归母净利润为全年最低”），单位写在标题或坐标轴上。
- 瀑布图、足球场图等用 `bar` / `barh` 自己画，不引入其他绘图库。

## 版式（CSS 分页）

```css
@page { size: A4; margin: 18mm 16mm 18mm 16mm;
  @top-left { content: "贵州茅台（600519.SH）2025 年报分析"; font: 7.5pt var(--sans); color: #6B7280; }
  @bottom-right { content: counter(page) " / " counter(pages); font: 7.5pt var(--sans); color: #6B7280; } }
@page :first { @top-left { content: none; } }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
figure, table, .keep { break-inside: avoid; }  h2, h3 { break-after: avoid; }
thead { display: table-header-group; }          /* 跨页表格重复表头 */
```

- 首页用两栏（正文约 62%，侧栏约 34%，侧栏浅灰底色）；其余页单栏为主，两张半栏图可并排。
- 章节标题下加细线，编号用阿拉伯数字；表格用三线表（顶、表头下、底三条线），不画竖线。
- 每页最后不要只剩一个标题；大表或大图放不下就整体移到下一页。

## 转 PDF

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --no-pdf-header-footer \
  --print-to-pdf=runs/<run_id>/report/report.pdf --virtual-time-budget=10000 \
  "file://$PWD/runs/<run_id>/report/report.html"
```

Windows / Linux 用 Edge 或 Chromium 的同名参数。页眉页码用上面的 CSS `@page` 边距盒（Chrome 131 及以上支持），
不要用 Chrome 自带的页眉页脚。

## 自检（交付前必须做）

1. 把 PDF 每页渲染成 PNG（`pdfplumber.open(pdf).pages[i].to_image(resolution=110).save(...)`），用 Read 逐页看：
   - 中文是否有方框或缺字；英文和数字是否用了西文字体（不是宋体里的半角字形）；
   - 图、表有没有被分页切开；有没有孤立的标题、空白页、溢出版心的表格；
   - 页眉、页码是否正确，首页没有页眉；
   - 图中文字是否清晰，字号是否与正文协调。
2. 用 pdfplumber 读 `page.chars` 的 `fontname`，确认嵌入字体符合预期（西文 Charter/Helvetica，中文思源宋体/苹方等）。
3. 再跑一次 `guard` 确认 `narrative.md` 通过；抽查 3 个表格数字能对回 `analysis.json` / `valuation.json`。
4. 发现问题改 HTML/CSS 或图表后重新生成，直到逐页检查没有问题。

交付时告诉用户 PDF 和 HTML 路径、页数、使用的字体、哪些输入是假设或外部数据，以及“不构成投资建议”。
