"""
backend.api.routes.health
==========================

Low-risk endpoints: liveness probe, LLM provider catalog, and root
service descriptor. No business logic, no state — safe to mount first.
"""
from __future__ import annotations

import logging
import os
import tempfile
import time as _time
from pathlib import Path

from fastapi import APIRouter, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.config import LLM_PROVIDER
from backend.api.services.providers import _get_providers_with_keys
from backend.main import get_real_ip  # R10.5 Fix-N: XFF 代理 IP

router = APIRouter(tags=["health"])
# R9: /providers enumeration-vector 防护 — 该端点暴露 provider 拓扑 + has_key 状态,
# 高频调用可推断基础设施. 加 30/minute 限流, 前端模型选择器轮询不会触发, 但阻断
# 自动化 enumeration. /health 保留不限流 (k8s/load-balancer 健康检查场景).
# R10.5 Fix-N: key_func 改 get_real_ip (XFF 优先).
limiter = Limiter(key_func=get_real_ip)
# FastAPI 0.115+ compatibility: include_router accesses on_startup/on_shutdown
# directly; ensure defaults exist (this is a no-op on older versions where
# they're already class-level defaults).
router.on_startup = []  # type: ignore[attr-defined]
router.on_shutdown = []  # type: ignore[attr-defined]

logger = logging.getLogger(__name__)


def _check_cache_writable() -> dict:
    """R10 (M-20): 验证 backend/.cache 目录 SQLite 可写.

    实际场景: 容器 read_only 根 fs + tmpfs /tmp 之后, SQLite cache DB
    必须能 INSERT/UPDATE 才行. 这个 round-trip 测试:
      1) 在 .cache 目录创建临时 SQLite DB
      2) CREATE TABLE + INSERT 1 行 + SELECT 验证 + DELETE
      3) 删掉测试文件

    返回: {writable: bool, latency_ms: float, error: str|None}
    """
    start = _time.monotonic()
    cache_dir = Path(__file__).resolve().parents[3] / "backend" / ".cache"
    # 兼容: 容器内 / 本地测试
    candidates = [cache_dir, Path("/app/backend/.cache"), Path(tempfile.gettempdir())]
    last_error: str | None = None
    for d in candidates:
        try:
            d.mkdir(parents=True, exist_ok=True)
        except (PermissionError, OSError) as e:
            last_error = f"mkdir {d}: {e}"
            continue
        # round-trip test
        test_db = d / f"_healthcheck_{os.getpid()}.sqlite"
        try:
            import sqlite3
            with sqlite3.connect(str(test_db), timeout=2.0) as conn:
                conn.execute("CREATE TABLE IF NOT EXISTS _hc (id INTEGER PRIMARY KEY, ts REAL)")
                conn.execute("INSERT INTO _hc (ts) VALUES (?)", (_time.time(),))
                rows = conn.execute("SELECT COUNT(*) FROM _hc").fetchone()
                conn.execute("DELETE FROM _hc WHERE id = (SELECT MAX(id) FROM _hc)")
                conn.commit()
            assert rows and rows[0] >= 1, "round-trip count mismatch"
            # 清理
            try:
                test_db.unlink()
            except OSError:
                pass
            latency = (_time.monotonic() - start) * 1000.0
            return {
                "writable": True,
                "latency_ms": round(latency, 2),
                "path": str(d),
                "error": None,
            }
        except Exception as e:
            last_error = f"sqlite at {d}: {e}"
            continue
    latency = (_time.monotonic() - start) * 1000.0
    return {
        "writable": False,
        "latency_ms": round(latency, 2),
        "path": None,
        "error": last_error or "no writable cache directory found",
    }


@router.get("/health")
async def health():
    """健康检查。

    R10 (M-20): 加 SQLite cache 写权限 round-trip 验证 — k8s/docker 健康检查
    不仅看进程在不在, 还要看 cache DB 能否 INSERT (容器 read_only fs 配错就
    会在第一次 /search 报 OperationalError). status 字段:
      - "ok": 全部健康
      - "degraded": cache 不可写但服务可访问 (前端可继续用 mock)
    """
    cache_check = _check_cache_writable()
    status = "ok" if cache_check["writable"] else "degraded"
    resp = {
        "status": status,
        "service": "ScholarFlow",
        "version": "1.0.0",
    }
    # 仅当 cache 异常时附 details, 正常情况不暴露 (减少响应体积 + 信息泄露)
    if not cache_check["writable"]:
        resp["cache"] = cache_check
        logger.warning(f"[health] cache not writable: {cache_check['error']}")
    return resp


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
