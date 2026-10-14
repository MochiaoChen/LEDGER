# LEDGER 宣传片工程

成片：`LEDGER-宣传片-4m48s.mp4`（1920×1080、30 fps、288 秒、H.264 + AAC）。
方向与镜头表见 `DIRECTION.md`，范围与用户要求见 `BRIEF.md`，每个上屏数字的来源见 `evidence/feature-evidence.md`。

用 [归藏 product video skill](https://github.com/op7418/guizang-product-video-skill)（提交 18842e0）的起步工程搭建；
起步工程代码为 AGPL-3.0（`LICENSE`、`NOTICE.md`），本目录没有并入 `finagent/`，是否入库、是否写进 `THIRD_PARTY.md` 由团队决定。

## 重新生成

```bash
# 0. 依赖：Node ≥ 22、FFmpeg、poppler（pdftoppm）、uv；字体放到 public/fonts/（见 evidence/style-audit.md）
npm install
git clone https://github.com/op7418/guizang-product-video-skill ../.skill   # 只用它的 scripts/

# 1. 数据与素材（在仓库根目录跑，读 ~/finagent-samples/中际旭创_2025）
../.venv/bin/python tools/gen_data.py          # src/data/data.json、public/pages/
../.venv/bin/python tools/tui_shot.py          # public/tui/*.svg（终端界面原始导出）
python3 tools/tui_inline.py                    # src/data/tui.json

# 2. 时间线、配乐、音效、混音
node tools/make_plan.mjs                       # plan.json（时间只在这里写）
uv run --with numpy --with scipy python tools/make_typing.py
uv run --with numpy --with scipy python tools/score.py
python3 ../.skill/scripts/sfx_landmarks.py assets/sfx/*.wav > evidence/sfx-landmarks.txt
python3 ../.skill/scripts/mix_audio.py plan.json

# 3. 画面
npm run build
node stills.mjs evidence/stills 60 116 153      # 抽几帧看
node tools/render_all.mjs --jobs 4              # 分镜头并行渲染 + 拼接 + 配音，约 7 分钟
node tools/render_all.mjs --only qc             # 只重渲某个镜头

# 4. 检查
python3 ../.skill/scripts/check_delivery.py plan.json --video renders/final.mp4 --mix-report evidence/audio-mix.json
```

改镜头时长或动作时间只改 `tools/make_plan.mjs`，然后从第 2 步重跑；`evidence/sfx-landmarks.json` 由第 2 步的测量结果整理而来（脚本见本次会话记录，可照 `sfx-landmarks.txt` 的格式重建）。
本机 Playwright 自带的 headless shell 下载停滞，`browser.mjs` 改用本机已有的 Chromium；换机器后可用 `FILM_CHROME` 指定可执行文件。
