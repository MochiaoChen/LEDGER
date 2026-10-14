#!/bin/bash
# 用法：tools/sheet.sh 输出.jpg 列数 时间1 时间2 ...   把 evidence/stills 里对应静帧拼成联系表
out=$1; cols=$2; shift 2
args=(); n=0
for t in "$@"; do f=$(printf "evidence/stills/t%06.2f.png" $t); args+=(-i "$f"); n=$((n+1)); done
ffmpeg -v error -y "${args[@]}" -filter_complex "$(for i in $(seq 0 $((n-1))); do printf "[%d:v]scale=960:540[v%d];" $i $i; done)$(for i in $(seq 0 $((n-1))); do printf "[v%d]" $i; done)xstack=inputs=$n:layout=$(for i in $(seq 0 $((n-1))); do printf "%d_%d" $(( (i % cols) * 960 )) $(( (i / cols) * 540 )); [ $i -lt $((n-1)) ] && printf "|"; done):fill=black" -frames:v 1 -q:v 3 "$out"
