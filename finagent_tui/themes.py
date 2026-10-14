"""终端界面主题：三套 LEDGER 配色，取自计划书 paper/proposal/ledger.sty 的墨蓝、印章红、账页底色。

每套主题分两部分：Textual 的 `Theme`（界面框架、边框、页签、表格的颜色），和 `PALETTE`（render.py 里
Rich 文本用的语义色：通过、未过、提醒、弱化、强调……）。切换主题时两边一起换，表格里的文字颜色才不会和底色打架。
实色、硬边，不用半透明和渐变。卡片边框和滚动条用中性色（border-blurred / scrollbar），主色只留给选中项与评级这类要抢眼的地方。
"""

from __future__ import annotations

from textual.theme import Theme

DEFAULT = "ledger-graphite"

THEMES = {
    # 墨蓝夜：深墨蓝底、暖白字、印章红为主色、金色强调。和宣传片的暗场同一套色。
    "ledger-ink": Theme(
        name="ledger-ink", dark=True,
        background="#0E1520", surface="#141D2B", panel="#1B2738", boost="#22314A",
        foreground="#E9E4D6", primary="#D1574A", secondary="#5E8FC4", accent="#D2A85C",
        success="#6BBF8A", warning="#E3A64F", error="#E5675C",
        variables={"border": "#D2A85C", "border-blurred": "#2E3D55", "footer-key-foreground": "#D2A85C",
                   "block-cursor-background": "#D1574A", "block-cursor-foreground": "#FFFFFF",
                   "input-selection-background": "#D1574A 35%",
                   "scrollbar": "#2E3D55", "scrollbar-hover": "#3E5070", "scrollbar-active": "#D2A85C", "scrollbar-background": "#141D2B"},
    ),
    # 账页：米白底、墨蓝字、印章红主色。投影或白天演示时更清楚。
    "ledger-paper": Theme(
        name="ledger-paper", dark=False,
        background="#F7F4EC", surface="#FFFDF8", panel="#EDE7D9", boost="#E3DCCB",
        foreground="#1C2F4A", primary="#A8382A", secondary="#2F5E8C", accent="#A88449",
        success="#3D7A4F", warning="#A86A12", error="#B83A2E",
        variables={"border": "#A8382A", "border-blurred": "#C9C2B2", "footer-key-foreground": "#A8382A",
                   "block-cursor-background": "#1C2F4A", "block-cursor-foreground": "#F7F4EC",
                   "input-selection-background": "#A88449 35%",
                   "scrollbar": "#C9C2B2", "scrollbar-hover": "#B3AB98", "scrollbar-active": "#A8382A", "scrollbar-background": "#EDE7D9"},
    ),
    # 石墨：近黑中性底、纯白字、红蓝两色，最接近普通终端，信息最密的时候最好读。
    "ledger-graphite": Theme(
        name="ledger-graphite", dark=True,
        background="#121212", surface="#1A1A1A", panel="#222222", boost="#2C2C2C",
        foreground="#E8E8E8", primary="#E5484D", secondary="#4C9EEB", accent="#F2C94C",
        success="#46A758", warning="#F2C94C", error="#E5484D",
        variables={"border": "#4C9EEB", "border-blurred": "#3A3A3A", "footer-key-foreground": "#F2C94C",
                   "block-cursor-background": "#E5484D", "block-cursor-foreground": "#FFFFFF",
                   "input-selection-background": "#4C9EEB 35%",
                   "scrollbar": "#3A3A3A", "scrollbar-hover": "#4A4A4A", "scrollbar-active": "#4C9EEB", "scrollbar-background": "#1A1A1A"},
    ),
}

# render.py 的语义色。heat_lo / heat_mid / heat_hi 是敏感性热力表的三个锚点（低 → 中 → 高）。
PALETTE = {
    "ledger-ink": {"ok": "#6BBF8A", "bad": "#E5675C", "warn": "#E3A64F", "muted": "#6C7A90", "accent": "#D2A85C", "strong": "#F3EEE2",
                   "file": "#7FB0E0", "tool": "#B79CF2", "badge_fg": "#0E1520", "row_hl": "#22314A",
                   "heat_lo": "#7A2E2A", "heat_mid": "#1B2738", "heat_hi": "#2E5E45"},
    "ledger-paper": {"ok": "#3D7A4F", "bad": "#B83A2E", "warn": "#A86A12", "muted": "#8A8473", "accent": "#2F5E8C", "strong": "#1C2F4A",
                     "file": "#2F5E8C", "tool": "#7A4FA8", "badge_fg": "#FFFDF8", "row_hl": "#E3DCCB",
                     "heat_lo": "#E8B4AC", "heat_mid": "#FFFDF8", "heat_hi": "#B9D7BF"},
    "ledger-graphite": {"ok": "#46A758", "bad": "#E5484D", "warn": "#F2C94C", "muted": "#7A7A7A", "accent": "#4C9EEB", "strong": "#FFFFFF",
                        "file": "#4C9EEB", "tool": "#B38CF2", "badge_fg": "#121212", "row_hl": "#2C2C2C",
                        "heat_lo": "#6E2427", "heat_mid": "#222222", "heat_hi": "#22553A"},
    # Textual 自带主题沿用原来的 tokyo-night 配色
    "_fallback": {"ok": "#9ece6a", "bad": "#f7768e", "warn": "#e0af68", "muted": "#565f89", "accent": "#7aa2f7", "strong": "#c0caf5",
                  "file": "#7dcfff", "tool": "#bb9af7", "badge_fg": "#1a1b26", "row_hl": "#24283b",
                  "heat_lo": "#8c2f45", "heat_mid": "#24283b", "heat_hi": "#3d6b3a"},
}
