import React from 'react';
import data from '../data/data.json';
import {useLocal, p, rise, fade, act, ease, lerp, count} from '../kit/time.js';
import {Title, GateLine, Seal} from '../kit/ui.jsx';
// 12 排版交付：30 页真实研报页面（中际旭创1003.pdf 逐页渲染）平铺成看板，镜头抬起；首页抬到前景。
const PAGES = data.report.page_files, COLS = 10;
const g10 = {...data.gates[9], detail: '…/report/' + data.gates[9].detail.split('/report/')[1].split('（')[0]};   // 省略路径前缀和括号里的检查说明，免得压到首页
export function LayoutView() {
  const l = useLocal(), A = {pg: act('layout-pages'), cv: act('layout-cover'), g10: act('gate-10'), g11: act('gate-11')};
  const lift = p(l, A.pg, 5.4, ease.io), side = p(l, A.cv - 0.4, 1.0, ease.io3);
  const rx = lerp(62, 24, lift), z = lerp(-420, 0, lift);
  return <>
    <div className="ly-stage" style={{opacity: 1 - 0.78 * side}}>
      <div className="ly-board" style={{transform: `translate3d(${lerp(0, -260, side).toFixed(1)}px, ${lerp(60, 0, lift).toFixed(1)}px, ${z.toFixed(1)}px) rotateX(${rx.toFixed(2)}deg) rotateZ(${lerp(-7, -2, lift).toFixed(2)}deg)`}}>
        {PAGES.map((f, i) => { const at = A.pg + i * 0.045, u = p(l, at, 0.6);
          return <div className="ly-pg" key={f} style={{left: (i % COLS) * 164, top: Math.floor(i / COLS) * 226, opacity: Math.min(1, u * 1.6), transform: `translate3d(0, ${(1 - u) * -80}px, ${((1 - u) * 260).toFixed(1)}px)`}}><img src={'pages/' + f} alt="" /></div>; })}
      </div>
    </div>
    <Title l={l} at={0.1} mode="rise" x={96} y={96} w={1100} en="Typeset and deliver" zh="排版设计师交出 30 页研报" zhSize={56} />
    {l >= A.cv - 0.4 && <>
      <div className="ly-cover" style={{opacity: p(l, A.cv - 0.3, 0.4, ease.out2), transform: `translateY(${(1 - p(l, A.cv - 0.3, 0.9)) * 120}px) scale(${lerp(0.82, 1, p(l, A.cv - 0.3, 0.9))}) rotate(${lerp(-3, 0, p(l, A.cv - 0.3, 0.9))}deg)`}}><img src={'pages/' + data.report.cover_file} alt="" /></div>
      <div className="ly-st">
        <div style={rise(l, A.cv, 0.5, 20)}><div className="v">{Math.round(count(l, A.cv, 1.0, data.report.pages))}</div><div className="k">页 PDF 研报</div></div>
        <div style={rise(l, A.cv + 0.3, 0.5, 20)}><div className="v">{Math.round(count(l, A.cv + 0.3, 1.0, 68))}</div><div className="k">个图表</div></div>
      </div>
      <div className="ly-list" style={rise(l, A.cv + 1.2, 0.6, 16)}><b>目录、图表目录、免责声明</b>齐全；<br />另附 <span className="mono">model.xlsx</span>：{data.workbook.sheets.length} 张表、{data.workbook.n_formulas} 条公式联动。</div>
    </>}
    <Seal l={l} at={A.g11 + 0.6} x={1668} y={96} size={156} rot={8} text="核" sub="11 / 11" />
    <GateLine l={l} at={A.g10} gate={g10} x={96} y={888} w={1080} />
    <GateLine l={l} at={A.g11} gate={data.gates[10]} x={96} y={944} w={1080} />
  </>;
}
