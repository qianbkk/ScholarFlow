@echo off
REM ScholarFlow 前端启动器 (R10.5.1 重写)
REM 由 scholarflow.bat 通过 start /MIN 调用, 参数 %1 = 项目根目录绝对路径
REM 设计目标同 _start_backend.bat: 无嵌套引号 + 总是先写日志 + 失败 pause
chcp 65001 >nul
setlocal EnableExtensions

REM 接受根目录参数
set "ROOT=%~1"
if "%ROOT%"=="" set "ROOT=%~dp0.."
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

REM 建日志目录
if not exist "%ROOT%\logs" mkdir "%ROOT%\logs"

REM 切到 frontend 目录
cd /d "%ROOT%\frontend"

REM 写启动头
echo ============================================================ > "%ROOT%\logs\frontend.log"
echo ScholarFlow 前端启动 [vite dev server] >> "%ROOT%\logs\frontend.log"
echo 时间: %date% %time% >> "%ROOT%\logs\frontend.log"
echo 项目根: %ROOT% >> "%ROOT%\logs\frontend.log"
echo 当前目录: %CD% >> "%ROOT%\logs\frontend.log"
echo ============================================================ >> "%ROOT%\logs\frontend.log"
echo. >> "%ROOT%\logs\frontend.log"

REM 环境检查
where npx >> "%ROOT%\logs\frontend.log" 2>&1
where node >> "%ROOT%\logs\frontend.log" 2>&1
echo. >> "%ROOT%\logs\frontend.log"

REM 检查 node_modules 是否存在
if not exist "node_modules" (
    echo [警告] node_modules 不存在, 尝试 npm install... >> "%ROOT%\logs\frontend.log"
    call npm install >> "%ROOT%\logs\frontend.log" 2>&1
    echo. >> "%ROOT%\logs\frontend.log"
)

REM 启动 vite
echo [启动] npx vite --host 127.0.0.1 --port 5173 >> "%ROOT%\logs\frontend.log"
call npx vite --host 127.0.0.1 --port 5173 >> "%ROOT%\logs\frontend.log" 2>&1
set "EXITCODE=%ERRORLEVEL%"

REM vite 退出后记录
echo. >> "%ROOT%\logs\frontend.log"
echo [退出] vite 退出码: %EXITCODE% >> "%ROOT%\logs\frontend.log"
echo [提示] 按任意键关闭此窗口 >> "%ROOT%\logs\frontend.log"
pause >nul
endlocal
