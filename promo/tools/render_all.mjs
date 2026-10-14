// 分镜头并行渲染，再无损拼接并配上已核对的混音：
//   node tools/render_all.mjs [--jobs 4] [--only search,code]   （--only 只重渲这些镜头，其余复用 renders/seg/ 里已有的片段）
// 每个镜头调用起步工程的 render.mjs --from --to；拼接前按 render.mjs 的同一套规则核对 plan 与 master 的哈希。
import {createHash} from 'node:crypto';
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {existsSync} from 'node:fs';
import {spawn} from 'node:child_process';
const args = process.argv.slice(2), opt = (k, d) => { const i = args.indexOf(k); return i < 0 ? d : args[i + 1]; };
const plan = JSON.parse(await readFile('plan.json', 'utf8'));
const jobs = Number(opt('--jobs', 4)), only = opt('--only', null)?.split(',');
const out = opt('--output', 'renders/final.mp4');
await mkdir('renders/seg', {recursive: true});
const seg = (s, i) => `renders/seg/${String(i + 1).padStart(2, '0')}-${s.id}.mp4`;
const todo = plan.shots.map((s, i) => ({s, i})).filter(({s, i}) => (only ? only.includes(s.id) : true) || !existsSync(seg(s, i)));
const run = (cmd, a) => new Promise((res, rej) => { const p = spawn(cmd, a, {stdio: ['ignore', 'ignore', 'inherit']}); p.on('error', rej); p.on('close', c => c === 0 ? res() : rej(new Error(`${cmd} ${a.join(' ')} → ${c}`))); });
const t0 = Date.now(); let next = 0;
await Promise.all(Array.from({length: jobs}, async () => {
  while (next < todo.length) { const {s, i} = todo[next++]; await run('node', ['render.mjs', '--from', String(s.start), '--to', String(s.end), '--output', seg(s, i)]); console.log(`${s.id} ✓ ${((Date.now() - t0) / 1000).toFixed(0)}s`); }
}));
const digest = b => createHash('sha256').update(b).digest('hex');
const report = JSON.parse(await readFile('evidence/audio-mix.json', 'utf8'));
if (report.planSha256 !== digest(await readFile('plan.json'))) throw new Error('混音记录与当前 plan 不一致，先重新混音');
if (!report.cues?.length) throw new Error('混音记录里没有音效');
if (digest(await readFile('assets/master.wav')) !== report.master.sha256) throw new Error('master.wav 与混音记录不一致');
await writeFile('renders/seg/list.txt', plan.shots.map((s, i) => `file '${seg(s, i).replace('renders/seg/', '')}'`).join('\n') + '\n');
await run('ffmpeg', ['-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', 'renders/seg/list.txt', '-i', 'assets/master.wav', '-map', '0:v:0', '-map', '1:a:0',
  '-c:v', 'copy', '-c:a', 'aac', '-b:a', '256k', '-ar', '48000', '-t', String(plan.duration), '-movflags', '+faststart', out]);
console.log(out, `${((Date.now() - t0) / 1000).toFixed(0)}s`);
