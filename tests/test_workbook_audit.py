"""Excel 仅由机器审计；PDF 无对应工作簿时保持未运行。"""

import zipfile

from finagent.core.config import PROJECT_ROOT
from finagent.evaluation.workbook_audit import audit_workbook, find_matching_workbook


def test_exact_pdf_match_and_three_statement_audit():
    deliveries = PROJECT_ROOT / "report" / "交付"
    reports = PROJECT_ROOT / "eval" / "review_pack" / "v0" / "reports"
    for company in ("宁德时代", "招商轮船"):
        workbook = find_matching_workbook(reports / f"{company}.pdf", deliveries)
        assert workbook is not None
        audit = audit_workbook(workbook)
        assert audit["status"] == "pass", audit.get("reason")
        assert audit["formula_count"] > 500
        assert len(audit["checks"]) == 25
        assert all(c["formula_link_ok"] and c["cache_matches_independent"] for c in audit["checks"])
    assert find_matching_workbook(reports / "贵州茅台.pdf", deliveries) is None
    assert audit_workbook(None)["status"] == "not_run"


def test_wrong_formula_link_fails_even_with_zero_cache(tmp_path):
    source = PROJECT_ROOT / "report" / "交付" / "0930 宁德时代 Opus" / "sheet.xlsx"
    target = tmp_path / "changed.xlsx"
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(target, "w") as changed:
        for info in original.infolist():
            content = original.read(info.filename)
            if info.filename == "xl/worksheets/sheet10.xml":
                assert b"ROUND(D11-D21,6)" in content
                content = content.replace(b"ROUND(D11-D21,6)", b"ROUND(D11-D20,6)", 1)
            changed.writestr(info, content)
    audit = audit_workbook(target)
    assert audit["status"] == "fail"
    assert any(not x["formula_link_ok"] for x in audit["checks"])
