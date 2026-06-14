"""
scholarflow.py 启动管理器烟雾测试 (R10.5.23).

回归保护: 之前 R10.5.20 vite proxy 错改到 8766 + bat 脚本默认 8000,
        用户看到 "前端连不上后端" 困惑 30 分钟. 现在固化配置:
          - BACKEND_PORT 默认 8000
          - FRONTEND_PORT 默认 5173
          - frontend/vite.config.ts proxy target 跟 BACKEND_PORT 同步

测试策略: 静态分析源文件 (不真 import, 避免 conftest env 副作用).
"""
from __future__ import annotations

import re
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest


SCHOLARFLOW_PY = (ROOT / "scholarflow.py").read_text(encoding="utf-8")
VITE_CFG = (ROOT / "frontend" / "vite.config.ts").read_text(encoding="utf-8")


# ===== Test 1: vite.config.ts proxy target = BACKEND_PORT 默认值 (8000) =====
def test_vite_proxy_target_aligned():
    """R10.5.23: vite.config.ts proxy target 必须跟 scholarflow.py BACKEND_PORT 默认同步.

    防 R10.5.20 错改 8766 的回归. 静态读文件验证.
    """
    m = re.search(r"target:\s*['\"]http://127\.0\.0\.1:(\d+)", VITE_CFG)
    assert m, "vite.config.ts missing '/api' proxy target"
    target_port = int(m.group(1))
    assert target_port == 8000, (
        f"vite proxy target port {target_port} != BACKEND_PORT default 8000. "
        f"R10.5.20 坑: 错改 8766 导致前端连不上后端."
    )


# ===== Test 2: vite.config.ts server.port = 5173 =====
def test_vite_server_port_default_5173():
    """vite.config.ts server.port 默认 5173 跟 scholarflow.py FRONTEND_PORT 对齐."""
    m = re.search(r"port:\s*(\d+)", VITE_CFG)
    assert m, "vite.config.ts missing server.port"
    assert int(m.group(1)) == 5173


# ===== Test 3: scholarflow.py 公开 API 都在 =====
def test_scholarflow_manager_exposes_api():
    """scholarflow.py 公开 API: start_local / stop_local / BACKEND_PORT / FRONTEND_PORT."""
    for name in ("def start_local(", "def stop_local(",
                 "BACKEND_PORT =", "FRONTEND_PORT =",
                 "def port_in_use("):
        assert name in SCHOLARFLOW_PY, f"missing public API: {name!r}"


# ===== Test 4: BACKEND_PORT 默认 8000 =====
def test_backend_port_default_8000():
    """R10.5.23: BACKEND_PORT 默认 8000, 跟 vite.config.ts proxy target 同步."""
    m = re.search(r'BACKEND_PORT\s*=\s*int\(os\.environ\.get\(["\']BACKEND_PORT["\'],\s*["\'](\d+)["\']\)\)', SCHOLARFLOW_PY)
    assert m, "BACKEND_PORT not declared as int(os.environ.get('BACKEND_PORT', '...'))"
    assert int(m.group(1)) == 8000


# ===== Test 5: FRONTEND_PORT 默认 5173 =====
def test_frontend_port_default_5173():
    """FRONTEND_PORT 默认 5173, 跟 vite.config.ts server.port 一致."""
    m = re.search(r'FRONTEND_PORT\s*=\s*int\(os\.environ\.get\(["\']FRONTEND_PORT["\'],\s*["\'](\d+)["\']\)\)', SCHOLARFLOW_PY)
    assert m, "FRONTEND_PORT not declared as int(os.environ.get('FRONTEND_PORT', '...'))"
    assert int(m.group(1)) == 5173


# ===== Test 6: port_in_use 逻辑行为 (在源码外独立测 socket) =====
def test_socket_bind_and_release_semantics():
    """port_in_use 依赖 socket.connect, 用真 socket 测占用 / 释放行为.

    不直接 import scholarflow.py (避免 conftest 副作用), 仅验证基础假设.
    """
    free_port = 49152
    # 占用端口
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", free_port))
    s.listen(1)
    # 验证 connect 成功
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        try:
            probe.connect(("127.0.0.1", free_port))
            in_use = True
        except (ConnectionRefusedError, socket.timeout, OSError):
            in_use = False
    s.close()
    assert in_use is True, "socket.connect 应对 bind+listen 的端口成功"
    # 释放后 connect 应失败
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        try:
            probe.connect(("127.0.0.1", free_port))
            in_use = True
        except (ConnectionRefusedError, socket.timeout, OSError):
            in_use = False
    assert in_use is False, "socket.close 后 connect 应失败"


# ===== Test 7: start_local 端口冲突时打印 taskkill 指引 =====
def test_start_local_includes_taskkill_hint():
    """R10.5.23: 端口冲突时给 taskkill + set BACKEND_PORT 指引, 不静默 fail."""
    # 静态检查 start_local 包含指引字符串
    assert "taskkill" in SCHOLARFLOW_PY, "missing taskkill hint in start_local"
    assert "BACKEND_PORT" in SCHOLARFLOW_PY, "missing BACKEND_PORT env hint in start_local"
    # 错误信息要醒目
    assert "already in use" in SCHOLARFLOW_PY, "missing 'already in use' error msg"


# ===== Test 8: vite proxy 注释里说明端口 8000 跟 bat 脚本同步 =====
def test_vite_config_documents_8000_alignment():
    """vite.config.ts proxy target 注释里说明 8000 来源, 防未来误改."""
    assert "R10.5.23" in VITE_CFG or "scholarflow.py" in VITE_CFG, (
        "vite.config.ts proxy 注释应说明 8000 跟 scholarflow.py 对齐"
    )
    assert "8000" in VITE_CFG, "vite.config.ts 注释应包含 8000"


# ===== Test 9: BACKEND_PORT env 化 (用户可手动指定) =====
def test_backend_port_overridable_via_env():
    """BACKEND_PORT 从 env 读, 用户可设 BACKEND_PORT=8766 避开冲突."""
    assert 'os.environ.get("BACKEND_PORT"' in SCHOLARFLOW_PY


# ===== Test 10: status 命令在没服务时也能跑 =====
def test_status_function_exists():
    """show_status() 是 scholarflow.py 公开 API, 验证存在."""
    assert "def show_status(" in SCHOLARFLOW_PY
    # status 读 PID 文件 + port 探测, 不应依赖具体服务在跑
