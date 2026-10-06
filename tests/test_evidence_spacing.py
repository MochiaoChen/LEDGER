"""Evidence matching must preserve numeric boundaries between PDF table cells."""

from finagent.parsing.document import Chunk, Document
from finagent.tasks.financials.external import find_evidence


def test_adjacent_table_numbers_keep_their_boundaries():
    chunk = Chunk("c1", "annual.pdf", 15, "table",
                  "| 自有船总计 235 3884.59 9.95 64 788.02 |")
    doc = Document("annual.pdf", "sha", [chunk])
    for raw in ("235", "3884.59", "9.95", "64", "788.02"):
        assert find_evidence(doc, 15, raw) is chunk
    assert find_evidence(doc, 15, "2353884.59") is None


def test_integer_does_not_match_decimal_in_source():
    """原文 3884.59 时，抄成整数 3884 不能通过证据校验；句末句号不影响。"""
    doc = Document("annual.pdf", "sha", [Chunk("c1", "annual.pdf", 15, "table", "| 运力 3884.59 |"),
                                         Chunk("c2", "annual.pdf", 16, "text", "全年营业收入 3884。")])
    assert find_evidence(doc, 15, "3884") is None
    assert find_evidence(doc, 15, "3,884.59") is not None
    assert find_evidence(doc, 16, "3884") is not None


def test_declared_unit_must_match_page_unit():
    """万元表被写成“元”：数字能在原文找到，但单位与页面声明不符，拒收。"""
    from finagent.tasks.financials.external import _to_fact
    doc = Document("annual.pdf", "sha", [Chunk("c1", "annual.pdf", 8, "table", "| 营业收入 | 12,345.67 |",
                                               unit_hint="万元")])
    item = {"metric_id": "revenue", "period": "2025", "raw_value": "12,345.67", "page": 8}
    assert "不一致" in _to_fact({**item, "unit": "元"}, doc)
    assert _to_fact({**item, "unit": "万元"}, doc).value == 123456700.0
    assert _to_fact(item, doc).value == 123456700.0  # 未写单位时沿用页面声明
