"""Historical binding must not compare annual consolidated totals with other scopes."""

from finagent.output.guard import _binding_candidate, _extras_scaled_numbers, check_text


def test_binding_candidate_avoids_quarter_segment_and_cash_flow_aliases():
    segment = {"油轮运输": [102.89]}
    claim = {"sentence": "2025 年公司营业收入 281.77 亿元。", "is_forecast": False}
    assert _binding_candidate(claim, 2025, segment)
    for sentence in (
        "2025 年一季度营业收入 55.95 亿元。",
        "油轮运输营业收入 102.89 亿元。",
        "购建固定资产、无形资产支付的现金 77.97 亿元。",
        "2024 年收入 257.99 亿元，2025 年收入 281.77 亿元。",
        "预计 2026 年营业收入 298.68 亿元。",
    ):
        assert not _binding_candidate({"sentence": sentence, "is_forecast": False}, 2025, segment)


def test_operating_table_units_are_scaled_for_source_check():
    values = []
    _extras_scaled_numbers({"tables": [{"columns": [{"unit": "万吨"}, {"unit": "亿元"}],
                                "rows": [{"values": [8162, 0.55]}]}]}, values)
    assert check_text("货运量 8,162 万，收入 0.55 亿元", values) == []
