@echo off
rem FinAgent CLI for Windows (no install needed)
set "ROOT=%~dp0.."
set "PY=%ROOT%\.venv\Scripts\python.exe"
if not exist "%PY%" set "PY=python"
set "PYTHONPATH=%ROOT%;%PYTHONPATH%"
"%PY%" -m finagent %*
