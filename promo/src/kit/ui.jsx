import React from 'react';
import {p, rise, fade, stamp, typed, ease} from './time.js';
/** 标题块。三种入场轮换使用，避免每个镜头同一种出场：type（英文键入）、rise（中文逐字升起）、wipe（遮罩擦出）。 */
export function Title({l, at = 0.2, en, zh, desc, x = 96, y = 96, w = 860, mode = 'rise', cls = '', zhSize, descAt}) {
  const dAt = descAt ?? at + 0.7;
  const enText = mode === 'type' ? typed(en, l, at, 34) : en;
  const zhChars = Array.from(zh);
  return <div className={'ttl ' + cls} style={{left: x, top: y, width: w}}>
    <div className="t-en" style={mode === 'type' ? {opacity: l >= at ? 1 : 0} : fade(l, at, 0.4)}>
      <i style={{transform: `scaleX(${p(l, at, 0.5)})`}} /><span>{enText}</span>
    </div>
    <div className="t-zh" style={zhSize ? {fontSize: zhSize} : null}>
      {mode === 'wipe'
        ? <span style={{display: 'inline-block', clipPath: `inset(0 ${(1 - p(l, at + 0.15, 0.7, ease.io3)) * 100}% 0 0)`}}>{zh}</span>
        : zhChars.map((c, i) => <span key={i} className="u" style={rise(l, at + 0.15 + i * 0.035, 0.55, 26)}>{c}</span>)}
    </div>
    {desc && <div className="t-desc" style={rise(l, dAt, 0.6, 16)}>{desc}</div>}
  </div>;
}
/** 印章：通过闸门、校验通过时盖下。 */
export function Seal({l, at, x, y, size = 150, rot = -6, text = '核', sub}) {
  return <div className="seal" style={{left: x, top: y, width: size, height: size, fontSize: size * 0.6, lineHeight: 1, ...stamp(l, at, rot)}}>
    <span>{text}</span>{sub && <small style={{fontSize: size * 0.105, marginTop: size * 0.04}}>{sub}</small>}
  </div>;
}
/** 闸门盖章提示条：照抄 status 输出的那一行。 */
export function GateLine({l, at, gate, x = 96, y = 900, tone = 'dark', w}) {
  const u = p(l, at, 0.45);
  const dark = tone === 'dark';
  return <div className="abs mono nowrap" style={{left: x, top: y, width: w, fontSize: 27, display: 'flex', alignItems: 'center', gap: 18, opacity: l >= at ? 1 : 0, transform: `translateX(${(1 - u) * -24}px)`}}>
    <span style={{background: 'var(--seal)', color: '#fff', padding: '5px 14px', fontWeight: 700, transform: `scale(${1.5 - 0.5 * p(l, at, 0.2, ease.out)})`, display: 'inline-block'}}>[✓]</span>
    <span style={{fontWeight: 700, color: dark ? 'var(--fg)' : 'var(--ink)'}}>{gate.n} {gate.name}</span>
    <span style={{color: dark ? 'var(--dim)' : 'var(--mute)', clipPath: `inset(0 ${(1 - p(l, at + 0.15, 0.7, ease.out)) * 100}% 0 0)`}}>{gate.detail}</span>
  </div>;
}
