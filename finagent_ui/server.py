"""标准库 HTTP 适配层：上传、执行、状态刷新、暂停和真实文件下载。"""
import argparse
import base64
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
from .state import empty, load, snapshot
from finagent.core.config import PROJECT_ROOT

STATIC = Path(__file__).parent / 'static'
MAX_BYTES = 100 * 1024 * 1024

class Service:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.processes = {}
        self.lock = threading.Lock()

    def path(self, key):
        if not re.fullmatch(r'[0-9a-f]{32}', key):
            raise ValueError('任务编号无效')
        return self.root / 'jobs' / key / 'job.json'

    def latest(self):
        jobs = sorted((self.root / 'jobs').glob('*/job.json'), key=lambda p: p.stat().st_mtime)
        return jobs[-1].parent.name if jobs else None

    def read(self, key):
        job = load(self.path(key))
        if not job:
            raise ValueError('找不到任务')
        proc = self.processes.get(key)
        if proc and proc.poll() is not None and job['status'] in ('running', 'paused'):
            job['status'] = 'failed'
            job['error'] = '执行进程已退出，请检查任务日志'
        job['elapsed'] = int(time.time() - job['started'])
        data = snapshot(job['workspace'], job) if job.get('workspace') else {**empty(), **job}
        data.pop('pdf', None)
        if job['status'] == 'paused':
            data['status'] = 'paused'
        return data

    def start(self, body):
        company = str(body.get('company', '')).strip()
        year = int(body.get('year', 0))
        if not company or len(company) > 80 or re.search(r'[/\\\x00-\x1f]', company) or company in ('.', '..'):
            raise ValueError('请填写有效公司名称')
        if not 1990 <= year <= 2100:
            raise ValueError('请填写有效年报年度')
        if body.get('allow_unverified') is not True:
            raise ValueError('上传来源未在项目清单核验，请明确确认使用此文件')
        raw = base64.b64decode(body.get('content', ''), validate=True)
        if not raw.startswith(b'%PDF-') or len(raw) > MAX_BYTES:
            raise ValueError('仅接受不超过 100 MB 的 PDF 年报')
        price = body.get('price')
        if price is not None and (float(price) <= 0 or not body.get('price_source')):
            raise ValueError('股价必须为正数并填写来源')
        with self.lock:
            if any(p.poll() is None for p in self.processes.values()):
                raise ValueError('已有任务正在执行或暂停，请先完成当前任务')
            key = uuid.uuid4().hex
            folder = self.path(key).parent
            folder.mkdir(parents=True)
            name = Path(str(body.get('filename', 'annual-report.pdf'))).name
            if not name.lower().endswith('.pdf'):
                name = 'annual-report.pdf'
            pdf = folder / name
            pdf.write_bytes(raw)
            job = dict(id=key, company=company, year=year, file=name, pdf=str(pdf),
                       dest=str(self.root / 'workspaces'), allow_unverified=True, status='running',
                       started=time.time(), price=float(price) if price is not None else None,
                       price_source=body.get('price_source'))
            path = self.path(key)
            path.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
            log = (folder / 'process.log').open('w', encoding='utf-8')
            try:
                proc = subprocess.Popen([sys.executable, '-m', 'finagent_ui.worker', str(path)],
                        cwd=PROJECT_ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            finally:
                log.close()
            self.processes[key] = proc
        return {'id': key}

    def pause(self, key, resume=False):
        if os.name == 'nt':
            raise ValueError('Windows 暂不支持进程组暂停；请在 macOS/Linux 使用')
        with self.lock:
            proc = self.processes.get(key)
            job = load(self.path(key))
            if not proc or proc.poll() is not None:
                raise ValueError('任务未运行，或由其他服务进程启动')
            os.killpg(proc.pid, signal.SIGCONT if resume else signal.SIGSTOP)
            job['status'] = 'running' if resume else 'paused'
            temp = self.path(key).with_suffix('.ui.tmp')
            temp.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
            temp.replace(self.path(key))
        return {'status': job['status']}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def allowed(self):
        if not self.server.token and self.headers.get('Host', '').split(':')[0] not in ('127.0.0.1', 'localhost', '[::1]'):
            self.reply(403, {'error': '本地服务仅接受本机地址'})
            return False
        origin = self.headers.get('Origin')
        allowed = self.server.origin
        local = f'http://{self.headers.get("Host", "")}'
        if origin and origin not in (local, allowed):
            self.reply(403, {'error': '此来源未获准访问服务'})
            return False
        if self.path.startswith('/api/') and self.server.token:
            if self.headers.get('Authorization') != 'Bearer ' + self.server.token:
                self.reply(401, {'error': '服务访问凭证不正确'})
                return False
        return True

    def headers_common(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        origin = self.headers.get('Origin')
        if origin and origin == self.server.origin:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        self.send_header('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Private-Network', 'true')

    def reply(self, code, data):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.headers_common()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        if self.allowed_origin():
            self.send_response(204)
            self.headers_common()
            self.end_headers()

    def allowed_origin(self):
        origin = self.headers.get('Origin')
        if origin and origin not in (self.server.origin, f'http://{self.headers.get("Host", "")}'):
            self.reply(403, {'error': '此来源未获准访问服务'})
            return False
        return True

    def do_GET(self):
        if not self.allowed():
            return
        try:
            parsed = urlparse(self.path)
            parts = parsed.path.strip('/').split('/')
            if parsed.path == '/api/source':
                key = parse_qs(parsed.query).get('id', [''])[0]
                job = self.server.service.read(key)
                meta = load(Path(job['workspace']) / 'sample.json', {})
                return self.reply(200, {'path': meta['pdf']})
            if parsed.path == '/api/state':
                key = parse_qs(parsed.query).get('id', [self.server.service.latest()])[0]
                return self.reply(200, self.server.service.read(key) if key else empty())
            if len(parts) == 4 and parts[:2] == ['api', 'jobs'] and parts[3] == 'page':
                job = self.server.service.read(parts[2])
                ws = Path(job['workspace']).resolve()
                meta = load(ws / 'sample.json', {})
                source = (ws / meta['pdf']).resolve()
                if not source.is_relative_to(ws):
                    raise ValueError('原年报路径无效')
                page_no = int(parse_qs(parsed.query).get('page', ['1'])[0])
                if not 1 <= page_no <= 2000:
                    raise ValueError('原文页码无效')
                cache = self.server.service.path(parts[2]).parent / 'page-preview'
                cache.mkdir(exist_ok=True)
                image = cache / f'{page_no}.png'
                if not image.exists():
                    import pdfplumber
                    with pdfplumber.open(source) as pdf:
                        if page_no > len(pdf.pages):
                            raise ValueError('原文页码超过年报页数')
                        pdf.pages[page_no - 1].to_image(resolution=110).save(image)
                return self.send_file(image)
            if len(parts) == 4 and parts[:2] == ['api', 'jobs'] and parts[3] == 'file':
                job = self.server.service.read(parts[2])
                rel = parse_qs(parsed.query).get('path', [''])[0]
                ws = Path(job['workspace']).resolve()
                path = (ws / rel).resolve()
                files = {a['path'] for a in job['artifacts']}
                meta = load(ws / 'sample.json', {})
                if rel == meta.get('pdf'):
                    files.add(rel)
                if not path.is_relative_to(ws) or rel not in files or not path.is_file():
                    raise ValueError('文件尚未生成或不可下载')
                return self.send_file(path)
            if parsed.path.startswith('/api/'):
                return self.reply(404, {'error': '接口不存在'})
            rel = unquote(parsed.path).lstrip('/')
            if rel in ('', 'tui', 'web'):
                rel = 'index.html'
            path = (STATIC / rel).resolve()
            if not path.is_relative_to(STATIC.resolve()) or not path.is_file():
                return self.reply(404, {'error': '文件不存在'})
            return self.send_file(path)
        except (Exception, SystemExit) as exc:
            return self.reply(400, {'error': str(exc)})

    def send_file(self, path):
        import mimetypes
        raw = path.read_bytes()
        self.send_response(200)
        self.headers_common()
        self.send_header('Content-Type', mimetypes.guess_type(str(path))[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        if not self.allowed():
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size <= 0 or size > MAX_BYTES * 4 // 3 + 16384:
                return self.reply(413, {'error': '请求过大或为空'})
            body = json.loads(self.rfile.read(size))
            if self.path == '/api/jobs':
                return self.reply(201, self.server.service.start(body))
            parts = self.path.strip('/').split('/')
            if len(parts) == 4 and parts[:2] == ['api', 'jobs'] and parts[3] in ('pause', 'resume'):
                return self.reply(200, self.server.service.pause(parts[2], parts[3] == 'resume'))
            return self.reply(404, {'error': '接口不存在；盲审本次未开放执行'})
        except (Exception, SystemExit) as exc:
            return self.reply(400, {'error': str(exc)})

def main(argv=None):
    parser = argparse.ArgumentParser(description='FinAgent Web / TUI 共用服务')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--state-dir', default=str(PROJECT_ROOT.parent.parent / 'runtime'))
    parser.add_argument('--origin', default='', help='允许的公开前端 Origin')
    args = parser.parse_args(argv)
    token = os.environ.get('FINAGENT_UI_TOKEN', '')
    if args.host not in ('127.0.0.1', 'localhost', '::1') and not token:
        parser.error('对外监听必须设置 FINAGENT_UI_TOKEN')
    from finagent.report_pipeline import _check_location
    _check_location(Path(args.state_dir) / 'workspaces' / 'location-check', PROJECT_ROOT)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.service = Service(args.state_dir)
    server.origin, server.token = args.origin, token
    print(f'FinAgent Web: http://{args.host}:{args.port}/web\nTUI 浏览器视图: http://{args.host}:{args.port}/tui', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for proc in server.service.processes.values():
            if proc.poll() is None:
                if os.name != 'nt':
                    os.killpg(proc.pid, signal.SIGCONT)
                    os.killpg(proc.pid, signal.SIGTERM)
                else:
                    proc.terminate()
        server.server_close()
    return 0

if __name__ == '__main__':
    sys.exit(main())
