"""计算引擎的步骤编排：固定步骤的任务流（财报分析 / 估值 / 研报核查），每步可追踪、可单独重跑。

多 Agent 的会话编排在 finagent/report_pipeline.py；本模块只管引擎内部的确定性步骤，不调用模型。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import tracing


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
