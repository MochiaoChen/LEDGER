"""人工质检页：逐公司拆分、来源校验与安全渲染。"""

import json

import pytest

from finagent.evaluation.review_docs import _safe_json, build_review_docs


def _pack(tmp_path):
    pack = tmp_path / "v0"
    (pack / "reports").mkdir(parents=True)
    rubric = {
        "version": "test_v0", "layers": {"L0": "硬闸门", "L1": "数据闭合"},
        "items": [
            {"id": "L0-01", "layer": "L0", "title": "数字护栏", "criterion": "逐项核对", "points": 0},
            {"id": "L1-01", "layer": "L1", "title": "引用安全", "criterion": "<script>alert(1)</script>", "points": 3},
        ],
    }
    (pack / "rubric.json").write_text(json.dumps(rubric, ensure_ascii=False), encoding="utf-8")
    for company in ("甲公司", "乙公司"):
        result = pack / "results" / company
        result.mkdir(parents=True)
        score = {
            "rubric": "test_v0", "total": 80, "deliverable": True, "not_deliverable_reasons": [],
            "items": [
                {"id": "L0-01", "layer": "L0", "passed": True, "reason": "无异常", "evidence": ""},
                {"id": "L1-01", "layer": "L1", "passed": False,
                 "reason": "原文 <img src=x onerror=alert(1)>", "evidence": "页 3"},
            ],
        }
        (result / "score.json").write_text(json.dumps(score, ensure_ascii=False), encoding="utf-8")
        (pack / "reports" / f"{company}.pdf").write_bytes(b"%PDF-1.4\n")
    return pack


def test_individual_review_pages_and_safe_content(tmp_path):
    pack = _pack(tmp_path)
    out = tmp_path / "demo"
    paths = build_review_docs(pack, out)
    assert {p.name for p in paths} == {"甲公司.html", "乙公司.html"}
    text = (out / "甲公司.html").read_text(encoding="utf-8")
    assert "目录" not in text and "乙公司" not in text
    assert "甲公司 · 研报质检" in text
    assert text.count('class="review-item"') == 2
    assert "改判：通过" in text and "尚未复核" in text
    assert "导出质检 JSON" in text and "导入先前 JSON" in text
    assert "下载原始研报 PDF" in text
    assert "JVBERi0xLjQK" in text  # 内嵌 PDF，单页文件可独立传递
    assert "<script>alert(1)</script>" not in text
    assert "<img src=x onerror=alert(1)>" not in text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in text
    assert "\\u003c/script\\u003e" in _safe_json({"x": "</script>"})


def test_source_fingerprint_changes_when_pdf_changes(tmp_path):
    pack = _pack(tmp_path)
    out = tmp_path / "demo"
    build_review_docs(pack, out)
    before = (out / "甲公司.html").read_text(encoding="utf-8")
    (pack / "reports" / "甲公司.pdf").write_bytes(b"%PDF-1.4\nchanged")
    build_review_docs(pack, out)
    after = (out / "甲公司.html").read_text(encoding="utf-8")
    assert before != after
    assert (out / "乙公司.html").is_file()


def test_refuses_mismatched_score(tmp_path):
    pack = _pack(tmp_path)
    score_path = pack / "results" / "甲公司" / "score.json"
    score = json.loads(score_path.read_text(encoding="utf-8"))
    score["items"][0]["layer"] = "L1"
    score_path.write_text(json.dumps(score, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="层级"):
        build_review_docs(pack, tmp_path / "demo")
