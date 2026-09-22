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
