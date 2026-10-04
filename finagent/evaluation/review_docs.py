"""把质检查看包拆成逐公司、可离线批注并导出 JSON 的 HTML 文件。"""

from __future__ import annotations

import base64
import hashlib
import json
from html import escape
from pathlib import Path
from typing import Any

from ..core.config import PROJECT_ROOT
from .workbook_audit import audit_workbook, find_matching_workbook

TEMPLATE = Path(__file__).with_name("review_doc_template.html")
LAYERS = ("L0", "L1", "L2", "L3", "N")
MACHINE_ONLY = {"L0-02", "L0-03", "L1-02", "L1-03", "L1-04", "L1-05", "L1-06", "L1-07", "L1-08"}


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


def _item_html(item: dict[str, Any], result: dict[str, Any], *, state: str) -> str:
    item_id = str(item["id"])
    negative = item["layer"] == "N"
    passed = bool(result["passed"])
    baseline = ("命中" if passed else "未命中") if negative else ("通过" if passed else "未过")
    tone = "bad" if state != "clear" else "ok"
    evidence = escape(str(result.get("evidence") or ""))
    reason = escape(str(result.get("reason") or "—"))
    examples = "；".join(str(x) for x in item.get("fail_examples", []))
    example_html = f'\n  <p class="example">反例：{escape(examples)}</p>' if examples else ""
    evidence_html = f'\n    <p class="evidence"><span class="field-label">证据</span>{evidence}</p>' if evidence else ""
    controls = f'''
  <div class="decision-group" role="group" aria-label="{escape(item_id, quote=True)} 问题是否成立">
    <span class="decision-prompt">模型指出的问题成立吗？</span>
    <button type="button" data-decision="confirmed_issue" aria-pressed="false">对，问题成立</button>
    <button type="button" data-decision="false_alarm" aria-pressed="false">错，模型误判</button>
    <button type="button" data-decision="needs_check" aria-pressed="false" class="quiet">待核查</button>
  </div>
  <div class="followup" data-panel="confirmed_issue" hidden><label>建议怎样修改报告或标准？（可选）
    <textarea data-field="fix" rows="2" maxlength="5000" placeholder="写具体修改动作；如无补充可留空"></textarea></label></div>
  <div class="followup" data-panel="false_alarm" hidden>
    <label>模型误判在哪里？<textarea data-field="reason" rows="2" maxlength="5000" placeholder="必填：说明为什么原判定不成立"></textarea></label>
    <label>支持你判断的 PDF 页码或证据<textarea data-field="evidence" rows="2" maxlength="5000" placeholder="必填：注明页码、段落或可核对的原文依据"></textarea></label>
  </div>
  <div class="followup" data-panel="needs_check" hidden><label>还需要核查什么？
    <textarea data-field="pending" rows="2" maxlength="5000" placeholder="必填：列出缺少的证据或需要谁确认"></textarea></label></div>''' if state == "human_issue" else ""
    note = ('<p class="item-note">该条由机器核对，不要求人工解算。</p>' if state == "machine_issue"
            else '<p class="item-note">模型认为无问题，默认沿用；尚未经人工核验。</p>' if state == "clear" else "")
    open_attr = " open" if state != "clear" else ""
    reviewable = ' data-reviewable="true"' if state == "human_issue" else ""
    return f'''<details class="review-item {state}" data-item-id="{escape(item_id, quote=True)}"{reviewable}{open_attr}>
  <summary class="item-top"><span class="item-id">{escape(item_id)}</span>
    <h3>{escape(str(item["title"]))}</h3>
    <span class="baseline {tone}">原判定：{baseline}</span>
    <span class="points">{float(item["points"]):g} 分</span></summary>
  <div class="item-body">
  <p class="criterion">{escape(str(item["criterion"]))}</p>{example_html}
  <div class="finding"><span class="field-label">原理由</span><p>{reason}</p>{evidence_html}</div>{note}{controls}
  </div>
</details>'''


def _document(rubric: dict[str, Any], score: dict[str, Any], company: str,
              source_hash: str, pdf_bytes: bytes, machine_excel: dict[str, Any]) -> str:
    items = rubric["items"]
    by_id = {str(row["id"]): row for row in score["items"]}
    if len(by_id) != len(score["items"]) or set(by_id) != {str(item["id"]) for item in items}:
        raise ValueError(f"{company} 的评分条目与 rubric 不一致，拒绝生成质检页")
    if any(by_id[str(item["id"])]["layer"] != item["layer"] for item in items):
        raise ValueError(f"{company} 的评分层级与 rubric 不一致，拒绝生成质检页")
    all_flagged = [item for item in items if (bool(by_id[str(item["id"])]["passed"])
                   if item["layer"] == "N" else not bool(by_id[str(item["id"])]["passed"]))]
    flagged_items = [item for item in all_flagged if item["id"] not in MACHINE_ONLY]
    machine_only_issues = [item for item in all_flagged if item["id"] in MACHINE_ONLY]
    cleared_items = [item for item in items if item not in all_flagged]
    sections = []
    for layer in LAYERS:
        sub = [item for item in items if item["layer"] == layer]
        if not sub:
            continue
        title = f'{layer} {escape(str(rubric["layers"][layer]))}'
        problem_count = sum(item in all_flagged for item in sub)
        note = f"{problem_count} 项原评问题；每条可单独展开或折叠"
        sections.append(f'<section class="layer"><h2>{title}</h2><p class="layer-note">{note}</p>'
                        + "".join(_item_html(item, by_id[str(item["id"])],
                                             state="human_issue" if item in flagged_items else
                                             "machine_issue" if item in machine_only_issues else "clear") for item in sub)
                        + "</section>")
    data = {"company": company, "rubric_version": rubric["version"], "source_sha256": source_hash,
            "baseline_total": score["total"], "baseline_deliverable": score["deliverable"],
            "flagged_count": len(flagged_items), "machine_excel": machine_excel,
            "items": [{"item_id": item["id"], "layer": item["layer"],
                       "baseline_passed": bool(by_id[str(item["id"])]["passed"]),
                       "model_flagged": item in all_flagged, "flagged": item in flagged_items,
                       "machine_only": item in machine_only_issues} for item in items]}
    template = TEMPLATE.read_text(encoding="utf-8")
    pdf_link = ('<button class="pdf-button" id="view-pdf" type="button">页内查看 PDF</button>'
                '<button class="pdf-button" id="download-pdf" type="button">下载 PDF</button>')
    excel_status = machine_excel["status"]
    if excel_status == "pass":
        machine_html = (f'<strong class="machine-state pass">配套 Excel 局部审计通过</strong><p>匹配配套 sheet.xlsx；'
                        f'{machine_excel["formula_count"]} 个公式有缓存，'
                        f'{len(machine_excel["checks"])} 项三表勾稽的公式引用与独立复算均通过。'
                        f'最大差额 {machine_excel["max_abs_residual_mm"]:g} 百万元；各期公式写法一致。'
                        + (f'另有 {len(machine_excel["warnings"])} 条提示（公式内写死数字或易变函数），'
                           f'如 {escape(machine_excel["warnings"][0])}。' if machine_excel.get("warnings") else "")
                        + '</p>')
    elif excel_status == "fail":
        machine_html = (f'<strong class="machine-state fail">机器核对未通过</strong>'
                        f'<p>{escape(str(machine_excel.get("reason") or "公式、缓存或三表勾稽存在异常"))}</p>')
    else:
        machine_html = '<strong class="machine-state na">未执行工作簿检查</strong><p>未找到与该 PDF 完全匹配的配套 Excel；不能推断公式或勾稽已通过。</p>'
    model_ts = by_id.get("L0-02", {})
    model_dcf = by_id.get("L0-03", {})
    machine_html += (f'<p class="machine-note">原评模型引擎：三表勾稽 {"通过" if model_ts.get("passed") else "未过"}'
                     f'（{escape(str(model_ts.get("reason", "无记录")))}）；'
                     f'DCF 同口径 {"通过" if model_dcf.get("passed") else "未过"}'
                     f'（{escape(str(model_dcf.get("reason", "无记录")))}）。</p>'
                     '<p class="machine-note">工作簿检查不等于在 Excel 中完整重算，也不需要质检员手工解公式。</p>')
    if machine_only_issues:
        machine_html += '<details class="machine-issues"><summary>原评另有程序检测问题，点击查看</summary><ul>'
        machine_html += "".join(f'<li><b>{escape(str(item["id"]))} {escape(str(item["title"]))}</b>：'
                                f'{escape(str(by_id[str(item["id"])].get("reason") or "无说明"))}</li>'
                                for item in machine_only_issues)
        machine_html += '</ul></details>'
    layer_stats = "".join(f'<span>{k} {float(score["layers"][k]["earned"]):g}/'
                          f'{float(score["layers"][k]["possible"]):g}</span>' for k in ("L1", "L2", "L3"))
    replacements = {
        "__TITLE__": escape(f"{company} · 研报质检"),
        "__COMPANY__": escape(company),
        "__RUBRIC_VERSION__": escape(str(rubric["version"])),
        "__BASELINE_TOTAL__": f'{float(score["total"]):g}',
        "__BASELINE_STATUS__": "达到交付标准" if score["deliverable"] else "未达交付标准",
        "__BASELINE_REASONS__": escape("；".join(score.get("not_deliverable_reasons", [])) or "无"),
        "__LAYER_STATS__": layer_stats,
        "__FLAGGED_COUNT__": str(len(flagged_items)),
        "__CLEARED_COUNT__": str(len(cleared_items)),
        "__MACHINE_EXCEL__": machine_html,
        "__PDF_LINK__": pdf_link,
        "__SECTIONS__": "\n".join(sections),
        "__PACK_DATA__": _safe_json(data),
        "__PDF_DATA__": base64.b64encode(pdf_bytes).decode("ascii"),
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template


def build_review_docs(pack: Path, out: Path, deliveries_root: Path | None = None) -> list[Path]:
    """从已封存的 v0 包生成独立质检页；不重跑模型，也不改原判定。"""
    rubric_path = pack / "rubric.json"
    rubric_bytes = rubric_path.read_bytes()
    rubric = _read_json(rubric_path)
    deliveries_root = deliveries_root or PROJECT_ROOT / "report" / "交付"
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
        pdf_bytes = pdf.read_bytes()
        if not pdf_bytes.startswith(b"%PDF-"):
            raise ValueError(f"{company} 的输入不是有效 PDF")
        workbook = find_matching_workbook(pdf, deliveries_root)
        machine_excel = audit_workbook(workbook)
        digest = hashlib.sha256(rubric_bytes + b"\n" + score_bytes + b"\n"
                                + pdf_bytes + b"\n"
                                + machine_excel.get("workbook_sha256", "").encode()).hexdigest()
        target = out / f"{company}.html"
        target.write_text(_document(rubric, score, company, digest, pdf_bytes, machine_excel), encoding="utf-8")
        paths.append(target)
    return paths
