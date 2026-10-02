"""DeepSeek 研报执行器：在单公司工作区内用受限工具完成 report_pipeline 闸门。

模型只读本工作区的 skill、年报指定页和产物；所有计算交给 FinAgent。
此处是逻辑访问边界，不声称提供操作系统级沙箱。模型只能编写声明式布局，
报告由受信任的 safe_report 程序渲染，不能提交或运行模型生成的 Python。
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
MAX_CONTEXT_CHARS = 85_000
MAX_TOOLS_PER_ROUND = 16


def emit(kind: str, **data: Any) -> None:
    """输出与 report_pipeline.run_agent 兼容的逐行事件。"""
    print(json.dumps({"type": f"deepseek.{kind}", **data}, ensure_ascii=False), flush=True)


def _tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required,
                           "additionalProperties": False}}}


def _compact_messages(messages: list[dict[str, Any]], stage: str, next_step: str) -> list[dict[str, Any]]:
    """Bound repeated tool-history cost while preserving the newest thinking/tool exchange.

    DeepSeek needs reasoning_content + tool replies from the immediately preceding
    assistant turn. Older exchanges have already produced on-disk artifacts and are
    audited separately, so the model can re-read a needed source on demand.
    """
    if len(json.dumps(messages, ensure_ascii=False)) <= MAX_CONTEXT_CHARS or len(messages) <= 4:
        return messages
    last = next((i for i in range(len(messages) - 1, 1, -1) if messages[i]["role"] == "assistant"), 2)
    recent = messages[last:]
    summary = {"role": "user", "content":
               f"较早的工具输出已压缩，已写文件和运行记录仍在工作区。当前阶段：{stage}。"
               f"当前闸门提示：{next_step}。如需依据，请按需重读本公司文件；不要猜数。"}
    return [*messages[:2], summary, *recent]


STR = {"type": "string"}
TOOLS = [
    _tool("read_file", "读取工作区内允许的文本文件。先按阶段读 skill，不读引擎源码。",
          {"path": STR}, ["path"]),
    _tool("list_files", "列出允许目录中的文件名，不递归。", {"path": STR}, ["path"]),
    _tool("read_pdf_pages", "读取本公司年报的 PDF 物理页码，一次最多 20 页；输出带页码。",
          {"pages": {"type": "array", "items": {"type": "integer"}, "maxItems": 20}}, ["pages"]),
    _tool("write_file", "只写本公司的 data/extractions/<公司_年度>/ 下的 JSON 或 Markdown；不能写 Python/HTML。",
          {"path": STR, "content": STR}, ["path", "content"]),
    _tool("replace_text", "仅对本公司 narrative.md 作唯一匹配的原句替换；小范围改稿优先使用，避免整篇重写。",
          {"old": STR, "new": STR}, ["old", "new"]),
    _tool("copy_template", "复制研报文稿模板到本公司目录；已有文件时拒绝覆盖。",
          {"name": {"type": "string", "enum": ["narrative"]}}, ["name"]),
    _tool("run_finagent", "执行白名单中的校验、估值、护栏或状态检查；参数由 harness 固定生成。",
          {"action": {"type": "string", "enum": ["schema", "verify_facts", "verify_extra", "valuation", "guard", "review", "revise", "auto_review", "status"]}},
          ["action"]),
    _tool("render_report", "用受信任的固定排版程序读取 layout.json 与文稿，生成 PDF 与逐页预览。",
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
            if not rel_path.is_relative_to(self.work) or rel_path.suffix not in {".json", ".md"}:
                raise ValueError("只能写本公司的抽取与研报文件")
            allowed_outputs = {self.work / "facts.json", self.work / "extras.json",
                               self.work / "valuation_assumptions.json", self.work / "report/framework.md",
                               self.work / "report/narrative.md", self.work / "report/layout.json",
                               self.work / "report/delivery.md"}
            if rel_path not in allowed_outputs:
                raise ValueError("该产物由程序生成或不属于模型可写的白名单")
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
            data = json.loads(content)  # 无效 JSON 不落盘。
            if file.relative_to(self.ws) == self.work / "valuation_assumptions.json":
                # Market observations belong to the trusted input, not model prose.
                market = json.loads((self.ws / "inputs/market.json").read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("估值假设须为 JSON 对象")
                data["current_price"] = market["current_price"]
                data["price_source"] = market["price_source"]
                data["valuation_date"] = market.get("price_date")
                content = json.dumps(data, ensure_ascii=False, indent=2)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
        if tracer := tracing.current():
            tracer.register_artifact(file)
        return f"已写入 {file.relative_to(self.ws).as_posix()}；SHA-256 {_sha256(file)}"

    def sync_market_fields(self) -> bool:
        """Repair legacy/model-authored market metadata without touching valid runs."""
        relative = self.work / "valuation_assumptions.json"
        path = self.ws / relative
        if not path.is_file():
            return False
        market_path = self.ws / "inputs/market.json"
        if not market_path.is_file():
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("现有估值假设须为 JSON 对象")
        market = json.loads(market_path.read_text(encoding="utf-8"))
        desired = {"current_price": market["current_price"], "price_source": market["price_source"],
                   "valuation_date": market.get("price_date")}
        if all(data.get(k) == v for k, v in desired.items()):
            return False
        self.write_file(relative.as_posix(), json.dumps(data, ensure_ascii=False))
        return True

    def replace_text(self, old: str, new: str) -> str:
        if not isinstance(old, str) or not old or len(old) > 3000 or not isinstance(new, str) or len(new) > 5000:
            raise ValueError("替换文本长度无效")
        file = self._path((self.work / "report/narrative.md").as_posix(), write=True)
        original = file.read_text(encoding="utf-8")
        count = original.count(old)
        if count != 1:
            raise ValueError(f"原句必须恰好出现一次，实际出现 {count} 次；请先读取最新文稿")
        file.write_text(original.replace(old, new, 1), encoding="utf-8")
        if tracer := tracing.current():
            tracer.register_artifact(file)
        return f"已替换唯一原句；文稿 SHA-256 {_sha256(file)}"

    def copy_template(self, name: str) -> str:
        if name != "narrative":
            raise ValueError("未知模板")
        src = self.ws / ".claude/skills/finagent-report/templates/narrative.md"
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
            # 浏览器与渲染进程不应接触模型密钥或用户环境中的其他凭据。
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
        if action == "review":
            from .report_review import review
            from .report_pipeline import _latest_run
            run, _ = _latest_run(self.ws, work)
            if run is None:
                raise ValueError("还没有有效估值运行")
            narrative = self.ws / self.work / "report/narrative.md"
            if not narrative.is_file():
                raise ValueError("缺少文稿")
            result = review(self.ws, run, narrative)
            return json.dumps({"pass": result["pass"], "issues": result["issues"],
                               "review": f"{work}/report/review.json"}, ensure_ascii=False)
        if action == "revise":
            from .report_review import revise
            from .report_pipeline import _latest_run
            run, _ = _latest_run(self.ws, work)
            if run is None:
                raise ValueError("还没有有效估值运行")
            result = revise(self.ws, run, self.ws / self.work / "report/narrative.md")
            return json.dumps(result, ensure_ascii=False)
        if action == "auto_review":
            from .report_review import review_until_clear
            from .report_pipeline import _latest_run
            run, _ = _latest_run(self.ws, work)
            if run is None:
                raise ValueError("还没有有效估值运行")
            result = review_until_clear(self.ws, run, self.ws / self.work / "report/narrative.md")
            return json.dumps(result, ensure_ascii=False)[:MAX_TOOL_OUTPUT]
        raise ValueError("操作不在白名单中")

    def render_report(self) -> str:
        from .report_pipeline import _latest_run
        run, _ = _latest_run(self.ws, self.work.as_posix())
        if run is None:
            raise ValueError("还没有有效估值运行")
        layout = self.ws / self.work / "report/layout.json"
        if not layout.is_file():
            raise ValueError("声明式 layout.json 不存在")
        from .safe_report import required_basis_keys, validate_layout
        from .report_pipeline import _load
        extras = _load(run / "financials/extras.json")
        seg_path, detail_path = run / "valuation/segment_forecast.json", run / "valuation/three_statement_detail.json"
        validate_layout(_load(layout), {t["id"] for t in extras.get("tables", [])},
                        required_basis_keys(_load(seg_path) if seg_path.is_file() else {},
                                            _load(detail_path) if detail_path.is_file() else {}))
        return self._run([sys.executable, "-m", "finagent.safe_report", "--run-dir", f"runs/{run.name}",
                          "--narrative", f"{self.work.as_posix()}/report/narrative.md",
                          "--layout", f"{self.work.as_posix()}/report/layout.json"],
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
    if not meta.get("require_review"):
        meta["require_review"] = True
        (ws / META).write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tools = WorkspaceTools(ws, meta)
    if tools.sync_market_fields():
        emit("stage", stage="行情输入", detail="估值假设中的股价、来源和日期已与受信任的 market.json 同步")
    client = LLMClient(get_settings(llm_base_url="https://api.deepseek.com", llm_model=model,
                                    llm_api_key=os.environ["DEEPSEEK_API_KEY"], llm_mode="live",
                                    cache_dir=str(ws / ".pipeline/api_cache"), llm_timeout=180))
    guide = tracing.read_file(ws / "AGENTS.md").decode("utf-8")
    max_api_calls = int(os.getenv("FINAGENT_DEEPSEEK_MAX_CALLS", str(MAX_API_CALLS)))
    if not 1 <= max_api_calls <= MAX_API_CALLS:
        raise ValueError(f"FINAGENT_DEEPSEEK_MAX_CALLS 应在 1–{MAX_API_CALLS} 之间")
    api_calls = prompt_tokens = completion_tokens = 0
    # A late-stage correction can invalidate an earlier valuation or guard run.
    # Re-evaluate the first failed gate instead of staying stuck on the old stage.
    for _stage_iter in range(24):
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
                "文稿完成后优先调用 auto_review：它先跑数字护栏，再在最多五轮内用新上下文独立审读与局部修订；"
                "仍有 blocker 就停下，不得跳过。也可单独调用 guard/review/revise 排查具体问题。"
                "小范围修订优先用 replace_text 精确替换原句，避免整篇重写与引入新错误。"
                "排版只写 layout.json，不写 Python；标题须以固定的十个章节名开头，extra_tables 只选已核验表 ID。"
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
            if len(calls) > MAX_TOOLS_PER_ROUND:
                emit("error", detail=f"单轮请求了 {len(calls)} 个工具，超过 {MAX_TOOLS_PER_ROUND} 上限；进度已保留")
                return 4
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
            current = status(ws)
            first_bad = next((i for i, item in enumerate(current["stages"]) if not item["ok"]), None)
            if first_bad is None or first_bad != index or current["stages"][index]["ok"]:
                break
            if not calls:
                # 模型口头宣称结束但闸门未过，继续提醒；最多 30 轮。
                messages.append({"role": "user", "content": "当前闸门仍未通过：" + status(ws)["next"] + "。请继续调用工具。"})
            messages = _compact_messages(messages, stage["stage"], current["next"])
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
