import React from 'react';
import data from '../data/data.json';
import {useLocal, p, rise, fade, act, ease, typedLen, count} from '../kit/time.js';
import {Title, GateLine} from '../kit/ui.jsx';
// 08 真值表：账页。原文数字照抄入账，同比一列由程序计算（analysis.json 的 yoy_pct），出处写到页码与原文块。
const ROWS = data.truth.rows, T = data.truth.tieouts;
const pass = T.filter(t => t.status === 'pass').length;
const tail = (s, n) => Array.from(s).slice(Math.max(0, Array.from(s).length - n)).join('');
export function TruthView() {
  const l = useLocal(), A = {rows: act('truth-rows'), yoy: act('truth-yoy'), sig: act('truth-signal'), gate: act('gate-2')};
  const SIG = data.truth.signals[0];
  const STATS = [[data.facts.n, '条事实入账'], [data.facts.stats.rejected, '条被拒收'], [data.facts.check.conflicts, '处冲突'], [`${pass}/${T.length}`, '项勾稽通过']];
  return <>
    <div className="ledger-v red" style={{left: 62, transform: `scaleY(${p(l, 0, 0.9, ease.io3)})`}} />
    <div className="ledger-v red" style={{left: 70, transform: `scaleY(${p(l, 0.1, 0.9, ease.io3)})`}} />
    <Title l={l} at={0.1} mode="wipe" x={96} y={84} w={1500} en="One truth table" zh="一张真值表，下游只认它" zhSize={58} />
    <div className="tr-table">
      <div className="tr-row head" style={fade(l, 0.5, 0.4)}><span className="tr-c0" style={{fontSize: 23, fontWeight: 700}}>指标</span><span className="tr-c1" style={{fontSize: 23, fontWeight: 700}}>2025 年 · 元</span><span className="tr-c2" style={{fontSize: 23, fontWeight: 700}}>2024 年 · 元</span><span className="tr-c3" style={{fontSize: 23, color: 'var(--prog)'}}>同比 · 程序计算</span><span className="tr-c4" style={{fontSize: 23, color: 'var(--mute)'}}>出处</span><i className="ln" style={{transform: `scaleX(${p(l, 0.4, 0.9, ease.io3)})`}} /></div>
      {ROWS.map((r, i) => { const at = A.rows + i * 0.48, n1 = typedLen(r.raw.length, l, at + 0.1, 46), n2 = typedLen(r.raw_prev.length, l, at + 0.3, 46), yAt = A.yoy + i * 0.3;
        return <div className="tr-row" key={r.metric_id} style={{background: i % 2 ? 'transparent' : 'rgba(201,194,178,.16)'}}>
          <span className="tr-c0" style={fade(l, at, 0.3)}>{r.metric}</span>
          <span className="tr-c1">{tail(r.raw, n1)}</span><span className="tr-c2">{tail(r.raw_prev, n2)}</span>
          <span className="tr-c3" style={{opacity: l >= yAt ? 1 : 0}}>{l >= yAt ? '+' + count(l, yAt, 0.5, r.yoy_pct).toFixed(2) + '%' : ''}</span>
          <span className="tr-c4" style={fade(l, at + 0.5, 0.3)}>p.{r.page} · {r.chunk_id}</span>
          <i className="ln" style={{transform: `scaleX(${p(l, at, 0.7, ease.io3)})`}} />
        </div>; })}
    </div>
    <div className="tr-stats">{STATS.map(([v, k], i) => <div className="tr-stat" key={k} style={rise(l, 4.5 + i * 0.25, 0.5, 18)}><span className="v" style={{color: i ? 'var(--ok)' : 'var(--ink)'}}>{v}</span><span className="k">{k}</span></div>)}</div>
    <div className="abs" style={{left: 1010, top: 118, width: 814, fontSize: 27, lineHeight: 1.5, color: 'var(--mute)', ...rise(l, 1.6, 0.6, 14)}}>估值和纠错都从这张表取数；同比由程序计算，不经过模型。</div>
    <div className="tr-sig" style={{opacity: l >= A.sig ? 1 : 0}}>
      <div style={rise(l, A.sig, 0.4, 14)}><b className="tg" style={{background: 'var(--ink)'}}>事实</b><span>{SIG.fact}</span></div>
      <div style={rise(l, A.sig + 0.9, 0.4, 14)}><b className="tg" style={{background: 'var(--agent)'}}>推论</b><span>{SIG.inference}</span><em>异常信号 · {SIG.title}</em></div>
    </div>
    <GateLine l={l} at={A.gate} gate={data.gates[1]} x={96} y={944} tone="paper" />
  </>;
}
