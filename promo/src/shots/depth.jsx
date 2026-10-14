import React from 'react';
import data from '../data/data.json';
import {useLocal, p, rise, fade, act, ease} from '../kit/time.js';
import {Title, GateLine} from '../kit/ui.jsx';
// 08b 产业链与深度专题：产业链图是研报里的真实图表（runs/…/report/charts/chain.svg，reportkit 的 flow 原语生成），
// 驱动清单与四个专题的标题取自分析师会话写下的 report/framework.md。
const FW = data.framework, DR = FW.drivers.map(d => d.replace(/（.*?）/g, ''));
export function DepthView() {
  const l = useLocal(), A = {chain: act('depth-chain'), g3: act('gate-3'), tp: act('depth-topics'), g4: act('gate-4')};
  return <>
    <Title l={l} at={0.1} mode="rise" x={96} y={96} w={1700} en="Drivers and supply chain" zh="产业链和深度专题，由模型从资料里推出来" zhSize={52} />
    <div className="dp-cap" style={fade(l, A.chain, 0.4)}>研报图表 · 产业链 · reportkit flow</div>
    <div className="dp-card" style={{opacity: p(l, A.chain - 0.4, 0.4, ease.out2), clipPath: `inset(0 ${((1 - p(l, A.chain, 2.8, ease.io)) * 100).toFixed(2)}% 0 0 round 8px)`}}><img src={FW.chain_chart} alt="" /></div>
    <div className="dp-dr">
      <div className="dp-h" style={fade(l, 3.6, 0.4)}><b>{DR.length}</b>个驱动 · 每个都指到年报页码和预测参数</div>
      <div className="chips">{DR.map((d, i) => <span key={d} style={{opacity: p(l, 3.9 + i * 0.09, 0.3, ease.out2), transform: `translateY(${(1 - p(l, 3.9 + i * 0.09, 0.4)) * 12}px)`}}>{d}</span>)}</div>
    </div>
    <div className="dp-tp">
      <div className="dp-h" style={fade(l, A.tp - 0.3, 0.4)}><b>{FW.topics.length}</b>个深度专题 · 先提问，再带着问题去调研</div>
      {FW.topics.map((q, i) => <div className="q" key={i} style={{opacity: p(l, A.tp + i * 0.9, 0.3, ease.out2), transform: `translateX(${(1 - p(l, A.tp + i * 0.9, 0.5)) * 30}px)`}}><b>{i + 1}</b><span>{q}</span></div>)}
    </div>
    <div className="abs" style={{left: 910, top: 908, fontSize: 25, color: 'var(--dim)', whiteSpace: 'nowrap', ...rise(l, A.tp + 4.4, 0.6, 14)}}>系统不预设行业框架，skill 只给方法与约束。</div>
    <GateLine l={l} at={A.g3} gate={data.gates[2]} x={96} y={892} w={780} />
    <GateLine l={l} at={A.g4} gate={data.gates[3]} x={96} y={944} />
  </>;
}
