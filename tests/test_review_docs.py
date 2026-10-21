"""人工质检页：逐公司拆分、来源校验与安全渲染。"""

import json
import re

import pytest

from finagent.evaluation.review_docs import _safe_json, build_review_docs
from finagent.core.config import PROJECT_ROOT


def _pack(tmp_path):
    pack = tmp_path / "v0"
    (pack / "reports").mkdir(parents=True)
    rubric = {
        "version": "test_v0", "layers": {"L0": "硬闸门", "L1": "数据闭合", "N": "负向条目"},
        "items": [
            {"id": "L0-01", "layer": "L0", "title": "数字护栏", "criterion": "逐项核对", "points": 0},
            {"id": "L1-01", "layer": "L1", "title": "引用安全", "criterion": "<script>alert(1)</script>", "points": 3},
            {"id": "N-01", "layer": "N", "title": "虚构事实", "criterion": "不得虚构", "points": -5},
        ],
    }
    (pack / "rubric.json").write_text(json.dumps(rubric, ensure_ascii=False), encoding="utf-8")
    for company in ("甲公司", "乙公司"):
        result = pack / "results" / company
        result.mkdir(parents=True)
        score = {
            "rubric": "test_v0", "total": 80, "deliverable": True, "not_deliverable_reasons": [],
            "layers": {k: {"earned": 0, "possible": 1} for k in ("L1", "L2", "L3")},
            "items": [
                {"id": "L0-01", "layer": "L0", "passed": True, "reason": "无异常", "evidence": ""},
                {"id": "L1-01", "layer": "L1", "passed": False,
                 "reason": "原文 <img src=x onerror=alert(1)>", "evidence": "页 3"},
                {"id": "N-01", "layer": "N", "passed": True, "reason": "涉嫌虚构", "evidence": "页 4"},
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
    assert "LEDGER / 人工质检页" in text and "FinAgent / 人工质检页" not in text
    assert text.count('<details class="review-item ') == 3
    assert text.count('data-reviewable="true"') == 2  # L1 未过 + N 命中
    assert '<details class="review-item clear" data-item-id="L0-01">' in text
    assert 'class="cleared"' not in text
    assert 'id="collapse-all"' in text and 'id="expand-all"' in text
    assert 'id="onlyfail"' in text
    assert "模型指出的问题成立吗" in text and "错，模型误判" in text
    assert "默认沿用" in text and "其余 1 项" in text
    assert "导出质检 JSON" in text and "导入先前 JSON" in text
    assert "页内查看 PDF" in text and "下载 PDF" in text
    assert "未执行工作簿检查" in text
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


def test_real_pack_routes_only_flagged_issues(tmp_path):
    pack = PROJECT_ROOT / "eval" / "review_pack" / "v0"
    paths = build_review_docs(pack, tmp_path / "demo")
    assert len(paths) == 3
    for path in paths:
        text = path.read_text(encoding="utf-8")
        embedded = re.search(r'<script type="application/json" id="pack-data">(.*?)</script>', text)
        data = json.loads(embedded.group(1))
        assert text.count('<details class="review-item ') == len(data["items"])
        assert text.count('data-reviewable="true"') == data["flagged_count"]
        assert data["flagged_count"] == sum(item["flagged"] for item in data["items"])
        assert all(not (item["flagged"] and item["machine_only"]) for item in data["items"])
        assert len(data["items"]) == 40
        assert "aggregation: null" in text
        if path.stem in ("宁德时代", "招商轮船"):
            assert data["machine_excel"]["status"] == "pass"
        else:
            assert data["machine_excel"]["status"] == "not_run"
        if path.stem == "招商轮船":
            assert data["flagged_count"] == 13
            assert sum(item["machine_only"] for item in data["items"]) == 2
