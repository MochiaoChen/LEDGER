import React from 'react';
import data from '../data/data.json';
import {useLocal, p, rise, fade, act, ease, typed} from '../kit/time.js';
import {Title} from '../kit/ui.jsx';
import {tokenize, take} from '../kit/py.js';
// 07 源码出现并真实运行：左栏是调用与结果，右上是 external.py 的原文（真实行号），右下是第 94 页的原文块。
// 三次调用的结果都由 tools/gen_data.py 调用引擎的 find_evidence 得到，不是手写的。
const E = data.evidence, PAT = data.code.pattern, FE = data.code.find_evidence;
const patLines = PAT.text.split('\n'), feLines = FE.text.split('\n');
const LINES = [
  ...patLines.slice(-2).map((t, i) => ({no: PAT.line + patLines.length - 2 + i, t, k: 'p' + i})),
  {no: '', t: '', k: 'gap'},
  ...feLines.map((t, i) => ({no: FE.line + i, t, k: 'f' + i})),
].map(x => ({...x, tok: tokenize(x.t), len: Array.from(x.t).length}));
const TOTAL = LINES.reduce((n, x) => n + x.len + 2, 0);
const A = {ty: act('code-type'), run: act('code-run'), hit: act('code-hit'), tam: act('code-tamper'), rej: act('code-reject')};
const CPS = TOTAL / 9.3, R3 = A.rej + 2.6;
const firstRow = E.rows.find(r => r.includes(E.raw)).split('|').map(s => s.trim()).filter(Boolean);
const CH = E.on_page;
const pat2 = E.pattern.replace('38239935640', E.tampered.replace(/,/g, '').split('.')[0]);
export function CodeView() {
  const l = useLocal();
  let budget = l < A.ty ? 0 : Math.floor((l - A.ty) * CPS);
  const run = l >= A.tam ? 2 : l >= A.run ? 1 : 0, r0 = run === 2 ? A.tam : A.run, d = l - r0;
  // 执行指针：哪一行在跑（amber），哪一行返回（绿 / 红）
  const ptr = {};
  if (run === 1) {
    if (d >= 0.4 && d < 1.2) { ptr.f2 = 'a'; ptr.p1 = 'a'; }
    if (d >= 1.2 && d < 1.8) ptr.f5 = 'a';
    if (d >= 1.8 && l < A.hit) { ptr.f6 = 'a'; ptr.f7 = 'a'; }
    if (l >= A.hit) ptr.f8 = 'g';
  } else if (run === 2) {
    if (d >= 0.3 && d < 0.8) { ptr.f2 = 'a'; ptr.p1 = 'a'; }
    if (d >= 0.8 && l < A.rej) { ptr.f6 = 'a'; ptr.f7 = 'a'; }
    if (l >= A.rej && l < R3 + 0.6) ptr.f9 = 'r';
    if (l >= R3 + 0.6) { ptr.p1 = 'r'; ptr.p0 = 'r'; }
  }
  const HL = {a: 'rgba(235,165,92,.16)', g: 'rgba(103,196,143,.22)', r: 'rgba(240,117,107,.2)'};
  // 第 94 页原文块的状态
  const st = i => {
    if (run === 1) { const t = [1.8, 2.6][i]; if (i === 2) return 'idle'; if (i === 0) return d < t ? 'idle' : d < 2.5 ? 'scan' : 'miss'; return d < t ? 'idle' : l < A.hit ? 'scan' : 'hit'; }
    if (run === 2) { const t = 0.8 + i * 0.7; return d < t ? 'idle' : d < t + 0.6 ? 'scan' : 'miss'; }
    return 'idle';
  };
  const SC = {idle: ['var(--faint)', ''], scan: ['var(--agent-d)', '匹配中…'], miss: ['var(--bad-d)', '✗ 无命中'], hit: ['var(--ok-d)', '✓ 命中']};
  const panelOn = l >= 10.4, call1 = typed(`find_evidence(doc, page=${E.page},\n    raw="${E.raw}")`, l, A.run, 60), call2 = typed(`find_evidence(doc, page=${E.page},\n    raw="${E.tampered}")`, l, A.tam, 60);
  const numStyle = run === 1 && l >= A.hit ? {background: 'rgba(103,196,143,.25)', color: 'var(--ok-d)', outline: '2px solid var(--ok-d)'} : run === 2 && d >= 1.5 ? {color: 'var(--fg)'} : {color: 'var(--fg)'};
  return <>
    <Title l={l} at={0.15} mode="wipe" x={96} y={96} w={510} en="Verify, do not trust" zh="抄下的每个数，回原文逐字核对" zhSize={52} desc="程序到模型写的那一页，按数字边界查找；找不到就拒收，改一位也不行。" descAt={1.4} />
    <div className="term" style={{left: 634, top: 96, width: 1190, height: 610}}>
      <div className="bar"><span className="dots"><i /><i /><i /></span><span style={{color: 'var(--fg)'}}>{FE.file}</span><span style={{marginLeft: 'auto', color: 'var(--faint)'}}>计算引擎 · 不调用任何模型</span></div>
      <div className="body cd-code">
        {LINES.map(x => { const n = Math.max(0, Math.min(x.len, budget)); budget -= x.len + 2; const typing = n > 0 && n < x.len;
          return <div className="cd-ln" key={x.k}>{ptr[x.k] && <i className="hl" style={{background: HL[ptr[x.k]], borderLeft: `4px solid ${ptr[x.k] === 'a' ? 'var(--agent-d)' : ptr[x.k] === 'g' ? 'var(--ok-d)' : 'var(--bad-d)'}`}} />}
            <span className="no" style={{width: 60, paddingRight: 16, opacity: n > 0 || x.len === 0 ? 1 : 0}}>{x.no}</span>
            <span className="tx">{take(x.tok, n).map(([c, s], j) => <span key={j} className={c}>{s}</span>)}{typing && <i className="caret" />}</span></div>; })}
      </div>
    </div>
    {panelOn && <div className="term" style={{left: 634, top: 722, width: 1190, height: 232, opacity: p(l, 10.4, 0.4, ease.out2), transform: `translateY(${(1 - p(l, 10.4, 0.5)) * 30}px)`}}>
      <div className="body cd-page" style={{top: 0}}>
        <div className="cd-row"><span style={{color: 'var(--dim)', width: 340, fontFamily: 'var(--zh)'}}>第 {E.page} 页原文 · {CH.length} 个块</span><span style={{color: run ? 'var(--vio-d)' : 'var(--faint)'}}>{run ? 'pat = ' + (run === 2 ? pat2 : E.pattern) : '表格块优先'}</span></div>
        {CH.slice(0, 2).map((c, i) => { const s = st(i);
          return <React.Fragment key={c.chunk_id}>
            <div className="cd-row" style={{background: s === 'scan' ? 'rgba(235,165,92,.1)' : 'transparent'}}><span style={{width: 110, color: SC[s][0], fontWeight: 700}}>{c.chunk_id}</span><span style={{width: 110, color: 'var(--dim)'}}>{c.kind}</span><span style={{fontFamily: 'var(--zh)', color: 'var(--dim)'}}>{c.caption}</span><span style={{marginLeft: 'auto', color: SC[s][0], fontWeight: 700}}>{SC[s][1]}</span></div>
            {i === 1 && <div className="cd-row" style={{paddingLeft: 134, opacity: s === 'idle' ? .45 : 1}}><span className="c0" style={{color: 'var(--dim)'}}>{firstRow[0]}</span><span className="c1"><span style={{padding: '3px 8px', borderRadius: 4, ...numStyle}}>{run === 2 && d >= 1.5 ? <>{firstRow[1].split('239')[0]}<b style={{color: 'var(--bad-d)', textDecoration: 'underline'}}>239</b>{firstRow[1].split('239').slice(1).join('239')}</> : firstRow[1]}</span></span><span className="c2" style={{color: 'var(--dim)'}}>{firstRow[2]}</span></div>}
          </React.Fragment>; })}
        <div className="cd-row" style={{background: st(2) === 'scan' ? 'rgba(235,165,92,.1)' : 'transparent'}}><span style={{width: 110, color: SC[st(2)][0], fontWeight: 700}}>{CH[2].chunk_id}</span><span style={{width: 110, color: 'var(--dim)'}}>{CH[2].kind}</span><span style={{fontFamily: 'var(--zh)', color: 'var(--dim)'}}>页眉与正文</span><span style={{marginLeft: 'auto', color: SC[st(2)][0], fontWeight: 700}}>{run === 1 && l >= A.hit ? '已返回，不再查' : SC[st(2)][1]}</span></div>
      </div>
    </div>}
    {l >= A.run && <div className="cd-call" style={{top: 440, borderColor: l >= A.hit ? 'var(--ok-d)' : 'var(--line)', opacity: l >= A.tam ? .55 : 1}}>
      <div className="tag">模型抄的数，原样送检</div>
      <div><span className="k-fn">{call1.split('(')[0]}</span>{call1.includes('(') ? '(' + call1.split('(').slice(1).join('(') : ''}</div>
      {l >= A.hit && <div className="res" style={{color: 'var(--ok-d)', ...rise(l, A.hit, 0.35, 12)}}>→ Chunk {E.found.chunk_id} ({E.found.kind})  ✓ 收下</div>}
    </div>}
    {l >= A.tam && <div className="cd-call" style={{top: 626, borderColor: l >= A.rej ? 'var(--bad-d)' : 'var(--line)', ...rise(l, A.tam, 0.4, 20)}}>
      <div className="tag">演示：把 239 改成 293，只动一位</div>
      <div><span className="k-fn">{call2.split('(')[0]}</span>{call2.includes('(') ? '(' + call2.split('(').slice(1).join('(') : ''}</div>
      {l >= A.rej && <div style={rise(l, A.rej, 0.35, 12)}><div className="res" style={{color: 'var(--bad-d)'}}>→ None  ✗ 拒收</div><div className="why" style={{color: 'var(--bad-d)'}}>{E.reject_msg}</div></div>}
    </div>}
    {l >= R3 && <div className="abs" style={{left: 96, top: 868, width: 510, fontSize: 24, lineHeight: 1.45, color: 'var(--dim)', ...rise(l, R3, 0.4, 14)}}>
      只给整数部分 <span className="mono" style={{color: 'var(--fg)'}}>{E.bare}</span> 也是 <span className="mono" style={{color: 'var(--bad-d)', fontWeight: 700}}>None</span>：右边界不许再跟小数。
    </div>}
  </>;
}
