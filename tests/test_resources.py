"""离线年报资源完整性与来源清单。"""

import hashlib
import json

from conftest import ROOT


def test_annual_report_resource_manifest():
    base = ROOT / "report" / "resources"
    manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["fiscal_year"] == 2025
    assert {r["ticker"] for r in manifest["reports"]} == {"600519", "300750", "601872"}
    for item in manifest["reports"]:
        path = base / item["path"]
        data = path.read_bytes()
        assert data.startswith(b"%PDF-")
        assert len(data) == item["size_bytes"]
        assert hashlib.sha256(data).hexdigest() == item["sha256"]
        assert item["source_url"].startswith("https://")
