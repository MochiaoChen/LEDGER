"""分部预测的销量单位与单价名称：假设文件可写 volume_unit / price_label / price_unit（如 GWh、单价），
缺省仍为吨 / 吨价 / 万元/吨（茅台样例不变）。只影响工作簿表头，不影响计算。"""

from __future__ import annotations

from finagent.tasks.valuation import segment_forecast as seg_mod
from finagent.tasks.valuation.workbook import _Grid
from finagent.tasks.valuation.workbook_ts import _segment_sheet

EXTRAS = {"tables": [
    {"id": "product", "columns": [{"name": "营业收入"}, {"name": "营业成本"}],
     "rows": [{"label": "A", "values": [800e6, 600e6]}]},
    {"id": "volume", "columns": [{"name": "销量"}], "rows": [{"label": "A", "values": [10.0]}]},
]}
TRUTH = [{"metric_id": m, "period": "2025", "value": v} for m, v in
         (("revenue", 1000e6), ("operating_cost", 700e6), ("total_profit", 150e6), ("finance_expense", 0.0),
          ("depreciation", 10e6), ("amortization", 0.0))]
SCEN = {"volume_growth": [0.1, 0.1], "price_growth": [0.0, 0.0], "gm_change_pp": [0, 0]}


def _spec(**kw):
    return {"segments": [{"id": "a", "name": "A", "product_row": "A",
                          "scenarios": {k: SCEN for k in ("base", "downside", "upside")}}], **kw}


def _labels(seg):
    g_rows = []

    def add(g, sid, key, cells, **kw):
        r = g.add(cells, **kw)
        g_rows.append(cells[0] if cells else "")
        return r

    grid = _segment_sheet(seg, ["D", "E"], 2, add, lambda t: [t, "FY2025A", "FY2026E", "FY2027E"])
    assert isinstance(grid, _Grid)
    return [x for x in g_rows if isinstance(x, str)], grid.rows[1][0]


def test_default_units_are_tons():
    seg = seg_mod.build(_spec(), EXTRAS, TRUTH, "2025", 2)
    assert "volume_unit" not in seg  # 未指定时产物字段不变
    labels, note = _labels(seg)
    assert "A：销量（吨）" in labels and "A：吨价（万元/吨）" in labels and "吨价单位万元/吨" in note


def test_custom_units_flow_to_workbook():
    seg = seg_mod.build(_spec(volume_unit="GWh", price_label="单价", price_unit="万元/GWh"), EXTRAS, TRUTH, "2025", 2)
    assert seg["volume_unit"] == "GWh"
    labels, note = _labels(seg)
    assert "A：销量（GWh）" in labels and "A：单价增速" in labels and "A：单价（万元/GWh）" in labels
    assert "单价单位万元/GWh" in note and not any("吨" in x for x in labels)
