import React, {useSyncExternalStore} from 'react';
import {ShotContext, FilmClock} from './film-store.js';
import {shots} from './engine.js';
import {SHOT_VIEWS} from './shots/index.js';
import {Hud} from './hud.jsx';
import {Poster} from './shots/hook.jsx';
// 镜头之间一律硬切：明（纸面）与暗（会话）不做交叉淡化。
function ShotSection({s, i, children}) {
  const on = useSyncExternalStore(FilmClock.subscribe, () => { const t = FilmClock.get(); return t >= s.start && t < s.end; }, () => false);
  return <section data-shot={s.id} className={'shot tone-' + s.tone + ' shot-' + s.id} style={{zIndex: i + 1, opacity: on ? 1 : 0}}>{children}</section>;
}
export function Film() {
  return <main id="film">
    {shots.map((s, i) => {
      const View = SHOT_VIEWS[s.id];
      if (!View) throw new Error(`No view for shot "${s.id}" in src/shots/index.js`);
      return <ShotSection key={s.id} s={s} i={i}><ShotContext.Provider value={s}><View shot={s} /></ShotContext.Provider></ShotSection>;
    })}
    <Hud />
    <Poster />
  </main>;
}
