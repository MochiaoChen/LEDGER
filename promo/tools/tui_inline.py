#!/usr/bin/env python3
"""把 tools/tui_shot.py 导出的 SVG 处理成可内联的 src/data/tui.json。

只做显示适配，不改界面内容：
1. 去掉外链字体（Fira Code 的 CDN 地址），改用本片冻结的等宽字体；
2. Rich 导出 SVG 时 textLength 按字符数算，中日韩全角字符会被压成半宽而重叠，这里按终端单元格数（全角占 2 格）重算。
"""
import html
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABS = ["overview", "facts", "valuation", "score", "trace", "agents"]


def cells(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def fix(m):
    head, length, rest, body = m.group(1), float(m.group(2)), m.group(3), m.group(4)
    text = html.unescape(body)
    if not text or cells(text) == len(text):
        return m.group(0)
    return f'{head}textLength="{length / len(text) * cells(text):.1f}"{rest}>{body}</text>'


out = {}
for tab in TABS:
    svg = (ROOT / "public" / "tui" / f"{tab}.svg").read_text(encoding="utf-8")
    svg = re.sub(r"@font-face\s*\{[^}]*\}", "", svg)
    svg = svg.replace("Fira Code, monospace", '"Maple Mono", monospace').replace("font-family: arial", 'font-family: "Maple Mono"')
    svg = re.sub(r'(<text [^>]*?)textLength="([\d.]+)"([^>]*)>([^<]*)</text>', fix, svg)
    m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    out[tab] = {"w": float(m.group(1)), "h": float(m.group(2)), "svg": svg}
(ROOT / "src" / "data" / "tui.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
print({k: (v["w"], v["h"], len(v["svg"])) for k, v in out.items()})
