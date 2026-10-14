import React from 'react';
import data from '../data/data.json';
import {useLocal, p, rise, fade, act, ease, count} from '../kit/time.js';
import {Title, GateLine} from '../kit/ui.jsx';
import {tokenize} from '../kit/py.js';
// 11 复核改写与数字锁：改写前后的真实句对（narrative.draft.md → narrative.md），numlock 的原文与真实返回值。
const PAIR = data.narrative.pairs.find(x => x.before.includes('51.50%')) || data.narrative.pairs[0];
const NUMS = PAIR.tokens.map(t => t.replace(/(\d)(%|亿元|倍|万)/, '$1$2'));
// 字符级 LCS：标出被改掉与新写的字
function diff(a, b) { const A = Array.from(a), B = Array.from(b), n = A.length, m = B.length, L = Array.from({length: n + 1}, () => new Int16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const ka = new Array(n).fill(false), kb = new Array(m).fill(false); let i = 0, j = 0;
  while (i < n && j < m) { if (A[i] === B[j]) { ka[i] = kb[j] = true; i++; j++; } else if (L[i + 1][j] >= L[i][j + 1]) i++; else j++; }
  return [A.map((c, k) => [c, ka[k]]), B.map((c, k) => [c, kb[k]])]; }
const [DA, DB] = diff(PAIR.before, PAIR.after);
const numMask = s => { const mask = new Array(Array.from(s).length).fill(false); const re = /\d[\d,.]*%?/g; let m; while ((m = re.exec(s))) for (let k = m.index; k < m.index + m[0].length; k++) mask[k] = true; return mask; };
const MA = numMask(PAIR.before), MB = numMask(PAIR.after);
const CODE = data.code.numlock, LINES = CODE.text.split('\n').map((t, i) => ({no: CODE.line + i, tok: tokenize(t)}));
const NL = data.narrative.numlock;
const Lock = ({on}) => <svg width="20" height="22" viewBox="0 0 20 22" style={{verticalAlign: -2, marginLeft: 5, opacity: on}}><rect x="2" y="9" width="16" height="12" rx="2.5" fill="currentColor" /><path d="M5.5 9V6.5a4.5 4.5 0 0 1 9 0V9" fill="none" stroke="currentColor" strokeWidth="2.4" /></svg>;
function Sent({chars, mask, l, at, lockAt, kind}) {
  const out = []; let run = null;
  chars.forEach(([c, keep], i) => { if (mask[i]) { if (!run) { run = []; out.push(run); } run.push(c); } else { run = null; out.push([c, keep, i]); } });
  return out.map((x, i) => Array.isArray(x[0]) || typeof x[0] !== 'string' ? null : null) && out.map((x, i) => {
    if (x.length && typeof x[1] !== 'boolean') { const u = p(l, lockAt, 0.3, ease.out); return <span key={i} className="num" style={{color: u > 0 ? 'var(--ok-d)' : 'var(--agent-d)', background: `rgba(103,196,143,${0.16 * u})`, outline: u > 0 ? '2px solid rgba(103,196,143,.8)' : 'none'}}>{x.join('')}<Lock on={u} /></span>; }
    const [c, keep, idx] = x; const u = p(l, at + idx * 0.012, 0.3, ease.out2);
    return <span key={i} style={keep ? null : kind === 'del' ? {color: 'var(--bad-d)', textDecoration: u > 0.5 ? 'line-through' : 'none', opacity: 1 - 0.35 * u} : {color: 'var(--vio-d)', opacity: u}}>{c}</span>; });
}
export function ReviewView() {
  const l = useLocal(), A = {rw: act('review-rewrite'), lock: act('review-lock'), gate: act('gate-9')};
  return <>
    <Title l={l} at={0.1} mode="wipe" x={96} y={96} w={1700} en="Numbers locked" zh="复核编辑只改措辞，数字被锁住" zhSize={56} />
    <div className="rv-s" style={{top: 286, ...fade(l, 0.5, 0.4)}}><div className="lb"><span>改写前 · narrative.draft.md</span><span>主笔 · claude-opus-5-5</span></div><div className="tx"><Sent chars={DA} mask={MA} l={l} at={A.rw} lockAt={A.lock} kind="del" /></div></div>
    <div className="rv-s" style={{top: 432, borderColor: 'rgba(183,156,242,.5)', ...rise(l, A.rw, 0.5, 24)}}><div className="lb"><span style={{color: 'var(--vio-d)'}}>改写后 · narrative.md</span><span>复核编辑 · claude-sonnet-5-5</span></div><div className="tx"><Sent chars={DB} mask={MB} l={l} at={A.rw + 0.3} lockAt={A.lock + 0.3} kind="add" /></div></div>
    <div className="term" style={{left: 96, top: 596, width: 1262, height: 330, ...rise(l, A.lock + 1.0, 0.5, 24)}}>
      <div className="bar"><span className="dots"><i /><i /><i /></span><span style={{color: 'var(--fg)'}}>{CODE.file}</span><span style={{marginLeft: 'auto', color: 'var(--faint)'}}>数字锁</span></div>
      <div className="body rv-code">{LINES.map((x, i) => <div className="cd-ln" key={i} style={{height: 38, opacity: p(l, A.lock + 1.2 + i * 0.1, 0.3, ease.out2)}}><span className="no" style={{width: 56, paddingRight: 14}}>{x.no}</span><span className="tx">{x.tok.map(([c, s], j) => <span key={j} className={c}>{s}</span>)}</span></div>)}</div>
    </div>
    <div className="rv-res">
      <div className="big" style={rise(l, A.lock + 2.0, 0.5, 18)}><span style={{color: 'var(--dim)'}}>{NL.before}</span> → <span style={{color: 'var(--ok-d)'}}>{Math.round(count(l, A.lock + 2.2, 1.0, NL.after, NL.before))}</span></div>
      <div className="k" style={fade(l, A.lock + 2.2, 0.4)}>个数字：只许删，不许新增或改动</div>
      <div className="js" style={fade(l, A.lock + 3.2, 0.4)}>{'{'}<span style={{color: 'var(--prog-d)'}}>"ok"</span>: <span style={{color: 'var(--ok-d)', fontWeight: 700}}>true</span>, <span style={{color: 'var(--prog-d)'}}>"added"</span>: <span style={{color: 'var(--ok-d)', fontWeight: 700}}>{NL.added}</span>,{'\n '}<span style={{color: 'var(--prog-d)'}}>"new_sources"</span>: <span style={{color: 'var(--ok-d)', fontWeight: 700}}>0</span>,{'\n '}<span style={{color: 'var(--prog-d)'}}>"removed"</span>: <span style={{color: 'var(--agent-d)', fontWeight: 700}}>{NL.removed}</span>{'}'}</div>
      <div className="k" style={{marginTop: 18, whiteSpace: 'normal', lineHeight: 1.5, ...rise(l, A.lock + 4.2, 0.5, 14)}}>改写稿里出现任何新数字或新来源编号，都会被拒绝。</div>
    </div>
    <GateLine l={l} at={A.gate} gate={data.gates[8]} x={96} y={944} />
  </>;
}
