import React from 'react';
import data from '../data/data.json';
import {useLocal, p, rise, fade, act, ease, count, fmt} from '../kit/time.js';
import {Title} from '../kit/ui.jsx';
// 14 研报纠错核查：样例研报草稿（虚构公司，仓库 data/samples）与 findings.json 的真实判定；注入实验数字取自技术报告表 exp-tol。
const F = data.check.findings;
const SENT = []; F.forEach(f => { let s = SENT.find(x => x.text === f.sentence); if (!s) { s = {text: f.sentence, q: []}; SENT.push(s); } s.q.push(f); });
const SHOW = SENT.slice(0, 5); let QI = 0;
const PARTS = SHOW.map(s => { let rest = s.text; const out = []; s.q.forEach(f => { const k = rest.indexOf(f.quote); if (k < 0) return; if (k > 0) out.push({t: rest.slice(0, k)}); out.push({f, i: QI++}); rest = rest.slice(k + f.quote.length); }); if (rest) out.push({t: rest}); return out; });
const BAD = PARTS.flat().filter(x => x.f && x.f.verdict !== '正确');
const INJ = data.check.injection, SUM = data.check.summary;
export function CheckView() {
  const l = useLocal(), A = {ul: act('check-underline'), vd: act('check-verdict'), st: act('check-stats')};
  const swap = p(l, A.st - 0.4, 0.4, ease.out2);
  return <>
    <Title l={l} at={0.1} mode="rise" x={96} y={84} w={1700} en="Check their numbers too" zh="别人的研报，也逐条核对" zhSize={58} />
    <div className="ck-doc" style={fade(l, 0.5, 0.5)}>
      <div className="lb"><span>研报草稿 · research_draft.md</span><span>样例为虚构公司</span></div>
      {PARTS.map((par, k) => <p key={k}>{par.map((x, j) => { if (x.t) return <span key={j}>{x.t}</span>;
        const ok = x.f.verdict === '正确', at = A.ul + x.i * 0.2, vAt = A.vd + x.i * 0.16, col = ok ? 'var(--ok)' : 'var(--seal)';
        return <span className="ck-q" key={j} style={{color: l >= vAt && !ok ? 'var(--seal)' : undefined, fontWeight: l >= vAt && !ok ? 700 : 500}}>{x.f.quote}
          <u style={{background: l >= vAt ? col : 'var(--gold)', transform: `scaleX(${p(l, at, 0.35, ease.out)})`}} />
          {l >= vAt && <span className="ck-v" style={{color: col, opacity: p(l, vAt, 0.2, ease.out2)}}>{ok ? '✓' : '✗ ' + x.f.verdict}</span>}</span>; })}</p>)}
    </div>
    <div className="ck-r" style={{opacity: (1 - swap) * p(l, A.vd + 0.6, 0.4, ease.out2)}}>
      <div className="h">FINDINGS · {SUM.claims} 条断言 · {SUM.errors} 处错误 · {SUM.unverifiable} 条无法核实</div>
      {BAD.slice(0, 6).map((x, i) => <div className="ck-f" key={i} style={rise(l, A.vd + 0.8 + i * 0.22, 0.4, 12)}><span className="q">{x.f.quote}</span><span className="t">{x.f.verdict}</span><span style={{color: 'var(--mute)'}}>真值</span><span className="tv">{x.f.truth}</span></div>)}
    </div>
    {l >= A.st - 0.4 && <div className="ck-big" style={{opacity: swap}}>
      <div className="h" style={{fontFamily: 'var(--en)', fontSize: 22, letterSpacing: '.08em', color: 'var(--mute)', borderBottom: '3px solid var(--ink)', paddingBottom: 10, whiteSpace: 'nowrap'}}>注入实验 · 四张真实财报真值表</div>
      <div className="row" style={rise(l, A.st, 0.4, 14)}><span className="v">{fmt(Math.round(count(l, A.st, 1.0, INJ.claims)))}</span><span className="k">条程序生成的断言，{INJ.errors} 条含错</span></div>
      <div className="row" style={rise(l, A.st + 0.6, 0.4, 14)}><span className="v" style={{color: 'var(--ok)'}}>100%</span><span className="k">含错断言全部查出（召回）</span></div>
      <div className="row" style={rise(l, A.st + 1.2, 0.4, 14)}><span className="v" style={{color: 'var(--ok)'}}>{INJ.fp}</span><span className="k">条正确断言被误报</span></div>
      <div className="row" style={rise(l, A.st + 1.8, 0.4, 14)}><span className="v" style={{color: 'var(--prog)'}}>{INJ.type_acc}%</span><span className="k">错误类型判对</span></div>
    </div>}
    <div className="abs" style={{left: 96, top: 936, fontSize: 28, color: 'var(--mute)', whiteSpace: 'nowrap', ...rise(l, 2.4, 0.6, 14)}}>容差按研报数字的展示精度计算；预测和缺少真值的断言判“无法核实”，不算错。</div>
  </>;
}
