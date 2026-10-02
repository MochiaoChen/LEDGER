"""DeepSeek 报告测试：双公司输入、模型参数、引用检查。"""

import json
from http.client import RemoteDisconnected

from finagent.core.config import get_settings
from finagent.core.llm import LLMClient
from finagent.deepseek_harness import _quality_check, prepare_company, run_company


def test_prepare_two_real_annual_reports(tmp_path):
    catl = prepare_company("宁德时代", tmp_path)
    cm = prepare_company("招商轮船", tmp_path)
    assert catl["ticker"] == "300750" and cm["ticker"] == "601872"
    assert catl["source_sha256"] != cm["source_sha256"]
    for item in (catl, cm):
        source = (tmp_path / f"{item['ticker']}_{item['company']}" / "source_pack.md").read_text(encoding="utf-8")
        assert "年报 PDF 第" in source
        assert item["source_sha256"] in source
        assert len(item["selected_pages"]) >= 40


def test_flash_request_uses_official_model_and_thinking(tmp_path, monkeypatch):
    settings = get_settings(
        llm_model="deepseek-flash", llm_api_key="fake-test-key", llm_mode="live",
        cache_dir=str(tmp_path / "cache"),
    )
    client = LLMClient(settings)
    seen = {}

    def fake_post(body):
        seen.update(body)
        return {"model": "deepseek-flash", "choices": [{"message": {"content": "ok"}}], "usage": {"total_tokens": 2}}

    monkeypatch.setattr(client, "_post", fake_post)
    assert client.chat([{"role": "user", "content": "hi"}], reasoning_effort="high")["content"] == "ok"
    assert seen["model"] == "deepseek-flash"
    assert seen["thinking"] == {"type": "enabled"}
    assert seen["reasoning_effort"] == "high"
    assert "temperature" not in seen and "seed" not in seen
    assert client.last_call["usage"]["total_tokens"] == 2


def test_deepseek_retries_dropped_connection(tmp_path, monkeypatch):
    settings = get_settings(llm_model="deepseek-flash", llm_api_key="fake-test-key", llm_mode="live",
                            cache_dir=str(tmp_path / "cache"))
    client = LLMClient(settings)
    calls = []

    def fake_urlopen(_request, timeout):
        calls.append(timeout)
        if len(calls) < 3:
            raise RemoteDisconnected("Remote end closed connection without response")

        class Reply:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self):
                return b'{"choices":[{"message":{"content":"ok"}}]}'

        return Reply()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda *_: None)
    assert client._post({"model": "deepseek-flash", "messages": []})["choices"][0]["message"]["content"] == "ok"
    assert len(calls) == 3


def test_draft_is_flagged_when_numeric_claim_has_no_source():
    qa = _quality_check("2025 年收入增长。\n\n现金流变化见原文。【年报第20页】", {20})
    assert qa["status"] == "needs_review"
    assert qa["numeric_paragraphs_without_citation"]
    assert _quality_check("收入变动见原文。【年报第999页】", {20})["invalid_citation_pages"] == [999]
    assert _quality_check("净利润同比增？【年报第20页】", {20})["status"] == "needs_review"


def test_run_company_records_framework_report_and_qa(tmp_path):
    prepared = prepare_company("宁德时代", tmp_path)

    class FakeClient:
        last_call = {"model": "deepseek-flash", "usage": {"total_tokens": 5}}

        def chat(self, messages, **kwargs):
            if kwargs.get("json_mode"):
                return {"content": json.dumps({"investment_thesis": ["收入驱动见第20页"]}, ensure_ascii=False)}
            return {"content": "# 宁德时代分析\n\n2025 年收入结构见年报。【年报第20页】"}

    result = run_company(prepared, FakeClient())
    folder = tmp_path / "300750_宁德时代"
    assert result["status"] == "draft_ready_for_review"
    assert (folder / "framework.json").is_file()
    assert (folder / "report_draft.md").is_file()
    assert json.loads((folder / "manifest.json").read_text(encoding="utf-8"))["report_call"]["usage"]["total_tokens"] == 5
