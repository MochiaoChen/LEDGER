"""研报渲染凭证（finagent/output/render_check.py）：排版闸门只认与当前 HTML、PDF、排版代码匹配且实测 10.5pt 的凭证。

不启动浏览器，直接构造 render_check.json。
"""

import json

from finagent.output.render_check import BODY_PT, VERSION, check_render_record, digest, renderer_hash


def _setup(tmp_path, actual_pt=BODY_PT):
    kit = tmp_path / "reportkit"
    kit.mkdir()
    (kit / "report.css").write_text("body { font-size: 10.5pt; }", encoding="utf-8")
    report = tmp_path / "report"
    report.mkdir()
    (report / "report.html").write_text("<p>正文</p>", encoding="utf-8")
    (report / "report.pdf").write_bytes(b"%PDF-1.4\n%%EOF")
    record = {"version": VERSION, "ok": True,
              "html_sha256": digest(report / "report.html"), "pdf_sha256": digest(report / "report.pdf"),
              "renderer_sha256": renderer_hash(kit),
              "layout": {"overflow": [], "font_errors": [], "broken_images": []},
              "pdf": {"pages": 1, "samples": [{"text": "正文", "page": 1, "actual_pt": actual_pt}]}}
    (report / "render_check.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return report, kit


def test_matching_record_passes(tmp_path):
    report, kit = _setup(tmp_path)
    assert check_render_record(report, kit) == (True, "宽度与正文实测字号通过")


def test_missing_record_fails(tmp_path):
    report, kit = _setup(tmp_path)
    (report / "render_check.json").unlink()
    ok, detail = check_render_record(report, kit)
    assert not ok and "render_check.json" in detail


def test_stale_pdf_or_renderer_fails(tmp_path):
    report, kit = _setup(tmp_path)
    (report / "report.pdf").write_bytes(b"%PDF-1.4\nchanged\n%%EOF")
    assert check_render_record(report, kit)[0] is False

    (tmp_path / "b").mkdir()
    report2, kit2 = _setup(tmp_path / "b")
    (kit2 / "report.css").write_text("body { font-size: 7pt; }", encoding="utf-8")
    ok, detail = check_render_record(report2, kit2)
    assert not ok and "排版代码" in detail


def test_shrunk_pdf_font_fails(tmp_path):
    # Chrome 因版心溢出整份缩小时，PDF 正文实测约 7pt
    report, kit = _setup(tmp_path, actual_pt=7.0)
    ok, detail = check_render_record(report, kit)
    assert not ok and "10.5pt" in detail
