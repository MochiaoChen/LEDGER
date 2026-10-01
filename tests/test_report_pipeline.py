"""研报流水线：隔离工作区的内容边界、阶段闸门与收回。"""

import json
import os

import pytest

from conftest import ROOT
from finagent import report_pipeline as rp


@pytest.fixture()
def ws(tmp_path):
    return rp.build("贵州茅台", 2025, tmp_path / "samples", price=1500.0, price_source="测试行情")


def test_workspace_contains_only_skills_engine_and_one_company(ws):
    assert (ws / ".claude/skills/finagent-research/SKILL.md").is_file()
    assert (ws / ".claude/skills/finagent-report/reportkit/core.py").is_file()
    assert (ws / "finagent/__main__.py").is_file()
    assert not (ws / "finagent/deepseek_harness.py").exists()
    assert not list(ws.rglob("__pycache__"))
    pdfs = list(ws.rglob("*.pdf"))
    assert [p.relative_to(ws).as_posix() for p in pdfs] == ["report/resources/贵州茅台/600519_贵州茅台_2025_年度报告.pdf"]
    assert (ws / "report/resources/贵州茅台/locate.json").is_file()
    # 不带其他公司的抽取、文稿、运行与交付，也不带测试和评测
    assert sorted(p.name for p in (ws / "data").iterdir()) == ["extractions", "samples"]
    assert [p.name for p in (ws / "data/extractions").iterdir()] == ["贵州茅台_2025"]
    assert not list((ws / "data/extractions/贵州茅台_2025").rglob("*.*"))
    for name in ("tests", "eval", "README.md", ".env", "runs/.gitkeep"):
        assert not (ws / name).exists()
    assert os.access(ws / "py", os.X_OK)


def test_workspace_guide_and_permissions(ws):
    meta = json.loads((ws / "sample.json").read_text(encoding="utf-8"))
    assert meta["verified_source"] and meta["inputs"]["market"]["current_price"] == 1500.0
    guide = (ws / "CLAUDE.md").read_text(encoding="utf-8")
    assert "贵州茅台 2025" in guide and "1500.0" in guide and "测试行情" in guide
    assert "report_pipeline status" in guide and "读取边界" in guide
    perms = json.loads((ws / ".claude/settings.json").read_text(encoding="utf-8"))["permissions"]
    assert f"Read(/{ROOT.parent.as_posix()}/**)" in perms["deny"]
    assert "Edit(./finagent/**)" in perms["deny"] and "Write(./.claude/**)" in perms["deny"]


def test_build_guards(tmp_path):
    with pytest.raises(SystemExit, match="allow-unverified"):
        rp.build("恒瑞医药", 2025, tmp_path)
    with pytest.raises(SystemExit, match="price-source"):
        rp.build("贵州茅台", 2025, tmp_path, price=1.0)
    with pytest.raises(SystemExit, match="不能放在"):
        rp.build("贵州茅台", 2025, ROOT / "runs")
    rp.build("贵州茅台", 2025, tmp_path)
    with pytest.raises(SystemExit, match="已存在"):
        rp.build("贵州茅台", 2025, tmp_path)


def test_status_gates_and_collect(ws, tmp_path):
    res = rp.status(ws)
    assert not res["done"] and res["next"].startswith("1 财务抽取")
    work = ws / "data/extractions/贵州茅台_2025"
    (work / "facts.json").write_text("{}", encoding="utf-8")
    (work / "facts.verified.json").write_text(json.dumps({"check": {"ok": True}}), encoding="utf-8")
    (work / "report/framework.md").write_text("# 框架", encoding="utf-8")
    stages = {s["stage"]: s for s in rp.status(ws)["stages"]}
    assert stages["1 财务抽取"]["ok"] and stages["2 分析框架"]["ok"]
    assert not stages["3 经营数据"]["ok"]
    # 修改 facts 后校验结果过期
    os.utime(work / "facts.json", (2e9, 2e9))
    assert not rp.status(ws)["stages"][0]["ok"]
    # 前序阶段未通过时，后续阶段即使有文件也不算通过
    (work / "report/delivery.md").write_text("说明", encoding="utf-8")
    assert not rp.status(ws)["stages"][-1]["ok"]

    root = tmp_path / "repo"
    with pytest.raises(SystemExit, match="闸门"):
        rp.collect(ws, root=root)
    out = rp.collect(ws, root=root, force=True)
    assert (root / out["extractions"] / "report/framework.md").is_file()
    with pytest.raises(SystemExit, match="overwrite"):
        rp.collect(ws, root=root, force=True)
