"""DeepSeek 执行器的路径边界、工具白名单与流水线接入。"""

import json
import subprocess
import sys
import pytest

from finagent import deepseek_agent as ds
from finagent import report_pipeline as rp


@pytest.fixture()
def workspace(tmp_path):
    return rp.build("贵州茅台", 2025, tmp_path / "samples", price=1500.0, price_source="测试行情")


def test_deepseek_command_and_windows_wrapper(workspace):
    command = rp.agent_command("deepseek")
    assert command[1:3] == ["-m", "finagent.deepseek_agent"]
    assert rp.agent_command("deepseek", "deepseek-flash")[-2:] == ["--model", "deepseek-flash"]
    assert (workspace / "finagent/deepseek_agent.py").is_file()
    assert (workspace / "py.cmd").read_text(encoding="utf-8").startswith("@echo off")
    assert "MPLCONFIGDIR" in (workspace / "py.cmd").read_text(encoding="utf-8")


def test_tools_restrict_reads_and_writes(workspace):
    meta = json.loads((workspace / "sample.json").read_text(encoding="utf-8"))
    tools = ds.WorkspaceTools(workspace, meta)
    assert "贵州茅台" in tools.read_file("AGENTS.md")
    assert "finagent-research" in tools.read_file(".claude/skills/finagent-research/SKILL.md")
    assert "extractions/" in tools.list_files("data")
    assert "locate.json" in tools.list_files("report/resources/贵州茅台")
    for path in ("../CLAUDE.md", "finagent/core/config.py", "sample.json", ".pipeline/api_cache/test.json"):
        with pytest.raises(ValueError):
            tools.read_file(path)
    for path in ("../escape.md", "AGENTS.md", "finagent/evil.py", "data/extractions/别家_2025/facts.json"):
        with pytest.raises(ValueError):
            tools.write_file(path, "{}")
    with pytest.raises(json.JSONDecodeError):
        tools.write_file("data/extractions/贵州茅台_2025/facts.json", "not json")
    assert not (workspace / "data/extractions/贵州茅台_2025/facts.json").exists()
    result = tools.write_file("data/extractions/贵州茅台_2025/facts.json", "{}")
    assert "SHA-256" in result
    with pytest.raises(ValueError, match="只能写"):
        tools.write_file("data/extractions/贵州茅台_2025/report/build_report.py", "raise SystemExit()")
    with pytest.raises(ValueError, match="未知模板"):
        tools.copy_template("build_report")
    with pytest.raises(ValueError, match="程序生成"):
        tools.write_file("data/extractions/贵州茅台_2025/report/review.json", "{}")
    tools.write_file("data/extractions/贵州茅台_2025/report/narrative.md", "原句，保留。")
    with pytest.raises(ValueError, match="恰好出现一次"):
        tools.replace_text("不存在", "新句")
    assert "SHA-256" in tools.replace_text("原句", "新句")
    assert tools.read_file("data/extractions/贵州茅台_2025/report/narrative.md") == "新句，保留。"


def test_market_fields_are_copied_from_trusted_input(workspace):
    meta = json.loads((workspace / "sample.json").read_text(encoding="utf-8"))
    tools = ds.WorkspaceTools(workspace, meta)
    path = "data/extractions/贵州茅台_2025/valuation_assumptions.json"
    tools.write_file(path, json.dumps({"current_price": 1, "price_source": "模型猜测", "valuation_date": "1900-01-01"}))
    saved = json.loads((workspace / path).read_text(encoding="utf-8"))
    market = json.loads((workspace / "inputs/market.json").read_text(encoding="utf-8"))
    assert saved["current_price"] == market["current_price"]
    assert saved["price_source"] == market["price_source"]
    assert saved["valuation_date"] == market.get("price_date")
    saved["price_source"] = "改写后的非原始来源"
    (workspace / path).write_text(json.dumps(saved), encoding="utf-8")
    assert tools.sync_market_fields()
    assert json.loads((workspace / path).read_text(encoding="utf-8"))["price_source"] == market["price_source"]
    assert not tools.sync_market_fields()


def test_tool_actions_cannot_run_arbitrary_command(workspace):
    meta = json.loads((workspace / "sample.json").read_text(encoding="utf-8"))
    tools = ds.WorkspaceTools(workspace, meta)
    with pytest.raises(ValueError, match="白名单"):
        tools.run_finagent("all; echo secret")
    with pytest.raises(ValueError, match="未知工具"):
        tools.dispatch("run_shell", {"cmd": "echo secret"})
    with pytest.raises(RuntimeError, match="命令退出码 7"):
        tools._run([sys.executable, "-c", "raise SystemExit(7)"])
    assert "1 财务抽取" in tools.run_finagent("status")
    tools.copy_template("narrative")
    with pytest.raises(ValueError, match="已有工作"):
        tools.copy_template("narrative")


def test_pdf_hash_checked_before_model_can_read(workspace):
    meta = json.loads((workspace / "sample.json").read_text(encoding="utf-8"))
    meta["pdf_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="SHA-256"):
        ds.WorkspaceTools(workspace, meta)


def test_render_rejects_missing_chinese_glyphs_even_on_zero_exit(workspace, monkeypatch):
    meta = json.loads((workspace / "sample.json").read_text(encoding="utf-8"))
    tools = ds.WorkspaceTools(workspace, meta)
    monkeypatch.setattr(ds.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(
        args[0], 0, stdout="", stderr="Glyph 24615 missing from font(s) Arial"))
    with pytest.raises(RuntimeError, match="中文字体缺失"):
        tools._run([sys.executable, "-c", "pass"], clean_env=True)


def test_thinking_tool_response_is_preserved(workspace, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-not-a-real-key")
    states = {"calls": 0}
    real_status = rp.status

    def fake_status(ws):
        state = real_status(ws)
        if states["calls"] >= 2:
            for stage in state["stages"]:
                stage["ok"] = True
            state["done"] = True
        return state

    seen_messages = []

    class FakeClient:
        def __init__(self, _settings):
            self.last_call = {"usage": {"prompt_tokens": 2, "completion_tokens": 1}, "request_sha256": "test"}

        def chat(self, messages, **_kwargs):
            seen_messages.append(messages.copy())
            states["calls"] += 1
            if states["calls"] == 1:
                return {"role": "assistant", "content": None, "reasoning_content": "已检查闸门",
                        "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "read_file",
                                         "arguments": json.dumps({"path": "AGENTS.md"})}}]}
            return {"role": "assistant", "content": "完成", "reasoning_content": "继续", "tool_calls": []}

    monkeypatch.setattr(ds, "LLMClient", FakeClient)
    monkeypatch.setattr(ds, "status", fake_status)
    assert ds.run(workspace) == 0
    assert seen_messages[1][-2]["reasoning_content"] == "已检查闸门"
    assert seen_messages[1][-1]["role"] == "tool"


def test_usage_parser_deepseek(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text("\n".join(json.dumps({"type": "deepseek.usage", "usage": {"prompt_tokens": 4,
                        "completion_tokens": 3}}) for _ in range(2)), encoding="utf-8")
    assert rp._usage(path, "deepseek") == {"input_tokens": 8, "output_tokens": 6}


def test_context_compaction_preserves_last_reasoning_tool_pair(monkeypatch):
    monkeypatch.setattr(ds, "MAX_CONTEXT_CHARS", 100)
    messages = [
        {"role": "system", "content": "rules"}, {"role": "user", "content": "stage"},
        {"role": "assistant", "content": "old" * 100},
        {"role": "assistant", "content": None, "reasoning_content": "latest reasoning",
         "tool_calls": [{"id": "call-1"}]},
        {"role": "tool", "tool_call_id": "call-1", "content": "latest result"},
    ]
    compact = ds._compact_messages(messages, "6 文稿", "rerun guard")
    assert len(compact) == 5
    assert compact[-2]["reasoning_content"] == "latest reasoning"
    assert compact[-1]["tool_call_id"] == "call-1"
    assert "old" not in str(compact)
