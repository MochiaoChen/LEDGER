// 把终端界面导出的 SVG 渲染成 PNG（修正全角宽度、换本片字体后截图）：node tools/svg2png.mjs <svg> <png>
import {launch} from '../browser.mjs';
import {readFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
const [src, out] = process.argv.slice(2);
const svg = execFileSync('python3', ['-I', '-c', `
import sys, re, html, unicodedata
sys.path.insert(0, 'tools'); from tui_inline import fix
s = open(sys.argv[1], encoding='utf-8').read()
s = re.sub(r"@font-face\\s*\\{[^}]*\\}", "", s).replace("Fira Code, monospace", '"Maple Mono", monospace').replace("font-family: arial", 'font-family: "Maple Mono"')
s = re.sub(r'(<text [^>]*?)textLength="([\\d.]+)"([^>]*)>([^<]*)</text>', fix, s)
print(s)`, src], {encoding: 'utf8', maxBuffer: 64 << 20});
const font = 'file://' + path.resolve('public/fonts');
const b = await launch();
const p = await b.newPage({viewport: {width: 1531, height: 928}, deviceScaleFactor: 1.5});
await p.setContent(`<html><head><style>@font-face{font-family:"Maple Mono";src:url(${font}/MapleMono-NF-CN-Regular.ttf)}@font-face{font-family:"Maple Mono";font-weight:700;src:url(${font}/MapleMono-NF-CN-Bold.ttf)}body{margin:0}</style></head><body>${svg}</body></html>`, {waitUntil: 'load'});
await p.evaluate(async () => { await document.fonts.load('20px "Maple Mono"', '账A'); await document.fonts.ready; });
await p.locator('svg').first().screenshot({path: out});
await b.close();
console.log(out);
