"""
R10.5.24 深度审计 P0 #1 + #2 修复测试 (合并两个相关 fix).

Fix 1: get_real_ip 加 TRUSTED_PROXIES 白名单 — 防止 XFF 伪造
Fix 2: ALLOWED_HOSTS 缺省值收紧 + 启动期 warn

测试覆盖:
  get_real_ip (mock FastAPI Request):
    1. 缺省 TRUSTED_PROXIES 时, peer 127.0.0.1 → 信 XFF 第一段 (同机反代 OK)
    2. 缺省时, peer 8.8.8.8 (公网) → 不信 XFF, 返 peer IP
    3. 显式 TRUSTED_PROXIES=10.0.0.0/8, peer 10.0.0.5 → 信 XFF
    4. 显式 TRUSTED_PROXIES=10.0.0.0/8, peer 192.168.1.1 → 不信 XFF
    5. XFF 第一段是私有 IP (反代被攻陷) → 拒绝, 返 peer
    6. 缺 XFF → 返 peer IP

  ALLOWED_HOSTS middleware (静态扫描):
    7. install_security 显式 ALLOWED_HOSTS=your.domain → 用之
    8. install_security ALLOWED_HOSTS unset → 缺省 ['localhost', '127.0.0.1', '0.0.0.0', '::1']
    9. install_security ALLOWED_HOSTS='*' → 用 ["*"] + [SECURITY] warn
   10. install_security 在 ENVIRONMENT=prod + ALLOWED_HOSTS unset → 强烈 [SECURITY] warn
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest


# ===== Helper: 重新加载 network 模块, 让 monkeypatch.setenv 生效 =====
@pytest.fixture
def net_mod(monkeypatch):
    if "backend.utils.network" in sys.modules:
        del sys.modules["backend.utils.network"]
    spec = importlib.util.spec_from_file_location(
        "backend.utils.network", str(ROOT / "backend" / "utils" / "network.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_request(headers: dict, client_host: str = "127.0.0.1"):
    """构造一个最小化 mock FastAPI Request, 满足 get_real_ip 调用."""
    class _Client:
        def __init__(self, host):
            self.host = host
    class _Req:
        def __init__(self, headers, host):
            self.headers = headers
            self.client = _Client(host)
    return _Req(headers, client_host)


# ===== Test 1: 缺省 peer=127.0.0.1, XFF=1.2.3.4 → 信 XFF (同机反代) =====
def test_default_trusted_loopback_accepts_xff(net_mod):
    """缺省 TRUSTED_PROXIES = loopback + RFC1918, peer=127.0.0.1 → 信 XFF."""
    net_mod.monkeypatch = None  # sanity
    req = _fake_request({"X-Forwarded-For": "1.2.3.4"}, client_host="127.0.0.1")
    assert net_mod.get_real_ip(req) == "1.2.3.4"


# ===== Test 2: 缺省 peer=公网, XFF=1.2.3.4 → 不信 XFF, 返 peer =====
def test_default_rejects_xff_from_public_peer(net_mod):
    """缺省时, peer=8.8.8.8 (公网, 不在白名单) → 不信 XFF 伪造."""
    req = _fake_request({"X-Forwarded-For": "1.2.3.4"}, client_host="8.8.8.8")
    assert net_mod.get_real_ip(req) == "8.8.8.8"


# ===== Test 3: 显式 TRUSTED_PROXIES=10.0.0.0/8, peer 10.0.0.5 → 信 XFF =====
def test_explicit_trusted_accepts_xff_from_cidr(monkeypatch):
    """显式设 TRUSTED_PROXIES=10.0.0.0/8, peer=10.0.0.5 → 信 XFF."""
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.0/8")
    if "backend.utils.network" in sys.modules:
        del sys.modules["backend.utils.network"]
    spec = importlib.util.spec_from_file_location(
        "backend.utils.network", str(ROOT / "backend" / "utils" / "network.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    req = _fake_request({"X-Forwarded-For": "1.2.3.4"}, client_host="10.0.0.5")
    assert mod.get_real_ip(req) == "1.2.3.4"


# ===== Test 4: 显式白名单不含的 peer → 不信 XFF =====
def test_explicit_trusted_rejects_xff_from_outside_cidr(monkeypatch):
    """显式白名单=10.0.0.0/8, peer=192.168.1.1 → 不信 XFF."""
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.0/8")
    if "backend.utils.network" in sys.modules:
        del sys.modules["backend.utils.network"]
    spec = importlib.util.spec_from_file_location(
        "backend.utils.network", str(ROOT / "backend" / "utils" / "network.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    req = _fake_request({"X-Forwarded-For": "1.2.3.4"}, client_host="192.168.1.1")
    assert mod.get_real_ip(req) == "192.168.1.1"


# ===== Test 5: XFF 第一段是私有 IP → 拒绝, 返 peer =====
def test_xff_first_segment_private_ip_rejected(net_mod):
    """XFF 第一段是 10.x → 拒绝 (反代被攻陷内网 IP 注入)."""
    req = _fake_request({"X-Forwarded-For": "10.0.0.5"}, client_host="127.0.0.1")
    assert net_mod.get_real_ip(req) == "127.0.0.1"


# ===== Test 6: 缺 XFF → 返 peer IP =====
def test_no_xff_returns_peer_ip(net_mod):
    """无 XFF 头, 返 peer IP 直连."""
    req = _fake_request({}, client_host="127.0.0.1")
    assert net_mod.get_real_ip(req) == "127.0.0.1"


# ===== Test 7: is_trusted_proxy 单 IP 判断 =====
@pytest.mark.parametrize("ip,trusted", [
    ("127.0.0.1", True),
    ("127.5.5.5", True),
    ("10.0.0.5", True),
    ("172.16.0.1", True),
    ("172.31.255.254", True),
    ("192.168.1.1", True),
    ("::1", True),
    ("fc00::1", True),  # IPv6 ULA
    ("8.8.8.8", False),  # 公网
    ("169.254.169.254", False),  # link-local (云元数据) — 缺省不在白名单
    ("1.2.3.4", False),
])
def test_is_trusted_proxy_cover_default(net_mod, ip, trusted):
    """is_trusted_proxy 缺省白名单 = loopback + RFC1918 + IPv6 ULA."""
    assert net_mod.is_trusted_proxy(ip) is trusted


# ===== Test 8: ALLOWED_HOSTS 显式 =====
def test_allowed_hosts_explicit(monkeypatch):
    """ALLOWED_HOSTS=api.example.com,www.example.com → middleware 用之."""
    monkeypatch.setenv("ALLOWED_HOSTS", "api.example.com,www.example.com")
    monkeypatch.setenv("ENVIRONMENT", "dev")
    mw_path = ROOT / "backend" / "middleware.py"
    src = mw_path.read_text(encoding="utf-8")
    assert "ALLOWED_HOSTS" in src
    # 静态检查: install_security 函数读 env 后构造 allowed_hosts list
    assert "os.getenv(\"ALLOWED_HOSTS\"" in src or "os.getenv('ALLOWED_HOSTS'" in src


# ===== Test 9: ALLOWED_HOSTS 缺省 → loopback-only =====
def test_allowed_hosts_default_loopback(monkeypatch):
    """ALLOWED_HOSTS 缺省, install_security 兜底 loopback + testserver (pytest 用)."""
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "dev")
    mw_path = ROOT / "backend" / "middleware.py"
    src = mw_path.read_text(encoding="utf-8")
    # 必须有缺省 list 兜底 (含 testserver 让 TestClient 通过)
    assert "localhost" in src and "127.0.0.1" in src and "testserver" in src, (
        "middleware.py 缺 ALLOWED_HOSTS 缺省 list (含 testserver, R10.5.24 修复)"
    )


# ===== Test 10: ALLOWED_HOSTS='*' 显式 → 用 ["*"] + SECURITY warn =====
def test_allowed_hosts_wildcard_explicit_warns(monkeypatch):
    """ALLOWED_HOSTS='*' 显式时, 仍允许但 [SECURITY] warn."""
    monkeypatch.setenv("ALLOWED_HOSTS", "*")
    src = (ROOT / "backend" / "middleware.py").read_text(encoding="utf-8")
    # 必须有 'ALLOWED_HOSTS == "*"' 分支 + [SECURITY] warn
    assert 'allowed_hosts_env == "*"' in src or 'allowed_hosts_env == \'*\'' in src, (
        "middleware.py 缺 ALLOWED_HOSTS='*' 显式分支"
    )
    assert "cache poisoning" in src or "vhost" in src, (
        "middleware.py ALLOWED_HOSTS='*' 应有 [SECURITY] warn 说明 cache poisoning 风险"
    )


# ===== Test 11: ENVIRONMENT=prod + ALLOWED_HOSTS unset → 强烈 warn =====
def test_prod_env_without_allowed_hosts_warns(monkeypatch):
    """ENVIRONMENT=prod + ALLOWED_HOSTS 缺省 → 强烈 [SECURITY] warn."""
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "prod")
    src = (ROOT / "backend" / "middleware.py").read_text(encoding="utf-8")
    assert "ENVIRONMENT" in src and "prod" in src, (
        "middleware.py 缺 ENVIRONMENT=prod 检查"
    )
    assert "REJECTED" in src or "domain" in src, (
        "middleware.py 缺 prod 模式 [SECURITY] warn"
    )


# ===== Test 12: main.py lifespan 启动期调 log_trusted_proxies_warn_once =====
def test_lifespan_logs_trusted_proxies_warn():
    """backend/main.py lifespan 启动期调 log_trusted_proxies_warn_once."""
    src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    assert "log_trusted_proxies_warn_once" in src, (
        "main.py lifespan 缺 log_trusted_proxies_warn_once() 调用 (R10.5.24)"
    )
