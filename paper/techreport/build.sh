#!/bin/bash
# 整书编译：合并去重参考文献 → latexmk
set -e
cd "$(dirname "$0")"
python3 - <<'PY'
import re,glob
seen={};out=[]
for f in ['refs.bib']+sorted(glob.glob('bib/*.bib')):
    s=open(f,encoding='utf-8').read()
    for m in re.finditer(r'@\w+\s*\{\s*([^,\s]+)\s*,.*?(?=\n@|\Z)',s,re.S):
        k=m.group(1)
        if k in seen: continue
        seen[k]=f; out.append(m.group(0).strip())
open('allrefs.bib','w',encoding='utf-8').write('\n\n'.join(out)+'\n')
print(len(out),'bib entries')
PY
latexmk -xelatex -interaction=nonstopmode -halt-on-error main.tex > build.log 2>&1 || { grep -n -A6 '^!' main.log | head -40; exit 1; }
grep -E 'multiply defined|Citation.*undefined' main.log | sort -u | head -40 || true
grep -o 'Output written on main.xdv ([0-9]* pages' main.log || true
