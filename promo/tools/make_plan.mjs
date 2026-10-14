// 由镜头定义生成 plan.json：时间只在这里写一次（按小节对齐，100 BPM，每小节 2.4 秒）。
// node tools/make_plan.mjs
import {readFile, writeFile} from 'node:fs/promises';
import {existsSync} from 'node:fs';
const BAR = 2.4, FPS = 30;
const R = 'repo:';
// id, 小节数, 底色, 类型, 英文标题, 中文标题, 上屏说明, 白话解释, 是否卖点, 来源, 组件, 动作[相对秒, id, 描述, 是否要音效, 音效类型]
const defs = [
  ['hook', 6, 'dark', 'title', 'Which number is made up?', '一份研报，650 个数字', '模型写出来的研报，哪一个数字是它自己编的？',
    '系统生成的中际旭创深度研报正文约 2 万字，数字锁统计到 650 个带单位的数字；读者没法逐个分辨真假。', false, [], null,
    [[0.9, 'hook-count', '数字计数开始滚动', true, 'typing'], [7.2, 'hook-question', '问题大字出现', true, 'whoosh'], [11.4, 'hook-zero', '答案“零”落下', true, 'resolve']]],
  ['brand', 5, 'paper', 'title', 'LEDGER', '金融投研多 Agent 系统', '模型负责读和写，程序负责算和查，每个数字都能追到原文页码。',
    'LEDGER 是多 Agent 投研系统：模型会话只读、抄、写、判断，全部计算和校验由确定性 Python 完成，抽取结果带页码出处。', true, [R + 'CLAUDE.md', R + 'docs/architecture.md'], null,
    [[0.3, 'brand-stamp', '字标逐字落下', true, 'pop'], [5.4, 'brand-seal', '印章盖下', true, 'resolve'], [7.8, 'brand-tracks', '六个选题列出', true, 'toggle']]],
  ['rule', 6, 'split', 'title', 'Models read. Code computes.', '模型不做算术', '模型抄下的数要过校验才能入账；连“约三倍”这样的约数，也不许心算。',
    '设计规范第 1 条：LLM 只负责读、抄、写、判断，所有数值计算由确定性 Python 完成，连约数也不许心算。', true, [R + 'CLAUDE.md'], null,
    [[1.2, 'rule-split', '明暗两栏展开', true, 'sweep'], [6.6, 'rule-pass', '原文数字过闸入账', true, 'success'], [10.2, 'rule-reject', '心算约数被挡回', true, 'error']]],
  ['cmd', 5, 'dark', 'workspace', 'One command, five sessions', '一条命令，起五个会话', '编排器在仓库之外搭好隔离工作区，依次启动五个无头 Claude Code 会话，彼此只靠文件交接。',
    'report_pipeline build 在仓库目录树之外建工作区，run 依次启动研究助理、分析师、主笔、复核编辑、排版设计师五个无头会话。', true, [R + 'finagent/report_pipeline.py'], R + 'finagent/report_pipeline.py',
    [[0.6, 'cmd-type', '键入 build 命令', true, 'typing'], [4.2, 'cmd-run', '回车运行', true, 'click'], [6.0, 'cmd-sessions', '五个会话依次列出', true, 'pop'], [9.6, 'cmd-gates', '11 道闸门刻度出现', true, 'toggle']]],
  ['search', 12, 'dark', 'workspace', 'Agent runtime: search', '研究助理先上网搜集资料', '29 次检索、41 次抓取，登记 51 个来源；摘句里找不到所登记的数字，程序就拒收。',
    '研究助理会话（Opus）真实运行记录：29 次 WebSearch、41 次 WebFetch、506 秒；sources.json 登记 51 个来源 184 条带数字摘句，verify-sources 逐条核对摘句包含该数字。', true,
    ['file:evidence/session-research.md', R + 'finagent/output/sources.py'], 'file:src/shots/search.jsx',
    [[1.8, 'search-first', '第一条检索发出', true, 'click'], [3.0, 'search-stream', '事件流滚动', true, 'typing'], [16.2, 'search-card', '来源卡片登记', true, 'pop'], [19.2, 'search-verify', '摘句数字核对通过', true, 'success'], [25.8, 'gate-1', '闸门 1 资料搜集盖章', true, 'ding-dong']]],
  ['read', 7, 'dark', 'detail', 'Read and transcribe', '分析师读年报，只抄数，不计算', '每条记录写清指标、期间、原文数字和页码，一个字符都不改。',
    '分析师会话直接读年报 PDF，把数字原样抄进 facts.json，带 metric_id、period、raw_value、page；本次抽取 98 条。', true, [R + 'finagent/tasks/financials/external.py', 'file:evidence/feature-evidence.md'], 'file:src/shots/read.jsx',
    [[2.4, 'read-scan', '扫描线停在营业收入一行', true, 'sweep'], [4.8, 'read-type', '写入 facts.json', true, 'typing'], [13.2, 'read-count', '98 条事实计数', true, 'pop']]],
  ['code', 12, 'dark', 'detail', 'Verify, do not trust', '抄下的每个数，回原文逐字核对', '程序到模型写的那一页，按数字边界查找；找不到就拒收，改一位也不行。',
    'external.find_evidence 在所写页码的原文块里按数字边界正则查找模型抄的数字；真实数字命中 c0351 表格块，改动一位或只给整数部分都返回 None 并拒收。', true,
    [R + 'finagent/tasks/financials/external.py:56', 'file:evidence/feature-evidence.md'], R + 'finagent/tasks/financials/external.py',
    [[0.6, 'code-type', '源码逐行出现', true, 'typing'], [12.6, 'code-run', '对真实数字运行', true, 'click'], [16.2, 'code-hit', '第 94 页命中', true, 'success'], [19.2, 'code-tamper', '改动一位再跑', true, 'click'], [22.2, 'code-reject', '未找到，拒收', true, 'error']]],
  ['truth', 7, 'paper', 'detail', 'One truth table', '一张真值表，下游只认它', '估值和纠错都从这张表取数；同比由程序计算，异常信号把事实和推论分开写。',
    'analyze() 产出的 truth_table 是估值和纠错的唯一数据来源；本次 98 条事实拒收 0、冲突 0，8 项勾稽通过，同比由程序计算。', true, [R + 'finagent/tasks/financials/analyze.py', 'file:evidence/feature-evidence.md'], 'file:src/shots/truth.jsx',
    [[0.9, 'truth-rows', '账页逐行写入', true, 'typing'], [6.0, 'truth-yoy', '同比列由程序算出', true, 'toggle'], [9.6, 'truth-signal', '异常信号：事实与推论分开', true, 'pop'], [13.2, 'gate-2', '闸门 2 财务抽取盖章', true, 'ding-dong']]],
  ['depth', 8, 'dark', 'detail', 'Drivers and supply chain', '产业链和深度专题，由模型从资料里推出来', '系统不预设行业框架：驱动清单、产业链图和四个专题，都由分析师会话从年报与资料包推导。',
    'skill 只给方法与约束；本次分析框架列出 15 个驱动、4 个深度专题，研报里的产业链图由 reportkit 的 flow 原语生成，专题调研补充 16 个问题、共 51 个来源。', true,
    [R + 'CLAUDE.md', 'file:evidence/feature-evidence.md'], 'file:src/shots/depth.jsx',
    [[1.2, 'depth-chain', '产业链图从上游画到下游', true, 'sweep'], [5.4, 'gate-3', '闸门 3 分析框架盖章', true, 'toggle'], [6.6, 'depth-topics', '四个深度专题列出', true, 'pop'], [13.8, 'gate-4', '闸门 4 深度调研盖章', true, 'toggle']]],
  ['compute', 9, 'paper', 'detail', 'Code does the math', '所有计算，交给确定性 Python', '三表联动、三情景 DCF 和敏感性，连同 865 条公式写进工作簿，可以逐格审计。',
    '估值引擎不调用模型：分部预测、三表联动、FCFF DCF 三情景与敏感性全部由 Python 计算，model.xlsx 15 张表共 865 条公式。', true,
    [R + 'finagent/tasks/valuation/dcf.py', R + 'finagent/tasks/valuation/ts_engine.py', 'file:evidence/feature-evidence.md'], 'file:src/shots/compute.jsx',
    [[1.2, 'gate-5', '闸门 5 经营数据盖章', true, 'toggle'], [1.8, 'gate-6', '闸门 6 估值假设盖章', true, 'toggle'], [3.0, 'compute-matrix', '敏感性矩阵逐格算出', true, 'typing'], [8.4, 'compute-bars', '三情景每股价值', true, 'pop'], [12.6, 'compute-formula', '工作簿公式流', true, 'sweep'], [18.0, 'gate-7', '闸门 7 估值运行盖章', true, 'ding-dong']]],
  ['write', 7, 'dark', 'detail', 'Every number cited', '主笔写稿，护栏逐个数字查出处', '文稿里的数字，要么来自真值表，要么带来源编号；查不到出处就过不了闸门。',
    '主笔会话写 narrative.md，guard 核对出处、指标绑定和外部数字的 [S编号]；本次无出处数字 0、指标期间不符 0、外部数字缺引用 0。', true,
    [R + 'finagent/output/guard.py', 'file:evidence/feature-evidence.md'], 'file:src/shots/write.jsx',
    [[0.6, 'write-type', '文稿流式写出', true, 'typing'], [8.4, 'write-guard', '护栏逐项归零', true, 'success'], [13.2, 'gate-8', '闸门 8 文稿盖章', true, 'ding-dong']]],
  ['review', 6, 'dark', 'detail', 'Numbers locked', '复核编辑只改措辞，数字被锁住', '改写稿里出现任何新数字或新来源编号，数字锁都会拒绝。',
    '复核编辑会话（Sonnet）只改措辞与结构；numlock 要求改写稿里每个“数字+单位”都原样出现在改写前文稿中，本次 665 → 650，新增 0。', true,
    [R + 'finagent/output/numlock.py:29', 'file:evidence/feature-evidence.md'], R + 'finagent/output/numlock.py',
    [[1.2, 'review-rewrite', '句子被改写', true, 'sweep'], [4.2, 'review-lock', '数字逐个上锁', true, 'toggle'], [11.4, 'gate-9', '闸门 9 复核改写盖章', true, 'ding-dong']]],
  ['layout', 6, 'dark', 'workspace', 'Typeset and deliver', '排版设计师交出 30 页研报', '68 个图表、带目录和免责声明的 PDF，加一份公式联动的估值工作簿。',
    '排版会话用 reportkit 生成 30 页、68 个图表的 PDF（中际旭创1003.pdf）并写交付说明；11 道闸门全部通过。', true, ['file:evidence/feature-evidence.md'], 'file:src/shots/layout.jsx',
    [[0.3, 'layout-pages', '30 页铺开', true, 'sweep'], [6.0, 'layout-cover', '首页抬起', true, 'whoosh'], [9.0, 'gate-10', '闸门 10 排版盖章', true, 'toggle'], [10.2, 'gate-11', '闸门 11 交付说明盖章，全部通过', true, 'success']]],
  ['qc', 8, 'dark', 'detail', 'Blind review', '盲评质检：评分标准对生成方不可见', '质检员只拿到交付物，按四层 40 条标准打分；问题单只带理由与证据，回到对应会话返工。',
    '质检在仓库与工作区之外评审：L0 硬闸门与 L1 数据闭合由程序判，L2/L3 由盲评判，程序计分；三个版本同一标准 46～49 → 74/67 → 90/88，重复盲评逐条一致 86%～91%。', true,
    [R + 'finagent/evaluation/rubric.py', R + 'eval/results/v2_中际旭创/score.json', R + 'eval/calibration/summary.json'], 'file:src/shots/qc.jsx',
    [[1.2, 'qc-room', '交付物进入评审间', true, 'whoosh'], [4.2, 'qc-layers', '四层评分逐层出分', true, 'toggle'], [8.4, 'qc-total', '总分 90', true, 'success'], [11.4, 'qc-versions', '三个版本的分数', true, 'pop']]],
  ['check', 6, 'paper', 'detail', 'Check their numbers too', '别人的研报，也逐条核对', '抽出研报里的数字断言，与财报真值比对，判断错在数值、单位、期间还是口径。',
    '纠错核查把研报数字断言与真值表逐条核对并判断错误类型；注入实验 1,334 条断言、754 条含错，按展示精度容差召回 100%、误报 0。', true,
    [R + 'finagent/tasks/report_check/verify.py', R + 'paper/techreport/sections/13_experiments.tex'], 'file:src/shots/check.jsx',
    [[1.2, 'check-underline', '断言逐个划出', true, 'typing'], [4.8, 'check-verdict', '判定结论弹出', true, 'error'], [9.6, 'check-stats', '注入实验结果', true, 'pop']]],
  ['trace', 6, 'dark', 'workspace', 'Trace everything', '全程留痕，在终端里随时回看', '文件哈希、工具调用、会话事件流都有记录，评审可以原样复现。',
    '终端界面 finagent tui 读取工作区产物，展示闸门、真值表、估值、质检、追溯与 Agent 会话；本片画面为该界面导出的原始 SVG。', true,
    [R + 'finagent_tui/app.py', R + 'finagent/core/tracing.py'], R + 'finagent_tui/app.py',
    [[0.6, 'trace-open', '终端界面打开', true, 'whoosh'], [5.4, 'trace-tab', '从真值表切到追溯页', true, 'click'], [9.6, 'trace-tab2', '切到 Agent 页', true, 'click-alt']]],
  ['end', 4, 'paper', 'end', 'LEDGER', '每个数字，都对得上原文', '研报内容用于展示系统能力，不构成投资建议。',
    '片尾落版：系统名、一句收束和免责声明。', false, [], null,
    [[0.6, 'end-mark', '字标落版', true, 'resolve'], [3.6, 'end-seal', '印章盖下', true, 'pop']]],
];
let t = 0;
const shots = defs.map(([id, bars, tone, type, headlineEn, headline, description, plainExplanation, claim, source, component, acts]) => {
  const start = +t.toFixed(3); t += bars * BAR; const end = +t.toFixed(3);
  return {id, start, end, bars, tone, type, headlineEn, headline, description, plainExplanation, descriptionAt: 0.8, claim, source, component,
    actions: acts.map(([at, aid, action, soundRequired, kind]) => ({id: aid, at, action, soundRequired, ...(kind ? {kind} : {})}))};
});
const duration = +t.toFixed(3);
// 音效落点（scripts/sfx_landmarks.py 实测，见 evidence/sfx-landmarks.json）；没有测量文件时先不写 cue
let cues = [];
if (existsSync('evidence/sfx-landmarks.json')) {
  const lm = JSON.parse(await readFile('evidence/sfx-landmarks.json', 'utf8'));
  const GAIN = JSON.parse(await readFile('tools/sfx-gain.json', 'utf8'));
  for (const s of shots) for (const a of s.actions) {
    if (!a.kind) continue;
    // 连续键入用按时长生成的专用文件（tools/make_typing.py），其余用内置音效
    const name = a.kind === 'typing' && lm['typing-' + a.id] ? 'typing-' + a.id : a.kind;
    const m = lm[name]; if (!m) throw new Error('no landmark for ' + name);
    const usePeak = ['whoosh', 'sweep'].includes(a.kind);
    const syncOffset = +(usePeak ? m.peak : m.onset).toFixed(3);
    const at = +(s.start + a.at - syncOffset).toFixed(3);
    cues.push({at: Math.max(0, at), actionId: a.id, file: `assets/sfx/${name}.wav`, gain: GAIN[a.kind] ?? 1, role: 'sfx', kind: a.kind, syncOffset: at < 0 ? +(s.start + a.at).toFixed(3) : syncOffset});
  }
}
const plan = {
  demo: false, product: 'LEDGER', style: 'repo', width: 1920, height: 1080, fps: FPS, duration,
  repo: '..', scope: {versions: '全量产品（截至 2026-10-13 main 分支）', platforms: ['cli-tui', '流水线产物（PDF 研报 / 估值工作簿）'], notCovered: ['网页前端（由其他成员开发，本片未涉及）']},
  audioRequired: true, sfxRequired: true,
  typography: {mode: 'bilingual', zhFont: 'Noto Sans SC', enFont: 'Maple Mono NF CN', zhStyle: 'sans-serif'},
  audio: {beatGrid: {bpm: 100, offset: 0}, ducking: {enabled: true}, music: {file: 'assets/music.wav', gain: 0.7}, cues},
  shots: shots.map(({kind, ...s}) => ({...s, actions: s.actions.map(({kind, ...a}) => a)})),
};
await writeFile('plan.json', JSON.stringify(plan, null, 2) + '\n');
console.log('plan.json', duration + 's', shots.length + ' shots', cues.length + ' cues');
console.log(shots.map(s => `${s.id} ${s.start}-${s.end}`).join(' | '));
