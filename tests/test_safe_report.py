"""Declarative renderer must reject code, markup and unverified table IDs."""

import pytest

from finagent.safe_report import required_basis_keys, validate_layout


def layout():
    return {"sector": "电力设备 · 电池", "headings": [
        "投资逻辑：出货增长", "公司概况：动力与储能双业务", "业绩回顾：收入增长",
        "经营分析：储能增速高", "盈利能力：毛利率改善", "资产负债与现金流：回款稳定",
        "盈利预测：量价驱动", "估值：折现敏感", "投资建议：谨慎增持", "风险提示：销量低于预期",
    ], "extra_tables": ["product"], "assumption_basis": {"储能销量增速": "见经营分析"},
            "method_note": "合并口径；分部预测为分析师假设。"}


def test_layout_accepts_only_verified_data():
    assert validate_layout(layout(), {"product"})["extra_tables"] == ["product"]
    for changed in ({"extra_tables": ["fake"]}, {"headings": ["x"] * 10},
                    {"script": "import os"}, {"extra_tables": ["product", "product"]}):
        doc = layout()
        doc.update(changed)
        with pytest.raises(ValueError):
            validate_layout(doc, {"product"})


def test_existing_extra_tables_cannot_be_silently_omitted():
    doc = layout()
    doc["extra_tables"] = []
    with pytest.raises(ValueError, match="至少选择"):
        validate_layout(doc, {"product"})


def test_forecast_assumptions_need_specific_basis():
    seg = {"scenarios": {"base": {"segments": [{"name": "动力电池"}],
                                  "expense_ratios": {"selling": [0.1]}}}}
    keys = required_basis_keys(seg, {"drivers": {"dividend_payout": [0.5]}})
    assert keys == {"动力电池销量增速", "动力电池单价增速", "动力电池毛利率",
                    "销售费用率", "其他费用率", "现金分红率"}
    with pytest.raises(ValueError, match="关键假设依据缺失"):
        validate_layout(layout(), {"product"}, keys)
    doc = layout()
    doc["assumption_basis"] = {key: "依据经营分析第 4 节的历史趋势" for key in keys}
    assert validate_layout(doc, {"product"}, keys)["assumption_basis"]
