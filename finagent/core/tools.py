"""Tool 注册表：统一描述、调用与追踪，并可导出为 function-calling schema。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import tracing


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    fn: Callable[..., Any]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolRegistry:
    tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, name: str, description: str, parameters: dict[str, Any]) -> Callable:
        def deco(fn: Callable) -> Callable:
            self.tools[name] = Tool(name, description, parameters, fn)
            return fn

        return deco

    def schemas(self) -> list[dict[str, Any]]:
        return [t.schema() for t in self.tools.values()]

    def call(self, name: str, arguments: dict[str, Any] | str) -> Any:
        if name not in self.tools:
            raise KeyError(f"未知工具：{name}")
        args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments)
        t0 = time.time()
        tracing.log("tool_start", tool=name, kwargs=args)
        try:
            result = self.tools[name].fn(**args)
        except Exception as exc:
            tracing.log("tool_error", tool=name, error=f"{type(exc).__name__}: {exc}")
            raise
        tracing.log("tool_end", tool=name, result=result, elapsed_ms=round((time.time() - t0) * 1000, 1))
        return result


registry = ToolRegistry()
