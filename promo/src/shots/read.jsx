import React from 'react';
import data from '../data/data.json';
import {useLocal, p, rise, fade, count, act, ease, lerp, typedLen} from '../kit/time.js';
import {Title} from '../kit/ui.jsx';
// 06 读年报抄数：左边是年报第 94 页原图，右边是模型写下的 facts.json（真实内容）。
const IMG_W = 1240, IMG_H = Math.round(1240 / data.evidence.page_aspect), VW = 900, VH = 612;
const B = data.evidence.boxes;
const FACTS = [data.facts.sample.find(f => f.metric_id === 'revenue'), {...data.facts.sample.find(f => f.metric_id === 'revenue'), period: '2024', raw_value: '23,862,159,738.37'}, data.facts.sample.find(f => f.metric_id === 'operating_cost')];
const BOXES = [B[2], B[3], B[4]];   // 其中：营业收入 2025 / 2024，营业成本 2025
const fit = VH / IMG_H, zoom = 1.2;
const cam = (s, cx, cy) => ({s, x: VW / 2 - cx * IMG_W * s, y: VH / 2 - cy * IMG_H * s});
const C0 = {s: fit, x: (VW - IMG_W * fit) / 2, y: 0}, C1 = cam(zoom, 0.385, 0.6), C2 = cam(zoom, 0.385, 0.655);
const lines = f => [
  [['', '{'], ['key', '"metric_id"'], ['', ': '], ['s', `"${f.metric_id}"`], ['', ', '], ['key', '"period"'], ['', ': '], ['s', `"${f.period}"`], ['', ',']],
  [['', ' '], ['key', '"raw_value"'], ['', ': '], ['num', `"${f.raw_value}"`], ['', ', '], ['key', '"unit"'], ['', ': '], ['s', `"${f.unit}"`], ['', ',']],
  [['', ' '], ['key', '"page"'], ['', ': '], ['pg', String(f.page)], ['', ', '], ['key', '"table"'], ['', ': '], ['s', `"${f.table}"`], ['', '},']],
];
const LINES = FACTS.flatMap(lines), LEN = LINES.map(ln => ln.reduce((n, [, s]) => n + Array.from(s).length, 0));
export function ReadView() {
  const l = useLocal(), A = {scan: act('read-scan'), ty: act('read-type'), cnt: act('read-count')};
  const u = p(l, 0.9, A.scan - 0.9, ease.io3), v = p(l, A.ty + 4.2, 1.2, ease.io3);
  const c = {s: lerp(lerp(C0.s, C1.s, u), C2.s, v), x: lerp(lerp(C0.x, C1.x, u), C2.x, v), y: lerp(lerp(C0.y, C1.y, u), C2.y, v)};
  const boxAt = [A.scan, A.ty + 2.4, A.ty + 5.0];
  const scanY = lerp(-10, VH + 10, p(l, 0.3, A.scan - 0.3, ease.io));
  const tyAt = [A.ty, A.ty + 2.6, A.ty + 5.2];
  return <>
    <Title l={l} at={0.15} mode="rise" x={96} y={96} w={1700} en="Read and transcribe" zh="分析师读年报，只抄数，不计算" zhSize={56} />
    <div className="rd-view">
      <img src={'pages/' + data.report.ar_file} width={IMG_W} height={IMG_H} alt="" style={{transform: `translate(${c.x.toFixed(2)}px, ${c.y.toFixed(2)}px) scale(${c.s.toFixed(4)})`}} />
      {BOXES.map((b, i) => l >= boxAt[i] && <div key={i} className="rd-box" style={{left: c.x + b.x0 * IMG_W * c.s - 8, top: c.y + b.y0 * IMG_H * c.s - 6, width: (b.x1 - b.x0) * IMG_W * c.s + 16, height: (b.y1 - b.y0) * IMG_H * c.s + 12, opacity: p(l, boxAt[i], 0.25, ease.out2)}} />)}
      {l < A.scan && <div className="rd-scan" style={{top: scanY}} />}
    </div>
    <div className="rd-tag" style={fade(l, 0.8, 0.4)}>{data.evidence.pdf_name} · 第 {data.evidence.page} / {data.evidence.n_pages} 页 · 合并利润表</div>
    <div className="term" style={{left: 1040, top: 292, width: 784, height: 520}}>
      <div className="bar"><span className="dots"><i /><i /><i /></span><span>data/extractions/{data.company}_{data.year}/facts.json</span></div>
      <div className="body rd-json">
        {LINES.map((ln, i) => { const at = tyAt[Math.floor(i / 3)] + (i % 3) * 0.75; let n = typedLen(LEN[i], l, at, 62); if (l < at) return <div key={i}> </div>;
          return <div key={i} style={{marginBottom: i % 3 === 2 ? 14 : 0}}>{ln.map(([c, s], j) => { const a = Array.from(s), t = a.slice(0, Math.max(0, n)).join(''); n -= a.length; return <span key={j} className={c}>{t}</span>; })}{l < at + LEN[i] / 62 && <i className="caret" />}</div>; })}
      </div>
    </div>
    <div className="rd-cnt" style={rise(l, A.cnt, 0.5, 20)}><span className="v">{Math.round(count(l, A.cnt, 1.2, data.facts.n))}</span><span className="k">条事实，每一条都带原文页码</span></div>
    <div className="abs" style={{left: 1040, top: 936, fontSize: 28, color: 'var(--dim)', whiteSpace: 'nowrap', ...rise(l, 3.4, 0.6, 14)}}>指标、期间、原文数字、页码，一个字符都不改。</div>
  </>;
}
