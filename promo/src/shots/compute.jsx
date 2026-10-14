import React from 'react';
import data from '../data/data.json';
import {useLocal, p, rise, fade, act, ease, count, fmt, clamp} from '../kit/time.js';
import {Title, GateLine} from '../kit/ui.jsx';
// 09 确定性计算：敏感性矩阵、三情景每股价值、WACC 与工作簿公式，全部取自 valuation.json 与 model.xlsx。
const V = data.valuation, M = V.sens.m, W = V.wacc.wacc * 100;
const SC = [['悲观', V.scenarios.downside, '#8A8473'], ['基准', V.scenarios.base, 'var(--ink)'], ['乐观', V.scenarios.upside, 'var(--prog)']];
const MAX = Math.max(...SC.map(s => s[1]));
const flat = M.flat(), lo = Math.min(...flat), hi = Math.max(...flat);
const waccF = data.workbook.sheets.find(s => s.sheet === 'WACC').sample.slice(-1)[0];
const FX = data.workbook.sheets.filter(s => s.n_formulas > 10).flatMap(s => s.sample.slice(0, 6).map(f => ({sheet: s.sheet, ...f})));
const ROWF = [FX.filter((_, i) => i % 2 === 0), FX.filter((_, i) => i % 2 === 1)];
const pp = v => (v > 0 ? '+' : v < 0 ? '−' : '±') + Math.abs(v * 100).toFixed(1);
export function ComputeView() {
  const l = useLocal(), A = {mx: act('compute-matrix'), bars: act('compute-bars'), fx: act('compute-formula'), gate: act('gate-7')};
  const G = [5, 6].map(n => [data.gates[n - 1], act('gate-' + n)]);
  return <>
    <Title l={l} at={0.1} mode="rise" cls="prog" x={96} y={84} w={900} en="Code does the math" zh="所有计算，交给确定性 Python" zhSize={56} />
    <div className="cp-gl">{G.map(([g, at]) => <div key={g.n} style={{opacity: l >= at ? 1 : 0, transform: `translateX(${(1 - p(l, at, 0.3)) * 20}px)`}}><b>[✓]</b><em>{g.n} {g.name}</em><span>{g.detail}</span></div>)}</div>
    <div className="cp-mx" style={fade(l, A.mx - 0.8, 0.5)}>
      <div className="cap">敏感性：每股价值（元）<span>{V.sens.name}</span></div>
      <div className="cp-grid">
        <div className="hd" />{V.sens.x.map((x, j) => <div className="hd" key={j}>g {pp(x)}pp</div>)}
        {M.map((row, i) => <React.Fragment key={i}>
          <div className="rh">WACC {(W + V.sens.y[i] * 100).toFixed(2)}%</div>
          {row.map((v, j) => { const at = A.mx + (i + j) * 0.34 + j * 0.05, on = l >= at, u = p(l, at, 0.35, ease.out), base = i === 2 && j === 2, heat = (v - lo) / (hi - lo);
            return <div className="cp-cell" key={j} style={{background: on ? `rgba(47,94,140,${(0.04 + heat * 0.3).toFixed(3)})` : '#fff', borderColor: base && on ? 'var(--seal)' : undefined, borderWidth: base && on ? 3 : undefined, fontWeight: base ? 700 : 500, color: base ? 'var(--seal)' : undefined}}>{on ? fmt(v * (0.6 + 0.4 * u), 2) : ''}</div>; })}
        </React.Fragment>)}
      </div>
    </div>
    <div className="cp-sc" style={fade(l, A.bars - 0.3, 0.4)}>
      <div className="cap">三情景 DCF：每股价值（元）<span>FCFF · 取自三表模型</span></div>
      {SC.map(([nm, v, col], i) => { const at = A.bars + i * 0.6, u = p(l, at, 0.9, ease.out);
        return <div className="cp-bar" key={nm} style={{opacity: l >= at ? 1 : 0}}><span className="nm" style={{color: col}}>{nm}</span><span className="tr"><i style={{right: 0, background: col, transform: `scaleX(${(u * v / MAX).toFixed(4)})`}} /></span><span className="vl" style={{color: col}}>{fmt(v * u, 2)}</span></div>; })}
      <div className="cp-wacc" style={rise(l, A.bars + 2.2, 0.5, 14)}><b>WACC {W.toFixed(2)}%</b><span>WACC!{waccF.cell} ={waccF.f}</span></div>
      <div style={{marginTop: 16, fontSize: 22, color: 'var(--mute)', whiteSpace: 'nowrap', ...fade(l, A.bars + 2.6, 0.4)}}>系统输出示例，不构成投资建议</div>
    </div>
    <div className="cp-fxc" style={rise(l, A.fx - 0.2, 0.5, 16)}><span className="v">{Math.round(count(l, A.fx, 1.6, data.workbook.n_formulas))}</span><span className="k">条公式写进 model.xlsx · {data.workbook.sheets.length} 张表联动，可以逐格审计</span></div>
    <div className="cp-fx" style={fade(l, A.fx, 0.5)}>
      {ROWF.map((row, r) => <div className="rowf" key={r} style={{top: r * 56, transform: `translateX(${(-(l - A.fx) * (r ? 74 : 104) - r * 180).toFixed(1)}px)`}}>
        {[...row, ...row].map((f, i) => <span className="f" key={i}><b>{f.sheet}!{f.cell}</b>={f.f}</span>)}
      </div>)}
    </div>
    <GateLine l={l} at={A.gate} gate={data.gates[6]} x={96} y={944} tone="paper" />
  </>;
}
