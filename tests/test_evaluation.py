"""研报评测：评分标准、程序检查、评审输出解析、计分与 refine 循环。"""

import json

import pytest

from finagent import report_pipeline as rp
from finagent.evaluation import __main__ as ev
from finagent.evaluation import judge
from finagent.evaluation.checks import CHECKS, run_checks
from finagent.evaluation.rubric import Bundle, judge_items, load_rubric, score


@pytest.fixture()
def rubric():
    return load_rubric()


def test_rubric_layers_and_weights(rubric):
    pts = {}
    for it in rubric["items"]:
        pts[it["layer"]] = pts.get(it["layer"], 0) + it["points"]
        if it["judge"] == "program":
            assert it["check"] in CHECKS
    assert (pts["L1"], pts["L2"], pts["L3"]) == (35, 45, 20) and pts["L0"] == 0 and pts["N"] < 0
    hidden = judge_items(rubric)
    assert hidden and all("points" not in it and "layer" not in it for it in hidden)
    assert {it["id"] for it in hidden} == {it["id"] for it in rubric["items"] if it["judge"] == "llm"}


def _all(rubric, passed=True, negative=False):
    return {it["id"]: {"passed": negative if it["layer"] == "N" else passed, "reason": "r", "evidence": "e"}
            for it in rubric["items"]}


def test_score_caps_and_delivery(rubric):
    full = score(rubric, _all(rubric))
    assert full["total"] == 100 and full["deliverable"]
    res = _all(rubric)
    res["L0-01"]["passed"] = False  # 硬闸门失败 → 封顶
    sc = score(rubric, res)
    assert sc["total"] == rubric["gate_cap"] and not sc["deliverable"] and "L0-01" in sc["caps"][0]["by"]
    res = _all(rubric)
    res["N-01"]["passed"] = True  # 命中负向条目：扣分并封顶 70
    sc = score(rubric, res)
    assert sc["deduction"] == -8 and sc["total"] == 70 and not sc["deliverable"]
    sc = score(rubric, _all(rubric, negative=True))
    assert sc["deduction"] == rubric["negative_floor"]
    res = _all(rubric)
    del res["L2-01"]
    sc = score(rubric, res)
    assert sc["missing"] == ["L2-01"] and sc["total"] == 96


def _bundle(tmp_path, text="DCF 基准情景每股价值 1,531.40 元，给予“买入”评级。本报告不构成投资建议。"):
    run, work = tmp_path / "run", tmp_path / "work"
    (run / "valuation").mkdir(parents=True)
    (work / "report").mkdir(parents=True)
    scen = [{"scenario": k, "scenario_cn": k, "enterprise_value_mm": ev_, "equity_value_mm": ev_ + 100,
             "value_per_share": (ev_ + 100) * 1e6 / 1e9, "tv_percent_ev": 0.7}
            for k, ev_ in (("base", 1531300.0), ("downside", 1000000.0), ("upside", 2000000.0))]
    val = {"value_range": {"low": 1000.1, "base": 1531.4, "high": 2000.1}, "scenarios": scen,
           "bridge_base": {"add_backs": 150.0, "deductions": 50.0},
           "three_statement_tie": {"status": "pass", "items": ["revenue"], "max_abs_diff_mm": 0},
           "sensitivity_directionality": {"passed": True, "details": [{"check": "a", "passed": True}]}}
    fs = {"market": {"price": 1237.0, "price_date": "2026-09-24", "price_source": "x", "total_shares": 1e9},
          "rating": {"rating": "买入", "upside": 0.238, "rule": "买入：≥20%；增持：≥5%；中性：≥-5%；减持：≥-20%；卖出：其余"},
          "years": [{"year": "2025A", "gross_margin": 91.0, "revenue_growth": 10.0},
                    {"year": "2026E", "gross_margin": 90.0, "revenue_growth": 8.0}]}
    seg = {"base_year": {"revenue": 100.0, "other_revenue": 20.0, "segments": [{"revenue": 60.0}, {"revenue": 30.0}]}}
    for name, data in (("valuation", val), ("forecast_summary", fs), ("segment_forecast", seg)):
        (run / "valuation" / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (work / "report/narrative.md").write_text(text, encoding="utf-8")
    return Bundle("测试公司", run, work)


def test_program_checks(tmp_path, rubric):
    b = _bundle(tmp_path)
    p = {}
    assert CHECKS["bridge"](b, p)["passed"] and CHECKS["per_share"](b, p)["passed"]
    assert CHECKS["rating"](b, p)["passed"] and CHECKS["text_valuation"](b, p)["passed"]  # 千分位写法
    assert CHECKS["disclaimer"](b, p)["passed"] and CHECKS["scenario_order"](b, p)["passed"]
    assert CHECKS["forecast_continuity"](b, {"gross_margin_pp": 5, "growth_pp": 30})["passed"]
    seg = CHECKS["segment_base"](b, p)
    assert not seg["passed"] and "差 10.00" in seg["detail"]
    assert not CHECKS["terminal_share"](b, {"max": 0.6})["passed"]
    assert "缺" in CHECKS["sources"](b, p)["detail"] and not CHECKS["numlock"](b, p)["passed"]
    # 评级与规则不符
    fs = json.loads((b.run / "valuation/forecast_summary.json").read_text(encoding="utf-8"))
    fs["rating"]["upside"] = 0.1
    (b.run / "valuation/forecast_summary.json").write_text(json.dumps(fs, ensure_ascii=False), encoding="utf-8")
    assert "应为 增持" in CHECKS["rating"](b, p)["detail"]
    # 缺文件或格式异常不抛错，记为未通过
    res = run_checks(rubric, Bundle("空", tmp_path / "none", tmp_path / "none"))
    assert len(res) == sum(it["judge"] == "program" for it in rubric["items"])
    assert not any(r["passed"] for r in res.values())


def test_sources_and_review_checks_need_substance(tmp_path):
    """人工质检意见：只有文件不算数。引用要对得上登记，复核清单要有填完的事项。"""
    b = _bundle(tmp_path, "行业规模达 812.5 亿元[S1]。")
    src = {"questions": [{"id": "Q1", "queries": ["行业规模"], "status": "found", "sources": ["S1"]}],
           "sources": [{"id": "S1", "url": "https://example.com", "title": "t", "publisher": "p", "accessed": "2026-10-01",
                        "facts": [{"quote": "行业规模达 812.5 亿元", "value": 812.5, "unit": "亿元"}]}]}
    (b.work / "research").mkdir()
    (b.work / "research/sources.json").write_text(json.dumps(src, ensure_ascii=False), encoding="utf-8")
    assert CHECKS["sources"](b, {})["passed"]
    for text, why in (("行业规模达 812.5 亿元。", "外部数字没标编号"), ("行业规模达 812.5 亿元[S1]，增速见[S9]。", "引用未登记的编号"),
                      ("行业空间广阔。", "正文没有引用")):
        (b.work / "report/narrative.md").write_text(text, encoding="utf-8")
        assert not CHECKS["sources"](b, {})["passed"], why

    review = b.work / "report/review.md"
    head = "# 复核清单\n\n| # | 事项 | 为什么重要 | 当前处理 | 请核对 |\n|---|---|---|---|---|\n"
    review.write_text(head, encoding="utf-8")
    assert not CHECKS["review_list"](b, {})["passed"]  # 只有表头
    review.write_text(head + "| 1 | 缺分船型 TCE |  |  |  |\n", encoding="utf-8")
    assert not CHECKS["review_list"](b, {})["passed"]  # 事项没填完
    review.write_text(head + "| 1 | 缺分船型 TCE | 支撑利润见顶判断 | 只保留分部利润 | 是否有行业数据可补 |\n", encoding="utf-8")
    assert CHECKS["review_list"](b, {})["passed"]
    review.write_text("# 复核清单\n\n无\n", encoding="utf-8")
    assert CHECKS["review_list"](b, {})["passed"]


def test_read_judgments(tmp_path, rubric):
    path = tmp_path / "judgments.json"
    assert judge.read_judgments(path, rubric)[1] == ["评审未写出 judgments.json"]
    items = [{"id": "L2-01", "passed": True, "evidence": "e", "reason": "r"},
             {"id": "L2-01", "passed": False}, {"id": "L1-01", "passed": True}, {"id": "L2-02", "passed": "yes"}]
    path.write_text(json.dumps({"items": items}), encoding="utf-8")
    got, problems = judge.read_judgments(path, rubric)
    assert list(got) == ["L2-01"] and got["L2-01"]["passed"]
    assert "重复条目 L2-01" in problems and "多余条目 L1-01" in problems
    assert "L2-02: passed 不是布尔值" in problems and "缺条目 L2-02" in problems


def test_prepare_blind_dir(tmp_path, rubric):
    b = _bundle(tmp_path)
    dest = judge.prepare(b, rubric, tmp_path / "blind")
    assert (dest / "CLAUDE.md").is_file() and (dest / "deliverable/narrative.md").is_file()
    assert (dest / "deliverable/model/valuation.json").is_file()
    assert "points" not in (dest / "rubric.json").read_text(encoding="utf-8")
    cmd = judge.command()
    assert cmd[cmd.index("--model") + 1] == rp.QC_MODEL and "Write(./judgments.json)" in cmd
    with pytest.raises(SystemExit):
        judge.prepare(b, rubric, ev.RESULTS / "blind")  # 仓库内会读到 CLAUDE.md


def test_evaluate_without_judge_and_rescore(tmp_path, rubric):
    b = _bundle(tmp_path)
    out = tmp_path / "out"
    sc = ev.evaluate(b, out, use_judge=False)
    assert (out / "scorecard.md").is_file() and sc["layers"]["L2"]["earned"] == 0
    issues = json.loads((out / "issues.json").read_text(encoding="utf-8"))
    assert issues and all(set(i) == {"id", "route", "stage", "severity", "description", "evidence"} for i in issues)
    titles = {it["title"] for it in rubric["items"]}
    assert not any(i["description"] in titles for i in issues)  # 问题单不带条目标题
    # 评审结果补进来后重算，不重跑程序检查
    judged = [{"id": it["id"], "passed": not it["negative"]} for it in judge_items(rubric)]
    (out / "judgments.json").write_text(json.dumps({"items": judged}), encoding="utf-8")
    sc2 = ev.rescore(out, rubric)
    assert sc2["layers"]["L2"]["earned"] == 45 and sc2["total"] > sc["total"]
    assert "L2-01" in ev.compare_markdown([out, out])


def test_workspace_excludes_evaluation(tmp_path):
    ws = rp.build("贵州茅台", 2025, tmp_path / "samples")
    assert not (ws / "finagent/evaluation").exists()
    assert not list(ws.rglob("report_v*.json"))


def test_role_models():
    assert rp._role_model("claude", "write", None) == rp.GEN_MODEL
    assert rp._role_model("claude", "review", None) == rp.QC_MODEL
    assert rp._role_model("claude", "review", "x") == "x" and rp._role_model("claude", "review", "x", "y") == "y"
    assert rp._role_model("codex", "write", None) is None


def test_refine_loop_routes_issues_and_restores_best(tmp_path, monkeypatch):
    ws = rp.build("贵州茅台", 2025, tmp_path / "samples")
    monkeypatch.setenv("FINAGENT_EVAL_DIR", str(tmp_path / "evals"))
    report = ws / "data/extractions/贵州茅台_2025/report"
    (report / "review.md").write_text("# 复核清单\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(rp, "run_agent", lambda *a, **k: calls.append(("run", a[2], a[3])) or 0)
    monkeypatch.setattr(rp, "_session", lambda ws_, agent, model, role, prompt: calls.append((role, model, prompt)) or 0)
    monkeypatch.setattr(rp, "_writing_done", lambda ws_: True)
    real_status = rp.status
    monkeypatch.setattr(rp, "status", lambda ws_: {**real_status(ws_), "done": True})
    import finagent.evaluation.rubric as rb
    monkeypatch.setattr(rb, "bundle_from_workspace", lambda ws_: None)
    plan = [(60, [("generator", "缺定量驱动"), ("reviewer", "机器腔")]), (55, [("reviewer", "结论不先行")]),
            (58, [("reviewer", "x")])]

    def fake_eval(b, out, **kw):
        total, issues = plan.pop(0)
        out.mkdir(parents=True)
        (report / "narrative.md").write_text(f"第 {total} 分的文稿", encoding="utf-8")
        rows = [{"id": f"I{i}", "route": r, "stage": "s", "severity": "major", "description": d, "evidence": ""}
                for i, (r, d) in enumerate(issues)]
        (out / "issues.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        (out / "issues.md").write_text(ev.issues_markdown(rows), encoding="utf-8")
        return {"total": total, "deliverable": False, "not_deliverable_reasons": ["x"]}

    monkeypatch.setattr(ev, "evaluate", fake_eval)
    state = rp.refine(ws, max_rounds=3)
    assert [r["total"] for r in state["rounds"]] == [60, 55, 58] and state["best"] == 1
    assert state["stopped"] == "达到最大轮数 3" and state["restored"]
    roles = [c[0] for c in calls]
    assert roles == ["run", "fix", "review", "run", "revise"]  # 第 2 轮：先修、复核问题单，再按闸门续做；第 3 轮只有复核类
    assert calls[0][1:] == (rp.GEN_MODEL, rp.QC_MODEL) and calls[1][1] == rp.GEN_MODEL and calls[4][1] == rp.QC_MODEL
    assert "issues-generator.md" in calls[1][2] and "issues-reviewer.md" in calls[2][2]
    # 问题单在工作区里，评测结果（含分值）不在
    assert (ws / ".pipeline/rounds/1/issues-generator.md").is_file()
    assert not list(ws.rglob("score.json")) and (tmp_path / "evals" / ws.name / "loop.json").is_file()
    assert (report / "narrative.md").read_text(encoding="utf-8") == "第 60 分的文稿"  # 回滚到最佳一轮
    assert "质检循环未达交付标准" in (report / "review.md").read_text(encoding="utf-8")


def test_stop_reasons():
    r = lambda t, d=False, g=1, v=1: {"total": t, "deliverable": d, "issues": {"generator": g, "reviewer": v}}  # noqa: E731
    assert rp._stop_reason([r(80, True)], 3, 2) == "达到交付标准"
    assert rp._stop_reason([r(50), r(51), r(52)], 5, 2).startswith("连续两轮")
    assert rp._stop_reason([r(50), r(60)], 5, 2) is None
    assert rp._stop_reason([r(50, g=0, v=0)], 5, 2) == "没有可回传的问题"


def test_refine_stops_without_evaluating_when_gates_fail(tmp_path, monkeypatch):
    ws = rp.build("贵州茅台", 2025, tmp_path / "samples")
    monkeypatch.setenv("FINAGENT_EVAL_DIR", str(tmp_path / "evals"))
    monkeypatch.setattr(rp, "run_agent", lambda *a, **k: 0)
    monkeypatch.setattr(ev, "evaluate", lambda *a, **k: pytest.fail("闸门未通过不应评测"))
    state = rp.refine(ws, max_rounds=2)
    assert state["rounds"] == [] and state["stopped"].startswith("第 1 轮闸门未通过")
