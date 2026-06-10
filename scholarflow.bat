@echo off
chcp 65001 >nul
REM ScholarFlow 一键管理 (R10.5.1 重写: .bat 仅作 Python 入口)
REM 真正逻辑在 scholarflow.py 里 (subprocess.Popen + requests 健康检查)
REM 之前 .bat 嵌套引号 / start 命令的兼容性问题全部消除
cd /d "%~dp0"
python scholarflow.py %*
if errorlevel 1 pause
