import React from 'react';
import data from '../data/data.json';
import {useLocal, p, rise, fade, typed, act, ease} from '../kit/time.js';
import {Title} from '../kit/ui.jsx';
// 04 一条命令：按 CLAUDE.md 的命令模板代入本工作区的真实参数；五个会话的角色与模型取自 agent_runs.json。
const ROLE = {research: ['研究助理', '阶段 1'], analyst: ['分析师', '阶段 2～7'], write: ['主笔', '阶段 8'], review: ['复核编辑', '阶段 9'], layout: ['排版设计师', '阶段 10～11']};
const ORDER = ['research', 'analyst', 'write', 'review', 'layout'];
const MODEL = Object.fromEntries(data.agent_runs.map(r => [r.role, r.model]));
const C1 = `python -m finagent.report_pipeline build --company ${data.company} --year ${data.year} --price ${data.valuation.price}`;
const C2 = 'python -m finagent.report_pipeline run';
const hl = s => s.split(/(\s--[a-z-]+|\s-m)/).map((x, i) => /^\s-/.test(x) ? <span key={i} className="flag">{x}</span> : x);
export function CmdView() {
  const l = useLocal(), A = {ty: act('cmd-type'), run: act('cmd-run'), ses: act('cmd-sessions')};
  const c1 = typed(C1, l, A.ty, 30), c2 = typed(C2, l, A.run + 0.75, 46);
  return <>
    <Title l={l} at={0.1} mode="type" x={96} y={100} w={1700} en="One command, five sessions" zh="一条命令，起五个会话" zhSize={56} />
    <div className="term" style={{left: 96, top: 280, width: 1728, height: 600}}>
      <div className="bar"><span className="dots"><i /><i /><i /></span><span>contest — zsh</span><span style={{marginLeft: 'auto'}}>finagent.report_pipeline · 确定性 Python 编排器，不是模型</span></div>
      <div className="body cmd-body">
        <div><span className="pr">$ </span>{hl(c1)}{l < A.run && <i className="caret" />}</div>
        {l >= A.run + 0.15 && <div className="dim">  工作区  <span style={{color: 'var(--fg)'}}>{data.workspace}</span>   <span>← 在仓库目录树之外，模型读不到仓库与评分标准</span></div>}
        {l >= A.run + 0.4 && <div className="dim">  年报    {data.evidence.pdf_name} · {data.evidence.n_pages} 页</div>}
        {l >= A.run + 0.7 && <div><span className="pr">$ </span>{hl(c2)}{l < A.ses && <i className="caret" />}</div>}
        <div style={{marginTop: 10}}>
          {ORDER.map((r, i) => { const at = A.ses + i * 0.6; const col = r === 'review' ? 'var(--vio-d)' : 'var(--agent-d)';
            return <div className="cmd-row" key={r} style={{opacity: l >= at ? 1 : 0, transform: `translateX(${(1 - p(l, at, 0.35)) * 26}px)`}}>
              <span className="no">{i + 1}</span><span className="role" style={{color: col}}>{ROLE[r][0]}</span><span className="model">{MODEL[r]}</span>
              <span className="inv">claude -p --output-format stream-json</span><span className="hand">{ROLE[r][1]}</span>
            </div>; })}
        </div>
      </div>
    </div>
    <div className="abs" style={{left: 96, top: 908, fontSize: 30, color: 'var(--dim)', whiteSpace: 'nowrap', ...rise(l, 6.4, 0.6, 14)}}>五个无头 Claude Code 会话互不共享上下文，只靠工作区里的文件交接。</div>
  </>;
}
