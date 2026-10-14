// 时间工具：本片的视图都是镜头内时间 l 的纯函数，缓动取自 GSAP。
import gsap from 'gsap';
import {useContext} from 'react';
import {ShotContext, useShotState} from '../film-store.js';
import plan from '../../plan.json';

export const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
export const lerp = (a, b, u) => a + (b - a) * u;
const E = n => gsap.parseEase(n);
export const ease = {expo: E('expo.out'), out: E('power3.out'), out2: E('power2.out'), io: E('power2.inOut'), io3: E('power3.inOut'), inn: E('power2.in'), lin: x => x};
/** 0→1 的进度：从 at 开始、持续 dur。 */
export const p = (l, at, dur = 0.6, e = ease.expo) => e(clamp((l - at) / dur));
export const rise = (l, at, dur = 0.6, dy = 30) => { const u = p(l, at, dur); return {opacity: u, transform: `translateY(${((1 - u) * dy).toFixed(2)}px)`}; };
export const slide = (l, at, dur = 0.6, dx = 40) => { const u = p(l, at, dur); return {opacity: u, transform: `translateX(${((1 - u) * dx).toFixed(2)}px)`}; };
export const fade = (l, at, dur = 0.4) => ({opacity: p(l, at, dur, ease.out2)});
/** 盖章：放大落下，0.2 秒到位，不回弹。 */
export const stamp = (l, at, rot = 0) => { const u = p(l, at, 0.2, ease.out); return {opacity: l >= at ? Math.min(1, u * 2.4) : 0, transform: `rotate(${rot}deg) scale(${(1.9 - 0.9 * u).toFixed(3)})`}; };
export const typed = (text, l, at, cps) => { const cs = Array.from(text); if (l < at) return ''; return cs.slice(0, Math.min(cs.length, Math.floor((l - at) * cps) + 1)).join(''); };
export const typedLen = (n, l, at, cps) => (l < at ? 0 : Math.min(n, Math.floor((l - at) * cps) + 1));
export const count = (l, at, dur, to, from = 0, e = ease.out) => from + (to - from) * p(l, at, dur, e);
export const fmt = (n, d = 0) => Number(n).toLocaleString('en-US', {minimumFractionDigits: d, maximumFractionDigits: d});
export const mmss = s => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
/** 确定性伪随机（0..1），用于错落的入场顺序。 */
export const rnd = i => { const s = Math.sin(i * 127.1 + 311.7) * 43758.5453; return s - Math.floor(s); };

export const shotOf = id => plan.shots.find(s => s.id === id);
/** 动作在镜头内的时间：plan.json 是唯一来源。 */
export const act = id => { for (const s of plan.shots) { const a = s.actions.find(x => x.id === id); if (a) return a.at; } throw new Error('unknown action ' + id); };
export const actAbs = id => { for (const s of plan.shots) { const a = s.actions.find(x => x.id === id); if (a) return s.start + a.at; } throw new Error('unknown action ' + id); };

/** 镜头内时间（按帧量化）；离开镜头后停在边界，不再触发重渲染。 */
export function useLocal() {
  const {start, end} = useContext(ShotContext);
  const len = end - start;
  return useShotState(l => (l < -0.1 ? -0.1 : l > len + 0.1 ? len + 0.1 : Math.round(l * plan.fps) / plan.fps));
}
