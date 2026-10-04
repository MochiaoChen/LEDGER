"""评审校准：劣化算子只改目标内容；汇总按原稿多数判定计算命中与连带改判。"""

import json

import pytest

from finagent.evaluation.calibrate import DEGRADATIONS, degrade, summarize_company

NARRATIVE = """<!-- section: title -->
标题

<!-- section: summary -->
**盈利预测及投资建议：** 我们预计……给予“卖出”评级。

**风险提示：** 工业场景放量超预期；估值参数偏差。

<!-- section: thesis -->
### 核心观点

第一段观点。

### 市场关注的问题与我们的判断

- 问题一。

<!-- section: deep_industry -->
### 行业空间

**出货进入万台级。** 行业出货 1.8 万台 [S14]。

**中长期空间。** 机构预测 51 万台 [S15]。

<!-- section: deep_topic_4 -->
### 深度专题四：450 元的股价隐含了什么

反向 DCF。

<!-- section: deep_expectations -->
### 预期差：增速与估值方法

我们比市场保守。

<!-- section: valuation -->
### DCF 估值

每股价值 49.88 元。

### 相对估值与交叉验证

市销率参照。

<!-- section: risks -->
- **工业场景放量超预期**：乐观情景每股价值 109.06 元。

<!-- section: tracking -->
### 跟踪指标

- 三季报收入增速。
"""


def test_every_degradation_changes_only_what_it_claims():
    for kind in DEGRADATIONS:
        assert degrade(NARRATIVE, kind) != NARRATIVE
    assert "交叉验证" not in degrade(NARRATIVE, "no_cross_check") and "DCF 估值" in degrade(NARRATIVE, "no_cross_check")
    gap = degrade(NARRATIVE, "no_expectation_gap")
    assert "市场关注" not in gap and "反向 DCF" not in gap and "我们比市场保守" not in gap and "核心观点" in gap
    flipped = degrade(NARRATIVE, "contradiction")
    assert "给予“买入”评级" in flipped and flipped.count("买入") == 1
    assert "109.06" not in degrade(NARRATIVE, "generic_risks")
    assert "三季报收入增速" not in degrade(NARRATIVE, "no_tracking")
    assert "4,800 亿元" in degrade(NARRATIVE, "unsourced_number")
    assert "根据程序计算结果" in degrade(NARRATIVE, "machine_tone")


def test_degradation_refuses_when_section_missing():
    with pytest.raises(ValueError):
        degrade("<!-- section: title -->\n标题\n", "no_tracking")


def _write(d, name, flags, total, meta=None):
    p = d / name
    p.mkdir(parents=True)
    items = [{"id": i, "layer": "N" if i.startswith("N") else "L2", "judge": "llm",
              "passed": f if i.startswith("N") else not f} for i, f in flags.items()]
    (p / "score.json").write_text(json.dumps({"items": items, "total": total}), encoding="utf-8")
    if meta:
        (p / "variant.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def test_summary_counts_hits_against_clean_majority(tmp_path):
    base = {"L2-09": False, "L2-12": False, "N-01": False}
    _write(tmp_path, "clean1", base, 88)
    _write(tmp_path, "clean2", base | {"L2-12": True}, 85)
    _write(tmp_path, "clean3", base, 88)
    _write(tmp_path, "no_cross_check", base | {"L2-09": True}, 82, {"targets": ["L2-09"], "desc": "删交叉验证"})
    _write(tmp_path, "unsourced_number", base | {"L2-12": True}, 80, {"targets": ["N-01"], "desc": "无来源数字"})
    s = summarize_company(tmp_path)
    assert s["stability"]["unanimous"] == 2 and s["stability"]["total_range"] == 3
    v = {x["variant"]: x for x in s["variants"]}
    assert v["no_cross_check"]["hit"] == {"L2-09": True} and v["no_cross_check"]["collateral"] == []
    assert v["unsourced_number"]["hit"] == {"N-01": False} and v["unsourced_number"]["collateral"] == ["L2-12"]
    assert s["detection"] == {"valid": 2, "hit": 1, "rate": 0.5}


def test_rescore_flags_judge_that_never_wrote_judgments(tmp_path):
    # 额度用尽时评审会话第一轮就退出：不能静默把评审条目全部按不通过计分
    from finagent.evaluation.__main__ import rescore
    from finagent.evaluation.rubric import load_rubric

    (tmp_path / "checks.json").write_text("{}", encoding="utf-8")
    (tmp_path / "bundle.json").write_text(json.dumps({"company": "测试"}), encoding="utf-8")
    (tmp_path / "judge_run.json").write_text(json.dumps({"exit_code": 1}), encoding="utf-8")
    sc = rescore(tmp_path, load_rubric())
    assert any("judgments.json" in p for p in sc["judge_problems"])
    assert any("异常退出" in p for p in sc["judge_problems"])
