"""backend.utils.network — 反向代理后真实 IP 提取 + 网络工具

R10.5 Fix-P0-Audit-1.2 (审计报告 XYZ §1.2):
  旧实现 get_real_ip 在 backend/main.py, health.py / search.py 都要
  `from backend.main import get_real_ip`. main.py 又 import health.py
  / search.py 形成循环依赖.  Python 模块缓存能'刚好不炸'但任何
  __init__.py / 打包工具 / 加载顺序变化都可能炸.
  修复: 把 get_real_ip 提到独立工具模块, 两侧从这导入, 切断循环.

原 main.py 内的 get_real_ip 仍然保留 (向后兼容), 标 deprecated
指向这里, 后续 R11+ 清理.

R10.5.24 (深度审计 P0 #1): 真实 IP 提取在反代环境下必须受 TRUSTED_PROXIES
白名单控制. 旧实现无条件信任 XFF 头第一段公网 IP, 如果攻击者直接打后端
(绕过反代) 自己构造 XFF: 1.2.3.4, 限流就基于伪造 IP, 等于绕过限流.
修复:
  1. 加 TRUSTED_PROXIES env (CIDR 列表, 逗号分隔), 缺省 = 接受 loopback +
     私有 IP (开发期反代通常跑在同机 127.0.0.1 或 172.x 内网).
  2. 直连 IP (peer IP) 不在白名单时, 忽略 XFF, 降级到 peer IP — 不信伪造.
  3. 同时启动期打印一次 [SECURITY] warn, 提醒运维白名单是否合理.
"""
from __future__ import annotations

import ipaddress
import logging
import os

from fastapi import Request
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)


def _parse_trusted_proxies() -> list:
    """TRUSTED_PROXIES env 解析成 IPNetwork 列表. 缺省走 loopback + RFC1918 私有段.

    缺省范围: loopback (127/8, ::1) + RFC 1918 私有 (10/8, 172.16/12, 192.168/16)
    + 唯一本地 IPv6 (fc00::/7). 覆盖单机 dev + 同机反代 + 局域网反代.

    警告: 这是开发期 / 同机房部署的合理默认. 跨机房 / 多层反代必须显式
    设 TRUSTED_PROXIES=<反代 IP 段>, 否则攻击者从公网直连后端 + 自填 XFF
    就能伪造 IP 绕过限流.
    """
    raw = os.getenv("TRUSTED_PROXIES", "").strip()
    if not raw:
        # 缺省: 接受 loopback + RFC 1918 + IPv6 ULA
        return [
            ipaddress.ip_network(n, strict=False)
            for n in ("127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12",
                      "192.168.0.0/16", "fc00::/7")
        ]
    out = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            out.append(ipaddress.ip_network(token, strict=False))
        except ValueError:
            logger.warning(f"[network] TRUSTED_PROXIES ignoring invalid CIDR: {token!r}")
    return out


_TRUSTED_PROXIES = _parse_trusted_proxies()


def is_trusted_proxy(ip_str: str) -> bool:
    """判断 IP 是否在 TRUSTED_PROXIES 白名单内. 用于 XFF 信任判断."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return any(ip in net for net in _TRUSTED_PROXIES)


def log_trusted_proxies_warn_once() -> None:
    """启动期打印 [SECURITY] warn, 提醒运维白名单覆盖范围.

    只打一次 (用模块级 flag, 避免每个请求都刷屏).
    """
    if getattr(log_trusted_proxies_warn_once, "_done", False):
        return
    log_trusted_proxies_warn_once._done = True  # type: ignore[attr-defined]
    nets = ", ".join(str(n) for n in _TRUSTED_PROXIES)
    if os.getenv("TRUSTED_PROXIES"):
        logger.info(f"[network] TRUSTED_PROXIES (explicit) = [{nets}]")
    else:
        logger.warning(
            f"[SECURITY] TRUSTED_PROXIES not set, defaulting to loopback + RFC1918: "
            f"[{nets}]. For production multi-hop reverse proxy, set "
            f"TRUSTED_PROXIES=<反代 IP 段> in .env to avoid XFF spoofing."
        )


def get_real_ip(request: Request) -> str:
    """R10.5 Fix-N (审计 PPP §4.1): 反向代理后读 X-Forwarded-For 真实 IP.

    R10.5.24 (深度审计 P0 #1) 加固: 只有请求来自 TRUSTED_PROXIES 白名单的
    peer IP 时, 才信任 XFF 头第一段. 直连 (peer IP 不在白名单) → 忽略
    XFF, 降级到 peer IP, 防止客户端伪造 XFF 绕过限流.

    返回值: 字符串 IP, 用于 slowapi key_func / 客户端 IP 展示.
    """
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        first = xff.split(",")[0].strip()
        # 仅当 peer IP 是可信反代时, 才把 XFF 第一段当真 IP
        peer_ip = get_remote_address(request)
        if is_trusted_proxy(peer_ip):
            try:
                ip = ipaddress.ip_address(first)
                # XFF 第一段必须是公网 (防止反代被攻陷后内部 IP 注入)
                if not ip.is_private and not ip.is_loopback and not ip.is_link_local:
                    return first
            except ValueError:
                pass
        # peer 不在白名单 OR XFF 格式错 → 降级用 peer IP (不信 XFF)
    return get_remote_address(request)
