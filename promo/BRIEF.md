# 视频 brief

- **状态**：正式片（`plan.json` 的 `demo:false`）。
- **用途**：2026 北京市大学生金融人工智能竞赛初赛视频，要求不超过 5 分钟的 MP4。
- **用户原话（2026-10-13）**：“做一个宣传片，5 分钟，有中文，要有技术范儿，也要有产品 sense。我想要一个镜头是代码出现，还有 agent runtime 在 search 什么的。”
- **范围**：全量产品（截至 2026-10-13 的 main 分支）。平台面：命令行与终端界面、流水线产物（PDF 研报、估值工作簿）。**未覆盖**：网页前端（由其他成员开发）。范围是按“比赛宣传片”推定的，用户没有单独拍板，交付时已说明。
- **风格**：`repo`。色板取自 `paper/proposal/ledger.sty`，终端界面与研报页面原样上镜。风格同样是推定，不是用户确认的选择。
- **画幅 / 时长 / 语言**：1920×1080、30 fps、288 秒（4 分 48 秒）；中文为主，英文小标。
- **主线素材**：真实工作区 `~/finagent-samples/中际旭创_2025`（11 道闸门全部通过，评测 90 分）。
- **链接 / CTA**：仓库是私有的，片中不出现链接。
- **品牌与字体**：系统名 LEDGER；中文 Noto Sans SC、英文与代码 Maple Mono NF CN，均为 OFL 许可，字体文件冻结在 `public/fonts/`（体积大，不入库，来源见 `evidence/style-audit.md`）。
- **声音**：配乐为代码原创合成（`tools/score.py`）；音效用 skill 内置的原创 WAV，连续键入声由 `tools/make_typing.py` 合成。没有旁白。
- **合规**：片中研报是系统对真实上市公司生成的样例，含估值结论；片尾和估值镜头都标了“不构成投资建议”。纠错镜头用的是仓库里的虚构公司样例，画面上已标注。
- **证据**：`evidence/` 下的 feature-evidence、session-research、style-audit、component-usage、copy-review、audio-selection。
