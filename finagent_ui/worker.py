"""独立子进程调用原 build/run；不调用 refine 或 evaluation。"""
import json
import sys
from pathlib import Path
from finagent.report_pipeline import build, run_agent

def main():
    path = Path(sys.argv[1])
    job = json.loads(path.read_text(encoding='utf-8'))
    def save():
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
        temp.replace(path)
    try:
        ws = build(job['company'], job['year'], Path(job['dest']), pdf=job['pdf'],
                   tag=job['id'], allow_unverified=job['allow_unverified'],
                   price=job.get('price'), price_source=job.get('price_source'))
        job['workspace'] = str(ws)
        save()
        code = run_agent(ws)
        job['status'] = 'finished' if code == 0 else 'blocked'
        job['exit_code'] = code
    except (Exception, SystemExit) as exc:
        job['status'], job['error'] = 'failed', str(exc)
    save()
    return 0 if job['status'] == 'finished' else 1

if __name__ == '__main__':
    sys.exit(main())
