from finagent.core.numbers import half_ulp, parse_number, pct_change
from finagent.tasks.financials.extract import parse_period
from finagent.tasks.financials.schema import match_label


def test_parse_number():
    assert parse_number("1,234.50") == 1234.5
    assert parse_number("(1,234.50)") == -1234.5
    assert parse_number("-12.3%") == -12.3
    assert parse_number("—") is None
    assert parse_number("增加1.23个百分点") is None


def test_pct_change_negative_base():
    assert pct_change(50, -100) == 150.0  # 基期为负用 |基期|
    assert pct_change(1, 0) is None


def test_half_ulp():
    assert half_ulp("58.62", 1e8) == 0.005 * 1e8


def test_label_matching_is_exact():
    assert match_label("五、净利润") == "net_profit"
    assert match_label("归属于母公司股东的净利润") == "np_parent"
    assert match_label("其中：营业收入") == "revenue"
    assert match_label("基本每股收益（元／股）") == "eps_basic"
    assert match_label("合计") is None
    assert match_label("合计", "九、非经常性损益项目及金额") == "non_recurring"


def test_parse_period():
    assert parse_period("2024年") == "2024"
    assert parse_period("2024年12月31日") == "2024"
    assert parse_period("2024年1-9月") == "2024Q1-3"
    assert parse_period("2024年第三季度") == "2024Q3"
    assert parse_period("本年比上年增减") == "chg"
    assert parse_period("本期", 2024) == "2024"
    assert parse_period("上期", 2024) == "2023"


def test_da_is_known_metric_for_claim_diagnosis():
    """折旧摊销（da）由 analyze 派生，也在口径组里；不在指标字典时，口径错误会被误判为数值错误。"""
    from finagent.tasks.report_check.verify import verify_claims

    def row(mid, v):
        return {"metric_id": mid, "period": "2025", "value": v, "raw": str(v), "unit": "元", "source": {},
                "method": "derived" if mid == "da" else "rule_table"}

    table = [row("depreciation", 8e8), row("amortization", 2e8), row("da", 1e9)]
    claim = {"id": "C1", "metric_id": "depreciation", "period": "2025", "claim_type": "level", "unit": "亿元",
             "raw_value": "10.00", "value": 10.0, "quote": "固定资产折旧 10.00 亿元", "is_forecast": False}
    f = verify_claims([claim], table)["findings"][0]
    assert f["verdict"] == "口径错误" and "折旧摊销" in f["explanation"]
    da_claim = {**claim, "metric_id": "da", "raw_value": "8.00", "value": 8.0, "quote": "折旧摊销 8.00 亿元"}
    assert verify_claims([da_claim], table)["findings"][0]["verdict"] == "口径错误"
