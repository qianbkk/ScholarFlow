"""
backend.api.routes.health
==========================

Low-risk endpoints: liveness probe, LLM provider catalog, and root
service descriptor. No business logic, no state — safe to mount first.
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.config import LLM_PROVIDER
from backend.api.services.providers import _get_providers_with_keys

router = APIRouter(tags=["health"])
# R9: /providers enumeration-vector 防护 — 该端点暴露 provider 拓扑 + has_key 状态,
# 高频调用可推断基础设施. 加 30/minute 限流, 前端模型选择器轮询不会触发, 但阻断
# 自动化 enumeration. /health 保留不限流 (k8s/load-balancer 健康检查场景).
limiter = Limiter(key_func=get_remote_address)
# FastAPI 0.115+ compatibility: include_router accesses on_startup/on_shutdown
# directly; ensure defaults exist (this is a no-op on older versions where
# they're already class-level defaults).
router.on_startup = []  # type: ignore[attr-defined]
router.on_shutdown = []  # type: ignore[attr-defined]


@router.get("/health")
async def health():
    """健康检查。"""
    return {
        "status": "ok",
        "service": "ScholarFlow",
        "version": "1.0.0",
    }


@router.get("/providers")
@limiter.limit("30/minute")
async def list_providers(request: Request):
    """返回所有可用 LLM provider 列表（含 has_key 状态 + 默认 provider）。

    前端模型选择器用此端点渲染下拉 — 只展示 has_key=true 的 provider。

    R9: 加 30/minute 限流防止 enumeration vector (审计员 #2 报告)。
    `request: Request` 参数是 slowapi 装饰器所必需, 用于从 Request 提取 client IP.
    """
    return {
        "default_provider": LLM_PROVIDER.lower(),
        "providers": _get_providers_with_keys(),
    }


@router.get("/")
async def root():
    return {
        "service": "ScholarFlow",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": ["GET /health", "GET /providers", "POST /search", "GET /search/stream"],
    }
