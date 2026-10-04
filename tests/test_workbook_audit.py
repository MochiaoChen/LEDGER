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


def test_formula_controls_flag_hardcodes_and_period_islands(tmp_path):
    """跨期写法孤岛判失败；写死的假设数字列为提示；约定常数、ROUND 精度、分位序号、勾稽容差不算写死。"""
    from finagent.evaluation.workbook_audit import formula_controls, hardcoded_literals

    assert hardcoded_literals("ROUND(B11-B21,6)") == []
    assert hardcoded_literals('QUARTILE(IF(($C$3:$C$9="Core")*ISNUMBER(H$3:H$9),H$3:H$9),3)') == []
    assert hardcoded_literals('IF(ABS(B24)<0.001,"OK","ERR")') == []
    assert hardcoded_literals("'三表-利润表'!B5*365/C7") == []
    assert hardcoded_literals("C5*1.08") == ["1.08"]

    def cell(f):
        return {"formula": f, "value": "1", "label": ""}
    sheets = {"预测": {"B5": cell("A5*1.1"), "C5": cell("B5*(1+C4)"), "D5": cell("C5*(1+D4)"),
                       "E5": cell("D5*1.25"), "F5": cell("E5*(1+F4)"), "G5": cell("SUM(B5:F5)")}}
    c = formula_controls(sheets)
    assert [x["cell"] for x in c["inconsistent_formulas"]] == ["预测!E5"]  # 中间一年被改写；末列合计不算
    assert {x["cell"] for x in c["hardcoded_formulas"]} == {"预测!B5", "预测!E5"}

    source = PROJECT_ROOT / "report" / "交付" / "0930 宁德时代 Opus" / "sheet.xlsx"
    audit = audit_workbook(source)
    assert audit["inconsistent_formulas"] == [] and audit["hardcoded_formulas"] == []
