#!/bin/bash
# 编译项目计划书：bash build.sh
cd "$(dirname "$0")" && latexmk -xelatex -interaction=nonstopmode -halt-on-error main.tex >/dev/null 2>&1
status=$?
grep -E "^! |Error" main.log | head -20
pdfinfo main.pdf 2>/dev/null | grep Pages
exit $status
