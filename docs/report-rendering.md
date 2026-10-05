# 报告打印与字号检查

所有公司共用 `.claude/skills/finagent-report/reportkit/`。正文固定 10.5pt，纸张纵向 A4，左右边距各 15mm，版心 180mm。

Chrome 遇到超宽表格会缩小整份 PDF：CSS 声明 10.5pt 不代表输出字形仍是 10.5pt。公共样式让长表头、文字说明和网址换行，数字尽量不换行；分栏使用 `minmax(0, 1fr)`，六期财务附表使用整栏。特别宽的自定义表格应拆表或改整栏。

`layout.to_pdf()` 统一经过 `render.py`：

1. 在临时 HTML 中按打印媒体与版心宽度测量 DOM 和文字范围，检查溢出、正文 CSS 字号、图表加载；临时浏览器使用独立 profile。
2. 打印到候选 PDF，定位真实正文原文，实测字形字号（10.5pt，容许 Chrome 取整产生的 0.12pt 偏差），检查 A4 纸张。
3. 通过才替换原 PDF，写 `render_check.json`，绑定 HTML、PDF 和公共排版代码的 SHA-256；失败保留旧 PDF，凭证记录失败原因。
4. 目录回填后的第二遍打印重新检查。`report_pipeline status` 的排版闸门核对凭证及另存 PDF 的一致性；修改产物或排版代码会使凭证过期。

新工作区由 `report_pipeline build` 自动带入当前设施。已有工作区显式升级：

```sh
python -m finagent.report_pipeline sync-renderer --workspace ~/finagent-samples/<公司>_<年度>
```

该命令只更新公共排版代码、渲染检查与相关说明，不改公司数据、文稿、编排脚本、历史 PDF。升级后需要重新执行公司编排脚本；旧版 PDF 没有当前凭证，不能算排版检查通过。

普通测试不要求浏览器；实际打印回归在装有 Chrome / Chromium / Edge 的环境运行：

```sh
FINAGENT_BROWSER_TESTS=1 python -m pytest -q tests/test_report_render.py
```

自动检查不能判断图中文字重叠、孤立标题或页面美观，仍需检查逐页预览。页数规范应通过内容编排满足，不能缩小正文来凑页数。
