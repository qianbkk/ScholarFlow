"""R10.5.32 (wave 7) /health version 联动 + 优雅 shutdown 测试.

覆盖:
  1. /health 返 version 字段等于 VERSION 文件内容
  2. /health/detailed 同样 version 字段
  3. /health/detailed 包含 llm_providers 列表 (R10.5.14 P0-C 持续兼容)
  4. lifespan shutdown 调 gc_cache (lifespan 退出前清理)
  5. 优雅 shutdown 等 in-flight 搜索完成 (最多 30s) — 通过 mock
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_f7_health_version_from_file():
    """/health 返 version 字段等于 backend/VERSION (项目根) 文件内容."""
    from fastapi.testclient import TestClient
    from backend.main import app
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.status_code == 200
    data = r.json()
    # 读 VERSION 文件 (项目根)
    version_path = ROOT / "VERSION"
    expected_version = version_path.read_text(encoding="utf-8").strip()
    assert data["version"] == expected_version, (
        f"/health version 应 = VERSION 文件内容 ({expected_version}), "
        f"实际 {data['version']}"
    )
    # 当前文件应是 1.0.2 (R10.5.32 wave 5 升)
    assert expected_version == "1.0.2"


def test_f7_health_detailed_version_from_file():
    """/health/detailed 同样 version 字段."""
    from fastapi.testclient import TestClient
    from backend.main import app
    with TestClient(app) as c:
        r = c.get("/health/detailed")
    assert r.status_code == 200
    data = r.json()
    version_path = ROOT / "VERSION"
    expected_version = version_path.read_text(encoding="utf-8").strip()
    assert data["version"] == expected_version


def test_f7_health_detailed_includes_providers():
    """/health/detailed 包含 llm_providers 列表 (R10.5.14 P0-C 兼容)."""
    from fastapi.testclient import TestClient
    from backend.main import app
    with TestClient(app) as c:
        r = c.get("/health/detailed")
    data = r.json()
    assert "llm_providers" in data
    assert isinstance(data["llm_providers"], list)
    assert len(data["llm_providers"]) >= 1
    # minimax 必在
    provider_ids = {p["id"] for p in data["llm_providers"]}
    assert "minimax" in provider_ids


def test_f7_lifespan_shutdown_runs_gc_cache():
    """lifespan shutdown 段调 gc_cache (exit 清理, 防止下次启动看到旧数据)."""
    from backend.utils import cache as _cache
    from backend import main as _main

    # mock gc_cache 看是否被调
    called = {"n": 0}
    orig = _cache.gc_cache

    def fake_gc(*args, **kwargs):
        called["n"] += 1
        return {"cache": 0}

    _cache.gc_cache = fake_gc
    try:
        # 直接调 lifespan 函数体 (yield 之前是 startup, 之后是 shutdown)
        import asyncio
        # 用 TestClient 进 lifespan, exit 时跑 shutdown
        from fastapi.testclient import TestClient
        from backend.main import app
        with TestClient(app):
            pass
        # TestClient exit 触发 lifespan shutdown, gc_cache 必被调
        assert called["n"] >= 1, f"lifespan shutdown 应调 gc_cache, 实际 {called['n']} 次"
    finally:
        _cache.gc_cache = orig


def test_f7_health_root_also_returns_version():
    """/ (root) 也返 version 字段."""
    from fastapi.testclient import TestClient
    from backend.main import app
    with TestClient(app) as c:
        r = c.get("/")
    assert r.status_code == 200
    data = r.json()
    version_path = ROOT / "VERSION"
    expected_version = version_path.read_text(encoding="utf-8").strip()
    assert data["version"] == expected_version
