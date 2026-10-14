import React from 'react';
import data from '../data/data.json';
import {useLocal, p, rise, fade, act, ease, count} from '../kit/time.js';
import {Title} from '../kit/ui.jsx';
// 13 盲评质检：分层得分取自 eval/results/v2_中际旭创/score.json，三个版本的总分取自 eval/results，校准取自 eval/calibration/summary.json。
const S = data.eval.scores, BEST = S['v2_' + data.company], LY = BEST.layers;
const LAYERS = [['L0', LY.L0.name, '程序判 · 不过不计分', '通过', null], ['L1', LY.L1.name, '程序判', `${LY.L1.earned} / ${LY.L1.possible}`, LY.L1.earned / LY.L1.possible], ['L2', LY.L2.name, '盲评', `${LY.L2.earned} / ${LY.L2.possible}`, LY.L2.earned / LY.L2.possible], ['L3', LY.L3.name, '盲评', `${LY.L3.earned} / ${LY.L3.possible}`, LY.L3.earned / LY.L3.possible], ['N', LY.N.name, '只扣分', `${LY.N.earned}`, null]];
const VERS = [['v0', '无搜集', ['v0_贵州茅台', 'v0_宁德时代', 'v0_招商轮船'], '#5E6478'], ['v1', '先搜集后分析', ['v1_中际旭创', 'v1_宇树科技'], 'var(--prog-d)'], ['v2', '深度专题', ['v2_中际旭创', 'v2_宇树科技'], 'var(--ok-d)']];
const BARS = VERS.flatMap(([v, , ids, col], g) => ids.map((id, k) => ({v, id, col, g, k, total: S[id].total, name: id.split('_')[1].slice(0, 2)})));
const CAL = data.eval.calibration, agr = CAL.map(c => Math.round(c.agreement * 100)).sort((a, b) => a - b), rng = CAL.map(c => c.total_range).sort((a, b) => a - b);
const FILES = [['#D9604F', data.report.pdf], ['#63C08A', 'model.xlsx'], ['#8D96A8', 'delivery.md']];
export function QcView() {
  const l = useLocal(), A = {room: act('qc-room'), lay: act('qc-layers'), tot: act('qc-total'), ver: act('qc-versions')};
  let x = 0;
  return <>
    <Title l={l} at={0.1} mode="type" x={96} y={96} w={1700} en="Blind review" zh="盲评质检：评分标准对生成方不可见" zhSize={56} />
    <div className="qc-room" style={fade(l, 0.1, 0.4)}>
      <div className="lb">OUTSIDE REPO & WORKSPACE</div><div className="zh">评审间里只有交付物</div>
      {FILES.map(([c, n], i) => { const at = A.room + i * 0.35, u = p(l, at, 0.6); return <div className="qc-file" key={n} style={{top: 130 + i * 76, opacity: u, transform: `translateX(${(1 - u) * -120}px)`}}><i style={{background: c}} />{n}</div>; })}
      <div className="abs" style={{left: 28, right: 28, top: 380, fontSize: 25, lineHeight: 1.55, color: 'var(--dim)', ...rise(l, A.room + 1.4, 0.5, 14)}}>质检员 <span className="mono" style={{color: 'var(--vio-d)'}}>claude-sonnet-5-5</span><br />没有参与写作，看不到仓库、工作区和生成过程。</div>
    </div>
    <div className="qc-lay">{LAYERS.map(([id, nm, by, sc, r], i) => { const at = A.lay + i * 0.8;
      return <div className="qc-l" key={id} style={{opacity: p(l, at, 0.3, ease.out2)}}><span className="id">{id}</span><span className="nm">{nm}</span><span className="by">{by}</span>
        <span className="sc" style={{color: r === null ? 'var(--ok-d)' : 'var(--fg)'}}>{sc}</span>{r !== null && <span className="bar"><i style={{transform: `scaleX(${(r * p(l, at + 0.1, 0.7, ease.out)).toFixed(4)})`}} /></span>}</div>; })}</div>
    {l >= A.tot && <div className="qc-tot"><span className="v" style={{transform: `scale(${1.4 - 0.4 * p(l, A.tot, 0.22, ease.out)})`, transformOrigin: 'left bottom', display: 'inline-block'}}>{Math.round(count(l, A.tot, 0.6, BEST.total, 60))}</span>
      <span className="k" style={fade(l, A.tot + 0.4, 0.4)}>分 · 可交付<br />{BEST.items} 条评分项：程序判 {BEST.by_judge.program}，盲评 {BEST.by_judge.llm}</span></div>}
    <div className="qc-ver" style={fade(l, A.ver - 0.3, 0.4)}>
      <div className="cap">同一评分标准，三个版本的流水线<span>单次盲评</span></div>
      {BARS.map((b, i) => { const gx = [0, 222, 378][b.g] + b.k * 66, at = A.ver + i * 0.22, u = p(l, at, 0.7, ease.out), h = b.total * 3.4;
        return <React.Fragment key={b.id}>
          <div className="qc-bar" style={{left: gx, height: h, background: b.col, transform: `scaleY(${u.toFixed(4)})`}} />
          <div className="qc-bv" style={{left: gx, bottom: 60 + h * u + 6, color: b.col, opacity: l >= at ? 1 : 0}}>{Math.round(b.total * u)}</div>
          <div className="qc-bl" style={{left: gx - 6, width: 68, opacity: l >= at ? 1 : 0}}><small>{b.name}</small></div>
        </React.Fragment>; })}
      {VERS.map(([v, note], g) => <div key={v} className="abs mono" style={{left: [0, 222, 378][g], bottom: -34, fontSize: 21, color: 'var(--dim)', whiteSpace: 'nowrap', ...fade(l, A.ver + 0.3 + g * 0.5, 0.4)}}><b style={{color: 'var(--fg)'}}>{v}</b> <span className="zh" style={{fontSize: 19}}>{note}</span></div>)}
    </div>
    <div className="qc-note" style={{top: 876, ...rise(l, A.ver + 2.6, 0.6, 14)}}>重复盲评 3 次：逐条一致 <b>{agr[0]}%～{agr[1]}%</b>，总分极差 <b>{rng[0]}～{rng[1]}</b> 分。</div>
    <div className="abs" style={{left: 660, top: 908, width: 600, fontSize: 25, lineHeight: 1.5, color: 'var(--dim)', ...rise(l, A.tot + 1.4, 0.6, 14)}}>问题单只带理由与证据，回到对应会话返工。</div>
  </>;
}
