"""backend.utils.network — 反向代理后真实 IP 提取 + 网络工具

R10.5 Fix-P0-Audit-1.2 (审计报告 XYZ §1.2):
  旧实现 get_real_ip 在 backend/main.py, health.py / search.py 都要
  `from backend.main import get_real_ip`. main.py 又 import health.py
  / search.py 形成循环依赖.  Python 模块缓存能'刚好不炸'但任何
  __init__.py / 打包工具 / 加载顺序变化都可能炸.
  修复: 把 get_real_ip 提到独立工具模块, 两侧从这导入, 切断循环.

原 main.py 内的 get_real_ip 仍然保留 (向后兼容), 标 deprecated
指向这里, 后续 R11+ 清理.
"""
from __future__ import annotations

import ipaddress

from fastapi import Request
from slowapi.util import get_remote_address


def get_real_ip(request: Request) -> str:
    """R10.5 Fix-N (审计 PPP §4.1): 反向代理后读 X-Forwarded-For 真实 IP.

    默认 get_remote_address 在 Nginx/Cloudflare 后拿到的是代理 IP, 所有真实用户
    共享同一限速桶, 5 个请求后全部 429. 修复: 优先 XFF 头第一段, 配合
    TrustedHostMiddleware 防 IP 伪造.

    返回值: 字符串 IP, 用于 slowapi key_func / 客户端 IP 展示.
    """
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        first = xff.split(",")[0].strip()
        # 仅信任公网 IP, 私有 IP (10.x, 192.168.x) 视为伪造降级到直连
        try:
            ip = ipaddress.ip_address(first)
            if not ip.is_private and not ip.is_loopback:
                return first
        except ValueError:
            pass
    return get_remote_address(request)
