"""Original-page selection is deterministic and bounded."""

from finagent.report_evidence import cited_pages, compact_tables, compact_truth, qualitative_only


def test_cited_pages_prefers_thesis_and_keeps_physical_page_numbers():
    framework = "## 一、投资逻辑\n依据 P9–P11、P20\n## 二、驱动清单\n后文 P77"
    assert cited_pages(framework, [15, 20, 1200, None], page_count=100) == [9, 10, 11, 20, 15, 77]
    assert cited_pages("P0、P101、P5", [], page_count=100, limit=1) == [5]


def test_compact_evidence_preserves_values_and_page_but_not_duplicate_metadata():
    fact = {"metric_id": "revenue", "period": "2025", "value": 123.0, "unit": "元",
            "raw": "123", "source": {"page": 9, "chunk_id": "c001"}}
    assert compact_truth([fact]) == [{"metric": "revenue", "period": "2025", "value": 123.0,
                                    "unit": "元", "page": 9}]
    table = {"id": "t", "title": "标题", "page": 12, "columns": [{"name": "收入", "unit": "元"}],
             "rows": [{"label": "业务", "raw": ["123"], "values": [123.0], "alias": ["别名"]}]}
    assert compact_tables([table])[0]["rows"] == [{"label": "业务", "values": [123.0]}]


def test_qualitative_excerpt_cannot_supply_unverified_numbers():
    text = "2025 年处置收益 6.77 亿元，出口单箱收入下降 2.4%。"
    masked = qualitative_only(text)
    assert "2025" not in masked and "6.77" not in masked and "2.4" not in masked
    assert "处置收益" in masked and "出口单箱收入下降" in masked
