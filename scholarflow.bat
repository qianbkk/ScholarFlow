@echo off
REM ============================================================
REM   ScholarFlow 一键管理脚本
REM   功能: 启动 / 停止 / 重启 / 状态 / 日志 / 安装 / 清理
REM   支持: 本地模式 (uvicorn + vite) 与 Docker 模式
REM   端口: 后端 8000  前端 5173
REM ============================================================
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

REM 切到脚本所在目录 (无论从哪里双击)
cd /d "%~dp0"

REM ===== 全局常量 =====
set "ROOT=%~dp0"
set "RUN_DIR=%ROOT%.run"
set "LOG_DIR=%ROOT%logs"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=5173"
set "BACKEND_PID_FILE=%RUN_DIR%\backend.pid"
set "FRONTEND_PID_FILE=%RUN_DIR%\frontend.pid"
set "BACKEND_LOG=%LOG_DIR%\backend.log"
set "FRONTEND_LOG=%LOG_DIR%\frontend.log"
set "BACKEND_TITLE=ScholarFlow-Backend"
set "FRONTEND_TITLE=ScholarFlow-Frontend"

REM 首次运行: 建 .run 和 logs 目录
if not exist "%RUN_DIR%" mkdir "%RUN_DIR%"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

REM ===== 工具函数 =====
:print_banner
echo.
echo  ===============================================================
echo    ScholarFlow 一键管理工具  v1.0
echo  ===============================================================
echo    后端  http://127.0.0.1:%BACKEND_PORT%   (uvicorn :%BACKEND_PORT%)
echo    前端  http://127.0.0.1:%FRONTEND_PORT%   (vite :%FRONTEND_PORT%)
echo    API   http://127.0.0.1:%BACKEND_PORT%/docs
echo  ===============================================================
echo.
goto :eof

:get_python
where python >nul 2>&1 && (set "PYTHON=python" & goto :eof)
where py >nul 2>&1 && (set "PYTHON=py -3" & goto :eof)
set "PYTHON="
goto :eof

:get_node
where node >nul 2>&1 && (set "NODE=node") || (set "NODE=")
where npm >nul 2>&1 && (set "NPM=npm") || (set "NPM=")
where npx >nul 2>&1 && (set "NPX=npx") || (set "NPX=")
goto :eof

:get_docker
where docker >nul 2>&1 && (set "DOCKER=docker") || (set "DOCKER=")
where docker-compose >nul 2>&1 && (set "DC=docker-compose") || (set "DC=")
if defined DOCKER (
    docker compose version >nul 2>&1 && (set "DC=docker compose")
)
goto :eof

:port_in_use
set "PORT_USED=0"
netstat -ano | findstr ":%~1 " | findstr "LISTENING" >nul 2>&1 && set "PORT_USED=1"
goto :eof

:port_owners
set "PORT_OWNERS="
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%~1 " ^| findstr "LISTENING"') do (
    if defined PORT_OWNERS (set "PORT_OWNERS=!PORT_OWNERS!,%%P") else (set "PORT_OWNERS=%%P")
)
goto :eof

:is_alive
tasklist /FI "PID eq %~1" 2>nul | findstr /C:"%~1" >nul
goto :eof

:read_pid
set "PID_VAL="
if exist "%~1" (
    set /p PID_VAL=<"%~1"
)
goto :eof

:kill_pid
if "%~1"=="" goto :eof
call :is_alive %~1
if not errorlevel 1 (
    taskkill /F /PID %~1 >nul 2>&1
    echo    [已停止] PID %~1
) else (
    echo    [跳过] PID %~1 已不存在
)
goto :eof

:check_status
call :get_python
call :get_node
echo.
echo  === 运行时状态 ===
echo.

REM 后端
set "BACKEND_STATUS=未运行"
set "BACKEND_PID=-"
call :read_pid "%BACKEND_PID_FILE%"
if defined PID_VAL (
    call :is_alive !PID_VAL!
    if not errorlevel 1 (
        set "BACKEND_STATUS=运行中 (本地)"
        set "BACKEND_PID=!PID_VAL!"
    ) else (
        set "BACKEND_STATUS=PID 文件过期 (PID !PID_VAL! 已死)"
    )
)
call :port_in_use %BACKEND_PORT%
if "!PORT_USED!"=="1" (
    call :port_owners %BACKEND_PORT%
    if "!BACKEND_STATUS!"=="未运行" set "BACKEND_STATUS=外部进程占用端口"
    echo    后端 (:%BACKEND_PORT%)  [!BACKEND_STATUS!]  PID: !BACKEND_PID!  占用进程: !PORT_OWNERS!
) else (
    echo    后端 (:%BACKEND_PORT%)  [!BACKEND_STATUS!]
)

REM 前端
set "FRONTEND_STATUS=未运行"
set "FRONTEND_PID=-"
call :read_pid "%FRONTEND_PID_FILE%"
if defined PID_VAL (
    call :is_alive !PID_VAL!
    if not errorlevel 1 (
        set "FRONTEND_STATUS=运行中 (本地)"
        set "FRONTEND_PID=!PID_VAL!"
    ) else (
        set "FRONTEND_STATUS=PID 文件过期 (PID !PID_VAL! 已死)"
    )
)
call :port_in_use %FRONTEND_PORT%
if "!PORT_USED!"=="1" (
    call :port_owners %FRONTEND_PORT%
    if "!FRONTEND_STATUS!"=="未运行" set "FRONTEND_STATUS=外部进程占用端口"
    echo    前端 (:%FRONTEND_PORT%)  [!FRONTEND_STATUS!]  PID: !FRONTEND_PID!  占用进程: !PORT_OWNERS!
) else (
    echo    前端 (:%FRONTEND_PORT%)  [!FRONTEND_STATUS!]
)

REM 健康检查
echo.
echo  === 健康检查 (curl) ===
curl -s -o nul -w "    后端 /health  HTTP %%{http_code}  耗时 %%{time_total}s\n" "http://127.0.0.1:%BACKEND_PORT%/health" 2>nul
if errorlevel 1 echo    后端 /health  [连接失败]
curl -s -o nul -w "    前端 /        HTTP %%{http_code}  耗时 %%{time_total}s\n" "http://127.0.0.1:%FRONTEND_PORT%/" 2>nul
if errorlevel 1 echo    前端 /        [连接失败]

REM Docker 容器
call :get_docker
if defined DOCKER (
    echo.
    echo  === Docker 容器 ===
    docker ps --filter "name=scholarflow" --format "    {{.Names}}  {{.Status}}  {{.Ports}}" 2>nul
)
echo.
pause
goto :menu

:install_deps
echo.
echo  === 安装依赖 ===
echo.

call :get_python
call :get_node
call :get_docker

set /p CHOICE="  Python 后端依赖? [Y/n]: "
if /i not "!CHOICE!"=="n" (
    if not defined PYTHON (
        echo    [错误] 未找到 python / py 命令, 请先安装 Python 3.11+
    ) else (
        echo    [1/2] 安装后端依赖 (requirements.txt + dev)...
        %PYTHON% -m pip install --upgrade pip
        %PYTHON% -m pip install -r "%ROOT%backend\requirements.txt"
        %PYTHON% -m pip install -r "%ROOT%requirements-dev.txt"
    )
)

set /p CHOICE="  Node 前端依赖? [Y/n]: "
if /i not "!CHOICE!"=="n" (
    if not defined NPM (
        echo    [错误] 未找到 npm 命令, 请先安装 Node.js 18+
    ) else (
        echo    [2/2] 安装前端依赖 (npm install)...
        cd /d "%ROOT%frontend"
        call npm install
        cd /d "%ROOT%"
    )
)

set /p CHOICE="  拉取 Docker 镜像? [y/N]: "
if /i "!CHOICE!"=="y" (
    if not defined DOCKER (
        echo    [错误] 未找到 docker, 跳过
    ) else (
        echo    [3/3] 拉取/构建 Docker 镜像...
        %DC% -f "%ROOT%docker-compose.yml" build
    )
)

echo.
echo    [完成] 依赖安装结束
echo.
pause
goto :menu

:start_local
echo.
echo  === 启动 (本地模式: uvicorn + vite) ===
echo.

call :get_python
call :get_node

if not defined PYTHON (
    echo    [错误] 未找到 python, 无法启动后端
    pause & goto :menu
)
if not defined NPX (
    echo    [错误] 未找到 npx, 无法启动前端
    pause & goto :menu
)

REM 端口占用检查
call :port_in_use %BACKEND_PORT%
if "!PORT_USED!"=="1" (
    echo    [警告] 端口 %BACKEND_PORT% 已被占用:
    netstat -ano | findstr ":%BACKEND_PORT% " | findstr "LISTENING"
    set /p CHOICE="    是否要 kill 占用进程后继续? [y/N]: "
    if /i "!CHOICE!"=="y" (
        for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%BACKEND_PORT% " ^| findstr "LISTENING"') do (
            call :kill_pid %%P
        )
    ) else (
        echo    [取消] 请手动释放端口后重试
        pause & goto :menu
    )
)
call :port_in_use %FRONTEND_PORT%
if "!PORT_USED!"=="1" (
    echo    [警告] 端口 %FRONTEND_PORT% 已被占用:
    netstat -ano | findstr ":%FRONTEND_PORT% " | findstr "LISTENING"
    set /p CHOICE="    是否要 kill 占用进程后继续? [y/N]: "
    if /i "!CHOICE!"=="y" (
        for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%FRONTEND_PORT% " ^| findstr "LISTENING"') do (
            call :kill_pid %%P
        )
    ) else (
        echo    [取消] 请手动释放端口后重试
        pause & goto :menu
    )
)

REM 启动后端 (新窗口, 不阻塞)
echo    [1/2] 启动后端 (uvicorn :%BACKEND_PORT%)...
start "%BACKEND_TITLE%" /MIN cmd /k "cd /d ""%ROOT%"" && set PYTHONIOENCODING=utf-8 && title %BACKEND_TITLE% && %PYTHON% -m uvicorn backend.main:app --host 127.0.0.1 --port %BACKEND_PORT% > ""%BACKEND_LOG%"" 2>&1"

REM 等后端就绪 (最多 30s)
echo    [等待] 后端就绪检查...
set /a TRIES=0
:wait_backend
set /a TRIES+=1
timeout /t 2 /nobreak >nul
curl -s -o nul -w "" "http://127.0.0.1:%BACKEND_PORT%/health" 2>nul
if not errorlevel 1 (
    echo    [OK] 后端就绪
    goto :backend_ready
)
if !TRIES! GEQ 15 (
    echo    [警告] 后端 30s 内未就绪, 请查看 logs\backend.log
    goto :backend_ready
)
goto :wait_backend
:backend_ready

REM 启动前端
echo    [2/2] 启动前端 (vite :%FRONTEND_PORT%)...
cd /d "%ROOT%frontend"
start "%FRONTEND_TITLE%" /MIN cmd /k "cd /d ""%ROOT%frontend"" && title %FRONTEND_TITLE% && %NPX% vite --host 127.0.0.1 --port %FRONTEND_PORT% > ""%FRONTEND_LOG%"" 2>&1"
cd /d "%ROOT%"

REM 等前端就绪
set /a TRIES=0
:wait_frontend
set /a TRIES+=1
timeout /t 2 /nobreak >nul
curl -s -o nul -w "" "http://127.0.0.1:%FRONTEND_PORT%/" 2>nul
if not errorlevel 1 (
    echo    [OK] 前端就绪
    goto :frontend_ready
)
if !TRIES! GEQ 15 (
    echo    [警告] 前端 30s 内未就绪, 请查看 logs\frontend.log
    goto :frontend_ready
)
goto :wait_frontend
:frontend_ready

REM 记录 PID (按窗口标题)
echo    [完成] 服务已启动
echo    后端日志: %BACKEND_LOG%
echo    前端日志: %FRONTEND_LOG%
echo.
set /p OPEN="  是否在浏览器打开? [Y/n]: "
if /i not "!OPEN!"=="n" start "" "http://127.0.0.1:%FRONTEND_PORT%/"
echo.
pause
goto :menu

:start_docker
echo.
echo  === 启动 (Docker 模式) ===
echo.
call :get_docker
if not defined DOCKER (
    echo    [错误] 未找到 docker, 请先安装 Docker Desktop
    pause & goto :menu
)
echo    [1/1] docker compose up -d ...
%DC% -f "%ROOT%docker-compose.yml" up -d --build
echo.
echo    [完成] Docker 容器已启动
echo.
set /p OPEN="  是否在浏览器打开? [Y/n]: "
if /i not "!OPEN!"=="n" start "" "http://127.0.0.1:%FRONTEND_PORT%/"
echo.
pause
goto :menu

:stop_service
echo.
echo  === 停止服务 ===
echo.

REM 1. 按 PID 文件
call :read_pid "%BACKEND_PID_FILE%"
if defined PID_VAL call :kill_pid !PID_VAL!
if exist "%BACKEND_PID_FILE%" del /q "%BACKEND_PID_FILE%"

call :read_pid "%FRONTEND_PID_FILE%"
if defined PID_VAL call :kill_pid !PID_VAL!
if exist "%FRONTEND_PID_FILE%" del /q "%FRONTEND_PID_FILE%"

REM 2. 按窗口标题 (兜底, 防 PID 文件丢失)
echo    [兜底] 按窗口标题查找并停止残留进程...
taskkill /F /FI "WINDOWTITLE eq %BACKEND_TITLE%*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq %FRONTEND_TITLE%*" >nul 2>&1

REM 3. 按端口 (深度兜底, 防 cmd /k 嵌套起新进程)
call :port_in_use %BACKEND_PORT%
if "!PORT_USED!"=="1" (
    set /p CHOICE="    [警告] 端口 %BACKEND_PORT% 仍被占用, 是否强制 kill 占用进程? [y/N]: "
    if /i "!CHOICE!"=="y" (
        for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%BACKEND_PORT% " ^| findstr "LISTENING"') do (
            call :kill_pid %%P
        )
    )
)
call :port_in_use %FRONTEND_PORT%
if "!PORT_USED!"=="1" (
    set /p CHOICE="    [警告] 端口 %FRONTEND_PORT% 仍被占用, 是否强制 kill 占用进程? [y/N]: "
    if /i "!CHOICE!"=="y" (
        for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%FRONTEND_PORT% " ^| findstr "LISTENING"') do (
            call :kill_pid %%P
        )
    )
)

REM 4. Docker
call :get_docker
if defined DOCKER (
    docker ps --filter "name=scholarflow" --format "{{.Names}}" 2>nul | findstr "scholarflow" >nul
    if not errorlevel 1 (
        set /p CHOICE="    [Docker] 检测到 scholarflow 容器, 是否一起停止? [y/N]: "
        if /i "!CHOICE!"=="y" (
            %DC% -f "%ROOT%docker-compose.yml" down
        )
    )
)

echo.
echo    [完成] 已停止
echo.
pause
goto :menu

:restart_service
echo.
echo  === 重启服务 ===
echo.
call :stop_service
echo.
echo    [继续] 现在启动服务...
echo.
set /p MODE="  启动模式: [1] 本地 (默认)  [2] Docker  [0] 取消: "
if "!MODE!"=="2" goto :start_docker
if "!MODE!"=="0" goto :menu
goto :start_local

:show_logs
echo.
echo  === 查看日志 (最后 30 行) ===
echo.
echo    [1] 后端日志
echo    [2] 前端日志
echo    [3] 后端实时 (tail -f, Ctrl+C 退出)
echo    [4] 前端实时 (tail -f, Ctrl+C 退出)
echo    [0] 返回
echo.
set /p LOG_CHOICE="  选择: "
if "!LOG_CHOICE!"=="1" (
    if not exist "%BACKEND_LOG%" (echo    [无] backend.log 不存在) else (
        powershell -NoProfile -Command "Get-Content '%BACKEND_LOG%' -Tail 30"
    )
) else if "!LOG_CHOICE!"=="2" (
    if not exist "%FRONTEND_LOG%" (echo    [无] frontend.log 不存在) else (
        powershell -NoProfile -Command "Get-Content '%FRONTEND_LOG%' -Tail 30"
    )
) else if "!LOG_CHOICE!"=="3" (
    if not exist "%BACKEND_LOG%" (echo    [无] backend.log 不存在) else (
        powershell -NoProfile -Command "Get-Content '%BACKEND_LOG%' -Wait -Tail 30"
    )
) else if "!LOG_CHOICE!"=="4" (
    if not exist "%FRONTEND_LOG%" (echo    [无] frontend.log 不存在) else (
        powershell -NoProfile -Command "Get-Content '%FRONTEND_LOG%' -Wait -Tail 30"
    )
)
echo.
pause
goto :menu

:clean_cache
echo.
echo  === 清理缓存 ===
echo.
echo    [警告] 将删除以下内容:
echo      - backend\.cache\  (SQLite 缓存)
echo      - logs\*.log       (本次运行日志)
echo      - frontend\dist\   (前端构建产物, 不影响 dev)
echo.
set /p CONFIRM="  确认清理? [y/N]: "
if /i not "!CONFIRM!"=="y" (
    echo    [取消]
    pause & goto :menu
)
if exist "%ROOT%backend\.cache" rmdir /s /q "%ROOT%backend\.cache" 2>nul && echo    [OK] backend\.cache
if exist "%ROOT%logs" (
    del /q "%ROOT%logs\*.log" 2>nul && echo    [OK] logs\*.log
)
if exist "%ROOT%frontend\dist" rmdir /s /q "%ROOT%frontend\dist" 2>nul && echo    [OK] frontend\dist
echo.
echo    [完成]
echo.
pause
goto :menu

:open_browser
echo.
start "" "http://127.0.0.1:%FRONTEND_PORT%/"
start "" "http://127.0.0.1:%BACKEND_PORT%/docs"
echo    [完成] 已打开浏览器
echo.
pause
goto :menu

:menu
call :print_banner
echo    [1] 启动 - 本地模式 (uvicorn + vite, 推荐开发用)
echo    [2] 启动 - Docker 模式 (docker-compose)
echo    [3] 停止
echo    [4] 重启
echo    [5] 查看状态
echo    [6] 查看日志
echo    [7] 安装依赖
echo    [8] 清理缓存
echo    [9] 在浏览器打开 (前端 + API 文档)
echo    [0] 退出
echo.
set /p ACT="  请选择 [0-9]: "
if "!ACT!"=="1" goto :start_local
if "!ACT!"=="2" goto :start_docker
if "!ACT!"=="3" goto :stop_service
if "!ACT!"=="4" goto :restart_service
if "!ACT!"=="5" goto :check_status
if "!ACT!"=="6" goto :show_logs
if "!ACT!"=="7" goto :install_deps
if "!ACT!"=="8" goto :clean_cache
if "!ACT!"=="9" goto :open_browser
if "!ACT!"=="0" goto :exit_script
echo    [错误] 无效选择
timeout /t 2 /nobreak >nul
goto :menu

:exit_script
echo.
echo    再见!
echo.
endlocal
exit /b 0
