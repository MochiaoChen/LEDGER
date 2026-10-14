import React from 'react';
import data from '../data/data.json';
import {useLocal, p, rise, fade, act, ease, typedLen} from '../kit/time.js';
import {Title, GateLine} from '../kit/ui.jsx';
// 10 主笔写稿与数字护栏：左边是 narrative.md 的两段原文（真实内容），右边把每个外部数字对到它的来源编号。
const NUM = /(\d[\d,]*(?:\.\d+)?\s?(?:%|亿元|万元|万颗|亿元以上)?)/;
const cut = (s, mark) => (s.includes(mark) ? s.slice(0, s.indexOf(mark) + mark.length) : s);
const PARAS = [data.narrative.field[2], cut(data.narrative.field[6], '[S28]。')].map(par => par.split(/(\[S\d+\])/).flatMap(seg => /^\[S\d+\]$/.test(seg) ? [{c: seg.slice(1, -1)}] : seg.split(NUM).filter(Boolean).map(s => (/^\d/.test(s) && /\d{2}|%/.test(s) && !/^20\d\d\s?$/.test(s) ? {n: s.trim(), pad: s.endsWith(' ') ? ' ' : ''} : {t: s}))));
// 每个数字对到它后面第一个来源编号；记录它在全文里的字符位置，用来对齐出现时间
const SEGS = []; let pos = 0; const BIND = [];
PARAS.forEach((par, k) => { let pending = []; par.forEach(s => { const text = s.t ?? (s.n ? s.n + s.pad : `[${s.c}]`); const len = Array.from(text).length; SEGS.push({...s, k, start: pos, len}); pos += len; if (s.n) pending.push(s.n); if (s.c && pending.length) { pending.forEach(n => BIND.push({n, sid: s.c, at: pos})); pending = []; } }); pos += 8; });
const TOTAL = pos, IDX = data.sources.index;
export function WriteView() {
  const l = useLocal(), A = {ty: act('write-type'), guard: act('write-guard'), gate: act('gate-8')};
  const CPS = TOTAL / 7.6, n = l < A.ty ? 0 : Math.floor((l - A.ty) * CPS);
  const rows = BIND.filter(b => n >= b.at), G = data.narrative.guard;
  const Z = [[G.unverified_numbers, '无出处数字'], [G.mismatched_claims, '指标期间不符'], [G.uncited_external, '外部数字缺引用']];
  return <>
    <Title l={l} at={0.1} mode="type" x={96} y={96} w={1700} en="Every number cited" zh="主笔写稿，护栏逐个数字查出处" zhSize={56} />
    <div className="term" style={{left: 96, top: 292, width: 1014, height: 636}}>
      <div className="bar"><span className="dots"><i /><i /><i /></span><span>report/narrative.md</span><span style={{marginLeft: 'auto', color: 'var(--faint)'}}>主笔 · claude-opus-5-5</span></div>
      <div className="body wr-doc">{[0, 1].map(k => <p key={k}>{SEGS.filter(s => s.k === k).map((s, i) => { const take = Math.max(0, Math.min(s.len, n - s.start)); if (!take) return null;
        if (s.c) return take >= s.len ? <span key={i} className="c">{s.c}</span> : null;
        if (s.n) return <span key={i} className="n">{Array.from(s.n + s.pad).slice(0, take).join('')}</span>;
        return <span key={i}>{Array.from(s.t).slice(0, take).join('')}</span>; })}{n > 0 && n < TOTAL && SEGS.filter(s => s.k === k).some(s => n >= s.start) && !(k === 0 && SEGS.some(s => s.k === 1 && n >= s.start)) && <i className="caret" />}</p>)}</div>
    </div>
    <div className="wr-g">
      <div className="h" style={fade(l, 1.0, 0.4)}><span>GUARD · 外部数字 → 来源编号</span><span>{rows.length} / {BIND.length}</span></div>
      {rows.slice(-5).map(b => { const at = A.ty + b.at / CPS, src = IDX[b.sid] || {};
        return <div className="wr-row" key={b.n + b.sid + b.at} style={{opacity: p(l, at, 0.25, ease.out2)}}><span className="v">{b.n}</span><span className="s">{b.sid}</span><span className="pb">{src.publisher} · {src.published}</span><span className="ok">✓</span></div>; })}
    </div>
    <div className="wr-z">{Z.map(([v, k], i) => { const at = A.guard + i * 0.6; return <div key={k} style={{opacity: l >= at ? 1 : 0}}><div className="v" style={{color: 'var(--ok-d)', transform: `scale(${1.5 - 0.5 * p(l, at, 0.2, ease.out)})`, transformOrigin: 'left bottom'}}>{v}</div><div className="k">{k}</div></div>; })}</div>
    <div className="abs" style={{left: 1150, top: 862, width: 674, fontSize: 27, lineHeight: 1.5, color: 'var(--dim)', ...rise(l, A.guard + 2.2, 0.6, 14)}}>全文 {data.narrative.numlock.before} 个数字：要么来自真值表，要么带来源编号。</div>
    <GateLine l={l} at={A.gate} gate={data.gates[7]} x={96} y={944} />
  </>;
}
