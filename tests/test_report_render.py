"""实际打印回归：超宽内容和整份缩放不能只靠 CSS 声明蒙混通过。"""

import json
import os
import sys
from pathlib import Path

import pytest

from conftest import ROOT
from finagent.output.render_check import check_render_record, digest, renderer_hash

KIT = ROOT / ".claude/skills/finagent-report/reportkit"
sys.path.insert(0, str(KIT.parent))
from reportkit import render  # noqa: E402
from reportkit.layout import chrome  # noqa: E402

TEXT = "这是一段用于检测报告真实字号与页面宽度的正文。所有公司的报告都应保持清晰可读。"


def page(tmp_path, extra="", style=""):
    p = tmp_path / "report.html"
    css = (KIT / "report.css").read_text(encoding="utf-8")
    p.write_text(f'<html><head><meta charset="utf-8"><style>{css}{style}</style></head>'
                 f'<body><p>{TEXT}</p>{extra}</body></html>', encoding="utf-8")
    return p


def test_render_record_binds_artifacts_and_renderer(tmp_path):
    report = tmp_path / "report"
    report.mkdir()
    for ext in ("html", "pdf"):
        (report / ("report." + ext)).write_text(ext)
    kit = tmp_path / "kit"
    kit.mkdir()
    (kit / "report.css").write_text("body{}")
    record = {"version":1, "ok":True, "html_sha256":digest(report / "report.html"),
              "pdf_sha256":digest(report / "report.pdf"), "renderer_sha256":renderer_hash(kit),
              "layout":{"overflow":[], "font_errors":[]},
              "pdf":{"pages":1, "samples":[{"actual_pt":10.47}]}}
    path = report / "render_check.json"
    path.write_text(json.dumps(record))
    assert check_render_record(report, kit)[0]
    (report / "report.pdf").write_text("旧凭证不能验证新文件")
    assert not check_render_record(report, kit)[0]
    record["pdf_sha256"] = digest(report / "report.pdf")
    path.write_text(json.dumps(record))
    (kit / "report.css").write_text("body{font-size:8pt}")
    assert not check_render_record(report, kit)[0]


def test_failed_preflight_keeps_previous_pdf(tmp_path, monkeypatch):
    p = page(tmp_path)
    p.with_suffix(".pdf").write_bytes(b"previous")
    def fail(*args):
        raise ValueError("页面宽度溢出")
    monkeypatch.setattr(render, "preflight", fail)
    with pytest.raises(ValueError, match="溢出"):
        render.to_pdf(p, "unused")
    assert p.with_suffix(".pdf").read_bytes() == b"previous"
    assert json.loads((tmp_path / "render_check.json").read_text())["ok"] is False


@pytest.fixture
def browser():
    if os.environ.get("FINAGENT_BROWSER_TESTS") != "1":
        pytest.skip("实际打印回归需 FINAGENT_BROWSER_TESTS=1 和 Chrome")
    return chrome()


def test_actual_pdf_long_headers_urls_and_financials(tmp_path, browser):
    head = "动力电池系统单价（2026E）"
    scenario = '<table class="data scenario"><tr>' + '<th>' + '</th><th>'.join([head]*10) + '</th></tr><tr>'
    scenario += '<td>' + '</td><td>'.join(["123.45"]*10) + '</td></tr></table>'
    sources = '<table class="data sources"><tr><th>编号</th><th>发布方</th><th>标题</th><th>日期</th><th>网址</th></tr>'
    sources += '<tr><td>S1</td><td>公司公告</td><td>年报来源</td><td>2026-10-05</td><td>https://example.com/' + 'a'*200 + '</td></tr></table>'
    fin = '<table class="fin"><tr><th>归母净利润增长率</th>' + '<th>2030E</th>'*6 + '</tr><tr><td>营业收入增长率</td>' + '<td>+123.45%</td>'*6 + '</tr></table>'
    (tmp_path / "wide.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="100"><rect width="1000" height="100" fill="red"/></svg>')
    sidebar = '<aside style="width:52mm"><img src="wide.svg" style="width:56mm"></aside>'
    p = page(tmp_path, sidebar + scenario + sources + '<div class="two fin-grid"><div>'+fin+'</div><div>'+fin+'</div></div>')
    pdf = render.to_pdf(p, browser)
    assert pdf.is_file()
    assert check_render_record(tmp_path, KIT)[0]


@pytest.mark.parametrize("extra,style", [
    ('<div style="width:260mm">超宽自定义元素</div>', ''),
    ('<table class="data"><tr><td>'+'1234567890'*40+'</td></tr></table>', ''),
    ('', 'p {font-size:8pt;}'),
    ('<img src="missing.svg">', ''),
])
def test_preflight_rejects_invalid_layout(tmp_path, browser, extra, style):
    with pytest.raises(ValueError):
        render.to_pdf(page(tmp_path, extra, style), browser)
    assert not (tmp_path / "report.pdf").exists()


def test_pdf_measurement_rejects_print_only_shrink(tmp_path, browser):
    # 预检时按 10.5pt 排版，实际 PDF 被缩放：后检必须独立识别。
    p = page(tmp_path)
    layout = render.preflight(p, browser)
    p.write_text(p.read_text().replace('</style>', 'body {zoom:0.8;}</style>'))
    pdf = tmp_path / "shrunk.pdf"
    render.browser_run(browser, p.as_uri(), "--no-pdf-header-footer", f"--print-to-pdf={pdf}")
    with pytest.raises(ValueError, match="实测"):
        render.measure_pdf(pdf, layout["samples"])
