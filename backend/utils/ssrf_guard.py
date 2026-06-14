"""
backend.utils.ssrf_guard — SSRF 防护 (U.txt + U2.txt + U3.txt 审计 #5)

背景: U.txt #2 报告 expand_citations / api 调用可能被恶意 DOI / URL 引到内网或
云元数据端点 (169.254.169.254) 扫描攻击. 实际 audit:
  - citation_expander 只用 paper_id 调 SS API, 自身不发散
  - SS / OA client 默认 follow_redirects=False (httpx 默认), 重定向风险低
  - 但 defense-in-depth 仍然 cheap, 给所有 httpx 调用加 URL 校验

实现: is_safe_url(url) — 拦截私有 IP / loopback / link-local / metadata 段,
       强制 https (允许 http 仅对已知学术 API 域名).

调用方: backend.api.semantic_scholar / openalex 的 _get_client() 在请求前
        检查, 命中拦截直接 raise SSRFError (不是网络错误, 是安全错误).
"""
from __future__ import annotations

import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# 学术 API 白名单 — 仅这些域名可走 http (其他必须 https)
_ACADEMIC_API_DOMAINS = frozenset({
    "api.semanticscholar.org",
    "api.openalex.org",
    "api.crossref.org",
    "api.anthropic.com",
    "api.minimaxi.com",
    "api.moonshot.cn",
    "open.bigmodel.cn",
    "api.deepseek.com",
})


class SSRFError(ValueError):
    """SSRF 拦截异常. 调用方应返 4xx (不是 5xx, 因为是 client 提供了恶意 URL)."""
    pass


def _resolve_and_check(host: str) -> None:
    """DNS 解析 host, 检查所有返回 IP 是否都是公网."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise SSRFError(f"DNS resolve failed for {host!r}: {e}")
    ips = {info[4][0] for info in infos}
    for ip_str in ips:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        # 拦截所有非全球单播地址
        if not ip.is_global:
            raise SSRFError(
                f"SSRF blocked: {host!r} resolves to non-public IP {ip_str} "
                f"(is_private={ip.is_private}, is_loopback={ip.is_loopback}, "
                f"is_link_local={ip.is_link_local}, is_multicast={ip.is_multicast})"
            )
        # 额外拦截 IPv6 link-local + unique local
        if ip.version == 6 and (ip.is_link_local or ip.is_site_local or ip.is_reserved):
            raise SSRFError(f"SSRF blocked: {host!r} resolves to IPv6 non-global {ip_str}")


def is_safe_url(url: str, *, allow_http: bool = False) -> bool:
    """Check URL is safe to fetch. Returns True if safe, False otherwise.

    不抛异常 (适合 check-only 调用). 想强制拦截请用 assert_safe_url().

    检查项:
      1. scheme 必须是 http(s) (allow_http=False 时强制 https)
      2. host 必须能 DNS 解析
      3. 所有解析到的 IP 都必须是公网 (not private/loopback/link-local/metadata)
      4. 不允许 file://, gopher:// 等
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if not allow_http and parsed.scheme != "https":
        # 例外: 学术 API 白名单可走 http (开发代理场景)
        if parsed.hostname not in _ACADEMIC_API_DOMAINS:
            return False
    if not parsed.hostname:
        return False
    try:
        _resolve_and_check(parsed.hostname)
    except SSRFError:
        return False
    return True


def assert_safe_url(url: str, *, allow_http: bool = False) -> None:
    """强制安全检查, 失败抛 SSRFError. 在所有外部 HTTP 请求前调用."""
    if not is_safe_url(url, allow_http=allow_http):
        raise SSRFError(f"SSRF blocked: {url!r}")


def assert_safe_https_url(url: str) -> None:
    """更严格: 强制 https. 给 SS / OA / Anthropic 等生产 API 用."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise SSRFError(f"Expected https URL, got {url!r}")
    assert_safe_url(url, allow_http=False)
