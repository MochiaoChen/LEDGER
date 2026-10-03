"""把质检查看包拆成逐公司、可离线批注并导出 JSON 的 HTML 文件。"""

from __future__ import annotations

import base64
import hashlib
import json
from html import escape
from pathlib import Path
from typing import Any

TEMPLATE = Path(__file__).with_name("review_doc_template.html")
LAYERS = ("L0", "L1", "L2", "L3", "N")


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"预期 JSON 对象：{path}")
    return data


def _safe_json(data: dict[str, Any]) -> str:
    """JSON 放在 script 文本节点；转义 HTML 结束符与行分隔符。"""
    return (json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _item_html(item: dict[str, Any], result: dict[str, Any]) -> str:
    item_id = str(item["id"])
    negative = item["layer"] == "N"
    passed = bool(result["passed"])
    baseline = ("命中" if passed else "未命中") if negative else ("通过" if passed else "未过")
    tone = "bad" if (passed if negative else not passed) else "ok"
    evidence = escape(str(result.get("evidence") or ""))
    reason = escape(str(result.get("reason") or "—"))
    examples = "；".join(str(x) for x in item.get("fail_examples", []))
    example_html = f'\n  <p class="example">反例：{escape(examples)}</p>' if examples else ""
    evidence_html = f'\n    <p class="evidence"><span class="field-label">证据</span>{evidence}</p>' if evidence else ""
    option_pass = "命中" if negative else "通过"
    option_fail = "未命中" if negative else "未过"
    return f'''<article class="review-item" data-item-id="{escape(item_id, quote=True)}">
  <div class="item-top"><span class="item-id">{escape(item_id)}</span>
    <h3>{escape(str(item["title"]))}</h3>
    <span class="baseline {tone}">原判定：{baseline}</span>
    <span class="points">{float(item["points"]):g} 分</span></div>
  <p class="criterion">{escape(str(item["criterion"]))}</p>{example_html}
  <div class="finding"><span class="field-label">原理由</span><p>{reason}</p>{evidence_html}</div>
  <div class="review-fields"><label>人工复核结论
    <select data-field="decision" aria-label="{escape(item_id, quote=True)} 人工复核结论">
      <option value="unreviewed">尚未复核</option><option value="accept">认可原判定</option>
      <option value="pass">改判：{option_pass}</option><option value="fail">改判：{option_fail}</option>
      <option value="needs_check">需进一步核查</option>
    </select></label>
    <label>评论与意见<textarea data-field="comment" rows="3" maxlength="5000"
      placeholder="写明改判依据、需补的证据或交给生成方的具体修改建议"></textarea></label></div>
</article>'''


def _document(rubric: dict[str, Any], score: dict[str, Any], company: str,
              source_hash: str, pdf_bytes: bytes | None) -> str:
    items = rubric["items"]
    by_id = {str(row["id"]): row for row in score["items"]}
    if len(by_id) != len(score["items"]) or set(by_id) != {str(item["id"]) for item in items}:
        raise ValueError(f"{company} 的评分条目与 rubric 不一致，拒绝生成质检页")
    if any(by_id[str(item["id"])]["layer"] != item["layer"] for item in items):
        raise ValueError(f"{company} 的评分层级与 rubric 不一致，拒绝生成质检页")
    sections = []
    for layer in LAYERS:
        sub = [item for item in items if item["layer"] == layer]
        if not sub:
            continue
        title = f'{layer} {escape(str(rubric["layers"][layer]))}'
        note = "程序判定 · 复核可提出异议" if layer in ("L0", "L1") else "模型盲评 · 请核对原文"
        sections.append(f'<section class="layer"><h2>{title}</h2><p class="layer-note">{note}</p>'
                        + "".join(_item_html(item, by_id[str(item["id"])]) for item in sub) + "</section>")
    data = {"company": company, "rubric_version": rubric["version"], "source_sha256": source_hash,
            "baseline_total": score["total"], "baseline_deliverable": score["deliverable"],
            "items": [{"item_id": item["id"], "layer": item["layer"],
                       "baseline_passed": bool(by_id[str(item["id"])]["passed"])} for item in items]}
    template = TEMPLATE.read_text(encoding="utf-8")
    pdf_link = '<button class="pdf-button" id="download-pdf" type="button">下载原始研报 PDF</button>' \
        if pdf_bytes else "<span>原研报 PDF 不在此包中</span>"
    replacements = {
        "__TITLE__": escape(f"{company} · 研报质检"),
        "__COMPANY__": escape(company),
        "__RUBRIC_VERSION__": escape(str(rubric["version"])),
        "__BASELINE_TOTAL__": f'{float(score["total"]):g}',
        "__BASELINE_STATUS__": "达到交付标准" if score["deliverable"] else "未达交付标准",
        "__BASELINE_REASONS__": escape("；".join(score.get("not_deliverable_reasons", [])) or "无"),
        "__PDF_LINK__": pdf_link,
        "__SECTIONS__": "\n".join(sections),
        "__PACK_DATA__": _safe_json(data),
        "__PDF_DATA__": base64.b64encode(pdf_bytes).decode("ascii") if pdf_bytes else "",
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template


def build_review_docs(pack: Path, out: Path) -> list[Path]:
    """从已封存的 v0 包生成独立质检页；不重跑模型，也不改原判定。"""
    rubric_path = pack / "rubric.json"
    rubric_bytes = rubric_path.read_bytes()
    rubric = _read_json(rubric_path)
    results_root = pack / "results"
    companies = sorted(p for p in results_root.iterdir() if p.is_dir() and (p / "score.json").is_file())
    if not companies:
        raise ValueError("质检包中没有可用的公司评分结果")
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for result_dir in companies:
        company = result_dir.name
        if company in (".", "..") or any(ch in company for ch in "/\\\0"):
            raise ValueError(f"无效公司名：{company}")
        score_bytes = (result_dir / "score.json").read_bytes()
        score = json.loads(score_bytes)
        if score.get("rubric") != rubric.get("version"):
            raise ValueError(f"{company} 的评分版本与标准不一致")
        pdf = pack / "reports" / f"{company}.pdf"
        pdf_bytes = pdf.read_bytes() if pdf.is_file() else None
        digest = hashlib.sha256(rubric_bytes + b"\n" + score_bytes + b"\n"
                                + (pdf_bytes or b"")).hexdigest()
        target = out / f"{company}.html"
        target.write_text(_document(rubric, score, company, digest, pdf_bytes), encoding="utf-8")
        paths.append(target)
    return paths
