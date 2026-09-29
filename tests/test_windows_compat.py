"""设备适配：Windows 路径不依赖 macOS 固定目录，且显式配置优先。"""

import importlib.util
import sys
from pathlib import Path

from conftest import ROOT


def _load_build_pdf():
    path = ROOT / "data" / "samples" / "build_pdf.py"
    spec = importlib.util.spec_from_file_location("finagent_build_pdf", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_cjk_font_env_override_accepts_windows_style_location(tmp_path, monkeypatch):
    font = tmp_path / "simkai.ttf"
    font.write_bytes(b"test font placeholder")
    monkeypatch.setenv("FINAGENT_CJK_FONT", str(font))
    assert _load_build_pdf().find_cjk_font() == font


def test_report_browser_env_override_is_cross_platform(tmp_path, monkeypatch):
    kit = ROOT / ".claude" / "skills" / "finagent-report"
    sys.path.insert(0, str(kit))
    try:
        from reportkit.layout import chrome

        browser = tmp_path / "chrome.exe"
        browser.write_bytes(b"placeholder")
        monkeypatch.setenv("FINAGENT_CHROME", str(browser))
        assert chrome() == str(browser)
    finally:
        sys.path.remove(str(kit))


def test_documented_windows_virtualenv_path():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "windows.yml").read_text(encoding="utf-8")
    assert r".\.venv\Scripts\python.exe" in readme
    assert "runs-on: windows-latest" in workflow and 'python-version: "3.12"' in workflow
