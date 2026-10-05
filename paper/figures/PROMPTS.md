# 论文示意图提示词

论文里 6 张示意图（图 1～6）交给图像模型画，放到本目录并按下表命名（`.png` 或 `.pdf` 均可），重新编译后自动替换占位框。
图 7（得分柱状图）和所有表格由 LaTeX 直接从仓库数据画，**不要**交给图像模型，避免数字失真。

| 文件名 | 论文位置 | 版面比例 |
|---|---|---|
| `fig1_architecture.png` | 图 1 四层结构 | 16:9 |
| `fig2_extraction.png` | 图 2 双通道抽取 | 16:7 |
| `fig3_valuation.png` | 图 3 估值链 | 16:6 |
| `fig4_guard.png` | 图 4 数字护栏与数字锁 | 16:6 |
| `fig5_pipeline.png` | 图 5 五会话流水线 + 11 道闸门 | 16:8 |
| `fig6_refine.png` | 图 6 质检闭环与信息隔离 | 16:8 |

## 使用方法

1. 每次生成 = **公共风格块 + 该图的提示词**，整段一起贴给图像模型。
2. 中文标签是最容易出错的地方。生成后逐字核对标签；有错字或乱码，就把提示词里的“标签”改成“在对应位置放编号圆点 ①②③……，不写文字”，
   出无字底图后在 Keynote / Figma / PPT 里按标签表补字（字体：思源黑体 / 苹方，字号统一）。
3. 图中**不出现任何实验数字**（得分、覆盖率等），示意图只表达结构。
4. 同一批图尽量在同一个会话里连续生成，并在第 2 张起加一句“与上一张保持完全相同的风格、配色、线宽与字体”。

---

## 公共风格块（每张图都先贴这一段）

```
Flat vector academic diagram for a NeurIPS paper. Pure white background. Clean, minimal, no gradients, no shadows,
no 3D, no textures, no clip-art, no people, no robots, no decorative icons, no logos, no watermark.
Rounded rectangles (corner radius small), uniform stroke width 1.5 px, solid triangular arrowheads, straight or
orthogonal (elbow) connectors only, no curved spaghetti lines. Generous whitespace, strict grid alignment,
equal spacing between boxes.
Color semantics (use ONLY these colors):
  - deterministic program / code components: fill #E8EEF5, stroke #1F3A5F, text #1F3A5F
  - LLM / model sessions: fill #FBEBD9, stroke #E08A2E, text #8A4B0F
  - gates / checks / blocking: fill #FFFFFF, stroke #B22222, text #B22222, drawn as small diamonds or short red bars
  - files / data artifacts: fill #F2F2F2, stroke #888888, text #333333, drawn as document shapes (folded corner)
  - arrows: #444444; feedback / reject arrows: dashed #B22222
Typography: sans-serif (Source Han Sans SC / PingFang SC), all labels horizontal, minimum label size readable at
single-column print width. Render ONLY the exact label strings given below, character by character; do not add,
translate, paraphrase or invent any other text. No title inside the image. No legend unless asked.
Output: high resolution, at least 3000 px wide.
```

---

## fig1_architecture —— 四层结构

```
Aspect ratio 16:9. Four horizontal layers stacked vertically, full width, separated by thin light-gray rules.
Each layer has a left label column (narrow) and a right content area.

Layer 4 (top) left label: "④ 质检循环"
  content: three boxes left-to-right connected by arrows:
    [model] "生成" -> [model] "复核" -> [program] "盲评计分"
  plus a dashed red arrow from "盲评计分" back to "生成", labeled "问题单"
Layer 3 left label: "③ 研报流水线"
  content: a large light-gray rounded container labeled "隔离工作区" holding five small orange boxes in a row:
    "研究助理" "分析师" "主笔" "复核编辑" "排版设计师", connected by arrows;
  between consecutive boxes draw a small red diamond (gate). Under the row, small red text: "11 道程序闸门"
Layer 2 left label: "② 技能层"
  content: four document-shaped gray boxes in a row: "finagent-research" "finagent-report" "finagent-review" "finagent-pipeline"
Layer 1 (bottom) left label: "① 计算引擎"
  content: a row of blue boxes: "抽取校验" "真值表" "三表 / DCF / 可比" "数字护栏" "数字锁" ;
  a thin blue bar spanning the full width beneath them labeled "全程追踪：文件哈希 · 事件流"

Vertical connectors: thin gray arrows from each orange session box in layer 3 down to layer 1 (sessions call the engine);
a thin arrow from layer 2 up to layer 3 (skills instruct sessions).
On the far right, a narrow vertical caption bar with two short lines stacked:
  top half orange text "模型：读 · 抄 · 写 · 判断"
  bottom half blue text "程序：校验 · 计算 · 拦截"
```

## fig2_extraction —— 证据约束的双通道抽取

```
Aspect ratio 16:7. Left-to-right flow.
Far left: gray document shape "年报 PDF".
From it, two parallel horizontal lanes:
  upper lane: [program] "locate 定位关键页" -> [program] "规则通道：白名单表格 · 科目匹配"
  lower lane: [model] "模型通道：按页读 PDF · 原文写法 + 页码"
Under the upper lane, four tiny gray tags in a row (same size): "稀疏网格" "跨页续表" "科目折行" "同页多单位"
The lower lane passes through a red check box: "逐字回查原文" ; a short dashed red arrow from it going down to a small
gray tag "拒收".
Both lanes merge into one [program] box: "合并：不静默取舍"; a dashed red arrow from it down to a tag "冲突 → 问题记录".
Then a red diamond gate labeled "verify-facts" with four tiny red labels around it: "拒收" "冲突" "勾稽" "核心缺失".
A dashed red feedback arrow from the gate back to the lower lane labeled "回原文修正（≤3 轮）".
Gate passes (solid arrow) to a cylinder-shaped database icon (blue stroke) labeled "真值表 T".
From "真值表 T" three thin arrows fan out to the right to small boxes: "财报分析" "估值" "研报纠错".
```

## fig3_valuation —— 估值链

```
Aspect ratio 16:6. Single left-to-right chain of blue program boxes:
"经营数据" -> "分部预测（销量 × 单价）" -> "三表联动" -> "FCFF 折现" -> "企业价值" -> "股权价值桥" -> "每股价值" -> "程序评级"
Above "分部预测" a small gray document "估值假设（标注依据）" with a thin arrow into it.
A dashed blue double-headed arrow arching below between "三表联动" and "FCFF 折现", labeled "逐期一致性核对".
Below "三表联动" a small red check box "勾稽：平衡 · 现金衔接 · 滚动".
Below "股权价值桥" a small gray tag "逐项加回 / 扣减".
Branch from "FCFF 折现" downward to two small blue boxes side by side: "三情景 + 敏感性" and "反向 DCF：股价隐含了什么".
Branch from "企业价值" upward to a small blue box "可比公司：交叉验证".
Right of "程序评级" a tiny gray tag "研报只引用，不自行给评级".
```

## fig4_guard —— 数字护栏与数字锁

```
Aspect ratio 16:6. Two panels side by side separated by a thin vertical gray rule.

Left panel, top label (small, dark gray): "数字护栏 guard"
  Left: gray document "文稿". Arrow to blue box "抽取“数字 + 单位”".
  Arrow to blue box "按单位与展示精度换算".
  Arrow to red diamond "在结论性产物中找得到？".
    Input into the diamond from above: two gray document shapes stacked: "运行产物（真值表 · 估值 · 预测）" and "外部来源登记 sources.json".
    A crossed-out small gray tag near the inputs: "不含：草稿断言 · 中间网格".
  From the diamond: three dashed red arrows going down to three small red tags: "无出处数字" "指标 / 期间绑定不符" "外部数字缺 [S编号]".
  Solid arrow right to a small blue tag "通过：事实 / 推论 / 观点 分类".

Right panel, top label: "数字锁 numlock"
  Two gray documents side by side: "初稿" and "改写稿", each containing a column of small rounded number chips (no digits, just blank chips).
  Lines connect chips of "改写稿" to identical chips in "初稿"; one chip in "初稿" has no partner and is faded (deleted is allowed).
  One extra chip in "改写稿" is outlined in red with a red cross, labeled "新增 / 改动 → 拒绝".
  Under the panel, a small blue caption: "只许删减，不许新增或改动".
```

## fig5_pipeline —— 五会话流水线与 11 道闸门

```
Aspect ratio 16:8.
Top: a wide blue banner box "确定性编排器 report_pipeline（不是模型）".
Below it, a large light-gray rounded container labeled at top-left "隔离工作区（仓库目录树之外）".
Inside, a horizontal timeline of 11 numbered stations (small circles 1..11) on a thin line, each followed by a small red bar (gate).
Above the timeline, five orange session boxes spanning their stages:
  "研究助理" spans station 1
  "分析师" spans stations 2–7
  "主笔" spans station 8
  "复核编辑" spans station 9
  "排版设计师" spans stations 10–11
Below each station, a tiny gray label (one per station, exactly):
  1 "资料搜集" 2 "财务抽取" 3 "分析框架" 4 "深度调研" 5 "经营数据" 6 "估值假设" 7 "估值运行" 8 "文稿" 9 "复核改写" 10 "排版" 11 "交付说明"
Between consecutive session boxes draw a small gray document icon labeled "文件交接" (only once between each pair, keep it tiny).
Inside the container, top-right corner: a small red padlock shape with text "禁读仓库 · 禁改引擎与技能".
Right of the container: gray document stack labeled "研报 PDF · 估值模型 · 复核清单".
Bottom-left, outside the container: a small blue box "status：新鲜度 · 前序阻断" with a thin arrow up to the timeline.
```

## fig6_refine —— 质检闭环与信息隔离

```
Aspect ratio 16:8. Two large regions side by side separated by a thick vertical dashed gray wall labeled vertically "信息隔离".
Left region, header text "生成侧（工作区内）":
  orange boxes stacked vertically: "分析师 / 主笔" , "复核编辑" , "排版设计师"
  a gray document at bottom: "交付物"
Right region, header text "评测侧（仓库与工作区之外）":
  gray document "评分标准（生成方不可见）" at top,
  blue box "程序检查 L0 / L1",
  orange box "盲评 L2 / L3 / 负向",
  blue box "Python 计分",
  red diamond "达标？"
Flow: "交付物" -> (solid arrow crossing the wall through a small gap labeled "只复制交付物") -> "程序检查" and "盲评" -> "Python 计分" -> "达标？".
From "达标？" a solid arrow right to a gray document "最佳轮次交付".
From "达标？" a dashed red arrow back across the wall labeled "问题单（只含理由与证据）", splitting into three dashed red arrows:
  to "分析师 / 主笔" labeled "数据 / 假设"
  to "复核编辑" labeled "措辞 / 结构"
  to "排版设计师" labeled "版面"
Bottom right small blue tag: "≤3 轮 · 提升 <2 分停止 · 回滚到最佳轮次".
```

---

## 备选：让文本模型直接出 TikZ（标签零错字）

图像模型实在写不对中文时，可把上面任一图的提示词交给文本模型，前面换成这段：

```
把下面的示意图描述写成可在 XeLaTeX + ctex 下编译的独立 TikZ 代码（\documentclass[tikz]{standalone}，
\usepackage[fontset=mac]{ctex}）。颜色严格使用：程序 #1F3A5F/#E8EEF5，模型 #E08A2E/#FBEBD9，闸门 #B22222，
产物 #888888/#F2F2F2。只用描述里给出的标签文字，不增删。节点用 positioning 库按网格对齐，线宽 0.8pt。
```

编译出的 PDF 改名为对应的 `figX_*.pdf` 放进本目录即可。
