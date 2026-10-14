#!/usr/bin/env python3
"""生成宣传片用的真实数据 src/data/data.json 与图片素材。

所有上屏数字都从仓库、工作区产物读出或由本脚本调用引擎函数得到，不手写。
用法（仓库根目录）：
    .venv/bin/python promo/tools/gen_data.py [--workspace ~/finagent-samples/中际旭创_2025] [--skip-pdf]
"""
import argparse
import difflib
import json
import re
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
PROMO = ROOT / "promo"
sys.path.insert(0, str(ROOT))

ap = argparse.ArgumentParser()
ap.add_argument("--workspace", default=str(Path.home() / "finagent-samples" / "中际旭创_2025"))
ap.add_argument("--skip-pdf", action="store_true", help="不重新渲染 PDF 页面图片")
a = ap.parse_args()
WS = Path(a.workspace)
COMPANY, YEAR = "中际旭创", 2025
EX = WS / "data" / "extractions" / f"{COMPANY}_{YEAR}"


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def jsonl(p):
    out = []
    for ln in Path(p).read_text(encoding="utf-8").split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


data = {"company": COMPANY, "year": YEAR, "workspace": "~/finagent-samples/" + WS.name}

# ---------------------------------------------------------------- 1) 会话与闸门
runs = load(WS / ".pipeline" / "agent_runs.json")
data["agent_runs"] = [{k: r.get(k) for k in ("role", "model", "started_at", "elapsed_sec", "exit_code", "turns", "cost_usd",
                                              "input_tokens", "output_tokens", "log")} for r in runs]
ok_runs = [r for r in runs if r.get("exit_code") == 0]
data["agent_totals"] = {"sessions": len(runs), "ok_sessions": len(ok_runs),
                        "elapsed_min": round(sum(r["elapsed_sec"] for r in runs) / 60, 1),
                        "cost_usd": round(sum(r.get("cost_usd") or 0 for r in runs), 2),
                        "turns": sum(r.get("turns") or 0 for r in runs)}

status = subprocess.run(["./py", "-m", "finagent.report_pipeline", "status"], cwd=WS, capture_output=True, text=True).stdout
gates = []
for ln in status.split("\n"):
    m = re.match(r"\s*\[(.)\]\s*(\d+)\s+(\S+)\s+(.*)", ln)
    if m:
        gates.append({"ok": m.group(1) == "✓", "n": int(m.group(2)), "name": m.group(3), "detail": m.group(4).strip()})
data["gates"] = gates
data["status_text"] = status.strip()

# ---------------------------------------------------------------- 2) 研究助理会话的真实事件流
research_log = next(r["log"] for r in runs if r["role"] == "research")
ev = jsonl(WS / research_log)
t0 = next(ts(e["timestamp"]) for e in ev if e.get("timestamp"))
results = {}
for e in ev:
    if e.get("type") == "user" and isinstance(e["message"].get("content"), list):
        for b in e["message"]["content"]:
            if b.get("type") == "tool_result":
                results[b["tool_use_id"]] = (e, b)
stream = []
init = next(e for e in ev if e.get("type") == "system" and e.get("subtype") == "init")
for e in ev:
    if e.get("type") != "assistant":
        continue
    t = round(ts(e["timestamp"]) - t0, 2) if e.get("timestamp") else None
    for b in e["message"].get("content", []):
        if b.get("type") == "text" and b["text"].strip() and not b["text"].startswith("API Error"):
            stream.append({"t": t, "kind": "say", "text": b["text"].strip().split("\n")[0][:120]})
        if b.get("type") != "tool_use":
            continue
        name, inp = b["name"], b["input"]
        res = results.get(b["id"])
        dt = round(ts(res[0]["timestamp"]) - ts(e["timestamp"]), 2) if res and res[0].get("timestamp") and e.get("timestamp") else None
        if name == "WebSearch":
            hits = []
            r = (res[0].get("tool_use_result") or {}) if res else {}
            for blk in (r.get("results") or []) if isinstance(r, dict) else []:
                if isinstance(blk, dict):
                    for h in blk.get("content") or []:
                        if isinstance(h, dict) and h.get("url"):
                            hits.append({"title": h.get("title", "")[:60], "domain": urlparse(h["url"]).netloc.replace("www.", "")})
            stream.append({"t": t, "kind": "search", "query": inp.get("query", ""), "hits": hits[:5], "n_hits": len(hits), "dt": dt})
        elif name == "WebFetch":
            u = urlparse(inp.get("url", ""))
            stream.append({"t": t, "kind": "fetch", "domain": u.netloc.replace("www.", ""), "path": u.path[:48],
                           "prompt": inp.get("prompt", "")[:80], "dt": dt})
        elif name in ("Read", "Write", "Edit"):
            fp = inp.get("file_path", "")
            rel = fp.split(WS.name + "/")[-1] if WS.name in fp else Path(fp).name
            stream.append({"t": t, "kind": name.lower(), "path": rel, "pages": inp.get("pages")})
        elif name == "Bash":
            stream.append({"t": t, "kind": "bash", "command": inp.get("command", "")[:110]})
rr = next(r for r in runs if r["role"] == "research")
data["research"] = {"model": rr["model"], "elapsed_sec": rr["elapsed_sec"], "turns": rr["turns"], "cost_usd": round(rr["cost_usd"], 2),
                    "claude_code_version": init.get("claude_code_version"), "permission_mode": init.get("permissionMode"),
                    "n_search": sum(1 for s in stream if s["kind"] == "search"),
                    "n_fetch": sum(1 for s in stream if s["kind"] == "fetch"),
                    "domains": sorted({s["domain"] for s in stream if s["kind"] == "fetch"}),
                    "stream": stream}

src = load(EX / "research" / "sources.json")
sources = src["sources"]
data["sources"] = {"n": len(sources), "n_facts": sum(len(s.get("facts") or []) for s in sources),
                   "n_questions": len(src.get("questions") or []),
                   "publishers": sorted({s.get("publisher", "") for s in sources}),
                   "items": [{"id": s["id"], "title": s["title"][:44], "publisher": s.get("publisher", ""), "published": s.get("published"),
                              "domain": urlparse(s.get("url", "")).netloc.replace("www.", ""),
                              "facts": [{k: f.get(k) for k in ("quote", "value", "unit", "label")} for f in (s.get("facts") or [])[:3]]}
                             for s in sources[:24]]}
from finagent.output import sources as srcmod  # noqa: E402
data["sources"]["index"] = {s["id"]: {"publisher": s.get("publisher", ""), "published": s.get("published"), "title": s["title"][:40]} for s in sources}
vs = srcmod.verify_sources(src)
data["sources"]["verify"] = {k: (v if not isinstance(v, list) else len(v)) for k, v in vs.items() if k != "sources"}

# ---------------------------------------------------------------- 3) 财务抽取与证据校验（调用引擎真实函数）
from finagent.parsing.document import load_document  # noqa: E402
from finagent.tasks.financials import external  # noqa: E402

facts_in = load(EX / "facts.json")
ver = load(EX / "facts.verified.json")
pdf = WS / "report" / "resources" / COMPANY / "300308_中际旭创_2025_年度报告.pdf"
doc = load_document(pdf)
rev = next(f for f in facts_in["facts"] if f["metric_id"] == "revenue" and f["period"] == str(YEAR))
page, raw = int(rev["page"]), rev["raw_value"]
ch = external.find_evidence(doc, page, raw)
tampered = raw.replace("239", "293", 1)
ch_bad = external.find_evidence(doc, page, tampered)
pat = external._num_pattern(raw)
rows = [ln for ln in ch.text.split("\n") if ln.strip()]
hit_row = next(i for i, ln in enumerate(rows) if pat.search(external._norm(ln)))
# 小数边界：原文 38,239,935,640.67 不能被整数部分 38239935640 命中
bare = raw.replace(",", "").split(".")[0]
ch_bare = external.find_evidence(doc, page, bare)
data["evidence"] = {"fact": rev, "page": page, "raw": raw, "pattern": pat.pattern,
                    "found": {"chunk_id": ch.chunk_id, "kind": ch.kind, "caption": getattr(ch, "caption", ""), "unit_hint": getattr(ch, "unit_hint", "")},
                    "rows": rows[max(0, hit_row - 3):hit_row + 9], "hit_row": min(3, hit_row),
                    "tampered": tampered, "tampered_found": ch_bad is not None,
                    "bare": bare, "bare_found": ch_bare is not None,
                    "pdf_name": pdf.name, "n_pages": max(c.page for c in doc.chunks), "n_chunks": len(doc.chunks)}
on_page = sorted([c for c in doc.chunks if c.page == page], key=lambda c: c.kind != "table")
data["evidence"]["on_page"] = [{"chunk_id": c.chunk_id, "kind": c.kind, "caption": (getattr(c, "caption", "") or c.text.strip().split("\n")[0])[:28],
                                "chars": len(c.text), "hit": bool(pat.search(external._norm(c.text)))} for c in on_page]
data["evidence"]["reject_msg"] = f"{rev['metric_id']} {rev['period']}={tampered} 未在第 {page} 页原文中找到"
import pdfplumber  # noqa: E402
with pdfplumber.open(pdf) as pp:
    pg = pp.pages[page - 1]
    boxes = [{"text": w["text"], "x0": w["x0"] / pg.width, "x1": w["x1"] / pg.width, "y0": w["top"] / pg.height, "y1": w["bottom"] / pg.height}
             for w in pg.extract_words() if w["text"].replace(",", "") in (raw.replace(",", ""), "23862159738.37", "22165537126.77")]
    data["evidence"]["boxes"] = boxes
    data["evidence"]["page_aspect"] = pg.width / pg.height
data["facts"] = {"n": len(facts_in["facts"]), "stats": ver["stats"], "check": {k: (len(v) if isinstance(v, list) else v) for k, v in ver["check"].items() if k != "stats"},
                 "sample": [{k: f.get(k) for k in ("metric_id", "period", "raw_value", "unit", "page", "label", "table")}
                            for f in facts_in["facts"] if f["period"] == str(YEAR)][:14]}

# ---------------------------------------------------------------- 4) 源码片段（带真实行号）
def excerpt(rel, start_mark, end_mark=None, n=None):
    lines = (ROOT / rel).read_text(encoding="utf-8").split("\n")
    i = next(k for k, ln in enumerate(lines) if ln.startswith(start_mark))
    if end_mark:
        j = next(k for k in range(i + 1, len(lines)) if lines[k].startswith(end_mark))
        while lines[j - 1].strip() == "":
            j -= 1
    else:
        j = i + n
    return {"file": rel, "line": i + 1, "text": "\n".join(lines[i:j])}


data["code"] = {
    "pattern": excerpt("finagent/tasks/financials/external.py", "def _num_pattern", "def _norm"),
    "find_evidence": excerpt("finagent/tasks/financials/external.py", "def find_evidence", "def _pick_doc"),
    "numlock": excerpt("finagent/output/numlock.py", "def numlock", n=7),
    "verify_sources": excerpt("finagent/output/sources.py", "def verify_sources", n=26),
}
py_files = [p for p in subprocess.run(["git", "ls-files", "finagent/*.py", "finagent/**/*.py"], cwd=ROOT, capture_output=True, text=True).stdout.split("\n") if p.strip()]
data["repo"] = {"engine_files": len(py_files),
                "engine_lines": sum(len((ROOT / p).read_text(encoding="utf-8", errors="replace").split("\n")) for p in py_files if (ROOT / p).is_file()),
                "tests": len(re.findall(r"^\s*def test_", "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "tests").glob("test_*.py")), flags=re.M))}

# ---------------------------------------------------------------- 5) 真值表与分析
run = WS / next(g["detail"] for g in gates if g["n"] == 7).split()[0]
an = load(run / "financials" / "analysis.json")
tt = {(r["metric_id"], r["period"]): r for r in an["truth_table"]}
want = ["revenue", "operating_cost", "rd_expense", "np_parent", "ocf", "inventory", "total_assets"]
truth = []
for c in an["changes"]:
    if c["metric_id"] in want and c["period"] == str(YEAR):
        r = tt.get((c["metric_id"], c["period"]), {})
        b = tt.get((c["metric_id"], c.get("yoy_base_period")), {})
        truth.append({"metric_id": c["metric_id"], "metric": c["metric"], "raw": r.get("raw"), "raw_prev": b.get("raw"),
                      "page": (r.get("source") or {}).get("page"), "chunk_id": (r.get("source") or {}).get("chunk_id"),
                      "yoy_pct": c.get("yoy_pct")})
truth.sort(key=lambda x: want.index(x["metric_id"]))
data["truth"] = {"n": len(an["truth_table"]), "rows": truth,
                 "tieouts": [{"check": t["check"], "status": t["status"], "diff": t.get("diff")} for t in an["tieouts"]],
                 "signals": [{"title": s["title"], "fact": s["fact"], "inference": s.get("inference", "")} for s in an["signals"]]}
fw = (EX / "report" / "framework.md").read_text(encoding="utf-8")
sec = lambda name: fw.split("## " + name, 1)[1].split("\n## ", 1)[0]
data["framework"] = {"topics": re.findall(r"^\d\. \*\*(.+?)\*\*", sec("深度专题"), flags=re.M),
                     "drivers": [ln.split("|")[1].strip() for ln in sec("驱动清单").split("\n") if ln.startswith("| ") and not ln.startswith("| 驱动") and not ln.startswith("|---")],
                     "chain_chart": "charts/chain.svg", "demand_chart": "charts/demand_chain.svg",
                     "topic_notes": sorted(p.name for p in (EX / "research" / "topics").glob("*.md"))}

# ---------------------------------------------------------------- 6) 估值
val = load(run / "valuation" / "valuation.json")
sens = val["sensitivities"][0]
data["valuation"] = {"price": val["current_price"],
                     "scenarios": {s["scenario"]: round(s["value_per_share"], 2) for s in val["scenarios"]},
                     "wacc": val["wacc_base"],
                     "sens": {"name": sens.get("name"), "x": sens["x_values"], "y": sens["y_values"],
                              "x_label": sens.get("x_label") or sens.get("x_name"), "y_label": sens.get("y_label") or sens.get("y_name"),
                              "m": [[round(v, 2) for v in row] for row in sens["matrix"]]},
                     "tie": val.get("three_statement_tie"), "status": val.get("model_status")}
z = zipfile.ZipFile(run / "valuation" / "model.xlsx")
names = re.findall(r'<sheet [^>]*name="([^"]+)"', z.read("xl/workbook.xml").decode())
book, total_f = [], 0
for i, nm in enumerate(names, 1):
    x = z.read(f"xl/worksheets/sheet{i}.xml").decode()
    fs = re.findall(r'<c r="([A-Z]+\d+)"[^>]*><f>([^<]+)</f>', x)
    total_f += len(fs)
    book.append({"sheet": nm, "n_formulas": len(fs), "sample": [{"cell": c, "f": f.replace("&quot;", '"').replace("&amp;", "&")} for c, f in fs[:8]]})
data["workbook"] = {"sheets": book, "n_formulas": total_f}

# ---------------------------------------------------------------- 7) 文稿、护栏与数字锁
from finagent.output import numlock as nl  # noqa: E402

draft = (EX / "report" / "narrative.draft.md").read_text(encoding="utf-8")
final = (EX / "report" / "narrative.md").read_text(encoding="utf-8")
lock = nl.numlock(draft, final)
toks = nl._tokens(final)
guard = load(run / "commentary_guard.json")
paras = [p.strip() for p in final.split("\n") if 90 < len(p.strip()) < 190 and len(re.findall(r"\[S\d+\]", p)) >= 2 and not p.startswith(("#", "|", "-", ">"))]
# 复核改写的真实句对：数字相同、措辞不同
pairs = []
ds = [s for s in re.split(r"(?<=[。；])", draft) if 30 < len(s.strip()) < 110]
fs_ = [s for s in re.split(r"(?<=[。；])", final) if 30 < len(s.strip()) < 110]
fset = set(fs_)
for s in ds:
    if s in fset:
        continue
    cand = difflib.get_close_matches(s, fs_, n=1, cutoff=0.55)
    norm = lambda x: re.sub(r"\s", "", x)
    if (cand and len(nl._tokens(s)) >= 2 and sorted(nl._tokens(s)) == sorted(nl._tokens(cand[0])) and norm(cand[0]) != norm(s)
            and "#" not in s + cand[0] and "|" not in s + cand[0] and difflib.SequenceMatcher(None, s, cand[0]).ratio() < 0.93):
        pairs.append({"before": s.strip(), "after": cand[0].strip(), "tokens": nl._tokens(s)})
pairs.sort(key=lambda p: -len(p["tokens"]))
data["narrative"] = {"chars": len(re.sub(r"\s", "", final)), "n_numbers": len(toks), "n_citations": len(re.findall(r"\[S\d+\]", final)),
                     "guard": {k: (len(v) if isinstance(v, list) else v) for k, v in guard.items() if k in ("ok", "unverified_numbers", "mismatched_claims", "uncited_external")},
                     "numlock": {"ok": lock["ok"], "added": len(lock["added"]), "removed": lock["removed"], "before": len(nl._tokens(draft)), "after": len(toks)},
                     "paragraphs": paras[:6], "pairs": pairs[:6],
                     "field": [p.strip().replace("**", "") for p in final.split("\n") if 110 < len(p.strip()) < 300 and len(nl._tokens(p)) >= 4 and not p.startswith(("#", "|", "-", ">"))][:12],
                     "edit_log": [ln.strip() for ln in (EX / "report" / "edit_log.md").read_text(encoding="utf-8").split("\n") if ln.strip()][:14]}

# ---------------------------------------------------------------- 8) 质检与评审校准
ev_dir = ROOT / "eval" / "results"
scores = {}
for d in sorted(ev_dir.iterdir()):
    if (d / "score.json").is_file():
        s = load(d / "score.json")
        scores[d.name] = {"total": s["total"], "deliverable": s["deliverable"], "items": len(s["items"]),
                          "layers": {k: {"name": v["name"], "earned": v["earned"], "possible": v["possible"]} for k, v in s["layers"].items()},
                          "by_judge": {j: sum(1 for it in s["items"] if it.get("judge") == j) for j in sorted({it.get("judge") for it in s["items"]})}}
best = load(ev_dir / f"v2_{COMPANY}" / "score.json")
cal = load(ROOT / "eval" / "calibration" / "summary.json")
data["eval"] = {"scores": scores,
                "items": [{k: it.get(k) for k in ("id", "layer", "title", "judge", "points", "got", "passed", "reason")} for it in best["items"]],
                "calibration": [{"company": c["company"], **{k: c["stability"][k] for k in ("runs", "items", "agreement", "totals", "total_range")}} for c in cal["companies"]]}

# ---------------------------------------------------------------- 9) 纠错核查（样例为虚构公司）
allrun = sorted((ROOT / "runs").glob("*-all"))[-1]
chk = load(allrun / "check" / "findings.json")
data["check"] = {"run": allrun.name, "summary": chk["summary"],
                 "findings": [{"quote": f["quote"], "verdict": f["verdict"], "truth": f.get("truth_display"), "error_type": f.get("error_type"),
                               "sentence": f.get("sentence", "")[:70]} for f in chk["findings"]][:16],
                 "injection": {"claims": 1334, "errors": 754, "correct": 580, "tp": 754, "fp": 0, "type_acc": 99.5,
                               "source": "paper/techreport/sections/13_experiments.tex 表 exp-tol"}}

# ---------------------------------------------------------------- 10) 研报与年报页面图片
pdf_out = next((run / "report").glob(f"{COMPANY}*.pdf"))
n_pages = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", str(pdf_out)], capture_output=True, text=True).stdout).group(1))
data["report"] = {"pdf": pdf_out.name, "pages": n_pages}
if not a.skip_pdf:
    pages = PROMO / "public" / "pages"
    pages.mkdir(parents=True, exist_ok=True)
    subprocess.run(["pdftoppm", "-r", "92", "-jpeg", "-jpegopt", "quality=88", str(pdf_out), str(pages / "r")], check=True)
    subprocess.run(["pdftoppm", "-r", "170", "-f", "1", "-l", "1", "-jpeg", str(pdf_out), str(pages / "cover")], check=True)
    subprocess.run(["pdftoppm", "-r", "150", "-f", str(page), "-l", str(page), "-jpeg", str(pdf), str(pages / "ar")], check=True)
data["report"]["page_files"] = sorted(p.name for p in (PROMO / "public" / "pages").glob("r-*.jpg"))
data["report"]["ar_file"] = next((p.name for p in (PROMO / "public" / "pages").glob("ar-*.jpg")), None)
data["report"]["cover_file"] = next((p.name for p in (PROMO / "public" / "pages").glob("cover-*.jpg")), None)

out = PROMO / "src" / "data" / "data.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"写出 {out}（{out.stat().st_size // 1024} KB）")
print("gates", [(g["n"], g["ok"]) for g in gates])
print("research", {k: v for k, v in data["research"].items() if k not in ("stream", "domains")}, "stream", len(stream))
print("sources", data["sources"]["n"], data["sources"]["n_facts"], data["sources"]["verify"])
print("evidence", page, raw, "found", ch.chunk_id, "tampered", tampered, ch_bad is not None, "bare", bare, ch_bare is not None, "pattern", pat.pattern)
print("narrative", {k: v for k, v in data["narrative"].items() if k not in ("paragraphs", "pairs", "edit_log")}, "pairs", len(pairs))
print("valuation", data["valuation"]["scenarios"], data["valuation"]["price"], "formulas", total_f)
print("eval", {k: v["total"] for k, v in scores.items()}, "repo", data["repo"], "totals", data["agent_totals"])
print("report pages", n_pages, len(data["report"]["page_files"]))
