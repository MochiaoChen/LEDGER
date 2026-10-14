import React, {useSyncExternalStore} from 'react';
import {FilmClock} from './film-store.js';
import plan from '../plan.json';
import data from './data/data.json';
import {actAbs, p, ease, shotOf} from './kit/time.js';
// 常驻层：左上字标、右上镜头编号、底部 11 道闸门刻度。因为流水线的 status 输出就是 11 行 [✓]，
// 所以用它代替章节字卡和进度条：剧情走到哪一道闸门，哪一格盖章。
const GATE_AT = data.gates.map(g => actAbs('gate-' + g.n));
const STRIP_FROM = actAbs('cmd-gates'), STRIP_TO = shotOf('end').start;
const WM_FROM = shotOf('rule').start, WM_TO = shotOf('end').start;
export function Hud() {
  const t = useSyncExternalStore(FilmClock.subscribe, () => Math.round(FilmClock.get() * plan.fps) / plan.fps, () => 0);
  const i = plan.shots.findIndex(s => t >= s.start && t < s.end), s = plan.shots[Math.max(0, i)];
  const strip = t >= STRIP_FROM && t < STRIP_TO, wm = t >= WM_FROM && t < WM_TO;
  return <div id="hud" className={'h-' + s.tone}>
    {wm && <div className="wm"><b />LEDGER</div>}
    {wm && <div className="ch">{String(i + 1).padStart(2, '0')} / {plan.shots.length}</div>}
    {strip && <div className="gates">
      {data.gates.map((g, k) => {
        const at = GATE_AT[k], lit = t >= at, u = p(t, at, 0.22, ease.out);
        const enter = p(t, STRIP_FROM + k * 0.05, 0.4);
        return <div key={g.n} className={'gate' + (lit ? ' lit' : '')} style={{opacity: enter, transform: `translateY(${(1 - enter) * 16}px)`}}>
          {lit && <i className="fill" style={{transform: `scale(${1.5 - 0.5 * u})`, opacity: Math.min(1, u * 2)}} />}
          <em>{lit ? '✓' : g.n}</em><span>{g.name}</span>
        </div>;
      })}
    </div>}
  </div>;
}
