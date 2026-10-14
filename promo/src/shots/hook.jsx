import React, {useSyncExternalStore} from 'react';
import data from '../data/data.json';
import {FilmClock} from '../film-store.js';
import {useLocal, p, rise, fade, count, fmt, act, ease, clamp} from '../kit/time.js';
// 01 开场（数据先行）：背景是系统真实产出的研报正文，数字逐个点亮；计数、提问、回答。
const NUM = /(\d[\d,]*(?:\.\d+)?(?:\s?(?:%|亿元|万元|元\/只|个百分点|美元|万颗|万只|亿美元|元|倍|只))?)/;
let N = 0;
const FIELD = data.narrative.field.map(par => par.split(/(\[S\d+\])/).flatMap(seg => /^\[S\d+\]$/.test(seg) ? [{c: seg}] : seg.split(NUM).filter(Boolean).map(s => (NUM.test(s) && /^\d/.test(s) ? {n: s, i: N++} : {t: s}))));
const A = {count: act('hook-count'), q: act('hook-question'), z: act('hook-zero')};
export function HookInner({l}) {
  const lit = Math.floor(count(l, A.count, 5.6, N, 0, ease.lin)), green = Math.floor(count(l, A.z, 0.8, N, 0, ease.lin));
  const asking = l >= A.q && l < A.z;
  const tok = i => {
    if (i < green) return {color: 'var(--ok-d)'};
    if (i >= lit) return null;
    if (asking) { const w = 0.5 + 0.5 * Math.sin(l * 4.4 + i * 2.1); return {color: w > 0.72 ? 'var(--bad-d)' : 'var(--agent-d)', opacity: 0.55 + 0.45 * w}; }
    return {color: 'var(--agent-d)'};
  };
  const cnt = Math.round(count(l, A.count, 5.6, data.narrative.n_numbers, 0, ease.out2));
  return <>
    <div className="hook-field" style={{transform: `translateY(${(-l * 46).toFixed(1)}px)`}}>
      {FIELD.map((par, k) => <p key={k}>{par.map((s, j) => s.t ? s.t : s.c ? <span key={j} className="n" style={{opacity: .6}}>{s.c}</span> : <span key={j} className="n" style={tok(s.i)}>{s.n}</span>)}</p>)}
    </div>
    <div className="hook-scrim" /><div className="hook-rule" />
    <div style={{opacity: 1 - p(l, A.q - 0.45, 0.3, ease.out2)}}>
      <div className="hook-num" style={fade(l, A.count - 0.5, 0.5)}>{fmt(cnt)}</div>
      <div className="hook-lab">
        <div className="a" style={rise(l, 1.5, 0.6)}>个带单位的数字</div>
        <div className="b" style={rise(l, 2.1, 0.6)}>来自一份系统生成的深度研报 · 正文 {fmt(data.narrative.chars)} 字</div>
      </div>
    </div>
    {l >= A.q - 0.05 && <div className="hook-q" style={{opacity: 1 - p(l, A.z - 0.35, 0.25, ease.out2)}}>
      <div className="en" style={fade(l, A.q, 0.4)}>WHICH ONE DID THE MODEL MAKE UP?</div>
      <div className="zh">{['哪一个，', '是模型编的？'].map((ln, r) => <div key={r}>{Array.from(ln).map((c, i) => <span key={i} className="u" style={rise(l, A.q + 0.1 + (r * 4 + i) * 0.07, 0.5, 44)}>{c}</span>)}</div>)}</div>
    </div>}
    {l >= A.z - 0.05 && <div className="hook-z">
      <div className="zero" style={{opacity: clamp((l - A.z) / 0.1), transform: `scale(${1.5 - 0.5 * p(l, A.z, 0.25, ease.out)})`, transformOrigin: 'left bottom'}}>0</div>
      <div>
        <div className="za" style={rise(l, A.z + 0.25, 0.5)}>个数字没有出处</div>
        <div className="zb" style={rise(l, A.z + 0.6, 0.5)}>这是 LEDGER 给每一份研报设的闸门。</div>
        <div className="zc" style={fade(l, A.z + 1.0, 0.4)}>guard · unverified_numbers = {data.narrative.guard.unverified_numbers} · 中际旭创 2025 研报实测</div>
      </div>
    </div>}
  </>;
}
export function HookView() { const l = useLocal(); return <HookInner l={l} />; }
/** 首帧海报：前 0.3 秒盖一份提问完成态，再用 0.3 秒淡出；底下的开场照常从 0 秒播放。 */
export function Poster() {
  const t = useSyncExternalStore(FilmClock.subscribe, () => { const x = FilmClock.get(); return x >= 0.62 ? 1 : Math.round(x * 60) / 60; }, () => 0);
  if (t >= 0.6) return null;
  return <div id="poster" style={{opacity: 1 - clamp((t - 0.3) / 0.3)}}><HookInner l={10.7} /></div>;
}
