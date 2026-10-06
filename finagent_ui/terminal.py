"""真实 Textual 终端驾驶舱；与网页共用 HTTP 服务，不复制生产流程。"""
import argparse
import asyncio
import json
import os
import base64
from pathlib import Path
import urllib.request
import webbrowser
from rich.text import Text
from rich.table import Table
from rich.console import Group
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Footer, Input, Label, Static
from textual.screen import ModalScreen
from .state import ROLES, STAGES, empty

class Upload(ModalScreen):
    def compose(self):
        with Vertical(id='upload-box'):
            yield Label('上传 / 更换年报 PDF')
            yield Input(placeholder='年报 PDF 的绝对路径', id='pdf-path')
            yield Input(placeholder='公司名称', id='company')
            yield Input(placeholder='年报年度，如 2025', id='year', type='integer')
            yield Label('确认开始即表示同意使用这份尚未在来源清单核验的年报。')
            yield Label('执行原项目五角色；不启动盲审。')
            with Horizontal():
                yield Button('取消', id='cancel')
                yield Button('确认上传并开始', id='start', variant='primary')
            yield Static('', id='upload-error')

    async def on_button_pressed(self, event):
        if event.button.id == 'cancel':
            self.dismiss()
        elif event.button.id == 'start':
            try:
                pdf = Path(self.query_one('#pdf-path', Input).value).expanduser()
                if not pdf.is_file() or pdf.stat().st_size > 100 * 1024 * 1024:
                    raise ValueError('请选择不超过 100 MB 的 PDF 文件')
                payload = dict(filename=pdf.name, company=self.query_one('#company', Input).value,
                    year=int(self.query_one('#year', Input).value),
                    content=base64.b64encode(pdf.read_bytes()).decode(), allow_unverified=True)
                event.button.disabled = True
                result = await asyncio.to_thread(self.app.request, '/api/jobs', payload)
                self.app.job_id = result['id']
                self.dismiss()
                await self.app.refresh_state()
            except Exception as exc:
                self.query_one('#upload-error', Static).update(str(exc))
                event.button.disabled = False

class Cockpit(App):
    CSS_PATH = Path(__file__).with_name('terminal.tcss')
    TITLE = 'FinAgent'
    BINDINGS = [('n','upload','新建任务'),('u','upload','更换年报'),('r','refresh','刷新'),
                ('w','web','Web'),('p','pause','暂停/继续'),('o','pdf','研报'),('x','xlsx','Excel'),('q','quit','退出')]
    def __init__(self, api):
        super().__init__()
        self.api = api.rstrip('/')
        self.token = os.getenv('FINAGENT_UI_TOKEN', '')
        self.job_id = ''
        self.data = empty()
        self.tick = 0
        self.blind = False

    def compose(self) -> ComposeResult:
        with Horizontal(id='top'):
            yield Static('▌ FinAgent', id='brand')
            yield Static('等待上传年报', id='filename')
            yield Button('上传 / 更换年报', id='upload-button')
            yield Button('切换 Web', id='web-button')
            yield Static('IDLE', id='status')
        with Horizontal(id='body'):
            with Vertical(id='sessions'):
                yield Static('AGENT SESSIONS', classes='caption')
                for i, r in enumerate(ROLES):
                    yield Static(f'{i+1:02d}  {r[0]}\n    等待中', id=f'role-{i}', classes='role')
                yield Button('□ 盲审质检员', id='blind')
                yield Static('独立选项 · 仅评分\n本次不执行盲审，不改交付物。', id='blind-info')
                yield Static('AGENT TOPOLOGY\n5 Agents · 11 Steps', id='topology')
            with Vertical(id='center'):
                yield Static('', id='flow')
                yield Label('证据流   LIVE   当前阶段：等待输入', id='stream-title')
                yield DataTable(id='evidence', cursor_type='row', zebra_stripes=True)
                with Horizontal(id='detail'):
                    yield Static('证据详情\n\n等待原项目事实与来源。', id='fact-detail')
                    yield Static('原始数据来源\n\n上传后按来源页码定位年报。', id='source-detail')
            with Vertical(id='right'):
                yield Static('GATE STATUS', id='gate')
                yield Static('FINAL DELIVERABLES\n\n深度研报 PDF   等待生成\n\n估值模型 Excel   等待生成', id='deliverables')
        yield Footer()

    def request(self, path, payload=None):
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        request = urllib.request.Request(self.api + path,
            data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                message = json.load(exc).get('error', str(exc))
            except Exception:
                message = str(exc)
            raise ValueError(message) from exc

    async def on_mount(self):
        self.query_one('#evidence', DataTable).add_columns('#','类型 / 指标','内容','来源','状态')
        self.set_interval(3, self.refresh_state)
        self.set_interval(.2, self.animate)
        await self.refresh_state()

    async def refresh_state(self):
        try:
            path = '/api/state' + ('?id=' + self.job_id if self.job_id else '')
            data = await asyncio.to_thread(self.request, path)
            self.data = data
            self.job_id = data.get('id', self.job_id)
            self.query_one('#filename', Static).update(data.get('file') or '等待上传年报')
            self.query_one('#status', Static).update(f"{data['status'].upper()}  {data.get('elapsed',0)//60:02d}:{data.get('elapsed',0)%60:02d}")
            stage = data['stage']
            for i, r in enumerate(ROLES):
                completed = all(data['stages'][n-1]['ok'] for n in r[1])
                active = stage in r[1] and data['status'] not in ('idle','complete')
                widget = self.query_one(f'#role-{i}', Static)
                widget.set_class(active, 'active')
                label = '已完成' if completed else '运行中' if active else '等待中'
                widget.update(Text(f'{i+1:02d}  {r[0]}\n    {label}' + (f'\nSKILL  {r[2]}' if active else ''), style='green' if completed else 'cyan' if active else 'white'))
            table = self.query_one('#evidence', DataTable)
            cursor = table.cursor_row
            table.clear()
            for i, e in enumerate(data.get('evidence', [])):
                table.add_row(str(i+1), str(e['name']), str(e['value']), str(e['source'].get('page') or '—'), e['status'])
            if table.row_count:
                table.move_cursor(row=min(cursor,table.row_count-1))
            self.query_one('#stream-title', Label).update(f'证据流   LIVE   当前阶段：{stage:02d} {STAGES[stage-1]}')
            self.query_one('#gate', Static).update(Text(f"GATE STATUS\n\nGATE-{stage:02d} {STAGES[stage-1]}\n\n{data.get('detail','')}\n\n下一步：\n{data.get('next','')}\n\n状态读取原项目 status；动画不代表通过。",style='bright_cyan'))
            files = data.get('artifacts', [])
            pdf = next((a for a in files if a['final'] and a['name'].endswith('.pdf')),None)
            xlsx = next((a for a in files if a['final'] and a['name'].endswith('.xlsx')),None)
            self.query_one('#deliverables',Static).update(f"FINAL DELIVERABLES\n\n深度研报 PDF\n{pdf['name'] if pdf else '等待全部闸门通过'}\n\n估值模型 Excel\n{xlsx['name'] if xlsx else '等待全部闸门通过'}")
            self.animate()
        except Exception as exc:
            self.query_one('#status',Static).update('连接未建立')
            self.query_one('#gate',Static).update(f'GATE STATUS\n\n{exc}\n\n请先启动 finagent web 服务。')

    def animate(self):
        self.tick += 1
        wave = ['▁▂▃▅▇▅▃▂','▂▃▅▇▅▃▂▁','▃▅▇▅▃▂▁▂','▅▇▅▃▂▁▂▃'][self.tick%4]
        flow = Text('执行流程  11 个阶段 · 多 Agent 协同 · 从数据到研报\n\n',style='bold white')
        for r in ROLES:
            flow.append(f"{r[0]} ({r[1][0]:02d}{'-'+str(r[1][-1]).zfill(2) if len(r[1])>1 else ''})  ",style='cyan')
        flow.append('\n')
        grid = Table.grid(expand=True, padding=(0, 0))
        cells = []
        for i, n in enumerate(STAGES):
            grid.add_column(ratio=1)
            passed = self.data['stages'][i]['ok']
            active = self.data['stage'] == i+1 and self.data['status'] in ('running','paused')
            color = '#00efa0' if passed else ('bold #ffd02c' if self.tick%2 else '#ffe781') if active else '#90baff'
            label = ('✓' if passed else str(i+1).zfill(2)) + '\n' + '\n'.join(n[j:j+3] for j in range(0,len(n),3))
            cells.append(Text(label,style=color,justify='center'))
        grid.add_row(*cells)
        self.query_one('#flow',Static).update(Group(flow,grid))
        self.query_one('#topology',Static).update(Text(f"AGENT TOPOLOGY\n5 Agents · 11 Steps\n{len(self.data.get('evidence',[]))} Evidence\n{self.data['status'].upper()}  {wave}",style='cyan'))

    def on_data_table_row_highlighted(self,event):
        evidence = self.data.get('evidence',[])
        if event.cursor_row >= len(evidence):
            return
        e = evidence[event.cursor_row]
        self.query_one('#fact-detail',Static).update(Text(f"证据详情\n\n指标名称　{e['name']}\n数值　{e['value']}\n报告期　{e['period']}\n分类　{e['status']}",style='white'))
        self.query_one('#source-detail',Static).update(Text('原始数据来源\n\n'+json.dumps(e['source'],ensure_ascii=False,indent=2),style='bright_cyan'))

    async def on_button_pressed(self,event):
        if event.button.id == 'upload-button':
            self.action_upload()
        elif event.button.id == 'web-button':
            self.action_web()
        elif event.button.id == 'blind':
            self.blind = not self.blind
            event.button.label = ('☑' if self.blind else '□') + ' 盲审质检员'
            self.notify('仅记录独立选项，不执行盲审，不改交付物。')

    def action_upload(self):
        self.push_screen(Upload())
    async def action_refresh(self):
        await self.refresh_state()
    def action_web(self):
        webbrowser.open(self.api + '/web')
    async def action_pause(self):
        try:
            if not self.job_id or self.data['status'] not in ('running','paused'):
                raise ValueError('当前没有可以暂停的任务')
            action = 'resume' if self.data['status']=='paused' else 'pause'
            await asyncio.to_thread(self.request, f'/api/jobs/{self.job_id}/{action}', {})
            await self.refresh_state()
        except Exception as exc:
            self.notify(str(exc),severity='error')
    def open_artifact(self, ext):
        # 本地终端仅打开本地工作区已有产物；远程服务通过 Web 下载。
        artifact = next((a for a in self.data.get('artifacts',[]) if a['final'] and a['name'].endswith(ext)),None)
        if not artifact:
            self.notify('交付物尚未生成',severity='warning')
            return
        path = Path(self.data.get('workspace','')) / artifact['path']
        if path.is_file():
            webbrowser.open(path.as_uri())
        else:
            self.action_web()
    def action_pdf(self):
        self.open_artifact('.pdf')
    def action_xlsx(self):
        self.open_artifact('.xlsx')

def main(argv=None):
    parser = argparse.ArgumentParser(description='与样板布局对应的真实终端 TUI')
    parser.add_argument('--api',default='http://127.0.0.1:8765')
    args = parser.parse_args(argv)
    Cockpit(args.api).run()
    return 0

if __name__ == '__main__':
    main()
