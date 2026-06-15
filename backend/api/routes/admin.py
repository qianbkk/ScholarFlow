"""
backend.api.routes.admin
========================

Admin 端点 — runtime mode 切换 (R10.5.20).

R10.5.28 (CG.txt 审计 P1 #5): 从 backend/main.py 抽出来, 减小 main.py
god-object 体积. 跟其它路由一样, 既挂 /api/v1/admin/* 也挂裸 /admin/*
(向后兼容旧客户端).

R10.5.21 (J.txt + K.txt 审计 #1): POST /admin/runtime-mode 严格 admin 鉴权.
依赖 require_admin (backend.auth.dependencies), 任何未授权调用都 401/403.

R10.5.20: 进程级 (per-worker) 状态, 4-worker Gunicorn 部署下每个 worker
独立 (跟 circuit_breaker.py 同模型). 短期接受, R11+ 切到 Redis.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth.dependencies import User, require_admin
from backend.utils.runtime_mode import (
    get_runtime_mode,
    set_runtime_mode,
    is_runtime_mock,
)

logger = logging.getLogger(__name__)


class RuntimeModeResponse(BaseModel):
    mode: str  # "mock" | "real"
    source: str  # "runtime" (前端切了) | "env" (env LLM_MOCK/API_MOCK 兜底)


class RuntimeModeRequest(BaseModel):
    mode: str  # "mock" | "real" | "auto"


async def get_runtime_mode_endpoint() -> RuntimeModeResponse:
    """返回当前 runtime mode + 来源 (env / runtime).

    GET 公开 — 不影响安全, 前端启动时拉取方便, 不暴露任何用户态.
    """
    rt_mode = get_runtime_mode()
    if rt_mode in ("mock", "real"):
        return RuntimeModeResponse(mode=rt_mode, source="runtime")
    return RuntimeModeResponse(
        mode="mock" if is_runtime_mock() else "real",
        source="env",
    )


async def set_runtime_mode_endpoint(
    req: RuntimeModeRequest,
    _admin: User = Depends(require_admin),
) -> RuntimeModeResponse:
    """切换 runtime mode. 'auto' = 恢复 env 行为.

    配置示例 (.env):
        ADMIN_USER_IDS=u_abc123,u_def456
    """
    if req.mode not in ("mock", "real", "auto"):
        raise HTTPException(
            status_code=400,
            detail=f"mode 必须是 mock/real/auto, 收到 {req.mode!r}",
        )
    set_runtime_mode(req.mode)  # type: ignore[arg-type]
    logger.info(f"[admin] runtime_mode → {req.mode} (by {_admin.user_id[:8]}***)")
    return RuntimeModeResponse(
        mode=req.mode,  # type: ignore[arg-type]
        source="runtime",
    )


# ===== Router: 自身挂 /admin/* 即可, 不再需要 main.py 的 add_api_route =====
router = APIRouter(prefix="/admin", tags=["admin"])
# FastAPI 0.115+ compatibility (跟 routes/auth.py 一致: APIRouter 不再含 on_startup)
router.on_startup = []  # type: ignore[attr-defined]
router.on_shutdown = []  # type: ignore[attr-defined]
router.add_api_route(
    "/runtime-mode", get_runtime_mode_endpoint, methods=["GET"],
    response_model=RuntimeModeResponse,
)
router.add_api_route(
    "/runtime-mode", set_runtime_mode_endpoint, methods=["POST"],
    response_model=RuntimeModeResponse,
)
