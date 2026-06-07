"""
backend.api.routes.health
==========================

Low-risk endpoints: liveness probe, LLM provider catalog, and root
service descriptor. No business logic, no state — safe to mount first.
"""
from __future__ import annotations

from fastapi import APIRouter

from backend.config import LLM_PROVIDER
from backend.api.services.providers import _get_providers_with_keys

router = APIRouter(tags=["health"])
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
async def list_providers():
    """返回所有可用 LLM provider 列表（含 has_key 状态 + 默认 provider）。

    前端模型选择器用此端点渲染下拉 — 只展示 has_key=true 的 provider。
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
