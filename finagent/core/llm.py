"""LLM 客户端：OpenAI 兼容 Chat Completions 接口，仅用标准库。

- temperature=0 + 固定 seed，降低输出波动；
- 请求哈希作为缓存键，响应落盘到 .cache/llm/，replay 模式下完全离线复现；
- 每次调用写入追踪日志（模型、请求哈希、是否命中缓存、token 用量、耗时）。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import tracing
from .config import Settings, get_settings


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, settings: Settings | None = None):
        self.s = settings or get_settings()
        self.cache_dir = Path(self.s.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.last_call: dict[str, Any] = {}

    @property
    def enabled(self) -> bool:
        return self.s.llm_enabled

    # ---------------------------------------------------------------- core
    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        json_mode: bool = False,
        purpose: str = "",
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        """返回 OpenAI 格式的 message 对象（含 content / tool_calls）。"""
        body: dict[str, Any] = {"model": self.s.llm_model, "messages": messages}
        if self.s.llm_model == "deepseek-flash":
            # V4.1 Flash defaults to thinking. Its API ignores temperature in
            # thinking mode; an explicit effort makes benchmark runs comparable.
            body["thinking"] = {"type": "enabled"}
            body["reasoning_effort"] = reasoning_effort or "high"
        else:
            body["temperature"] = self.s.llm_temperature
            body["seed"] = self.s.llm_seed
            if reasoning_effort:
                body["reasoning_effort"] = reasoning_effort
        if tools:
            body["tools"] = tools
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        key = hashlib.sha256(
            json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        cache_path = self.cache_dir / f"{key}.json"
        t0 = time.time()

        if cache_path.exists():
            resp = json.loads(cache_path.read_text(encoding="utf-8"))
            cache_hit = True
        elif self.s.llm_mode == "replay":
            raise LLMError(f"replay 模式下缓存缺失：{key}（purpose={purpose}）")
        elif not self.s.llm_api_key:
            raise LLMError("未配置 LLM_API_KEY；可设置 LLM_MODE=off 仅运行规则通道")
        else:
            resp = self._post(body)
            cache_path.write_text(json.dumps(resp, ensure_ascii=False, indent=1), encoding="utf-8")
            cache_hit = False

        message = resp["choices"][0]["message"]
        self.last_call = {
            "model": resp.get("model", self.s.llm_model),
            "request_sha256": key,
            "cache_hit": cache_hit,
            "usage": resp.get("usage"),
            "elapsed_ms": round((time.time() - t0) * 1000, 1),
        }
        tracing.log(
            "llm_call",
            purpose=purpose,
            model=self.s.llm_model,
            request_sha256=key,
            cache_hit=cache_hit,
            usage=resp.get("usage"),
            elapsed_ms=round((time.time() - t0) * 1000, 1),
            prompt_preview=messages[-1].get("content", "")[:500] if messages else "",
            response_preview=(message.get("content") or "")[:500],
            tool_calls=[tc["function"]["name"] for tc in message.get("tool_calls") or []],
        )
        return message

    def chat_json(self, system: str, user: str, *, purpose: str = "") -> Any:
        """要求模型输出 JSON，并做容错解析。"""
        message = self.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            json_mode=True,
            purpose=purpose,
        )
        return parse_json(message.get("content") or "")

    # ---------------------------------------------------------------- http
    def _post(self, body: dict[str, Any], retries: int = 3) -> dict[str, Any]:
        url = self.s.llm_base_url.rstrip("/") + "/chat/completions"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        last: Exception | None = None
        for attempt in range(retries):
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.s.llm_api_key}",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=self.s.llm_timeout) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "ignore")[:500]
                last = LLMError(f"HTTP {exc.code}: {detail}")
                if exc.code < 500 and exc.code != 429:
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last = exc
            time.sleep(2 ** attempt)
        raise LLMError(f"LLM 请求失败：{last}")


def parse_json(text: str) -> Any:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
        if start >= 0:
            end = max(text.rfind("}"), text.rfind("]"))
            return json.loads(text[start : end + 1])
        raise LLMError(f"无法解析 JSON：{text[:200]}")
