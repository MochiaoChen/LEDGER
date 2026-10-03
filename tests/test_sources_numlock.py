"""外部资料登记与数字锁：检索登记校验、外部数字须带来源编号、复核改写不得新增或改动数字。"""

from finagent.output.guard import check_text
from finagent.output.sources import check_citations, fact_values, verify_sources
from finagent.output.numlock import numlock


SOURCES = {
    "questions": [{"id": "Q1", "question": "全球油轮运力增速", "status": "found",
                   "queries": ["2026 油轮 运力 增速"], "sources": ["S1"]}],
    "sources": [{"id": "S1", "title": "油轮市场展望", "publisher": "Clarksons", "url": "https://example.com/a",
                 "published": "2026-01-15", "accessed": "2026-10-02",
                 "facts": [{"quote": "预计 2026 年全球油轮运力增长 2.1%，新船交付 1,234 万载重吨。",
                            "value": 2.1, "unit": "%", "label": "运力增速"},
                           {"quote": "新船交付 1,234 万载重吨", "value": 1234, "unit": "万", "label": "交付"}]}],
}


def test_verify_sources():
    assert verify_sources(SOURCES)["ok"]
    bad = {"questions": [{"id": "Q1", "status": "found", "queries": []}],
           "sources": [{"id": "S1", "title": "t", "publisher": "p", "url": "记忆", "accessed": "昨天",
                        "facts": [{"quote": "运力增长 2.1%", "value": 3.5, "unit": "%"}]}]}
    probs = " ".join(verify_sources(bad)["problems"])
    for key in ("缺网址", "accessed", "不在摘句", "没有检索记录", "没有关联来源"):
        assert key in probs, key
    assert fact_values(SOURCES)["S1"] == [2.1, 1234e4]


def test_external_numbers_need_citation():
    truth = [100.0]
    text = "预计 2026 年全球油轮运力增长 2.1%。"
    probs = check_citations(text, SOURCES, truth, check_text)
    assert probs and "[S编号]" in probs[0]["problem"]
    assert not check_citations("预计 2026 年全球油轮运力增长 2.1% [S1]。", SOURCES, truth, check_text)
    assert "不存在的来源" in check_citations("运力增长 2.1% [S9]。", SOURCES, truth, check_text)[0]["problem"]


def test_numlock_allows_deletion_blocks_new_numbers():
    draft = ("营业收入 58.62 亿元，同比增长 14.49%。不过，年报未披露分产品产量，只能间接验证。\n"
             "预计 2026 年运力增长 2.1% [S1]。<!-- 提示 12.3% -->")
    # 删句、改措辞：通过
    edited = "营业收入 58.62 亿元，同比增长 14.49%。我们预计 2026 年运力增长 2.1% [S1]。"
    res = numlock(draft, edited)
    assert res["ok"] and res["removed"] == 0
    assert numlock(draft, "营业收入 58.62 亿元。")["removed"] == 2
    # 改数字、补数字、新增来源编号：拒绝
    assert numlock(draft, "营业收入 58.6 亿元。")["added"] == ["58.6亿元"]
    assert numlock(draft, "毛利率 31.19%。")["added"] == ["31.19%"]
    assert numlock(draft, "运力增长 2.1% [S2]。")["new_sources"] == ["S2"]
    # 单位不同算改动；HTML 注释里的数字不算原稿内容
    assert not numlock(draft, "营业收入 58.62 万元。")["ok"]
    assert not numlock(draft, "增长 12.3%。")["ok"]
