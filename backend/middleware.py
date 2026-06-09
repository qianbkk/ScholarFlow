"""
Round 5 M-3: HTTP 安全头中间件 + /docs 门控
"""
import os
from fastapi import FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """添加 7 个 HTTP 安全响应头.

    Headers:
      * X-Content-Type-Options=nosniff — 防止 MIME-sniff
      * X-Frame-Options=DENY — 防止 clickjacking (iframe 嵌入)
      * X-XSS-Protection=1; mode=block — 老 IE/Chrome 反射 XSS 防护
      * Referrer-Policy=no-referrer — 不向第三方泄露 referer
      * Permissions-Policy=geolocation/microphone/camera=() — 关闭敏感 API
      * Strict-Transport-Security=max-age=31536000; includeSubDomains — HSTS 1y
      * Content-Security-Policy=default-src 'none'; ... — 严格 CSP

    CSP 注解:
      * default-src 'none' 拒绝所有默认加载 (API 是纯 JSON, 不会有资源)
      * script-src 'self' 'unsafe-inline' — Swagger UI / FastAPI docs 需 inline JS
      * style-src 'self' 'unsafe-inline' — Swagger UI 需 inline CSS
      * img-src 'self' data: https: — Swagger UI 加载 swagger.io 图片
      * connect-src 'self' — SSE / fetch 限本域
    """

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
        return response


def install_security(app: FastAPI) -> None:
    """注册 SecurityHeadersMiddleware + TrustedHostMiddleware 到 FastAPI app.

    注意: TrustedHostMiddleware 必须先 add (后 add 的 middleware 是外层),
    SecurityHeaders 在外层 — 所有响应都加安全头,即使是 TrustedHost 拒绝的 400.
    """
    # 1) TrustedHost: 防止 Host header 注入 / cache poisoning
    # 允许 host 走 env ALLOWED_HOSTS 配置,默认 ["*"] (开发期)
    allowed_hosts_env = os.getenv("ALLOWED_HOSTS", "*").strip()
    if allowed_hosts_env == "*":
        allowed_hosts = ["*"]
    else:
        allowed_hosts = [h.strip() for h in allowed_hosts_env.split(",") if h.strip()]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    # 2) SecurityHeaders: 7 个 HTTP 安全响应头
    app.add_middleware(SecurityHeadersMiddleware)
