#!/bin/bash
# 单独编译一个或多个章节文件，检查 LaTeX 错误（互不干扰，可并发）。
# 用法：bash check.sh sections/06_extraction.tex [sections/07_analysis.tex ...]
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/trcheck.XXXXXX")"
cp "$HERE/neurips_cn.sty" "$HERE/macros.tex" "$HERE/refs.bib" "$TMP/"
cp -r "$HERE/figures" "$TMP/" 2>/dev/null || true
cat "$HERE"/bib/*.bib >> "$TMP/refs.bib" 2>/dev/null || true
{
  echo '\documentclass[fontset=mac,zihao=5]{ctexart}'
  echo '\usepackage{neurips_cn}'
  echo '\input{macros}'
  echo '\begin{document}'
  for f in "$@"; do echo "\\input{$HERE/$f}"; done
  echo '\bibliographystyle{plainnat}\bibliography{refs}'
  echo '\end{document}'
} > "$TMP/main.tex"
cd "$TMP"
xelatex -interaction=nonstopmode -halt-on-error main.tex > build.log 2>&1 || { grep -n -A8 '^!' build.log | head -60; echo "FAILED (log: $TMP/build.log)"; exit 1; }
bibtex main > /dev/null 2>&1 || true
xelatex -interaction=nonstopmode main.tex > /dev/null 2>&1 || true
xelatex -interaction=nonstopmode main.tex > build.log 2>&1 || true
grep -E 'Overfull \\hbox \(([3-9][0-9]|[0-9]{3,})' build.log | head -10 || true
grep -E 'Citation .* undefined' build.log | sort -u | head -20 || true
echo "OK pages=$(grep -o 'Output written on main.pdf ([0-9]* page' build.log | grep -o '[0-9]* page' | head -1)  pdf=$TMP/main.pdf"
