import React from 'react';
import {useLocal, p, rise, fade, typedLen, act, ease} from '../kit/time.js';
import {Seal} from '../kit/ui.jsx';
// 02 品牌：账页横线与栏线画出，字标逐字落下，全称键入，印章盖下，六个选题入账。
const FULL = [['b', 'L'], ['t', 'LM-driven '], ['b', 'E'], ['t', 'quity Research with '], ['b', 'D'], ['t', 'eterministic '], ['b', 'G'], ['t', 'rounding, '], ['b', 'E'], ['t', 'valuation and '], ['b', 'R'], ['t', 'eporting']];
const FULL_N = FULL.reduce((n, s) => n + s[1].length, 0);
const ROWS = [['主选题', ['财报分析', '自动化估值建模', '研究报告质量评估']], ['子选题', ['数据提取', '产业链分析', '研究报告纠错核查']]];
const HL = [186, 452, 540, 760];
export function BrandView() {
  const l = useLocal(), A = {st: act('brand-stamp'), seal: act('brand-seal'), tr: act('brand-tracks')};
  let budget = typedLen(FULL_N, l, 2.5, 46);
  return <div className="abs" style={{inset: 0, transformOrigin: '30% 45%', transform: `scale(${(1 + 0.03 * p(l, 0, 12, ease.lin)).toFixed(5)})`}}>
    {HL.map((y, i) => <div key={y} className="ledger-h" style={{top: y, transform: `scaleX(${p(l, 0.05 + i * 0.12, 1.1, ease.io3)})`}} />)}
    <div className="ledger-v red" style={{left: 252, transform: `scaleY(${p(l, 0.1, 1.2, ease.io3)})`}} />
    <div className="ledger-v red" style={{left: 260, transform: `scaleY(${p(l, 0.2, 1.2, ease.io3)})`}} />
    <div className="ledger-v" style={{left: 1668, transform: `scaleY(${p(l, 0.3, 1.2, ease.io3)})`}} />
    <div className="brand-word">{Array.from('LEDGER').map((c, i) => { const u = p(l, A.st + i * 0.3, 0.22, ease.out); return <span key={i} style={{opacity: l >= A.st + i * 0.3 ? 1 : 0, transform: `translateY(${(1 - u) * -46}px) scale(${1.12 - 0.12 * u})`}}>{c}</span>; })}</div>
    <div className="brand-full" style={{fontSize: 28}}>{FULL.map(([k, s], i) => { const take = Math.max(0, Math.min(s.length, budget)); budget -= take; const x = s.slice(0, take); return k === 'b' ? <b key={i}>{x}</b> : <span key={i}>{x}</span>; })}</div>
    <div className="brand-zh">{Array.from('金融投研多 Agent 系统').map((c, i) => <span key={i} style={{display: 'inline-block', whiteSpace: 'pre', ...rise(l, 4.2 + i * 0.04, 0.55, 30)}}>{c}</span>)}</div>
    <div className="brand-desc" style={rise(l, 5.0, 0.6, 18)}>模型负责读和写，程序负责算和查，每个数字都能追到原文页码。</div>
    <Seal l={l} at={A.seal} x={1420} y={236} size={196} text="核" sub="VERIFIED" />
    <div className="brand-tracks">
      {ROWS.map(([k, vs], r) => <div className="row" key={k} style={fade(l, A.tr + r * 0.6, 0.3)}>
        <span className="k">{k}</span>
        {vs.map((v, i) => <span key={v} className="v" style={{clipPath: `inset(0 ${(1 - p(l, A.tr + 0.15 + r * 0.6 + i * 0.3, 0.45, ease.out)) * 100}% 0 0)`}}>{v}</span>)}
      </div>)}
    </div>
    <div className="brand-contest" style={fade(l, A.tr + 2.0, 0.5)}>2026 北京市大学生金融人工智能竞赛 · 金融投研智能体构建</div>
  </div>;
}
