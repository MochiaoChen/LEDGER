import React from 'react';
import data from '../data/data.json';
import {useLocal, p, rise, fade, slide, act, ease, lerp, clamp} from '../kit/time.js';
// 03 设计规范第 1 条：左暗（模型会话）右明（确定性引擎），中间一道闸门。原文数字过闸入账，心算约数被挡回。
const L = [['读 PDF', 'read'], ['抄数字', 'transcribe'], ['搜资料', 'search'], ['写文稿', 'write'], ['做判断', 'judge']];
const R = [['定位', 'locate'], ['校验', 'verify'], ['计算', 'compute'], ['护栏', 'guard'], ['数字锁', 'numlock']];
export function RuleView() {
  const l = useLocal(), A = {sp: act('rule-split'), pass: act('rule-pass'), rej: act('rule-reject')};
  const open = p(l, A.sp - 0.9, 0.9, ease.io3);
  // 过闸的数字：从左侧滑到闸门，过闸瞬间换成纸面墨色
  const u1 = p(l, A.pass - 1.3, 1.25, ease.io), v1 = p(l, A.pass, 0.7, ease.expo), passed = l >= A.pass;
  const x1 = passed ? lerp(1010, 1056, v1) : lerp(96, 420, u1);
  // 被挡回的约数：撞上闸门后弹回并划掉
  const u2 = p(l, A.rej - 1.3, 1.3, ease.inn), back = p(l, A.rej, 0.5, ease.expo), hit = l >= A.rej;
  const x2 = hit ? lerp(536, 470, back) : lerp(96, 536, u2);
  const shake = hit ? Math.sin((l - A.rej) * 60) * 8 * Math.max(0, 1 - (l - A.rej) / 0.3) : 0;
  return <>
    <div className="rule-dark" style={{transform: `scaleX(${open})`}} />
    <div className="rule-gate" style={{transform: `scaleY(${p(l, A.sp - 0.5, 0.8, ease.io3)})`}} />
    <div className="rule-band" style={{opacity: l >= A.sp ? 1 : 0, clipPath: `inset(0 ${(1 - p(l, A.sp, 0.6, ease.io3)) * 50}% 0 ${(1 - p(l, A.sp, 0.6, ease.io3)) * 50}%)`}}>
      <span className="zh">模型不做算术</span><span className="en">MODELS READ. CODE COMPUTES.</span>
    </div>
    <div className="rule-col" style={{left: 96, color: 'var(--fg)'}}>
      <div className="h-en" style={{color: 'var(--agent-d)', ...fade(l, 1.9, 0.4)}}>MODEL SESSIONS</div>
      <div className="h-zh" style={rise(l, 2.0, 0.6)}>模型会话</div>
      <ul>{L.map(([zh, en], i) => <li key={en} style={slide(l, 2.6 + i * 0.3, 0.5, -30)}>{zh}<span style={{color: 'var(--dim)'}}>{en}</span></li>)}</ul>
    </div>
    <div className="rule-col" style={{left: 1056, color: 'var(--ink)'}}>
      <div className="h-en" style={{color: 'var(--prog)', ...fade(l, 3.1, 0.4)}}>DETERMINISTIC ENGINE</div>
      <div className="h-zh" style={rise(l, 3.2, 0.6)}>确定性引擎</div>
      <ul>{R.map(([zh, en], i) => <li key={en} style={slide(l, 3.8 + i * 0.3, 0.5, 30)}>{zh}<span style={{color: 'var(--mute)'}}>{en}</span></li>)}</ul>
    </div>
    {l >= A.pass - 1.3 && <div className="rule-tok" style={{transform: `translate(${x1.toFixed(1)}px, 756px)`, background: passed ? 'transparent' : 'rgba(235,165,92,.14)', border: passed ? '2px solid var(--ink)' : '2px solid var(--agent-d)', color: passed ? 'var(--ink)' : 'var(--agent-d)', opacity: clamp((l - (A.pass - 1.3)) / 0.2)}}>
      {data.evidence.raw}<small style={{color: passed ? 'var(--ok)' : 'var(--dim)'}}>{passed ? `✓ 第 ${data.evidence.page} 页原文命中` : '模型抄下'}</small>
    </div>}
    {l >= A.rej - 1.3 && <div className="rule-tok" style={{transform: `translate(${(x2 + shake).toFixed(1)}px, 756px)`, background: hit ? 'rgba(240,117,107,.12)' : 'rgba(235,165,92,.14)', border: `2px solid ${hit ? 'var(--bad-d)' : 'var(--agent-d)'}`, color: hit ? 'var(--bad-d)' : 'var(--agent-d)', opacity: clamp((l - (A.rej - 1.3)) / 0.2), fontFamily: 'var(--zh)', zIndex: 8}}>
      <span style={{textDecoration: hit ? 'line-through' : 'none', textDecorationThickness: 4}}>“约三倍”</span><small style={{color: hit ? 'var(--bad-d)' : 'var(--dim)'}}>{hit ? '✗ 心算，拒收' : '模型心算'}</small>
    </div>}
    <div className="rule-desc" style={rise(l, 5.6, 0.6, 16)}>模型抄下的数要过校验才能入账；连“约三倍”这样的约数，也不许心算。</div>
    <div className="rule-code" style={fade(l, A.rej + 0.7, 0.4)}>ratio = cur / prev   <span style={{color: 'var(--mute)'}}># 倍数由程序算</span></div>
  </>;
}
