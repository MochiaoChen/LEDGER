// 统一的浏览器启动入口。Playwright 1.58.1 对应的 headless shell（1208）在本机下载停滞，
// 改用本机已有的 Playwright Chromium headless shell；FILM_CHROME 可指定其他可执行文件。
import {chromium} from 'playwright';
import {existsSync, readdirSync} from 'node:fs';
import {homedir} from 'node:os';
import path from 'node:path';
function localShell() {
  if (process.env.FILM_CHROME) return process.env.FILM_CHROME;
  const cache = path.join(homedir(), 'Library/Caches/ms-playwright');
  if (!existsSync(cache)) return undefined;
  const dirs = readdirSync(cache).filter(d => d.startsWith('chromium_headless_shell-')).sort().reverse();
  for (const d of dirs) for (const sub of ['chrome-headless-shell-mac-arm64', 'chrome-mac', 'chrome-headless-shell-mac-x64']) {
    const exe = path.join(cache, d, sub, 'chrome-headless-shell');
    if (existsSync(exe)) return exe;
  }
  return undefined;
}
export const launch = () => chromium.launch({headless: true, executablePath: localShell(),
  args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist', '--force-color-profile=srgb', '--font-render-hinting=none']});
