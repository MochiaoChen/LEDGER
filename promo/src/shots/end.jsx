import React from 'react';
import {useLocal, p, rise, fade, act, ease} from '../kit/time.js';
import {Seal} from '../kit/ui.jsx';
// 16 落版：字标、一句收束、免责声明。
const HL = [226, 520, 684, 796];
export function EndView() {
  const l = useLocal(), A = {mk: act('end-mark'), seal: act('end-seal')};
  return <>
    {HL.map((y, i) => <div key={y} className="ledger-h" style={{top: y, transform: `scaleX(${p(l, 0.05 + i * 0.1, 1.0, ease.io3)})`}} />)}
    <div className="ledger-v red" style={{left: 252, transform: `scaleY(${p(l, 0.1, 1.0, ease.io3)})`}} />
    <div className="ledger-v red" style={{left: 260, transform: `scaleY(${p(l, 0.2, 1.0, ease.io3)})`}} />
    <div className="end-word" style={{clipPath: `inset(0 ${(1 - p(l, A.mk, 0.9, ease.io3)) * 100}% 0 0)`}}>LEDGER</div>
    <div className="end-zh">{Array.from('每个数字，都对得上原文。').map((c, i) => <span key={i} style={{display: 'inline-block', ...rise(l, 1.6 + i * 0.05, 0.55, 30)}}>{c}</span>)}</div>
    <div className="end-sub" style={fade(l, 2.6, 0.5)}><b>L</b>LM-driven <b>E</b>quity Research with <b>D</b>eterministic <b>G</b>rounding, <b>E</b>valuation and <b>R</b>eporting</div>
    <Seal l={l} at={A.seal} x={1440} y={262} size={210} text="核" sub="VERIFIED" />
    <div className="end-foot" style={fade(l, 4.2, 0.6)}>2026 北京市大学生金融人工智能竞赛 · 金融投研智能体构建<br />片中研报为系统生成的样例，用于展示系统能力，不构成投资建议。</div>
  </>;
}
