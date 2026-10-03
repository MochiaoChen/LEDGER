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
