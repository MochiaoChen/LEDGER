"""DeepSeek 研报执行器：在单公司工作区内用受限工具完成 report_pipeline 闸门。

模型只读本工作区的 skill、年报指定页和产物；所有计算交给 FinAgent。
此处是逻辑访问边界，不声称提供操作系统级沙箱。模型生成的报告脚本只在
显式的 render_report 工具中运行，且不会继承 API Key。
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .core import tracing
from .core.config import get_settings
from .core.llm import LLMClient, LLMError
from .report_pipeline import META, _sha256, status

MODEL = "deepseek-flash"  # DeepSeek 官方当前 Flash 别名对应 V4.1 Flash。
MAX_ROUNDS_PER_STAGE = 30
MAX_API_CALLS = 80
MAX_PROMPT_TOKENS = 1_000_000
MAX_COMPLETION_TOKENS = 150_000
MAX_FILE_CHARS = 40_000
MAX_TOOL_OUTPUT = 16_000


def emit(kind: str, **data: Any) -> None:
    """输出与 report_pipeline.run_agent 兼容的逐行事件。"""
    print(json.dumps({"type": f"deepseek.{kind}", **data}, ensure_ascii=False), flush=True)


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required,
                           "additionalProperties": False}}}


STR = {"type": "string"}
TOOLS = [
    _tool("read_file", "读取工作区内允许的文本文件。先按阶段读 skill，不读引擎源码。",
          {"path": STR}, ["path"]),
    _tool("list_files", "列出允许目录中的文件名，不递归。", {"path": STR}, ["path"]),
    _tool("read_pdf_pages", "读取本公司年报的 PDF 物理页码，一次最多 20 页；输出带页码。",
          {"pages": {"type": "array", "items": {"type": "integer"}, "maxItems": 20}}, ["pages"]),
    _tool("write_file", "只写本公司的 data/extractions/<公司_年度>/ 下的 JSON、Markdown 或报告编排 Python 文件。",
          {"path": STR, "content": STR}, ["path", "content"]),
    _tool("copy_template", "复制研报文稿或编排脚本模板到本公司目录；已有文件时拒绝覆盖。",
          {"name": {"type": "string", "enum": ["narrative", "build_report"]}}, ["name"]),
    _tool("run_finagent", "执行白名单中的校验、估值、护栏或状态检查；参数由 harness 固定生成。",
          {"action": {"type": "string", "enum": ["schema", "verify_facts", "verify_extra", "valuation", "guard", "status"]}},
          ["action"]),
    _tool("render_report", "运行本公司的报告编排脚本，生成 PDF 与逐页预览；脚本不继承 API Key。",
          {}, []),
]


class WorkspaceTools:
    """将模型工具调用限制在单公司工作区和固定操作。"""

    def __init__(self, ws: Path, meta: dict[str, Any]):
        self.ws = ws.resolve()
        self.meta = meta
        self.work = Path("data/extractions") / meta["key"]
        self.pdf = Path(meta["pdf"])
        if not (self.ws / self.pdf).is_file():
            raise ValueError("工作区年报缺失")
        self.pdf_bytes = tracing.read_file(self.ws / self.pdf)
        if hashlib.sha256(self.pdf_bytes).hexdigest() != meta["pdf_sha256"]:
            raise ValueError("工作区年报缺失或 SHA-256 与构建记录不符")

    def _path(self, rel: str, *, write: bool = False) -> Path:
        path = Path(rel)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise ValueError("仅允许工作区内的相对路径")
        dest = (self.ws / path).resolve()
        if not dest.is_relative_to(self.ws):
            raise ValueError("路径越过工作区边界")
        rel_path = dest.relative_to(self.ws)
        if write:
            if not rel_path.is_relative_to(self.work) or rel_path.suffix not in {".json", ".md", ".py"}:
                raise ValueError("只能写本公司的抽取与研报文件")
            if rel_path.suffix == ".py" and rel_path != self.work / "report" / "build_report.py":
                raise ValueError("Python 文件只允许报告编排脚本")
        else:
            allowed = (rel_path in {Path("AGENTS.md"), Path("TASK.md")}
                       or rel_path.is_relative_to(Path(".claude/skills/finagent-research"))
                       or rel_path.is_relative_to(Path(".claude/skills/finagent-report"))
                       or rel_path.is_relative_to(Path(".agents/skills"))
                       or rel_path.is_relative_to(Path("data/samples"))
                       or rel_path.is_relative_to(self.work)
                       or rel_path.is_relative_to(Path("inputs"))
                       or rel_path.is_relative_to(Path("runs"))
                       or rel_path == self.pdf.parent / "locate.json")
            if not allowed or any(p in rel_path.parts for p in (".cache", ".pipeline", "__pycache__")):
                raise ValueError("该文件不在允许的读取范围")
        return dest

    def read_file(self, path: str) -> str:
        file = self._path(path)
        if not file.is_file() or file.suffix not in {".md", ".json", ".csv", ".txt", ".py"}:
            raise ValueError("文件不存在或不是允许的文本格式")
        if file.stat().st_size > MAX_FILE_CHARS * 4:
            raise ValueError("文件过大；请读取更小的产物，不要一次送入完整运行 JSON")
        content = tracing.read_file(file).decode("utf-8")
        if len(content) > MAX_FILE_CHARS:
            raise ValueError("文本超过单次读取上限")
        return content

    def list_files(self, path: str) -> str:
        # 只开放工作区结构导航，不扩大 read_file 的内容读取白名单。
        navigation = {".", "data", "data/extractions", "report", "report/resources",
                      self.pdf.parent.as_posix(), ".claude/skills"}
        if path in navigation:
            folder = (self.ws / path).resolve()
        else:
            folder = self._path(path)
        if not folder.is_dir():
            raise ValueError("目录不存在")
        return json.dumps(sorted(p.name + ("/" if p.is_dir() else "") for p in folder.iterdir())[:200], ensure_ascii=False)

    def read_pdf_pages(self, pages: list[int]) -> str:
        if not isinstance(pages, list) or not pages or len(pages) > 20 or any(not isinstance(n, int) or n < 1 for n in pages):
            raise ValueError("每次提供 1–20 个正整数 PDF 物理页码")
        import pdfplumber

        out = []
        with pdfplumber.open(io.BytesIO(self.pdf_bytes)) as pdf:
            for n in pages:
                if n > len(pdf.pages):
                    raise ValueError(f"PDF 只有 {len(pdf.pages)} 页")
                text = (pdf.pages[n - 1].extract_text(layout=False) or "").strip()
                if not text:
                    raise ValueError(f"第 {n} 页没有文本层，不能凭图像猜数")
                out.append(f"\n### PDF 物理第 {n} 页\n{text[:12_000]}")
        result = "\n".join(out)
        if len(result) > 50_000:
            raise ValueError("本次读取超过 5 万字；请分批选页")
        return result

    def write_file(self, path: str, content: str) -> str:
        file = self._path(path, write=True)
        if not isinstance(content, str) or len(content) > 250_000:
            raise ValueError("写入内容必须是 25 万字以内的文本")
        if file.suffix == ".json":
            json.loads(content)  # 无效 JSON 不落盘。
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
        if tracer := tracing.current():
            tracer.register_artifact(file)
        return f"已写入 {file.relative_to(self.ws).as_posix()}；SHA-256 {_sha256(file)}"

    def copy_template(self, name: str) -> str:
        if name not in {"narrative", "build_report"}:
            raise ValueError("未知模板")
        src = self.ws / ".claude/skills/finagent-report/templates" / f"{name}.{'py' if name == 'build_report' else 'md'}"
        dst = self.ws / self.work / "report" / src.name
        if dst.exists():
            raise ValueError("目标文件已存在；不会覆盖已有工作")
        shutil.copy2(src, dst)
        return f"已复制到 {dst.relative_to(self.ws).as_posix()}"

    def _run(self, argv: list[str], *, timeout: int = 300, clean_env: bool = False) -> str:
        env = os.environ.copy()
        env["MPLCONFIGDIR"] = str(self.ws / ".pipeline/mpl")
        env["FINAGENT_EXTRACTOR"] = "deepseek-harness"
        if clean_env:
            # 生成的报告脚本不应接触模型密钥或用户环境中的其他凭据。
            keep = ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "FINAGENT_CHROME")
            env = {k: v for k, v in env.items() if k in keep}
            env["HOME"] = str(self.ws / ".pipeline/home")
            env["MPLCONFIGDIR"] = str(self.ws / ".pipeline/mpl")
        (self.ws / ".pipeline/mpl").mkdir(parents=True, exist_ok=True)
        (self.ws / ".pipeline/home").mkdir(parents=True, exist_ok=True)
        result = subprocess.run(argv, cwd=self.ws, env=env, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout)
        output = (result.stdout + "\n" + result.stderr).strip()
        if result.returncode:
            raise RuntimeError(f"命令退出码 {result.returncode}：{output[-MAX_TOOL_OUTPUT:]}")
        if clean_env and re.search(r"Glyph \d+.*missing from font", output):
            raise RuntimeError("图表中文字体缺失；PDF 即使生成也不可交付，请修复字体后重渲染")
        return json.dumps({"exit_code": result.returncode, "output": output[-MAX_TOOL_OUTPUT:]}, ensure_ascii=False)

    def run_finagent(self, action: str) -> str:
        base = [sys.executable, "-m", "finagent"]
        work = self.work.as_posix()
        pdf = self.pdf.as_posix()
        if action == "status":
            return json.dumps(status(self.ws), ensure_ascii=False)
        if action == "schema":
            return self._run(base + ["schema"])
        if action == "verify_facts":
            return self._run(base + ["verify-facts", "--input", pdf, "--year", str(self.meta["year"]),
                                     "--facts", f"{work}/facts.json"])
        if action == "verify_extra":
            return self._run(base + ["verify-extra", "--input", pdf, "--extras", f"{work}/extras.json"])
        if action == "valuation":
            if not (self.ws / "inputs/market.json").is_file():
                raise ValueError("缺少有来源的当前股价，不能进行估值")
            cmd = base + ["valuation", "--input", pdf, "--year", str(self.meta["year"]),
                          "--company", self.meta["company"], "--assumptions", f"{work}/valuation_assumptions.json",
                          "--facts", f"{work}/facts.json", "--extras", f"{work}/extras.json", "--llm", "off"]
            if self.meta["inputs"].get("peers"):
                cmd += ["--peers", "inputs/peers.csv"]
            return self._run(cmd, timeout=600)
        if action == "guard":
            from .report_pipeline import _latest_run
            run, _ = _latest_run(self.ws, work)
            if run is None:
                raise ValueError("还没有有效估值运行")
            return self._run(base + ["guard", "--run-dir", f"runs/{run.name}",
                                     "--text", f"{work}/report/narrative.md"])
        raise ValueError("操作不在白名单中")

    def render_report(self) -> str:
        from .report_pipeline import _latest_run
        run, _ = _latest_run(self.ws, self.work.as_posix())
        if run is None:
            raise ValueError("还没有有效估值运行")
        script = self.ws / self.work / "report/build_report.py"
        if not script.is_file():
            raise ValueError("报告编排脚本不存在")
        return self._run([sys.executable, str(script.relative_to(self.ws)), "--run-dir", f"runs/{run.name}"],
                         timeout=900, clean_env=True)

    def dispatch(self, name: str, args: dict[str, Any]) -> str:
        if name not in {t["function"]["name"] for t in TOOLS}:
            raise ValueError("未知工具")
        audit_args = {k: (f"<内容 {len(v)} 字符>" if k == "content" and isinstance(v, str) else v)
                      for k, v in args.items()}
        tracing.log("tool_call", tool=name, args=audit_args)
        method = getattr(self, name)
        result = method(**args)
        return result[:MAX_TOOL_OUTPUT] if name not in {"read_pdf_pages", "read_file"} else result


def run(ws: Path, model: str = MODEL) -> int:
    """逐阶段调用 DeepSeek；每轮以真实 status 为准，不把模型自称完成当成过闸门。"""
    if not model.startswith("deepseek-"):
        raise ValueError("DeepSeek 执行器只接受 deepseek-* 模型")
    meta = json.loads(tracing.read_file(ws / META).decode("utf-8"))
    if not os.getenv("DEEPSEEK_API_KEY"):
        raise ValueError("缺少 DEEPSEEK_API_KEY；在仓库被忽略的 .env 填写，勿提交或发到聊天")
    tools = WorkspaceTools(ws, meta)
    client = LLMClient(get_settings(llm_base_url="https://api.deepseek.com", llm_model=model,
                                    llm_api_key=os.environ["DEEPSEEK_API_KEY"], llm_mode="live",
                                    cache_dir=str(ws / ".pipeline/api_cache"), llm_timeout=180))
    guide = tracing.read_file(ws / "AGENTS.md").decode("utf-8")
    max_api_calls = int(os.getenv("FINAGENT_DEEPSEEK_MAX_CALLS", str(MAX_API_CALLS)))
    if not 1 <= max_api_calls <= MAX_API_CALLS:
        raise ValueError(f"FINAGENT_DEEPSEEK_MAX_CALLS 应在 1–{MAX_API_CALLS} 之间")
    api_calls = prompt_tokens = completion_tokens = 0
    for _stage_iter in range(8):
        state = status(ws)
        if state["done"]:
            emit("stage", stage="全部", detail="8 个闸门通过")
            return 0
        index, stage = next((i, s) for i, s in enumerate(state["stages"]) if not s["ok"])
        if stage["stage"].startswith("4 ") and not (ws / "inputs/market.json").is_file():
            emit("error", detail="缺少有来源的当前股价；按工作区规范停在估值前")
            return 3
        emit("stage", stage=stage["stage"], detail=stage["next"])
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": (
                "你是 FinAgent 工作区里的 DeepSeek 研报执行模型。只能通过所给工具读取本公司年报与两个原版 Skill，"
                "不得访问工作区外、联网补公司数据、自己做算术或捏造数字。"
                "只推进当前闸门，不跳阶段；模型结论不能代替程序校验。"
                "估值假设可按工作区规则起草并标明分析师假设，不要求额外人工审批；缺有来源股价则停下。"
                "每次工具输出有错误时修正。完成当前阶段后调用 status，然后简短结束。")},
            {"role": "user", "content": guide + "\n\n当前闸门：" + json.dumps(stage, ensure_ascii=False)},
        ]
        for _round in range(MAX_ROUNDS_PER_STAGE):
            if (api_calls >= max_api_calls or prompt_tokens >= MAX_PROMPT_TOKENS
                    or completion_tokens >= MAX_COMPLETION_TOKENS):
                emit("error", detail="DeepSeek 调用或 token 上限已到，工作区进度保留；请检查 status 后决定是否继续")
                return 5
            response = client.chat(messages, tools=TOOLS, purpose=f"report_pipeline:{meta['key']}:{stage['stage']}",
                                   reasoning_effort="high")
            api_calls += 1
            usage = (client.last_call.get("usage") or {})
            prompt_tokens += usage.get("prompt_tokens", 0)
            completion_tokens += usage.get("completion_tokens", 0)
            emit("usage", model=model, usage=usage, request_sha256=client.last_call.get("request_sha256"),
                 cache_hit=client.last_call.get("cache_hit"))
            # 思考模式 + tools 的下一轮必须原样带回 reasoning_content。
            messages.append({"role": "assistant", **response})
            calls = response.get("tool_calls") or []
            if len(calls) > 8:
                raise ValueError("单轮工具调用过多，已停止")
            for call in calls:
                name = call.get("function", {}).get("name", "")
                try:
                    args = json.loads(call["function"].get("arguments") or "{}")
                    if not isinstance(args, dict):
                        raise ValueError("工具参数须为 JSON 对象")
                    result = tools.dispatch(name, args)
                    content = json.dumps({"ok": True, "result": result}, ensure_ascii=False)
                except (ValueError, TypeError, OSError, RuntimeError, json.JSONDecodeError,
                        subprocess.TimeoutExpired) as exc:
                    content = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
                emit("tool", stage=stage["stage"], tool=name, ok=json.loads(content)["ok"])
                messages.append({"role": "tool", "tool_call_id": call["id"], "content": content})
            if status(ws)["stages"][index]["ok"]:
                break
            if not calls:
                # 模型口头宣称结束但闸门未过，继续提醒；最多 30 轮。
                messages.append({"role": "user", "content": "当前闸门仍未通过：" + status(ws)["next"] + "。请继续调用工具。"})
        else:
            emit("error", detail=f"{stage['stage']} 达到 {MAX_ROUNDS_PER_STAGE} 轮上限：{status(ws)['next']}")
            return 4
    final = status(ws)
    emit("stage", stage="全部", detail="8 个闸门通过" if final["done"] else final["next"])
    return 0 if final["done"] else 4


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DeepSeek 研报流水线执行器；由 report_pipeline run 调用")
    parser.add_argument("--model", default=MODEL)
    args = parser.parse_args(argv)
    ws = Path.cwd()
    if not (ws / META).is_file():
        parser.error("必须在 report_pipeline 工作区运行")
    try:
        with tracing.RunTracer("deepseek-agent", runs_root=ws / "runs",
                               config={"model": args.model, "workspace": str(ws)}) as tracer:
            code = run(ws, args.model)
            tracer.event("agent_result", exit_code=code, gates_passed=sum(s["ok"] for s in status(ws)["stages"]))
            return code
    except (ValueError, LLMError, OSError) as exc:
        emit("error", detail=str(exc))
        return 2


if __name__ == "__main__":
    sys.exit(main())
