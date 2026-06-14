"""
U.txt + U2.txt + U3.txt 审计 #5 修复测试 (R10.5.22).

backend.utils.ssrf_guard 给所有 httpx 客户端加 URL 安全校验, 拦截
内网 IP / loopback / link-local / 云元数据端点扫描攻击.

测试覆盖:
  1. 公网 https 域名通过 (api.semanticscholar.org 等)
  2. loopback IP 拒绝 (127.0.0.1, ::1)
  3. 私有 IP 段拒绝 (RFC 1918: 10.x, 172.16-31.x, 192.168.x)
  4. link-local 拒绝 (169.254.x, AWS / GCP 元数据端点)
  5. localhost 域名拒绝
  6. 非 http(s) scheme 拒绝 (file://, gopher://, ftp://)
  7. allow_http=False 强制 https (除学术白名单)
  8. assert_safe_url 抛 SSRFError
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest

from backend.utils.ssrf_guard import (
    is_safe_url,
    assert_safe_url,
    assert_safe_https_url,
    SSRFError,
)


# ===== Test 1: 公网域名 (白名单) 通过 =====
@pytest.mark.parametrize("url", [
    "https://api.semanticscholar.org/graph/v1/paper/search",
    "https://api.openalex.org/works?search=test",
    "https://api.anthropic.com/v1/messages",
    "https://api.deepseek.com/chat",
    "https://api.crossref.org/works/10.1234/abc",
])
def test_safe_https_urls_pass(url):
    """白名单内的 https 公网 API 全部通过."""
    assert is_safe_url(url) is True
    assert_safe_https_url(url)  # 不抛


# ===== Test 2: loopback IP 拒绝 =====
@pytest.mark.parametrize("url", [
    "http://127.0.0.1/admin",
    "http://127.0.0.1:8080/internal",
    "http://[::1]/",
])
def test_loopback_blocked(url):
    """127.0.0.1 和 IPv6 ::1 全部 block (SSRF 内网扫描基础防御)."""
    assert is_safe_url(url) is False
    with pytest.raises(SSRFError):
        assert_safe_url(url)


# ===== Test 3: RFC 1918 私有 IP 段 =====
@pytest.mark.parametrize("url", [
    "http://10.0.0.1/admin",           # 10/8
    "http://10.255.255.254/api",      # 10/8 上限
    "http://172.16.0.1/internal",     # 172.16/12
    "http://172.31.255.254/internal", # 172.16/12 上限
    "http://192.168.1.1/router",      # 192.168/16
])
def test_rfc1918_blocked(url):
    """RFC 1918 私有 IP 段全部 block."""
    assert is_safe_url(url) is False
    with pytest.raises(SSRFError):
        assert_safe_url(url)


# ===== Test 4: link-local 169.254.x (云元数据) =====
@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",  # AWS / GCP 元数据
    "http://169.254.169.254/computeMetadata/v1/",  # GCP alt
    "http://169.254.0.1/",  # link-local 任意地址
])
def test_link_local_metadata_blocked(url):
    """169.254/16 link-local 是云元数据攻击主目标, 必 block."""
    assert is_safe_url(url) is False
    with pytest.raises(SSRFError):
        assert_safe_url(url)


# ===== Test 5: localhost 域名 =====
@pytest.mark.parametrize("url", [
    "http://localhost/admin",
    "http://localhost.localdomain/",
])
def test_localhost_blocked(url):
    """localhost 解析到 127.0.0.1, 必 block."""
    assert is_safe_url(url) is False


# ===== Test 6: 非 http(s) scheme =====
@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "gopher://127.0.0.1:11211/_FLUSHALL",
    "ftp://internal.server/file",
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
])
def test_non_http_scheme_blocked(url):
    """file/gopher/ftp/javascript/data 全部 block."""
    assert is_safe_url(url) is False
    with pytest.raises(SSRFError):
        assert_safe_url(url)


# ===== Test 7: 强制 https (除白名单) =====
def test_http_blocked_outside_whitelist():
    """非白名单域名强制 https, http 直接拒."""
    assert is_safe_url("http://example.com/foo") is False
    with pytest.raises(SSRFError):
        assert_safe_url("http://example.com/foo")


def test_http_allowed_for_academic_whitelist():
    """白名单学术 API 允许 http (开发代理场景)."""
    # 本地代理转 https, 但域名仍是白名单内
    assert is_safe_url("http://api.semanticscholar.org/test", allow_http=True) is True


def test_assert_safe_https_rejects_http():
    """更严格的 assert_safe_https_url 强制 https."""
    with pytest.raises(SSRFError):
        assert_safe_https_url("http://api.semanticscholar.org/")


# ===== Test 8: SSRFError 异常类型正确 =====
def test_ssrf_error_is_value_error():
    """SSRFError 应继承 ValueError (4xx 客户端错, 不是 5xx 服务端错)."""
    assert issubclass(SSRFError, ValueError)


# ===== Test 9: 异常消息不应泄露内部状态 =====
def test_ssrf_error_message_informative():
    """错误消息应包含 URL + 拦截原因, 方便排障."""
    with pytest.raises(SSRFError) as exc_info:
        assert_safe_url("http://10.0.0.1/admin")
    msg = str(exc_info.value)
    assert "10.0.0.1" in msg
    assert "private" in msg.lower() or "blocked" in msg.lower()


# ===== Test 10: 校验输入容错 (None / 空字符串 / 乱码) =====
@pytest.mark.parametrize("bad", [None, "", "not a url", "   ", "\n\n"])
def test_invalid_url_input_returns_false(bad):
    """垃圾输入返 False (不抛), 让调用方 fallback 跳过."""
    assert is_safe_url(bad) is False  # type: ignore[arg-type]
