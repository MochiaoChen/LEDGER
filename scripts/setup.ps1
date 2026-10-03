# FinAgent 一键准备环境（Windows PowerShell）：Python 虚拟环境与依赖 → Claude Code → .env → 自检。
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 [-InstallClaude] [-Live]
param([switch]$InstallClaude, [switch]$Live)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$py = if ($env:PYTHON) { $env:PYTHON } elseif (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }
& $py -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) { Write-Host "✗ 需要 Python 3.10+（建议 3.12）"; exit 1 }

Write-Host "== 1/4 Python 虚拟环境"
if (-not (Test-Path .venv)) { & $py -m venv .venv }
$venv = ".venv\Scripts\python.exe"
& $venv -m pip install -q --upgrade pip
& $venv -m pip install -q -r requirements.txt

Write-Host "== 2/4 Claude Code"
if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
  if ($InstallClaude -and (Get-Command npm -ErrorAction SilentlyContinue)) { npm install -g @anthropic-ai/claude-code }
  else { Write-Host "  未安装。需要 Node.js 18+，然后：npm install -g @anthropic-ai/claude-code（或加 -InstallClaude）" }
}
if (Get-Command claude -ErrorAction SilentlyContinue) {
  claude --version
  Write-Host "  登录：订阅用户运行 claude auth login；API 用户在 .env 填 ANTHROPIC_API_KEY"
}

Write-Host "== 3/4 .env"
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "  已从 .env.example 生成 .env，按注释填写" }
else { Write-Host "  已存在，未改动" }

Write-Host "== 4/4 自检"
if ($Live) { & $venv -m finagent.doctor --live } else { & $venv -m finagent.doctor }
exit $LASTEXITCODE
