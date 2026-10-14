import React from 'react';
import {createRoot} from 'react-dom/client';
import {flushSync} from 'react-dom';
import {Film} from './film.jsx';
import {seek, frame, master} from './engine.js';
import {SHOT_BUILDERS} from './shots/index.js';

const root = createRoot(document.getElementById('film-root'));
flushSync(() => root.render(<Film />));
window.seek = seek;
window.__master = master;
window.__filmReady = (async () => {
  await Promise.all(['500 30px "Noto Sans SC"', '700 30px "Noto Sans SC"', '900 30px "Noto Sans SC"', '400 30px "Maple Mono"', '500 30px "Maple Mono"', '700 30px "Maple Mono"'].map(f => document.fonts.load(f, '账A1')));
  await document.fonts.ready;
  await Promise.all([...document.images].map(i => i.decode().catch(() => {})));
  await frame(); await frame();
  for (const build of Object.values(SHOT_BUILDERS)) { const r = build(master); if (r instanceof Promise) await r; }
  await seek(0);
})();
let t0 = null, req = null;
window.playFilm = (from = 0) => { cancelAnimationFrame(req); t0 = null; const loop = async now => { t0 ??= now; await seek(from + (now - t0) / 1000); req = requestAnimationFrame(loop); }; req = requestAnimationFrame(loop); };
window.stopFilm = () => cancelAnimationFrame(req);
