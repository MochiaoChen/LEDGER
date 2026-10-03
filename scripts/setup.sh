#!/usr/bin/env bash
# FinAgent 一键准备环境（macOS / Linux）：Python 虚拟环境与依赖 → Claude Code → .env → 自检。
#   bash scripts/setup.sh                 # 准备环境
#   bash scripts/setup.sh --install-claude  # 缺 Claude Code 时用 npm 全局安装
#   bash scripts/setup.sh --live          # 自检时向生成与质检模型各发一次最小请求
set -euo pipefail
cd "$(dirname "$0")/.."

INSTALL_CLAUDE=0; LIVE=""
for arg in "$@"; do
  case "$arg" in
    --install-claude) INSTALL_CLAUDE=1 ;;
    --live) LIVE="--live" ;;
    *) echo "未知参数：$arg"; exit 2 ;;
  esac
done

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  for c in python3.12 python3; do command -v "$c" >/dev/null 2>&1 && { PY="$c"; break; }; done
fi
[ -n "$PY" ] || { echo "✗ 找不到 Python 3（建议 3.12），请先安装"; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || { echo "✗ Python 版本过低：$("$PY" --version)，需要 3.10+（建议 3.12）"; exit 1; }

echo "== 1/4 Python 虚拟环境（$("$PY" --version)）"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt

echo "== 2/4 Claude Code"
if ! command -v claude >/dev/null 2>&1; then
  if [ "$INSTALL_CLAUDE" = 1 ] && command -v npm >/dev/null 2>&1; then
    npm install -g @anthropic-ai/claude-code
  else
    echo "  未安装。需要 Node.js 18+，然后：npm install -g @anthropic-ai/claude-code（或重跑本脚本加 --install-claude）"
  fi
fi
if command -v claude >/dev/null 2>&1; then
  echo "  $(claude --version)"
  echo "  登录：订阅用户运行 claude auth login；API 用户在 .env 填 ANTHROPIC_API_KEY"
fi

echo "== 3/4 .env"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "  已从 .env.example 生成 .env，按其中注释填写（研报流水线只需 Claude 登录；Agent 版本需 LLM_API_KEY）"
else
  echo "  已存在，未改动"
fi

echo "== 4/4 自检"
.venv/bin/python -m finagent.doctor $LIVE
