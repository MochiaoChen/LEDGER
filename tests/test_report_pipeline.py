"""研报流水线：隔离工作区的内容边界、阶段闸门与收回。"""

import json
import os

import pytest

from conftest import ROOT
from finagent import report_pipeline as rp
from finagent.output import sources as sources_mod


@pytest.fixture()
def ws(tmp_path):
    return rp.build("贵州茅台", 2025, tmp_path / "samples", price=1500.0, price_source="测试行情")


def test_workspace_contains_only_skills_engine_and_one_company(ws):
    assert (ws / ".claude/skills/finagent-research/SKILL.md").is_file()
    assert (ws / ".claude/skills/finagent-report/reportkit/core.py").is_file()
    assert (ws / "finagent/__main__.py").is_file()
    assert not list(ws.rglob("__pycache__"))
    pdfs = list(ws.rglob("*.pdf"))
    assert [p.relative_to(ws).as_posix() for p in pdfs] == ["report/resources/贵州茅台/600519_贵州茅台_2025_年度报告.pdf"]
    assert (ws / "report/resources/贵州茅台/locate.json").is_file()
    # 不带其他公司的抽取、文稿、运行与交付，也不带测试和评测
    assert sorted(p.name for p in (ws / "data").iterdir()) == ["extractions", "samples"]
    assert [p.name for p in (ws / "data/extractions").iterdir()] == ["贵州茅台_2025"]
    assert not list((ws / "data/extractions/贵州茅台_2025").rglob("*.*"))
    for name in ("tests", "eval", "README.md", ".env", "runs/.gitkeep"):
        assert not (ws / name).exists()
    assert os.access(ws / "py", os.X_OK)


def test_workspace_guide_and_permissions(ws):
    meta = json.loads((ws / "sample.json").read_text(encoding="utf-8"))
    assert meta["verified_source"] and meta["inputs"]["market"]["current_price"] == 1500.0
    # 说明写在 AGENTS.md，Claude Code 通过 CLAUDE.md 引用同一份；skill 在 .agents/skills 有指向全文的入口
    assert (ws / "CLAUDE.md").read_text(encoding="utf-8") == "@AGENTS.md\n"
    guide = (ws / "AGENTS.md").read_text(encoding="utf-8")
    for name in rp.SKILLS:
        stub = (ws / ".agents/skills" / name / "SKILL.md").read_text(encoding="utf-8")
        assert f"name: {name}" in stub and f".claude/skills/{name}/SKILL.md" in stub
    assert not (ws / ".agents/skills/finagent-pipeline").exists()
    assert "贵州茅台 2025" in guide and "1500.0" in guide and "测试行情" in guide
    assert "report_pipeline status" in guide and "读取边界" in guide
    perms = json.loads((ws / ".claude/settings.json").read_text(encoding="utf-8"))["permissions"]
    assert f"Read(/{ROOT.parent.as_posix()}/**)" in perms["deny"]
    assert "Edit(./finagent/**)" in perms["deny"] and "Write(./.claude/**)" in perms["deny"]
    assert "Edit(./AGENTS.md)" in perms["deny"]
    # 外部信息必须联网检索：工作区放开 WebSearch / WebFetch，说明里写明不能凭记忆
    assert "WebSearch" in perms["allow"] and "WebSearch" not in perms["deny"] and "WebFetch" not in perms["deny"]
    assert "不能用记忆" in guide and "sources.json" in guide and "review.md" in guide and "finagent-review" in guide
    assert (ws / ".claude/skills/finagent-review/SKILL.md").is_file() and (ws / "REVIEW.md").is_file()
    assert "MPLCONFIGDIR" in (ws / "py").read_text(encoding="utf-8")


def test_repo_agent_skill_stubs_in_sync():
    names = sorted(p.name for p in (ROOT / ".claude/skills").iterdir() if (p / "SKILL.md").is_file())
    assert sorted(p.name for p in (ROOT / ".agents/skills").iterdir()) == names
    for name in names:
        assert (ROOT / ".agents/skills" / name / "SKILL.md").read_text(encoding="utf-8") == rp.skill_stub(name, ROOT), \
            "运行 python -m finagent.report_pipeline sync-skills"


def test_agent_commands_and_usage(tmp_path):
    claude = rp.agent_command("claude", "opus")
    assert claude[:2] == ["claude", "-p"] and "stream-json" in claude and claude[-2:] == ["--model", "opus"]
    codex = rp.agent_command("codex")
    assert codex[:2] == ["codex", "exec"] and "--skip-git-repo-check" in codex and codex[-1] == rp.TASK_PROMPT
    assert "tools.web_search=true" in codex and "WebSearch" in claude
    assert rp.agent_command("claude", None, rp.REVIEW_PROMPT)[2] == rp.REVIEW_PROMPT
    log = tmp_path / "c.jsonl"
    log.write_text("\n".join(json.dumps(e) for e in [
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "开始"}]}},
        {"type": "result", "num_turns": 12, "total_cost_usd": 3.5,
         "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 7}}]), encoding="utf-8")
    assert rp._usage(log, "claude") == {"turns": 12, "cost_usd": 3.5, "input_tokens": 100, "output_tokens": 7}
    log.write_text("\n".join(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 2}})
                             for _ in range(2)) + "\nnot json", encoding="utf-8")
    assert rp._usage(log, "codex") == {"input_tokens": 10, "output_tokens": 4}


def test_build_guards(tmp_path):
    with pytest.raises(SystemExit, match="allow-unverified"):
        rp.build("恒瑞医药", 2025, tmp_path)
    with pytest.raises(SystemExit, match="price-source"):
        rp.build("贵州茅台", 2025, tmp_path, price=1.0)
    with pytest.raises(SystemExit, match="不能放在"):
        rp.build("贵州茅台", 2025, ROOT / "runs")
    rp.build("贵州茅台", 2025, tmp_path)
    with pytest.raises(SystemExit, match="已存在"):
        rp.build("贵州茅台", 2025, tmp_path)
    tagged = rp.build("贵州茅台", 2025, tmp_path, tag="codex")
    assert tagged.name == "贵州茅台_2025_codex" and (tagged / "data/extractions/贵州茅台_2025").is_dir()


def _collect_sources(n_queries: int = 3, published: str = "2026-09-15") -> dict:
    """资料搜集：七个类别各一题，近 90 天内发布的来源三个。"""
    qs = [{"id": f"Q{i}", "phase": "collect", "category": cat, "question": cat, "status": "found",
           "queries": [f"{cat}-{k}" for k in range(n_queries)], "sources": ["S1"]}
          for i, cat in enumerate(sources_mod.CATEGORIES, 1)]
    src = [{"id": f"S{i}", "title": "t", "publisher": "p", "url": "https://example.com", "published": published,
            "accessed": "2026-10-03", "facts": [{"quote": "原文", "label": "x"}]} for i in (1, 2, 3)]
    return {"questions": qs, "sources": src}


def test_status_gates_and_collect(ws, tmp_path):
    res = rp.status(ws)
    assert not res["done"] and res["next"].startswith("1 资料搜集")
    work = ws / "data/extractions/贵州茅台_2025"
    meta = json.loads((ws / "sample.json").read_text(encoding="utf-8"))
    meta["as_of"] = "2026-10-03"
    (ws / "sample.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    (work / "research").mkdir()
    # 先搜集：缺类别、检索不足、来源过旧都不算通过
    thin = _collect_sources(n_queries=1, published="2025-01-01")
    thin["questions"] = thin["questions"][:3]
    (work / "research/sources.json").write_text(json.dumps(thin, ensure_ascii=False), encoding="utf-8")
    (work / "research/dossier.md").write_text("# 资料包", encoding="utf-8")
    first = rp.status(ws)["stages"][0]
    assert not first["ok"] and "未覆盖" in first["detail"] and "近 90 天来源 0 个" in first["detail"]
    (work / "research/sources.json").write_text(json.dumps(_collect_sources(), ensure_ascii=False), encoding="utf-8")
    assert rp.status(ws)["stages"][0]["ok"]
    (work / "facts.json").write_text("{}", encoding="utf-8")
    (work / "facts.verified.json").write_text(json.dumps({"check": {"ok": True}}), encoding="utf-8")
    (work / "report/framework.md").write_text("# 框架", encoding="utf-8")
    stages = {s["stage"]: s for s in rp.status(ws)["stages"]}
    assert stages["2 财务抽取"]["ok"] and not stages["3 分析框架"]["ok"]  # 缺外部调研清单
    (work / "report/framework.md").write_text("# 框架\n\n## 外部调研清单\n", encoding="utf-8")
    stages = {s["stage"]: s for s in rp.status(ws)["stages"]}
    assert stages["3 分析框架"]["ok"] and not stages["4 补充调研"]["ok"]
    # 补充调研：框架之后追加 phase=followup 的问题
    data = _collect_sources()
    data["questions"] += [{"id": f"F{i}", "phase": "followup", "question": "q", "status": "not_found",
                           "queries": ["a", "b"]} for i in range(rp.MIN_FOLLOWUP)]
    (work / "research/sources.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    stages = {s["stage"]: s for s in rp.status(ws)["stages"]}
    assert stages["4 补充调研"]["ok"] and not stages["5 经营数据"]["ok"]
    # 估值假设必须引用资料包
    (work / "valuation_assumptions.json").write_text(json.dumps({"current_price": 1500, "price_source": "x"}),
                                                   encoding="utf-8")
    stages = {s["stage"]: s for s in rp.status(ws)["stages"]}
    assert "[S编号]" in stages["6 估值假设"]["detail"]
    # 修改 facts 后校验结果过期
    os.utime(work / "facts.json", (2e9, 2e9))
    assert not rp.status(ws)["stages"][1]["ok"]
    # 前序阶段未通过时，后续阶段即使有文件也不算通过
    (work / "report/delivery.md").write_text("说明", encoding="utf-8")
    assert not rp.status(ws)["stages"][-1]["ok"]

    root = tmp_path / "repo"
    with pytest.raises(SystemExit, match="闸门"):
        rp.collect(ws, root=root)
    out = rp.collect(ws, root=root, force=True)
    assert (root / out["extractions"] / "report/framework.md").is_file()
    with pytest.raises(SystemExit, match="overwrite"):
        rp.collect(ws, root=root, force=True)
    assert "extractions" not in rp.collect(ws, root=root, force=True, delivery_only=True)

    row = rp.scorecard(ws)
    assert row["web_queries"] == 7 * 3 + 2 * rp.MIN_FOLLOWUP and row["web_sources"] == 3
    assert row["stages_passed"] == 1 and not row["done"] and row["valuation_runs"] == 0
    table = rp.scorecard_markdown([row])
    assert "闸门/11" in table and "未完成" in table and "不代表研报质量" in table


def test_review_stage_numlock(ws):
    """复核改写阶段：初稿、编辑日志、复核清单都要有，改写稿不得新增数字。"""
    rep_dir = ws / "data/extractions/贵州茅台_2025/report"
    stage = lambda: next(st for st in rp.status(ws)["stages"] if st["stage"] == "9 复核改写")  # noqa: E731
    assert "缺" in stage()["detail"]
    (rep_dir / "narrative.draft.md").write_text("营业收入 58.62 亿元。不过，年报未披露。", encoding="utf-8")
    (rep_dir / "narrative.md").write_text("营业收入 58.62 亿元，同比增长 9.99%。", encoding="utf-8")
    (rep_dir / "edit_log.md").write_text("删去自证", encoding="utf-8")
    (rep_dir / "review.md").write_text("无", encoding="utf-8")
    assert "数字锁未通过" in stage()["detail"] and "9.99%" in stage()["detail"]
    (rep_dir / "narrative.md").write_text("营业收入 58.62 亿元。", encoding="utf-8")
    assert "数字锁通过" in stage()["detail"]


def test_run_agent_chains_write_then_review(ws, monkeypatch):
    """先起研究助理会话做资料搜集，未通过不进写作；写作未完成不进复核；三个会话互不继承上下文。"""
    calls = []
    monkeypatch.setattr(rp, "_session", lambda ws_, agent, model, role, prompt: calls.append((role, model)) or 0)
    assert rp.run_agent(ws, "claude") == 1 and calls == [("research", rp.GEN_MODEL)]
    monkeypatch.setattr(rp, "_research_done", lambda ws_: True)
    calls.clear()
    assert rp.run_agent(ws, "claude") == 1 and calls == [("write", rp.GEN_MODEL)]
    monkeypatch.setattr(rp, "_writing_done", lambda ws_: True)
    calls.clear()
    rp.run_agent(ws, "claude")
    assert calls == [("review", rp.QC_MODEL)]


def test_extras_cache_without_verifier_fingerprint_is_rechecked(ws, monkeypatch):
    from finagent.parsing import document
    from finagent.tasks.financials import extras as extra_module

    work = ws / "data/extractions/贵州茅台_2025"
    extras = work / "extras.json"
    extras.write_text('{"tables":[]}', encoding="utf-8")
    cache = ws / ".pipeline/extras_check.json"
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps({"sha256": rp._sha256(extras), "ok": False, "rejected": 8,
                                 "tables": 1, "cells": 0}), encoding="utf-8")
    monkeypatch.setattr(document, "load_document", lambda *args: object())
    monkeypatch.setattr(extra_module, "verify_extras", lambda *args: {"tables": [], "rejected": []})
    checked = rp._extras_check(ws, json.loads((ws / "sample.json").read_text(encoding="utf-8")), extras)
    assert checked["ok"] and checked["rejected"] == 0 and checked["verifier_sha256"]


def test_copy_template_only_into_data(ws):
    out = rp.copy_template(ws, "narrative.md", "data/extractions/贵州茅台_2025/report/narrative.md")
    assert out.is_file() and "section" in out.read_text(encoding="utf-8")
    with pytest.raises(SystemExit, match="已存在"):
        rp.copy_template(ws, "narrative.md", "data/extractions/贵州茅台_2025/report/narrative.md")
    with pytest.raises(SystemExit, match="data/"):
        rp.copy_template(ws, "narrative.md", "finagent/x.md")
    with pytest.raises(SystemExit, match="没有模板"):
        rp.copy_template(ws, "../SKILL.md", "data/x.md")
