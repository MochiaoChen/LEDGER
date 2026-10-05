"""Chrome 预检、PDF 实测字号与可复核的渲染凭证。失败时保留原 PDF。"""

from __future__ import annotations

import html
import importlib.util
import json
import re
import subprocess
import tempfile
import unicodedata
from pathlib import Path

KIT = Path(__file__).resolve().parent
# 公司脚本可能使用指向另一个 checkout 的 editable 环境；契约须取当前工作区的文件。
_contract_path = KIT.parents[3] / "finagent/output/render_check.py"
_spec = importlib.util.spec_from_file_location("reportkit_render_contract", _contract_path)
_contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_contract)
BODY_PT, FONT_TOLERANCE_PT, VERSION = _contract.BODY_PT, _contract.FONT_TOLERANCE_PT, _contract.VERSION
digest, renderer_hash = _contract.digest, _contract.renderer_hash


def browser_run(browser: str, url: str, *options: str) -> str:
    """独立 profile；以完整 DOM / PDF 判完成，关闭本次进程树，不等后台服务退出。"""
    import os
    import signal
    import time

    with tempfile.TemporaryDirectory(prefix="finagent-chrome-") as profile:
        stdout_path, stderr_path = Path(profile) / "stdout", Path(profile) / "stderr"
        command = [browser, "--headless=new", "--no-first-run", "--no-default-browser-check",
                   "--disable-search-engine-choice-screen", "--disable-component-update",
                   "--disable-background-networking", f"--user-data-dir={profile}",
                   "--virtual-time-budget=10000", *options, url]
        pdf_path = next((Path(o.split("=", 1)[1]) for o in options if o.startswith("--print-to-pdf=")), None)
        with stdout_path.open("w") as stdout, stderr_path.open("w") as stderr:
            proc = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
            try:
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    dom = stdout_path.read_text(encoding="utf-8", errors="replace")
                    if pdf_path is not None:
                        if pdf_path.is_file() and pdf_path.read_bytes().rstrip().endswith(b"%%EOF"):
                            return dom
                    elif "</html>" in dom:
                        return dom
                    if proc.poll() is not None:
                        raise ValueError("Chrome 未输出完整产物：" + stderr_path.read_text(errors="replace")[-1000:])
                    time.sleep(0.1)
                raise TimeoutError("Chrome 渲染超时，未生成完整 DOM / PDF")
            finally:
                if os.name == "posix":
                    try:
                        os.killpg(proc.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                elif proc.poll() is None:
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        os.killpg(proc.pid, signal.SIGKILL)
                    else:
                        proc.kill()
                    proc.wait()


def preflight(html_path: Path, browser: str) -> dict:
    """以打印版心测量实际 DOM；没有测量结果或资源缺失同样拒收。"""
    page = html_path.read_text(encoding="utf-8")
    probe = (KIT / "render_probe.js").read_text(encoding="utf-8")
    base = f'<base href="{html.escape(html_path.resolve().as_uri(), quote=True)}">'
    page = page.replace("<head>", "<head>" + base, 1).replace("</body>", f"<script>{probe}</script></body>", 1)
    with tempfile.TemporaryDirectory(prefix="finagent-preflight-", dir=Path("/tmp") if Path("/tmp").is_dir() else None) as tmp:
        target = Path(tmp) / "probe.html"
        target.write_text(page, encoding="utf-8")
        dom = browser_run(browser, target.as_uri(), "--dump-dom")
    match = re.search(r'<script id="finagent-render-check" type="application/json">(.*?)</script>', dom, re.S)
    if not match:
        raise ValueError("渲染预检未完成，不能确认页面宽度与正文样式")
    result = json.loads(match.group(1))
    if result.get("error"):
        raise ValueError("渲染预检失败：" + result["error"])
    if result["broken_images"]:
        raise ValueError("图表加载失败：" + "、".join(result["broken_images"]))
    if result["overflow"]:
        detail = "；".join(f"{e['tag']}.{e['cls']}：{e['text']}" for e in result["overflow"][:5])
        raise ValueError("页面宽度溢出，会导致 PDF 整体缩小；请换行或改整栏：" + detail)
    if result["font_errors"] or not result["samples"]:
        raise ValueError("正文必须为 10.5pt，且须含可实测的正文段落：" + str(result["font_errors"]))
    return result


def measure_pdf(pdf: Path, samples: list[dict]) -> dict:
    """在实际 PDF 中定位正文原文，核验字形字号，而不是相信 CSS 声明。"""
    import pdfplumber

    found = {}
    with pdfplumber.open(pdf) as doc:
        pages = len(doc.pages)
        if any(abs(p.width - 595.28) > 1 or abs(p.height - 841.89) > 1 for p in doc.pages):
            raise ValueError("PDF 纸张须为纵向 A4")
        for index, page in enumerate(doc.pages, 1):
            chars = [{**c, "text":letter} for c in page.chars for letter in unicodedata.normalize("NFKC", c["text"]) if not letter.isspace()]
            text = "".join(c["text"] for c in chars)
            for sample in samples:
                needle = unicodedata.normalize("NFKC", sample["text"])
                if needle in found:
                    continue
                start = text.find(needle)
                if start < 0:
                    continue
                sizes = [c["size"] for c in chars[start:start + len(needle)]]
                actual = sorted(sizes)[len(sizes) // 2]
                found[needle] = {"text":needle, "page":index, "actual_pt":round(actual, 4)}
                if any(abs(size - BODY_PT) > FONT_TOLERANCE_PT for size in sizes):
                    raise ValueError(f"PDF 正文实测 {actual:.2f}pt，应为 10.5pt：{needle}（第 {index} 页）")
            if len(found) == len({unicodedata.normalize("NFKC", s["text"]) for s in samples}):
                break
    if len(found) != len({unicodedata.normalize("NFKC", s["text"]) for s in samples}):
        raise ValueError("PDF 正文样本未完整定位，无法确认实际字号")
    return {"pages":pages, "samples":list(found.values())}


def to_pdf(html_path: Path, browser: str) -> Path:
    pdf = html_path.with_suffix(".pdf")
    record_path = html_path.with_name("render_check.json")
    record = {"version":VERSION, "ok":False, "html_sha256":digest(html_path),
              "renderer_sha256":renderer_hash(KIT)}
    try:
        layout = preflight(html_path, browser)
        record["layout"] = layout
        with tempfile.TemporaryDirectory(prefix="finagent-pdf-", dir=html_path.parent) as tmp:
            candidate = Path(tmp) / "report.pdf"
            browser_run(browser, html_path.resolve().as_uri(), "--no-pdf-header-footer", f"--print-to-pdf={candidate}")
            record["pdf"] = measure_pdf(candidate, layout["samples"])
            record["pdf_sha256"] = digest(candidate)
            record["ok"] = True
            candidate.replace(pdf)
    except Exception as exc:
        record["error"] = str(exc)
        raise
    finally:
        record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return pdf
