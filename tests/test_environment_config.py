"""R10.5.12 ENVIRONMENT 模式区分 + 限流分档测试.

覆盖:
  1) ENVIRONMENT 解析 (dev / test / prod + 别名)
  2) RATE_LIMITS 三档 (dev 宽松, test 不限, prod 严格)
  3) SCHOLARFLOW_DB_DIR 按环境区分
  4) config 常量在路由里被正确读取
  5) auth _parse_limit_string 解析 slowapi 风格限制字符串
"""
from __future__ import annotations

import importlib
import os

import pytest


@pytest.fixture
def reload_config(monkeypatch):
    """每个 test 重新 import config 以读取 monkeypatch 设的 env."""
    def _reload(env: str | None = None, db_dir: str | None = None):
        if env is not None:
            monkeypatch.setenv("ENVIRONMENT", env)
        if db_dir is not None:
            monkeypatch.setenv("SCHOLARFLOW_DB_DIR", db_dir)
        import backend.config as c
        importlib.reload(c)
        return c
    return _reload


class TestEnvironmentAliases:
    def test_dev(self, reload_config):
        c = reload_config("dev")
        assert c.ENVIRONMENT == "dev"
        assert c.IS_DEV is True
        assert c.IS_PROD is False
        assert c.IS_TEST is False

    def test_test(self, reload_config):
        c = reload_config("test")
        assert c.ENVIRONMENT == "test"
        assert c.IS_TEST is True

    def test_prod(self, reload_config):
        c = reload_config("prod")
        assert c.ENVIRONMENT == "prod"
        assert c.IS_PROD is True

    def test_development_alias_to_dev(self, reload_config):
        c = reload_config("development")
        assert c.ENVIRONMENT == "dev"
        assert c.IS_DEV is True

    def test_production_alias_to_prod(self, reload_config):
        c = reload_config("production")
        assert c.ENVIRONMENT == "prod"

    def test_testing_alias_to_test(self, reload_config):
        c = reload_config("testing")
        assert c.ENVIRONMENT == "test"

    def test_unknown_falls_back_to_dev(self, reload_config):
        c = reload_config("garbage")
        assert c.ENVIRONMENT == "dev"  # 默认安全档 (限流宽松)


class TestRateLimitsByEnvironment:
    """R10.5.12: 限流按 ENVIRONMENT 分档 — 用户反馈对开发太严."""

    def test_dev_search_relaxed(self, reload_config):
        c = reload_config("dev")
        assert c.RATE_LIMITS_CURRENT["search"] == "30/minute;200/hour"
        # dev 限流明显比 prod 宽松
        assert "30" in c.RATE_LIMITS_CURRENT["search"]

    def test_prod_search_strict_legacy(self, reload_config):
        c = reload_config("prod")
        # prod 保持旧值 5/min 20/hour (用户测试前默认值, 不能放宽以免被滥用)
        assert c.RATE_LIMITS_CURRENT["search"] == "5/minute;20/hour"
        assert c.RATE_LIMITS_CURRENT["search_stream"] == "5/minute;20/hour"

    def test_test_search_unlimited(self, reload_config):
        c = reload_config("test")
        # test 模式限流 1000/minute 实际等于不限 (CI/pytest 不会撞墙)
        assert c.RATE_LIMITS_CURRENT["search"] == "1000/minute"
        assert c.RATE_LIMITS_CURRENT["search_stream"] == "1000/minute"
        assert c.RATE_LIMITS_CURRENT["search_cancel"] == "1000/minute"

    def test_dev_stream_more_relaxed_than_search(self, reload_config):
        c = reload_config("dev")
        # SSE 流式应该比同步更宽松 (用户连续点击刷新更友好)
        assert c.RATE_LIMITS_CURRENT["search_stream"] == "60/minute;500/hour"
        # stream 数字比 search 数字大
        search_n = int(c.RATE_LIMITS_CURRENT["search"].split("/")[0])
        stream_n = int(c.RATE_LIMITS_CURRENT["search_stream"].split("/")[0])
        assert stream_n > search_n


class TestRateLimitParser:
    """auth.py 内部 helper, 解析 slowapi 风格限制字符串."""

    def test_parse_minute_only(self):
        from backend.api.routes.auth import _parse_limit_string
        per_min, per_hour = _parse_limit_string("30/minute")
        assert per_min == 30
        assert per_hour is None

    def test_parse_hour_only(self):
        from backend.api.routes.auth import _parse_limit_string
        per_min, per_hour = _parse_limit_string("200/hour")
        assert per_min is None
        assert per_hour == 200

    def test_parse_combined(self):
        from backend.api.routes.auth import _parse_limit_string
        per_min, per_hour = _parse_limit_string("30/minute;200/hour")
        assert per_min == 30
        assert per_hour == 200

    def test_parse_legacy(self):
        from backend.api.routes.auth import _parse_limit_string
        per_min, per_hour = _parse_limit_string("5/minute;20/hour")
        assert per_min == 5
        assert per_hour == 20

    def test_parse_test_unlimited(self):
        from backend.api.routes.auth import _parse_limit_string
        per_min, per_hour = _parse_limit_string("1000/minute")
        assert per_min == 1000
        assert per_hour is None


class TestDatabaseDir:
    """R10.5.12: SCHOLARFLOW_DB_DIR 按环境区分, 避免测试污染 dev 缓存."""

    def test_explicit_db_dir_wins(self, reload_config):
        c = reload_config("dev", db_dir="/tmp/custom")
        assert c.SCHOLARFLOW_DB_DIR == "/tmp/custom"

    def test_test_uses_tempdir_when_not_explicit(self, reload_config):
        c = reload_config("test", db_dir=None)
        # 测试模式 + 没设 DB_DIR → /tmp (或 Windows TEMP)
        assert "scholarflow_test" in c.SCHOLARFLOW_DB_DIR

    def test_dev_uses_backend_cache(self, reload_config):
        c = reload_config("dev", db_dir="")  # 空字符串 → 不设 env
        # dev 模式 + 没设 DB_DIR env → backend/.cache
        assert c.SCHOLARFLOW_DB_DIR.endswith(".cache")
