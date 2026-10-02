"""研报流水线：隔离工作区的内容边界、阶段闸门与收回。"""

import json
import os
import zipfile

import pytest

from conftest import ROOT
from finagent import report_pipeline as rp


@pytest.fixture()
def ws(tmp_path):
    return rp.build("贵州茅台", 2025, tmp_path / "samples", price=1500.0, price_source="测试行情")


def test_workspace_contains_only_skills_engine_and_one_company(ws):
    assert (ws / ".claude/skills/finagent-research/SKILL.md").is_file()
    assert (ws / ".claude/skills/finagent-report/reportkit/core.py").is_file()
    assert (ws / "finagent/__main__.py").is_file()
    assert not (ws / "finagent/deepseek_harness.py").exists()
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
    assert rp.agent_command("deepseek", python="/test/env/python")[:3] == [
        "/test/env/python", "-m", "finagent.deepseek_agent"]
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


def test_status_gates_and_collect(ws, tmp_path):
    res = rp.status(ws)
    assert not res["done"] and res["next"].startswith("1 财务抽取")
    work = ws / "data/extractions/贵州茅台_2025"
    core = ("revenue", "np_parent", "ocf", "total_assets", "eps_basic")
    sample_facts = {"facts": [{"metric_id": metric, "period": str(year)}
                              for year in (2023, 2024, 2025) for metric in core]}
    (work / "facts.json").write_text(json.dumps(sample_facts), encoding="utf-8")
    (work / "facts.verified.json").write_text(json.dumps({"check": {"ok": True}}), encoding="utf-8")
    (work / "report/framework.md").write_text("# 框架", encoding="utf-8")
    stages = {s["stage"]: s for s in rp.status(ws)["stages"]}
    assert stages["1 财务抽取"]["ok"] and stages["2 分析框架"]["ok"]
    assert not stages["3 经营数据"]["ok"]
    # 修改 facts 后校验结果过期
    os.utime(work / "facts.json", (2e9, 2e9))
    assert not rp.status(ws)["stages"][0]["ok"]
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
    assert row["stages_passed"] == 0 and not row["done"] and row["valuation_runs"] == 0
    table = rp.scorecard_markdown([row])
    assert "闸门/8" in table and "独立审读" in table and "阻断项" in table
    assert "未完成" in table and "不代表研报质量" in table


def test_status_rejects_missing_history_and_duplicate_facts(ws):
    work = ws / "data/extractions/贵州茅台_2025"
    facts = {"facts": [{"metric_id": "revenue", "period": "2025"},
                        {"metric_id": "revenue", "period": "2025"}]}
    (work / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (work / "facts.verified.json").write_text(json.dumps({"check": {"ok": True}}), encoding="utf-8")
    first = rp.status(ws)["stages"][0]
    assert not first["ok"]
    assert "三年核心缺项 14" in first["detail"]
    assert "重复条目 1" in first["detail"]


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


def test_narrative_quality_rejects_process_language_and_placeholders(tmp_path):
    draft = tmp_path / "narrative.md"
    draft.write_text("程序归因显示增长。模型状态为 screen-grade。\n"
                     "这不是销量增长，而是估值的下限。TODO\n", encoding="utf-8")
    result = rp._narrative_quality(draft)
    assert not result["ok"]
    assert {issue.split(" L")[0] for issue in result["issues"]} >= {
        "内部流程话术", "冗余否定句式", "未完成占位符", "无依据的保底表述"}
    sections = ("title", "subtitle", "summary", "thesis", "overview", "performance", "business",
                "profitability", "balance", "cashflow", "forecast", "valuation", "recommendation", "risks")
    draft.write_text("\n".join(f"<!-- section: {name} -->\n" +
                               ("当前股价 10 元，DCF 12 元；收入 3 亿元，利润 2 亿元，现金流 4 亿元，"
                                "每股收益 1 元。风险提示：竞争加剧。" if name == "summary" else "分析。")
                               for name in sections), encoding="utf-8")
    assert rp._narrative_quality(draft)["ok"]
    draft.write_text(draft.read_text(encoding="utf-8").replace("当前股价", "参考股价"), encoding="utf-8")
    assert rp._narrative_quality(draft)["ok"]


def test_status_rejects_assumed_price_that_differs_from_market_input(ws):
    work = ws / "data/extractions/贵州茅台_2025"
    assumptions = work / "valuation_assumptions.json"
    assumptions.write_text(json.dumps({"current_price": 1501, "price_source": "测试行情",
                                       "valuation_date": None}), encoding="utf-8")
    stage = rp.status(ws)["stages"][3]
    assert not stage["ok"] and "current_price" in stage["detail"]
    assumptions.write_text(json.dumps({"current_price": 1500, "price_source": "测试行情"}), encoding="utf-8")
    assert "已核对行情来源" in rp.status(ws)["stages"][3]["detail"]


def test_deepseek_assumption_gate_requires_material_basis(ws):
    sample = ws / "sample.json"
    meta = json.loads(sample.read_text(encoding="utf-8"))
    meta["require_review"] = True
    sample.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    market = ws / "inputs/market.json"
    market_data = json.loads(market.read_text(encoding="utf-8"))
    market_data["price_date"] = "2026-09-30"
    market.write_text(json.dumps(market_data, ensure_ascii=False), encoding="utf-8")
    path = ws / "data/extractions/贵州茅台_2025/valuation_assumptions.json"
    path.write_text(json.dumps({"current_price": 1500, "price_source": "测试行情",
                                "valuation_date": "2026-09-30", "status": "分析师假设",
                                "rationale": {"forecast": "短"}}, ensure_ascii=False),
                    encoding="utf-8")
    gate = rp.status(ws)["stages"][3]
    assert not gate["ok"] and "non_operating" in gate["detail"] and "wacc" in gate["detail"]


def test_artifact_gates_reject_corrupt_excel_and_pdf(tmp_path):
    xlsx = tmp_path / "model.xlsx"
    xlsx.write_bytes(b"not an xlsx" * 200)
    assert not rp._xlsx_valid(xlsx)
    with zipfile.ZipFile(xlsx, "w") as out:
        out.writestr("xl/workbook.xml", "<workbook/>")
        out.writestr("padding", "x" * 1500)
    assert not rp._xlsx_valid(xlsx)
    with zipfile.ZipFile(xlsx, "w") as out:
        out.writestr("xl/workbook.xml", '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets>'
                     + ''.join(f'<sheet name="{name}"/>' for name in ("估值汇总", "DCF", "历史财务", "模型检查"))
                     + '</sheets></workbook>')
        for i in range(1, 5):
            out.writestr(f"xl/worksheets/sheet{i}.xml",
                         '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                         '<sheetData><row><c r="A1"><f>1+1</f><v>2</v></c></row></sheetData></worksheet>')
        out.writestr("padding", "x" * 1500)
    assert rp._xlsx_valid(xlsx)
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4\n" + b"x" * 1500)
    assert not rp._pdf_valid(pdf)[0]
