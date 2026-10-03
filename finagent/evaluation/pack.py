"""质检查看包：把研报 PDF、评分标准与各份打分结果整理进一个文件夹，入口 index.html（单文件、离线可看）。

  python -m finagent.evaluation pack --result eval/results/v0_贵州茅台 --result ... --out eval/review_pack/v0

文件夹结构：
  index.html            总览：对比矩阵、评分标准、逐家逐条的判定、理由与证据
  reports/<公司>.pdf     被评的研报
  rubric.json           评分标准（含分值）
  results/<公司>/        score.json、checks.json、judgments.json、scorecard.md
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from .rubric import load_rubric

LAYER_NOTE = {"L0": "程序判定，不计分；任一失败总分封顶", "L1": "程序判定", "L2": "评审模型判定",
              "L3": "评审模型判定", "N": "评审模型判定；命中扣分"}

CSS = """
:root{--bg:#f7f6f3;--surface:#fff;--fg:#1f1d1b;--muted:#6d6862;--line:#e4dfd8;--accent:#a3242b;
--ok:#2d6a3e;--okbg:#e6f1e8;--bad:#a3242b;--badbg:#f7e4e3;--na:#8a8178;
--sans:"PingFang SC","Microsoft YaHei","Noto Sans SC",system-ui,sans-serif;--mono:ui-monospace,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#161413;--surface:#1f1c1a;--fg:#ebe6e0;
--muted:#a39b92;--line:#3a3431;--accent:#e2747a;--ok:#86c99a;--okbg:#20322a;--bad:#e8868a;--badbg:#3b2224;--na:#8f877e;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#161413;--surface:#1f1c1a;--fg:#ebe6e0;--muted:#a39b92;--line:#3a3431;--accent:#e2747a;
--ok:#86c99a;--okbg:#20322a;--bad:#e8868a;--badbg:#3b2224;--na:#8f877e;color-scheme:dark}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.7 var(--sans);padding:24px 16px 64px}
main{max-width:1080px;margin:0 auto;display:flex;flex-direction:column;gap:36px}
h1{font-size:26px;margin:0}h2{font-size:20px;margin:0 0 4px;border-top:3px solid var(--accent);padding-top:12px}
h3{font-size:16px;margin:16px 0 6px}p{margin:0;max-width:75ch}.muted{color:var(--muted)}
nav{display:flex;flex-wrap:wrap;gap:8px}nav a{color:var(--accent);text-decoration:none;border:1px solid var(--line);
padding:2px 10px;border-radius:999px;background:var(--surface)}nav a:hover{border-color:var(--accent)}
.tbl{overflow-x:auto;border:1px solid var(--line);border-radius:6px;background:var(--surface)}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums;font-size:13px}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
th{background:var(--bg);color:var(--muted);font-weight:600;white-space:nowrap}tr:last-child td{border-bottom:0}
td.c{text-align:center}td.n{text-align:right;white-space:nowrap}
.pill{display:inline-block;min-width:3.2em;text-align:center;border-radius:4px;padding:0 6px;font-size:12px;font-weight:600}
.ok{background:var(--okbg);color:var(--ok)}.bad{background:var(--badbg);color:var(--bad)}.na{color:var(--na)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:12px 14px;display:flex;flex-direction:column;gap:4px}
.card .big{font-size:30px;font-weight:700;line-height:1.2}.card a{color:var(--accent)}
.item{border:1px solid var(--line);border-radius:6px;background:var(--surface);padding:10px 12px;display:grid;
grid-template-columns:auto 1fr;gap:4px 12px}.item+.item{margin-top:8px}.item .head{font-weight:600}
.item .body{grid-column:2;display:flex;flex-direction:column;gap:4px;min-width:0}
.ev{font-size:12.5px;color:var(--muted);border-left:3px solid var(--line);padding-left:8px;word-break:break-word}
details{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:8px 12px}
summary{cursor:pointer;font-weight:600}code{font-family:var(--mono);font-size:12px}
.filter{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
body.only-fail .item.pass{display:none}
"""


def _pill(passed: bool, negative: bool) -> str:
    if negative:
        return '<span class="pill bad">命中</span>' if passed else '<span class="pill na">未命中</span>'
    return '<span class="pill ok">通过</span>' if passed else '<span class="pill bad">未过</span>'


def _anchor(company: str) -> str:
    return "c-" + "".join(f"{ord(ch):x}" for ch in company)


def build_pack(results: list[Path], out: Path, rubric_path: str | Path | None = None, title: str = "研报质检") -> Path:
    rubric = load_rubric(rubric_path)
    if out.exists():
        shutil.rmtree(out)
    (out / "reports").mkdir(parents=True)
    (out / "results").mkdir()
    (out / "rubric.json").write_text(json.dumps(rubric, ensure_ascii=False, indent=2), encoding="utf-8")

    entries: list[dict[str, Any]] = []
    for d in results:
        bundle = json.loads((d / "bundle.json").read_text(encoding="utf-8"))
        company = bundle["company"]
        sc = json.loads((d / "score.json").read_text(encoding="utf-8"))
        dest = out / "results" / company
        dest.mkdir()
        for name in ("score.json", "checks.json", "judgments.json", "scorecard.md", "issues.md", "judge_run.json"):
            if (d / name).is_file():
                shutil.copy2(d / name, dest / name)
        pdf = None
        if bundle.get("pdf") and Path(bundle["pdf"]).is_file():
            pdf = f"reports/{company}.pdf"
            shutil.copy2(bundle["pdf"], out / pdf)
        run = json.loads((d / "judge_run.json").read_text(encoding="utf-8")) if (d / "judge_run.json").is_file() else {}
        entries.append({"company": company, "score": sc, "pdf": pdf, "evaluated_at": bundle.get("evaluated_at", ""),
                        "judge_model": run.get("model", "—")})

    (out / "index.html").write_text(_html(rubric, entries, title), encoding="utf-8")
    return out / "index.html"


def _html(rubric: dict[str, Any], entries: list[dict[str, Any]], title: str) -> str:
    items = rubric["items"]
    nav = "".join(f'<a href="#{_anchor(e["company"])}">{escape(e["company"])}</a>' for e in entries)
    nav += '<a href="#rubric">评分标准</a>'

    cards = []
    for e in entries:
        sc = e["score"]
        lay = sc["layers"]
        cards.append(
            f'<div class="card"><span class="muted">{escape(e["company"])}</span><span class="big">{sc["total"]:g}</span>'
            f'<span>{"达到交付标准" if sc["deliverable"] else "未达交付标准"}</span>'
            f'<span class="muted">L1 {lay["L1"]["earned"]:g}/{lay["L1"]["possible"]:g} · L2 {lay["L2"]["earned"]:g}/'
            f'{lay["L2"]["possible"]:g} · L3 {lay["L3"]["earned"]:g}/{lay["L3"]["possible"]:g} · 扣分 {sc["deduction"]:g}</span>'
            + (f'<a href="{e["pdf"]}">打开研报 PDF</a>' if e["pdf"] else "") + "</div>")

    head = "".join(f"<th>{escape(e['company'])}</th>" for e in entries)
    rows = [f'<tr><td><b>总分</b></td><td></td>' + "".join(f'<td class="c"><b>{e["score"]["total"]:g}</b></td>' for e in entries) + "</tr>"]
    by_id = [{r["id"]: r for r in e["score"]["items"]} for e in entries]
    for it in items:
        cells = "".join(f'<td class="c">{_pill(m[it["id"]]["passed"], it["layer"] == "N")}</td>' if it["id"] in m
                        else '<td class="c na">—</td>' for m in by_id)
        rows.append(f'<tr><td><a href="#r-{it["id"]}">{it["id"]}</a> {escape(it["title"])}</td>'
                    f'<td class="n">{it["points"]:g}</td>{cells}</tr>')
    matrix = f'<div class="tbl"><table><tr><th>条目</th><th>分值</th>{head}</tr>{"".join(rows)}</table></div>'

    sections = []
    for e, m in zip(entries, by_id):
        sc = e["score"]
        blocks = []
        for layer in ("L0", "L1", "L2", "L3", "N"):
            sub = [it for it in items if it["layer"] == layer]
            body = []
            for it in sub:
                r = m.get(it["id"], {})
                passed = r.get("passed", False)
                neg = layer == "N"
                good = (not passed) if neg else passed
                ev = f'<div class="ev">证据：{escape(r["evidence"])}</div>' if r.get("evidence") else ""
                body.append(f'<div class="item {"pass" if good else "fail"}">{_pill(passed, neg)}'
                            f'<span class="head">{it["id"]} {escape(it["title"])} <span class="muted">（{it["points"]:g} 分，'
                            f'{"程序" if it["judge"] == "program" else "评审"}）</span></span>'
                            f'<div class="body"><span>{escape(r.get("reason", "") or "—")}</span>{ev}</div></div>')
            blocks.append(f"<h3>{layer} {escape(rubric['layers'][layer])} <span class='muted'>· "
                          f"{escape(LAYER_NOTE[layer])}</span></h3>{''.join(body)}")
        reasons = "；".join(sc["not_deliverable_reasons"]) or "—"
        summary = (f'<p><b>评审总评：</b>{escape(sc.get("judge_summary", ""))}</p>' if sc.get("judge_summary") else "")
        sections.append(
            f'<section id="{_anchor(e["company"])}"><h2>{escape(e["company"])} · {sc["total"]:g} 分</h2>'
            f'<p class="muted">评测时间 {escape(e["evaluated_at"])} · 评审模型 {escape(e["judge_model"])}'
            + (f' · <a href="{e["pdf"]}">研报 PDF</a>' if e["pdf"] else "") + f'</p><p>未达标原因：{escape(reasons)}</p>'
            f'{summary}{"".join(blocks)}</section>')

    rub_rows = []
    for it in items:
        fe = "；".join(it.get("fail_examples", []))
        extra = f"<br><span class='muted'>阈值：{escape(json.dumps(it['params'], ensure_ascii=False))}</span>" if it.get("params") else ""
        rub_rows.append(f'<tr id="r-{it["id"]}"><td>{it["id"]}</td><td>{escape(it["title"])}</td><td class="n">{it["points"]:g}'
                        + (f'<br><span class="muted">封顶 {it["cap"]}</span>' if it.get("cap") is not None else "")
                        + f'</td><td>{"程序" if it["judge"] == "program" else "评审"}</td>'
                        f'<td>{escape(it["criterion"])}{extra}' + (f"<br><span class='muted'>反例：{escape(fe)}</span>" if fe else "")
                        + "</td></tr>")
    d = rubric.get("delivery", {})
    rules = (f"硬闸门任一失败总分封顶 {rubric['gate_cap']}；负向条目合计最多扣 {-rubric['negative_floor']} 分；"
             f"交付标准：总分 ≥ {d.get('total')}，"
             + "，".join(f"{k} 得分率 ≥ {v:.0%}" for k, v in d.get("layer_ratio", {}).items())
             + ("，不得命中负向条目" if not d.get("allow_negative") else "") + "。")
    rubric_html = (f'<section id="rubric"><h2>评分标准 {escape(rubric["version"])}</h2><p>{escape(rules)}</p>'
                   f'<div class="tbl"><table><tr><th>id</th><th>条目</th><th>分值</th><th>判定</th><th>判定标准</th></tr>'
                   f'{"".join(rub_rows)}</table></div></section>')

    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(title)}</title><style>{CSS}</style></head>
<body><main>
<header style="display:flex;flex-direction:column;gap:8px"><h1>{escape(title)}</h1>
<p class="muted">评分标准 {escape(rubric["version"])} · {len(entries)} 份研报 · 生成于 {datetime.now():%Y-%m-%d %H:%M}。
L0/L1 由程序读运行产物判定；L2/L3/负向条目由评审模型在只含交付物的目录里盲评，拿不准判不通过。</p>
<nav>{nav}</nav>
<label class="filter"><input type="checkbox" id="onlyfail" onchange="document.body.classList.toggle('only-fail',this.checked)"> 明细只看未过 / 命中的条目</label>
</header>
<section><h2>总览</h2><div class="cards">{"".join(cards)}</div></section>
<section><h2>逐条对比</h2><p class="muted">点条目 id 跳到评分标准。</p>{matrix}</section>
{"".join(sections)}
{rubric_html}
</main></body></html>
"""
