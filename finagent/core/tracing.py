"""运行追踪：记录文件访问、工具调用、LLM 调用和产物，保证过程可追溯、可复现。

每次运行生成一个目录 runs/<run_id>/：
  events.jsonl   逐条事件（file_read / tool_call / llm_call / artifact / note）
  manifest.json  运行汇总（输入文件哈希、配置、产物哈希、耗时）
"""

from __future__ import annotations

import functools
import hashlib
import json
import platform
import sys
import time
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

_current: ContextVar["RunTracer | None"] = ContextVar("finagent_tracer", default=None)

MAX_LOG_CHARS = 2000


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def _summarize(value: Any) -> Any:
    """把大对象截断，避免日志膨胀；完整结果由产物文件保存。"""
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = json.dumps(repr(value), ensure_ascii=False)
    if len(text) <= MAX_LOG_CHARS:
        return json.loads(text)
    return {"_truncated": True, "sha256": sha256_bytes(text.encode()), "preview": text[:MAX_LOG_CHARS]}


class RunTracer:
    def __init__(self, task: str, runs_root: str | Path = "runs", config: dict[str, Any] | None = None):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.run_id = f"{stamp}-{task}"
        self.dir = Path(runs_root) / self.run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self.task = task
        self.config = config or {}
        self._events = (self.dir / "events.jsonl").open("a", encoding="utf-8")
        self._seq = 0
        self._t0 = time.time()
        self.inputs: dict[str, str] = {}
        self.artifacts: dict[str, str] = {}
        self._token = None

    # ---- context ----
    def __enter__(self) -> "RunTracer":
        self._token = _current.set(self)
        self.event("run_start", task=self.task, config=self.config)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is not None:
            self.event("run_error", error=f"{exc_type.__name__}: {exc}")
        self.finish(status="error" if exc else "ok")
        if self._token is not None:
            _current.reset(self._token)

    # ---- events ----
    def event(self, kind: str, **payload: Any) -> None:
        self._seq += 1
        record = {
            "seq": self._seq,
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "kind": kind,
            **{k: _summarize(v) for k, v in payload.items()},
        }
        self._events.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._events.flush()

    def read_file(self, path: str | Path) -> bytes:
        """统一的文件读取入口：所有输入文件都应经由这里读取，以便记录哈希。"""
        p = Path(path)
        data = p.read_bytes()
        digest = sha256_bytes(data)
        self.inputs[str(p)] = digest
        self.event("file_read", path=str(p), bytes=len(data), sha256=digest)
        return data

    def write_artifact(self, name: str, content: str | bytes) -> Path:
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode("utf-8") if isinstance(content, str) else content
        path.write_bytes(data)
        return self.register_artifact(path)

    def write_json(self, name: str, obj: Any) -> Path:
        return self.write_artifact(name, json.dumps(obj, ensure_ascii=False, indent=2, default=str))

    def register_artifact(self, path: str | Path) -> Path:
        p = Path(path)
        digest = sha256_file(p)
        rel = str(p.relative_to(self.dir)) if p.is_relative_to(self.dir) else str(p)
        self.artifacts[rel] = digest
        self.event("artifact", path=rel, sha256=digest, bytes=p.stat().st_size)
        return p

    def finish(self, status: str = "ok") -> None:
        manifest = {
            "run_id": self.run_id,
            "task": self.task,
            "status": status,
            "started_at": datetime.fromtimestamp(self._t0).isoformat(timespec="seconds"),
            "elapsed_sec": round(time.time() - self._t0, 3),
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "config": self.config,
            "inputs": self.inputs,
            "artifacts": self.artifacts,
            "event_count": self._seq,
        }
        self.event("run_end", status=status, elapsed_sec=manifest["elapsed_sec"])
        (self.dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._events.close()


def current() -> RunTracer | None:
    return _current.get()


def log(kind: str, **payload: Any) -> None:
    tracer = current()
    if tracer is not None:
        tracer.event(kind, **payload)


def read_file(path: str | Path) -> bytes:
    tracer = current()
    if tracer is not None:
        return tracer.read_file(path)
    return Path(path).read_bytes()


def traced(name: str | None = None) -> Callable:
    """装饰器：记录函数（Tool）的入参、出参摘要、耗时与异常。"""

    def deco(fn: Callable) -> Callable:
        tool_name = name or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            t0 = time.time()
            log("tool_start", tool=tool_name, args=[_summarize(a) for a in args], kwargs=kwargs)
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                log("tool_error", tool=tool_name, error=f"{type(exc).__name__}: {exc}",
                    elapsed_ms=round((time.time() - t0) * 1000, 1))
                raise
            log("tool_end", tool=tool_name, result=result,
                elapsed_ms=round((time.time() - t0) * 1000, 1))
            return result

        return wrapper

    return deco
