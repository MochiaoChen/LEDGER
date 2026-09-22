"""编排层。

两种模式：
1. Pipeline：固定步骤的任务流（财报分析 / 估值 / 研报核查），每步可追踪、可单独重跑，
   保证结果稳定——这是评测主路径。
2. Agent：LLM 通过 function calling 自主选择 Tool 完成开放式指令（如“分析这份年报并估值”），
   Tool 内部仍调用确定性的 Pipeline 步骤，LLM 只做规划与总结，不做数值计算。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import tracing
from .llm import LLMClient
from .tools import ToolRegistry


@dataclass
class Step:
    name: str
    fn: Callable[[dict[str, Any]], Any]
    output_key: str


@dataclass
class Pipeline:
    name: str
    steps: list[Step] = field(default_factory=list)

    def step(self, name: str, output_key: str | None = None) -> Callable:
        def deco(fn: Callable[[dict[str, Any]], Any]) -> Callable:
            self.steps.append(Step(name, fn, output_key or name))
            return fn

        return deco

    def run(self, ctx: dict[str, Any]) -> dict[str, Any]:
        for i, st in enumerate(self.steps, 1):
            t0 = time.time()
            tracing.log("step_start", pipeline=self.name, step=st.name, index=i, total=len(self.steps))
            try:
                ctx[st.output_key] = st.fn(ctx)
            except Exception as exc:
                tracing.log("step_error", pipeline=self.name, step=st.name, error=f"{type(exc).__name__}: {exc}")
                raise
            tracing.log("step_end", pipeline=self.name, step=st.name,
                        elapsed_ms=round((time.time() - t0) * 1000, 1))
        return ctx


AGENT_SYSTEM = """你是一名严谨的金融投研智能体。你只能通过提供的工具获取数据和计算结果，
禁止自行编造或心算任何财务数字。完成任务的一般顺序：解析文档 → 抽取财务数据 → 分析 →（估值/核查）。
最终回答需区分【事实】（来自工具返回的原始数据，并注明来源）、【推论】（基于事实的计算或判断）、
【观点】（主观判断，须说明假设与风险）。"""


class Agent:
    def __init__(self, registry: ToolRegistry, llm: LLMClient | None = None, max_steps: int = 8):
        self.registry = registry
        self.llm = llm or LLMClient()
        self.max_steps = max_steps

    def run(self, instruction: str) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": AGENT_SYSTEM},
            {"role": "user", "content": instruction},
        ]
        tracing.log("agent_start", instruction=instruction, tools=list(self.registry.tools))
        for turn in range(1, self.max_steps + 1):
            msg = self.llm.chat(messages, tools=self.registry.schemas(), purpose=f"agent_turn_{turn}")
            messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")})
            calls = msg.get("tool_calls") or []
            if not calls:
                tracing.log("agent_end", turns=turn, answer=msg.get("content"))
                return {"answer": msg.get("content"), "turns": turn, "messages": messages}
            for call in calls:
                fn = call["function"]
                try:
                    result = self.registry.call(fn["name"], fn.get("arguments") or "{}")
                    content = json.dumps(result, ensure_ascii=False, default=str)[:12000]
                except Exception as exc:
                    content = json.dumps({"error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
        tracing.log("agent_end", turns=self.max_steps, answer=None, reason="max_steps")
        return {"answer": None, "turns": self.max_steps, "messages": messages}
