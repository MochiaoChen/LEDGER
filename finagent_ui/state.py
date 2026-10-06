"""将原工作区闸门、事实与文件交付映射为界面状态。"""
from pathlib import Path
import json
from finagent.report_pipeline import status, META

ROLES = [
    ('研究助理', [1], 'finagent-report', '编制基础材料'),
    ('分析师', list(range(2, 8)), 'finagent-research / finagent-report', '深度分析与验证'),
    ('主笔', [8], 'finagent-report', '撰写研究内容'),
    ('复核编辑', [9], 'finagent-review', '质量控制'),
    ('排版设计师', [10, 11], 'finagent-report', '生成最终交付'),
]
STAGES = ['资料搜集', '财务抽取', '分析框架', '深度调研', '经营数据校验', '估值假设', '估值运行', '形成文稿', '复核改写', '研报排版', '交付说明']

def load(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default

def empty():
    return dict(company='', year='', file='', status='idle', elapsed=0, stage=1,
                stages=[dict(name=n, ok=False) for n in STAGES], evidence=[], artifacts=[],
                progress=None, detail='上传年报后开始任务', next='等待输入', run_dir=None)

def snapshot(ws, job=None):
    job = job or {}
    ws = Path(ws)
    meta = load(ws / META, {})
    g = status(ws)
    stage = next((i + 1 for i, s in enumerate(g['stages']) if not s['ok']), 11)
    result = {**empty(), **job, 'company': meta['company'], 'year': meta['year'],
              'file': Path(meta['pdf']).name, 'stage': stage, 'workspace': str(ws),
              'stages': [dict(name=s['stage'].split(' ', 1)[1], ok=s['ok'], detail=s['detail']) for s in g['stages']],
              'detail': g['stages'][stage - 1]['detail'], 'next': g['next'], 'run_dir': g['run_dir']}
    if g['done']:
        result['status'] = 'complete'
    # 阶段通过比例，只代表已过闸门，不能伪装为当前会话进度。
    result['progress'] = round(sum(s['ok'] for s in g['stages']) / 11 * 100)
    work = ws / 'data' / 'extractions' / meta['key']
    verified_path = work / 'facts.verified.json'
    verified_fresh = verified_path.exists() and (not (work / 'facts.json').exists() or verified_path.stat().st_mtime >= (work / 'facts.json').stat().st_mtime)
    facts = load(verified_path if verified_fresh else work / 'facts.json', {}) or {}
    entries = facts if isinstance(facts, list) else facts.get('facts', facts.get('items', []))
    if isinstance(entries, dict):
        entries = list(entries.values())
    for f in entries if isinstance(entries, list) else []:
        if not isinstance(f, dict):
            continue
        source = f.get('source') or {k: f.get(k) for k in ('page', 'table', 'row', 'col')}
        if not isinstance(source, dict):
            source = {'source': str(source)}
        result['evidence'].append(dict(name=f.get('metric_name', f.get('label', f.get('metric_id', '财务事实'))),
              value=f.get('raw_value', f.get('raw', f.get('value', '—'))), period=f.get('period', ''), source=source,
              status='核验产物' if verified_fresh else '待核验', raw=f))
    # 仅允许下载工作区内的真实文件；交付文件须全部闸门通过。
    for base in [work, ws / g['run_dir'] if g['run_dir'] else None]:
        if not base or not base.exists():
            continue
        for p in sorted(base.rglob('*')):
            if not p.is_file() or p.suffix not in ('.json', '.csv', '.md', '.xlsx', '.pdf'):
                continue
            final = p.suffix in ('.xlsx', '.pdf')
            if final and not g['done']:
                continue
            result['artifacts'].append(dict(name=p.name, path=p.relative_to(ws).as_posix(),
                  final=final, size=p.stat().st_size, updated=p.stat().st_mtime))
    logs = sorted((ws / '.pipeline' / 'agents').glob('*.jsonl'))
    result['agent_log'] = []
    if logs:
        # 只取尾部，避免每次刷新读取完整的长会话。
        with logs[-1].open('rb') as stream:
            stream.seek(max(0, logs[-1].stat().st_size - 32768))
            lines = stream.read().decode('utf-8', errors='replace').splitlines()[-40:]
        for line in lines:
            try:
                event = json.loads(line)
                result['agent_log'].append({'type': event.get('type', ''), 'content': line[:1500]})
            except ValueError:
                pass
    return result
