import React from 'react';
import data from '../data/data.json';
import {useLocal, p, rise, fade, count, fmt, act, ease, clamp, lerp, mmss} from '../kit/time.js';
import {Title, GateLine} from '../kit/ui.jsx';
// 05 Agent 运行时在检索：画面里的每一行都来自研究助理会话的真实 stream-json 记录
// （.pipeline/agents/*-claude-research.jsonl），只压缩了时间。来源卡片与核对结果来自 sources.json 与 verify_sources。
const EV = data.research.stream, FIRST = EV.findIndex(e => e.kind === 'search');
const A = {first: act('search-first'), card: act('search-card'), ver: act('search-verify'), gate: act('gate-1')};
// 显示时刻：前三条检索放慢到能读清，之后加速，整体在来源卡片出现前播完
const AT = (() => {
  const gap = EV.map((e, i) => (i < FIRST ? 0.14 : lerp(0.62, 0.11, clamp((i - FIRST) / 9))));
  const tail = gap.slice(FIRST + 1).reduce((a, b) => a + b, 0), k = (A.card - 1.4 - A.first) / tail;
  const at = []; let t = A.first - FIRST * 0.14;
  EV.forEach((e, i) => { if (i === FIRST) t = A.first; else if (i > FIRST) t += gap[i] * k; else if (i > 0) t += 0.14; at.push(t); });
  return at;
})();
const COL = {search: 'var(--agent-d)', fetch: 'var(--prog-d)', read: 'var(--vio-d)', write: 'var(--ok-d)', edit: 'var(--ok-d)', bash: 'var(--dim)'};
const NAME = {search: 'WebSearch', fetch: 'WebFetch', read: 'Read', write: 'Write', edit: 'Edit', bash: 'Bash'};
const arg = e => e.kind === 'search' ? e.query : e.kind === 'fetch' ? e.domain + e.path : e.kind === 'bash' ? e.command : e.kind === 'say' ? e.text : e.path + (e.pages ? `  pages ${e.pages}` : '');
const ROWS = 12, RH = 48;
const S1 = data.sources.items[0], Q = S1.facts[0].quote;
const VAL = [S1.facts[0], S1.facts[1]];
const markQuote = (l) => {
  const parts = Q.split(/(417\.78|182\.49)/);
  return parts.map((s, i) => { const k = s === '417.78' ? 0 : s === '182.49' ? 1 : -1; if (k < 0) return s; const on = l >= A.ver + k * 0.6; return <mark key={i} style={{background: on ? 'rgba(103,196,143,.25)' : 'rgba(235,165,92,.18)', color: on ? 'var(--ok-d)' : 'var(--agent-d)', fontFamily: 'var(--en)', fontWeight: 700}}>{s}</mark>; });
};
export function SearchView() {
  const l = useLocal();
  const kf = EV.reduce((a, _, i) => a + p(l, AT[i], 0.16, ease.out2), 0), shown = EV.filter((_, i) => l >= AT[i]);
  const nS = shown.filter(e => e.kind === 'search').length, nF = shown.filter(e => e.kind === 'fetch').length;
  const cur = shown.length ? shown[shown.length - 1] : null, lastSearch = [...shown].reverse().find(e => e.kind === 'search');
  const off = Math.max(0, kf - ROWS) * RH;
  const cardOn = l >= A.card - 0.5, dim = 1 - 0.74 * p(l, A.card - 0.5, 0.5, ease.out2), side = 1 - p(l, A.card - 0.5, 0.4, ease.out2);
  const tilesAt = A.ver + 2.6, cardOut = p(l, tilesAt - 0.4, 0.35, ease.out2);
  return <>
    <Title l={l} at={0.15} mode="type" x={96} y={96} w={1700} en="Agent runtime: search" zh="研究助理先上网搜集资料" zhSize={56} />
    <div style={{opacity: dim}}>
      <div className="term" style={{left: 96, top: 292, width: 1090, height: 632}}>
        <div className="bar"><span className="dots"><i /><i /><i /></span><span>research · {data.research.model} · claude code {data.research.claude_code_version}</span><span style={{marginLeft: 'auto', color: 'var(--faint)'}}>stream-json</span></div>
        <div className="body sr-body"><div style={{position: 'absolute', left: 0, right: 0, top: 2, transform: `translateY(${-off.toFixed(1)}px)`}}>
          {EV.map((e, i) => { if (l < AT[i] || i < kf - ROWS - 2) return null; const u = p(l, AT[i], 0.2, ease.out2);
            return <div key={i} className={'sr-line' + (e.kind === 'say' ? ' say' : '')} style={{top: i * RH, opacity: u}}>
              <span className="ts">+{mmss(e.t || 0)}</span>
              {e.kind === 'say' ? <span className="bar-say" /> : <span className="tool" style={{color: COL[e.kind]}}>{NAME[e.kind]}</span>}
              <span className="arg" style={{color: e.kind === 'say' ? 'var(--agent-d)' : e.kind === 'search' ? 'var(--fg)' : 'var(--dim)'}}>{arg(e)}</span>
            </div>; })}
        </div></div>
      </div>
      <div style={{opacity: side}}>
      <div className="sr-cnt" style={{left: 1226, top: 300, ...fade(l, A.first - 0.4, 0.4)}}><div className="v" style={{color: 'var(--agent-d)'}}>{nS}</div><div className="k">次检索<b>WebSearch</b></div></div>
      <div className="sr-cnt" style={{left: 1530, top: 300, ...fade(l, A.first - 0.2, 0.4)}}><div className="v" style={{color: 'var(--prog-d)'}}>{nF}</div><div className="k">次抓取<b>WebFetch</b></div></div>
      <div className="abs mono nowrap" style={{left: 1226, top: 482, fontSize: 24, color: 'var(--dim)', ...fade(l, A.first, 0.4)}}>会话时钟 +{mmss(cur ? cur.t || 0 : 0)}<span style={{color: 'var(--faint)'}}>  / {mmss(data.research.elapsed_sec)}</span></div>
      {lastSearch && <div className="sr-hits">
        <div className="h">SEARCH RESULTS · {lastSearch.n_hits}</div>
        {lastSearch.hits.slice(0, 5).map((h, i) => <div className="sr-hit" key={i}><div className="t">{h.title}</div><div className="d">{h.domain}</div></div>)}
      </div>}
      </div>
    </div>
    {cardOn && <div className="sr-card" style={{height: 548, opacity: p(l, A.card, 0.3, ease.out2), transform: `translateY(${(1 - p(l, A.card, 0.5)) * 40}px)`}}>
      {l < tilesAt && <div style={{opacity: 1 - p(l, tilesAt - 0.35, 0.3, ease.out2)}}>
        <div className="hd"><span className="sid">{S1.id}</span><span>{S1.publisher}</span><span>·</span><span>{S1.published}</span><span style={{marginLeft: 'auto'}}>research/sources.json</span></div>
        <div className="ti">{S1.title}</div>
        <div className="q" style={fade(l, A.card + 0.7, 0.4)}>摘句　“{markQuote(l)}”</div>
        {VAL.map((f, k) => <div className="sr-reg" key={k} style={fade(l, A.card + 1.3 + k * 0.3, 0.3)}>
          <span className="lab">登记数字</span><span className="val" style={{color: l >= A.ver + k * 0.6 ? 'var(--ok-d)' : 'var(--agent-d)'}}>{f.value} {f.unit}</span><span className="what">{f.label}</span>
          <span className="ok" style={{opacity: l >= A.ver + k * 0.6 ? 1 : 0, transform: `scale(${1.5 - 0.5 * p(l, A.ver + k * 0.6, 0.2, ease.out)})`, display: 'inline-block'}}>✓ 摘句里有这个数</span>
        </div>)}
        <div className="abs mono nowrap" style={{left: 40, bottom: 34, fontSize: 23, color: 'var(--faint)', ...fade(l, A.ver + 1.2, 0.4)}}>finagent verify-sources · 摘句必须包含所登记的数字</div>
      </div>}
      {l >= tilesAt && <>
        <div className="sr-tiles">{Array.from({length: data.sources.n}, (_, i) => { const on = l >= tilesAt + i * 0.03; return <i key={i} style={{borderColor: on ? 'var(--ok-d)' : undefined, color: on ? 'var(--ok-d)' : undefined, background: on ? 'rgba(103,196,143,.08)' : 'transparent'}}>S{i + 1}</i>; })}</div>
        <div className="sr-sum">
          <div style={rise(l, tilesAt + 0.3, 0.5)}><div className="v">{Math.round(count(l, tilesAt + 0.3, 1.4, data.sources.n))}</div><div className="k">个来源登记入库</div></div>
          <div style={rise(l, tilesAt + 0.6, 0.5)}><div className="v">{Math.round(count(l, tilesAt + 0.6, 1.4, data.sources.n_facts))}</div><div className="k">条带数字的摘句</div></div>
          <div style={rise(l, tilesAt + 0.9, 0.5)}><div className="v" style={{color: 'var(--ok-d)'}}>{data.sources.verify.problems}</div><div className="k">条对不上原文</div></div>
        </div>
        <div className="abs" style={{left: 40, right: 40, bottom: 34, fontSize: 30, lineHeight: 1.5, color: 'var(--dim)', ...rise(l, tilesAt + 1.6, 0.6, 14)}}>外部数字必须带出处编号；摘句里找不到所登记的数字，程序就拒收。</div>
      </>}
    </div>}
    <GateLine l={l} at={A.gate} gate={data.gates[0]} x={96} y={944} />
  </>;
}
