"""Focused report writer accepts only a complete, substantial chapter map."""

import pytest

from finagent import report_writer
from finagent.report_writer import PARTS, compose_sections, polish_style, polish_unsupported_numbers


def test_compose_sections_requires_complete_substantial_content():
    raw = {key: ("关键经营数据与业务驱动分析。" * 50) for key in PARTS}
    text = compose_sections(raw)
    assert text.count("<!-- section:") == len(PARTS)
    assert "<!-- section: summary -->" in text
    with pytest.raises(ValueError, match="14 个章节"):
        compose_sections({"summary": "短"})
    raw["summary"] = "短"
    with pytest.raises(ValueError, match="过短"):
        compose_sections(raw)
    raw["summary"] = "充分的摘要。" * 100
    raw["title"] = "<script>alert(1)</script>"
    with pytest.raises(ValueError, match="HTML"):
        compose_sections(raw)


def test_style_polish_rejects_changed_numbers(tmp_path):
    class FakeClient:
        def chat_json(self, *_args, **_kwargs):
            return {"replacements": [{"old": "程序评级为卖出，价值 10 元。",
                                      "new": "评级为卖出，价值 11 元。"}]}

    with pytest.raises(ValueError, match="触碰数字"):
        polish_style(FakeClient(), "程序评级为卖出，价值 10 元。", tmp_path / "check.md")
    assert not (tmp_path / "check.md").exists()


def test_numeric_polish_removes_unverified_value_without_adding_one(tmp_path, monkeypatch):
    class FakeClient:
        def chat_json(self, *_args, **_kwargs):
            return {"replacements": [{"old": "未经核验的 9.54 亿元贡献利润。",
                                      "new": "相关收益对利润有贡献。"}]}

    monkeypatch.setattr(report_writer, "truth_values", lambda _run: [1.0])
    monkeypatch.setattr(report_writer, "check_text", lambda text, _values: ["9.54亿元"] if "9.54" in text else [])
    monkeypatch.setattr(report_writer, "check_binding", lambda _text, _run: [])
    assert polish_unsupported_numbers(FakeClient(), "未经核验的 9.54 亿元贡献利润。", tmp_path) == \
        "相关收益对利润有贡献。"
