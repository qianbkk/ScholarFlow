@echo off
REM ScholarFlow 后端启动器 (R10.5.1 重写)
REM 由 scholarflow.bat 通过 start /MIN 调用, 参数 %1 = 项目根目录绝对路径
REM 设计目标:
REM   1. 无嵌套引号 — 启动器独立 .bat, 没有 start "..." cmd /k "..." 的解析问题
REM   2. 总是先写日志 (即使 uvicorn 启动失败也能看到原因)
REM   3. 失败时 pause 保留窗口, 用户可以读错误信息
chcp 65001 >nul
setlocal EnableExtensions

REM 接受根目录参数 (来自 scholarflow.bat)
set "ROOT=%~1"
if "%ROOT%"=="" set "ROOT=%~dp0.."
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

REM 建日志目录
if not exist "%ROOT%\logs" mkdir "%ROOT%\logs"

REM 切到项目根
cd /d "%ROOT%"

REM 写启动头 (后续 uvicorn 输出都 append 到这)
echo ============================================================ > "%ROOT%\logs\backend.log"
echo ScholarFlow 后端启动 [PID %~f0 invocation] >> "%ROOT%\logs\backend.log"
echo 时间: %date% %time% >> "%ROOT%\logs\backend.log"
echo 项目根: %ROOT% >> "%ROOT%\logs\backend.log"
echo 当前目录: %CD% >> "%ROOT%\logs\backend.log"
echo ============================================================ >> "%ROOT%\logs\backend.log"
echo. >> "%ROOT%\logs\backend.log"

REM 环境检查 (写入日志)
where python >> "%ROOT%\logs\backend.log" 2>&1
echo. >> "%ROOT%\logs\backend.log"

REM 设置编码 (重要: 让 uvicorn 日志正确显示中文)
set PYTHONIOENCODING=utf-8

REM 启动 uvicorn (前台运行, 输出到日志)
echo [启动] python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 >> "%ROOT%\logs\backend.log"
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 >> "%ROOT%\logs\backend.log" 2>&1
set "EXITCODE=%ERRORLEVEL%"

REM uvicorn 退出后记录 (如果是因为错误退出会到这里)
echo. >> "%ROOT%\logs\backend.log"
echo [退出] uvicorn 退出码: %EXITCODE% >> "%ROOT%\logs\backend.log"
echo [提示] 按任意键关闭此窗口 >> "%ROOT%\logs\backend.log"
pause >nul
endlocal
