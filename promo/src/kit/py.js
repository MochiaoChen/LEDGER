// 极简 Python 着色：把一行源码切成 [类名, 文本]，供逐字出现时按字符预算截断。
const RE = /(#.*$)|("""[\s\S]*?"""|\br?"(?:\\.|[^"\\])*"|r?"(?:\\.|[^"\\])*")|\b(def|return|if|is|None|for|in|not|lambda|import|from|and|or|else)\b|\b(\d+(?:\.\d+)?)\b|\b(re|sorted|set|max|len|int|str|dict|list|Any|Chunk|Document)\b|([A-Za-z_]\w*)(?=\()/g;
export function tokenize(line) {
  const out = []; let last = 0, m;
  RE.lastIndex = 0;
  while ((m = RE.exec(line))) {
    if (m.index > last) out.push(['', line.slice(last, m.index)]);
    out.push([m[1] ? 'k-com' : m[2] ? 'k-str' : m[3] ? 'k-kw' : m[4] ? 'k-num' : m[5] ? 'k-bi' : 'k-fn', m[0]]);
    last = m.index + m[0].length;
  }
  if (last < line.length) out.push(['', line.slice(last)]);
  return out;
}
/** 取前 n 个字符的着色片段。 */
export function take(tokens, n) {
  const out = [];
  for (const [c, s] of tokens) { if (n <= 0) break; const a = Array.from(s); out.push([c, a.slice(0, n).join('')]); n -= a.length; }
  return out;
}
