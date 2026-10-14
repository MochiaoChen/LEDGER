import React from 'react';
import data from '../data/data.json';
import TUI from '../data/tui.json';
import {useLocal, p, rise, fade, act, ease, lerp} from '../kit/time.js';
import {Title} from '../kit/ui.jsx';
// 15 终端界面：画面是 finagent_tui（Textual）无头运行后导出的原始 SVG（tools/tui_shot.py），只做了取景与平移。
const VW = 1728, VH = 712;
const HTML = Object.fromEntries(Object.entries(TUI).map(([k, v]) => [k, {__html: v.svg}]));
const T = data.agent_totals;
export function TraceView() {
  const l = useLocal(), A = {open: act('trace-open'), t1: act('trace-tab'), t2: act('trace-tab2')};
  const tab = l >= A.t2 ? 'agents' : l >= A.t1 ? 'trace' : 'facts', t0 = tab === 'agents' ? A.t2 : tab === 'trace' ? A.t1 : A.open;
  const s = VW / TUI[tab].w, H = TUI[tab].h * s, pan = tab === 'agents' ? lerp(0, -(H - VH) * 0.3, p(l, t0 + 0.6, 3.4, ease.io)) : lerp(0, -(H - VH) * (tab === 'facts' ? 1 : 0.6), p(l, t0 + (tab === 'facts' ? 1.2 : 0.6), 3.4, ease.io));
  const flash = 1 - p(l, t0, 0.35, ease.out2);
  return <>
    <Title l={l} at={0.1} mode="wipe" x={96} y={84} w={880} en="Trace everything" zh="全程留痕，在终端里随时回看" zhSize={52} />
    <div className="tc-side" style={rise(l, 0.9, 0.6, 14)}>文件哈希、工具调用、会话事件流都有记录，评审可以原样复现。</div>
    <div className="tc-chips" style={fade(l, 1.8, 0.5)}><span><b>{T.sessions}</b>次会话（含返工）</span><span><b>{Math.round(T.elapsed_min)}</b>分钟</span><span><b>{T.turns}</b>轮</span></div>
    <div className="tc-view" style={{opacity: p(l, A.open, 0.35, ease.out2), transform: `translateY(${(1 - p(l, A.open, 0.6)) * 50}px)`}}>
      <div className="svgw" style={{width: TUI[tab].w, transform: `translateY(${pan.toFixed(1)}px) scale(${s.toFixed(5)})`}} dangerouslySetInnerHTML={HTML[tab]} />
      <div className="abs" style={{inset: 0, background: '#fff', opacity: flash * 0.16, pointerEvents: 'none'}} />
    </div>
  </>;
}
