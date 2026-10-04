"""PDF 表格的稀疏列合并、科目折行与跨页续表（用真实年报里出现过的版式构造）。"""

from finagent.parsing.document import Chunk, Document, compact_columns, link_continuation, merge_wrapped_labels
from finagent.tasks.financials.extract import extract_rule


def _table(cid: str, page: int, rows: list[list[str]], caption: str = "合并资产负债表") -> Chunk:
    return Chunk(cid, "annual.pdf", page, "table", "", rows=rows, unit_hint="元", caption=caption)


def _values(facts):
    return {(f.metric_id, f.period): f.value for f in facts}


def test_compact_columns_aligns_header_and_numbers():
    # 宁德时代：科目在第 2 列，表头“期末余额”比数字右移一列，其余列全空
    raw = [["", "项目", "", "", "期末余额", "", "", "期初余额", ""],
           ["", "货币资金", "", "333,512,927", "", "", "303,511,993", "", ""],
           ["投资活动产生的现金流量净额", "", "", "-79,421,912", "", "", "-19,213,430", "", ""]]
    assert compact_columns(raw) == [["项目", "期末余额", "期初余额"],
                                    ["货币资金", "333,512,927", "303,511,993"],
                                    ["投资活动产生的现金流量净额", "-79,421,912", "-19,213,430"]]


def test_compact_columns_leaves_regular_tables_alone():
    rows = [["项目", "附注", "2025年12月31日", "2024年12月31日"], ["货币资金", "1", "10", "9"]]
    assert compact_columns(rows) is rows


def test_wrapped_labels_rejoin_the_row_with_numbers():
    rows = [["项目", "2025年", "2024年"],
            ["归属于上市公司股东", "72,201,282", "50,744,682"],
            ["的扣除非经常性损益", "", ""],
            ["的净利润", "", ""],
            ["购建固定资产、无形资产和其他长", "42,344,558", "31,179,943"],
            ["期资产支付的现金", "", ""],
            ["流动负债：", "", ""],
            ["短期借款", "", ""]]
    out = merge_wrapped_labels(rows)
    assert [r[0].replace("\n", "") for r in out] == [
        "项目", "归属于上市公司股东的扣除非经常性损益的净利润", "购建固定资产、无形资产和其他长期资产支付的现金",
        "流动负债：", "短期借款"]


def test_continuation_inherits_header_and_keeps_its_own_page():
    # 茅台：资产负债表跨三页，续页没有表头；附注列在续页全空
    p1 = _table("c1", 57, [["项目", "附注", "2025年12月31日", "2024年12月31日"],
                           ["货币资金", "1", "100.00", "90.00"]])
    head = [list(r) for r in p1.rows]
    p2 = _table("c2", 58, [])
    assert link_continuation(p2, [["应付账款", "", "30.00", "20.00"]], p1, head)
    p3 = _table("c3", 59, [])
    assert link_continuation(p3, [["负债和所有者权益（或\n股东权益）总计", "", "300.00", "290.00"]], p2, head)
    facts, _ = extract_rule(Document("annual.pdf", "sha", [p1, p2, p3]), 2025)
    got = _values(facts)
    assert got[("accounts_payable", "2025")] == 30.0 and got[("total_liab_equity", "2024")] == 290.0
    ap = next(f for f in facts if f.metric_id == "accounts_payable" and f.period == "2025")
    assert ap.source["page"] == 58 and ap.source["continued_from"] == "c1"


def test_continuation_with_different_cell_split():
    # 茅台利润表：续页把“2024年度”一列劈成两列，与表头一起合并列后对齐
    p1 = _table("c1", 61, [["项目", "附注", "2025年度", "2024年度"],
                           ["信用减值损失（损失以“-”", "54", "17.00", "-23.00"]], caption="合并利润表")
    raw = [["号填列）", "", "", "", ""],
           ["四、利润总额（亏损总额以“－”号填列）", "", "120.00", "110.00", ""],
           ["五、净利润（净亏损以“－”号填列）", "", "90.00", "", "85.00"]]
    p2 = _table("c2", 62, [], caption="合并利润表")
    assert link_continuation(p2, raw, p1, [list(r) for r in p1.rows])
    assert p1.rows[-1][0] == "信用减值损失（损失以“-”\n号填列）"  # 折行尾巴接回上一页末行
    got = _values(extract_rule(Document("annual.pdf", "sha", [p1, p2]), 2025)[0])
    assert got[("total_profit", "2024")] == 110.0 and got[("net_profit", "2024")] == 85.0


def test_continuation_rejected_when_columns_do_not_line_up():
    p1 = _table("c1", 10, [["项目", "2025年", "2024年"], ["营业收入", "1", "2"]])
    p2 = _table("c2", 11, [])
    assert not link_continuation(p2, [["营业收入", "1", "2", "3", "4"]], p1, [list(r) for r in p1.rows])
    assert p2.continued_from == ""


def test_ratio_reported_change_is_percentage_points():
    # 宁德时代主要会计数据表：加权平均 ROE 24.91% vs 24.13%，“本年比上年增减”列示 0.78%（百分点差）
    from finagent.tasks.financials.analyze import FactTable, _tieouts

    src = {"source": "annual.pdf", "page": 11, "chunk_id": "c1"}
    facts = [{"metric_id": "roe_weighted", "period": "2025", "value": 24.91, "raw": "24.91%", "source": src},
             {"metric_id": "roe_weighted", "period": "2024", "value": 24.13, "raw": "24.13%", "source": src},
             {"metric_id": "roe_weighted.reported_yoy", "period": "2025", "value": 0.78, "raw": "0.78%", "source": src}]
    checks = [c for c in _tieouts(FactTable(facts), "2025") if "财报列示同比" in c["check"]]
    assert [c["status"] for c in checks] == ["pass"]
