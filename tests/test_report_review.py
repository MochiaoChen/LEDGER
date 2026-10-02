"""Independent review record must be current, structured, and blocker-consistent."""

import hashlib
import subprocess

import pytest

from finagent import report_review
from finagent.report_review import apply_replacements, escalate_material_issues, untouched_citations, validate_review


def test_validate_review_rejects_stale_and_fake_pass():
    issue = {"severity": "blocker", "excerpt": "份额提升", "reason": "分母不一致", "fix": "删除份额推论"}
    doc = {"narrative_sha256": "abc", "run_id": "run-1", "issues": [issue], "pass": False}
    assert not validate_review(doc, "abc", "run-1")["pass"]
    with pytest.raises(ValueError, match="不一致"):
        validate_review(doc, "def", "run-1")
    doc["pass"] = True
    with pytest.raises(ValueError, match="blocker"):
        validate_review(doc, "abc", "run-1")
    doc["issues"] = [{"severity": "critical", "excerpt": "a", "reason": "b", "fix": "c"}]
    with pytest.raises(ValueError, match="severity"):
        validate_review(doc, "abc", "run-1")


def test_targeted_revisions_are_atomic_and_unique():
    text = "第一句有问题。第二句保留。"
    assert apply_replacements(text, [{"old": "第一句有问题", "new": "第一句已修正"}]) == "第一句已修正。第二句保留。"
    with pytest.raises(ValueError, match="恰好出现一次"):
        apply_replacements(text, [{"old": "第一句", "new": "甲"}, {"old": "不存在", "new": "乙"}])
    with pytest.raises(ValueError, match="章节标记"):
        apply_replacements(text, [{"old": "第一句", "new": "<!-- section: hacked -->"}])
    issues = [{"excerpt": "第一句有问题"}]
    assert untouched_citations(issues, text, "第一句有问题。第二句已修正。") == ["第一句有问题"]
    assert untouched_citations(issues, text, "第一句已修正。第二句保留。") == []


def test_material_warning_escalates_but_minor_style_warning_remains():
    issues = [{"severity": "warning", "reason": "2025 年分红预案被写为已实施"},
              {"severity": "warning", "reason": "该句作了无出处的确定性因果断言"},
              {"severity": "warning", "reason": "短句节奏略显生硬"}]
    escalate_material_issues(issues)
    assert [x["severity"] for x in issues] == ["blocker", "blocker", "warning"]
    record = {"narrative_sha256": "abc", "run_id": "run-1", "issues": [
        {"severity": "warning", "excerpt": "口径", "reason": "分母口径不一致", "fix": "删除推论"}], "pass": True}
    with pytest.raises(ValueError, match="blocker"):
        validate_review(record, "abc", "run-1")


def test_review_until_clear_rechecks_after_each_revision(tmp_path, monkeypatch):
    narrative = tmp_path / "narrative.md"
    narrative.write_text("待改", encoding="utf-8")
    run = tmp_path / "run-1"
    run.mkdir()
    calls = {"review": 0, "guard": 0}

    def guard(*args, **kwargs):
        calls["guard"] += 1
        assert "DEEPSEEK_API_KEY" not in kwargs["env"]
        return subprocess.CompletedProcess(args[0], 0, "", "")

    def audit(ws, current_run, text):
        calls["review"] += 1
        raw = text.read_text(encoding="utf-8")
        issue = [] if raw == "已改" else [{"severity": "blocker", "excerpt": "待改", "reason": "无依据", "fix": "修正"}]
        return {"narrative_sha256": hashlib.sha256(raw.encode()).hexdigest(), "run_id": current_run.name,
                "issues": issue, "pass": not issue}

    def revise(ws, current_run, text):
        text.write_text("已改", encoding="utf-8")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sentinel")
    monkeypatch.setattr(report_review.subprocess, "run", guard)
    monkeypatch.setattr(report_review, "review", audit)
    monkeypatch.setattr(report_review, "revise", revise)
    result = report_review.review_until_clear(tmp_path, run, narrative, max_reviews=2)
    assert result["pass"] and result["rounds"] == 2
    assert calls == {"review": 2, "guard": 2}


def test_review_until_clear_stops_on_guard_failure(tmp_path, monkeypatch):
    narrative = tmp_path / "narrative.md"
    narrative.write_text("待改", encoding="utf-8")
    run = tmp_path / "run-1"
    run.mkdir()
    monkeypatch.setattr(report_review.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "mismatch", ""))
    monkeypatch.setattr(report_review, "review", lambda *a: pytest.fail("review should not run"))
    result = report_review.review_until_clear(tmp_path, run, narrative)
    assert not result["pass"] and result["reason"] == "数字护栏未通过"
