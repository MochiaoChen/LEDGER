"""运行环境自检：python -m finagent.doctor [--live]

逐项检查 Python 与依赖、Claude Code 命令行与登录、研报排版所需的浏览器与中文字体、.env 配置。
✗ 为必须修复，! 为可选功能缺失。--live 额外向生成与质检模型各发一次最小请求，确认模型可用（会消耗少量额度）。
不打印任何密钥。
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .core.config import PROJECT_ROOT
from .report_pipeline import GEN_MODEL, QC_MODEL

FONTS = ("Kaiti SC", "KaiTi", "STKaiti", "PingFang SC", "Songti SC", "Noto Sans CJK SC", "Noto Serif CJK SC",
         "Microsoft YaHei", "SimHei", "SimSun")


def _claude_auth() -> tuple[bool, str]:
    if os.getenv("ANTHROPIC_API_KEY"):
        return True, "使用 ANTHROPIC_API_KEY"
    try:
        out = subprocess.run(["claude", "auth", "status"], capture_output=True, text=True, timeout=30)
        info = json.loads(out.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return False, "无法读取登录状态"
    if info.get("loggedIn"):
        return True, f"已登录（{info.get('authMethod', '未知方式')}）"
    return False, "未登录：运行 claude auth login（订阅），或在 .env 设置 ANTHROPIC_API_KEY"


def _chrome() -> str:
    sys.path.insert(0, str(PROJECT_ROOT / ".claude" / "skills" / "finagent-report"))
    try:
        from reportkit.layout import chrome  # type: ignore[import-not-found]
        return chrome()
    finally:
        sys.path.pop(0)


def _ping(model: str) -> tuple[bool, str]:
    cmd = ["claude", "-p", "只回复 OK", "--model", model, "--max-turns", "1", "--output-format", "json"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=180, cwd=Path.home())
        res = json.loads(out.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as e:
        return False, f"调用失败：{type(e).__name__}"
    if res.get("is_error"):
        return False, str(res.get("result", ""))[:120]
    return True, f"响应 {str(res.get('result', '')).strip()[:20]}"


def checks(live: bool = False) -> list[tuple[str, str, str]]:
    """返回 [(状态 ✓/!/✗, 项目, 说明)]。"""
    rows: list[tuple[str, str, str]] = []
    add = lambda ok, name, detail, optional=False: rows.append(("✓" if ok else "!" if optional else "✗", name, detail))  # noqa: E731

    v = sys.version_info
    add(v >= (3, 10), "Python", f"{v.major}.{v.minor}.{v.micro}（{sys.executable}）"
        + ("" if v >= (3, 12) else "，建议 3.12"))
    for mod, why, optional in (("pdfplumber", "解析 PDF 年报", False), ("matplotlib", "研报图表", False),
                               ("PIL", "研报预览缩略图", True), ("pytest", "运行测试", True)):
        try:
            importlib.import_module(mod)
            add(True, mod, why)
        except ImportError:
            add(False, mod, f"{why}：pip install -r requirements.txt", optional)

    claude = shutil.which("claude")
    if claude:
        ver = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
        add(True, "Claude Code", ver or claude)
        ok, detail = _claude_auth()
        add(ok, "Claude 登录", detail)
    else:
        add(False, "Claude Code", "未安装：npm install -g @anthropic-ai/claude-code（需 Node.js 18+）")
    add(True, "模型分工", f"生成 {GEN_MODEL}，复核与质检 {QC_MODEL}（FINAGENT_GEN_MODEL / FINAGENT_QC_MODEL 可改）")
    if live and claude:
        for role, model in (("生成模型", GEN_MODEL), ("质检模型", QC_MODEL)):
            ok, detail = _ping(model)
            add(ok, role, f"{model}：{detail}")

    try:
        add(True, "浏览器（HTML → PDF）", _chrome())
    except SystemExit as e:
        add(False, "浏览器（HTML → PDF）", str(e))
    except Exception as e:  # reportkit 依赖 matplotlib，缺依赖时这里也会失败
        add(False, "浏览器（HTML → PDF）", f"无法检查：{type(e).__name__}: {e}")
    try:
        from matplotlib import font_manager
        have = {f.name for f in font_manager.fontManager.ttflist}
        hit = [f for f in FONTS if f in have]
        add(bool(hit), "中文字体", "、".join(hit[:3]) if hit else "未找到楷体/宋体/黑体等中文字体，图表中文会显示为方框")
    except ImportError:
        pass

    env = PROJECT_ROOT / ".env"
    add(env.is_file(), ".env", "已存在" if env.is_file() else "不存在：cp .env.example .env 后填写", optional=True)
    add(bool(os.getenv("LLM_API_KEY")), "Agent 版本模型密钥", "LLM_API_KEY 已设置" if os.getenv("LLM_API_KEY")
        else "LLM_API_KEY 未设置：Agent 版本只能 --llm off / replay；研报流水线不受影响", optional=True)
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="finagent.doctor", description="运行环境自检")
    ap.add_argument("--live", action="store_true", help="向生成与质检模型各发一次最小请求")
    args = ap.parse_args(argv)
    rows = checks(args.live)
    width = max(len(name) for _, name, _ in rows)
    for mark, name, detail in rows:
        print(f"  [{mark}] {name:<{width}}  {detail}")
    bad = sum(m == "✗" for m, _, _ in rows)
    print(f"\n{'全部必需项就绪' if not bad else f'{bad} 项必须修复'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
