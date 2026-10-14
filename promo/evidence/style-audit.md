# 风格审计

1. **色板**（来源 `paper/proposal/ledger.sty`）：墨蓝 `#1C2F4A`、次墨蓝 `#3E5A80`、印章红 `#A8382A`、金 `#A88449`、账页底色 `#F7F4EC`、栏线 `#C9C2B2`、弱文本 `#6B6B6B`；语义色：确定性程序 `#2F5E8C`、模型会话 `#C0782B`、通过 `#3D7A4F`。暗场另配一组提亮的对应色，写在 `src/film.css` 的 `:root`。
2. **字体**：
   - 中文标题与正文：Noto Sans SC 500 / 700 / 900（SIL OFL 1.1，文件取自仓库 `video/film/fonts/`，随附 `OFL.txt`）。
   - 英文小标、数据大字、代码与终端：Maple Mono NF CN Regular / Medium / Bold 7.9（SIL OFL 1.1，https://github.com/subframe7536/maple-font ，文件取自本机 `~/Library/Fonts`）。
   - 两套字体各自用 `@font-face` 指定，`client.jsx` 在出帧前逐个 `document.fonts.load` 确认加载。字体文件共约 66 MB，放在 `public/fonts/`，不入库。
3. **空间与形状**：左右边距 96px；终端与卡片圆角 12～14px、描边 1.5px；纸面镜头用 1.5px 栏线，不用阴影卡片（纠错镜头的“研报草稿”除外）。
4. **品牌**：仓库里没有图形标志，字标就是等宽粗体的 LEDGER；印章“核 VERIFIED”是本片为“校验通过”做的图形，不是既有品牌资产。
5. **镜头适配**：终端界面的 SVG 可以直接放大；研报与年报页面用位图；`status` 输出、事件流、源码用等宽字体重排。产品的终端界面本来就是暗色主题，直接使用。
6. **母题**：账页横线与红色栏线、印章、带页码的数字、11 行闸门清单、事件流。
7. **决策**：`repo`。保留的识别点：墨蓝 / 印章红 / 账页底色，研报的红色版式，终端界面的 tokyo-night 配色。
