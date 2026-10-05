"""报告渲染凭证：绑定 HTML、PDF 和排版代码，防止过期检查被当作通过。"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

VERSION = 1
BODY_PT = 10.5
FONT_TOLERANCE_PT = 0.12  # Chrome 的毫米到像素取整会产生约 0.03pt 偏差


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def renderer_hash(kit: Path) -> str:
    h = hashlib.sha256()
    h.update(Path(__file__).read_bytes())
    for p in sorted(kit.iterdir()):
        if p.is_file() and p.suffix in {".py", ".css", ".js", ".md"}:
            h.update(p.name.encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def check_render_record(report: Path, kit: Path) -> tuple[bool, str]:
    """只认与当前产物和排版代码匹配、确实测过字号的凭证。"""
    try:
        record = json.loads((report / "render_check.json").read_text(encoding="utf-8"))
        if record.get("version") != VERSION or record.get("ok") is not True:
            return False, "渲染检查未通过"
        for name in ("html", "pdf"):
            if record.get(name + "_sha256") != digest(report / ("report." + name)):
                return False, f"{name.upper()} 已修改，渲染检查过期"
        if record.get("renderer_sha256") != renderer_hash(kit):
            return False, "排版代码已修改，须重新渲染"
        if (record["layout"]["overflow"] or record["layout"]["font_errors"]
                or record["layout"].get("broken_images")):
            return False, "页面溢出或正文 CSS 字号错误"
        samples = record["pdf"]["samples"]
        if not samples or record["pdf"]["pages"] < 1:
            return False, "缺少 PDF 正文实测字号"
        if any(not math.isfinite(s["actual_pt"]) or abs(s["actual_pt"] - BODY_PT) > FONT_TOLERANCE_PT for s in samples):
            return False, "PDF 正文实测字号不符合 10.5pt"
        return True, "宽度与正文实测字号通过"
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False, "缺少有效的 render_check.json，须用新版 reportkit 重新渲染"
