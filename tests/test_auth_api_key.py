"""Tests for backend.auth — API Key 认证 + budget 隔离 (R10.5 Fix-P0-B).

覆盖:
  1. _hash_key: 同 key 同 hash, 改 1 字符变 hash
  2. _generate_key: 长度正确, 前缀 sf_, 唯一
  3. _register_user: 返 (User, raw_key), 数据库可查
  4. _lookup_user_by_key: 正确返 User, 无效 key 返 None
  5. issue_key_for_email: 新用户返 raw_key, 老用户返新 raw_key (旧失效)
  6. get_current_user: OPEN_MODE 跳校验; 无 key 401; 错 key 401; 对 key 200
  7. budget 隔离: user_a reserve 不影响 user_b
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
from fastapi import HTTPException

# OPEN_MODE 在测试里默认 True (CI 默认), 单独的认证测试用 monkeypatch 关掉
from backend.auth.dependencies import (
    _hash_key,
    _generate_key,
    _register_user,
    _lookup_user_by_key,
    issue_key_for_email,
    get_current_user,
    OPEN_MODE,
    User,
)
from backend.api.services.budget import (
    _check_and_reserve_budget,
    _return_budget,
    _load_user_budget_from_db,
)


# ===== _hash_key =====

class TestHashKey:
    def test_same_key_same_hash(self):
        assert _hash_key("sf_abc") == _hash_key("sf_abc")

    def test_different_key_different_hash(self):
        assert _hash_key("sf_abc") != _hash_key("sf_abd")

    def test_hash_is_64_hex(self):
        h = _hash_key("sf_test_key")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ===== _generate_key =====

class TestGenerateKey:
    def test_prefix_and_length(self):
        k = _generate_key()
        assert k.startswith("sf_")
        # 32 字节 url-safe = 43 字符 + "sf_" 前缀 = 46
        assert len(k) > 40

    def test_unique(self):
        keys = {_generate_key() for _ in range(100)}
        assert len(keys) == 100  # 100 个全唯一


# ===== _register_user / _lookup_user_by_key =====

class TestRegisterAndLookup:
    def test_register_creates_user_and_returns_key(self, tmp_path, monkeypatch):
        """注册返 (User, raw_key), raw_key 可 lookup 返同 user_id."""
        # 用临时 DB 避免污染
        from backend.utils import cache as cache_mod
        test_db = tmp_path / "test.sqlite"
        monkeypatch.setattr(cache_mod, "_DB", test_db)
        cache_mod._DB_INITIALIZED = False
        # 重新 init
        from backend.utils.cache import _init_db_once
        _init_db_once()

        user, raw_key = _register_user(display_name="Test User")
        assert user.user_id.startswith("u_")
        assert user.display_name == "Test User"
        assert raw_key.startswith("sf_")

        # 用 raw_key 能 lookup 回去
        looked = _lookup_user_by_key(raw_key)
        assert looked is not None
        assert looked.user_id == user.user_id

    def test_lookup_invalid_key_returns_none(self, tmp_path, monkeypatch):
        from backend.utils import cache as cache_mod
        monkeypatch.setattr(cache_mod, "_DB", tmp_path / "test.sqlite")
        cache_mod._DB_INITIALIZED = False
        from backend.utils.cache import _init_db_once
        _init_db_once()

        # 有效注册一个
        _, valid_key = _register_user()
        # 错 key
        looked = _lookup_user_by_key("sf_wrong_key_xxx")
        assert looked is None
        # 仍能 lookup 有效 key
        assert _lookup_user_by_key(valid_key) is not None


# ===== issue_key_for_email =====

class TestIssueKeyForEmail:
    def test_new_email_returns_key(self, tmp_path, monkeypatch):
        from backend.utils import cache as cache_mod
        monkeypatch.setattr(cache_mod, "_DB", tmp_path / "test.sqlite")
        cache_mod._DB_INITIALIZED = False
        from backend.utils.cache import _init_db_once
        _init_db_once()

        email = f"new-{uuid.uuid4().hex[:6]}@example.com"
        key = issue_key_for_email(email, display_name="Test")
        assert key is not None
        assert key.startswith("sf_")

    def test_existing_email_returns_new_key_invalidating_old(self, tmp_path, monkeypatch):
        from backend.utils import cache as cache_mod
        monkeypatch.setattr(cache_mod, "_DB", tmp_path / "test.sqlite")
        cache_mod._DB_INITIALIZED = False
        from backend.utils.cache import _init_db_once
        _init_db_once()

        email = f"existing-{uuid.uuid4().hex[:6]}@example.com"
        key1 = issue_key_for_email(email)
        # 再 issue 同 email → 新 key, 旧 key 失效
        key2 = issue_key_for_email(email)
        assert key1 != key2
        assert _lookup_user_by_key(key1) is None  # 旧失效
        assert _lookup_user_by_key(key2) is not None

    def test_invalid_email_returns_none(self, tmp_path, monkeypatch):
        from backend.utils import cache as cache_mod
        monkeypatch.setattr(cache_mod, "_DB", tmp_path / "test.sqlite")
        cache_mod._DB_INITIALIZED = False
        from backend.utils.cache import _init_db_once
        _init_db_once()

        assert issue_key_for_email("not-an-email") is None
        assert issue_key_for_email("") is None


# ===== get_current_user =====

class TestGetCurrentUser:
    @pytest.mark.asyncio
    async def test_open_mode_returns_dev_user(self, monkeypatch):
        """OPEN_MODE=true 时返 dev-user, 不需要 header."""
        from backend.auth import dependencies
        monkeypatch.setattr(dependencies, "OPEN_MODE", True)
        # 即使没 header, 返 dev-user
        user = await get_current_user(x_api_key=None)
        assert user.user_id == "dev-user"
        assert user.is_dev_user is True

    @pytest.mark.asyncio
    async def test_no_key_in_production_raises_401(self, monkeypatch):
        """OPEN_MODE=false + 无 X-API-Key → 401."""
        from backend.auth import dependencies
        monkeypatch.setattr(dependencies, "OPEN_MODE", False)
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(x_api_key=None)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_key_in_production_raises_401(self, tmp_path, monkeypatch):
        from backend.utils import cache as cache_mod
        monkeypatch.setattr(cache_mod, "_DB", tmp_path / "test.sqlite")
        cache_mod._DB_INITIALIZED = False
        from backend.utils.cache import _init_db_once
        _init_db_once()
        from backend.auth import dependencies
        monkeypatch.setattr(dependencies, "OPEN_MODE", False)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(x_api_key="sf_invalid_xxx")
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_key_in_production_returns_user(self, tmp_path, monkeypatch):
        from backend.utils import cache as cache_mod
        monkeypatch.setattr(cache_mod, "_DB", tmp_path / "test.sqlite")
        cache_mod._DB_INITIALIZED = False
        from backend.utils.cache import _init_db_once
        _init_db_once()
        from backend.auth import dependencies
        monkeypatch.setattr(dependencies, "OPEN_MODE", False)

        _, raw_key = _register_user(display_name="Prod Test")
        user = await get_current_user(x_api_key=raw_key)
        assert user.is_dev_user is False
        assert user.display_name == "Prod Test"


# ===== Budget 隔离 (per-user) =====

class TestBudgetIsolation:
    @pytest.mark.asyncio
    async def test_user_a_reserve_does_not_block_user_b(self, tmp_path, monkeypatch):
        """多用户 budget 隔离: user_a 用光预算, user_b 不受影响."""
        from backend.utils import cache as cache_mod
        monkeypatch.setattr(cache_mod, "_DB", tmp_path / "test.sqlite")
        cache_mod._DB_INITIALIZED = False
        from backend.utils.cache import _init_db_once
        _init_db_once()
        from backend.api.services import budget as budget_mod
        # 单用户 cap 5 美元/小时 (Fix-P0-B)
        # user_a reserve 4.5 美元 (通过)
        await _check_and_reserve_budget(4.5, user_id="user_a_test")
        # user_b reserve 4.5 美元 (独立计数, 通过)
        await _check_and_reserve_budget(4.5, user_id="user_b_test")
        # user_a 再 reserve 1.0 美元 (超 5 上限, 503)
        with pytest.raises(HTTPException) as exc:
            await _check_and_reserve_budget(1.0, user_id="user_a_test")
        assert exc.value.status_code == 503
        # user_b 仍能 reserve 0.5 美元
        await _check_and_reserve_budget(0.5, user_id="user_b_test")

    @pytest.mark.asyncio
    async def test_return_budget_per_user(self, tmp_path, monkeypatch):
        """每个用户的 _return_budget 各自生效."""
        from backend.utils import cache as cache_mod
        monkeypatch.setattr(cache_mod, "_DB", tmp_path / "test.sqlite")
        cache_mod._DB_INITIALIZED = False
        from backend.utils.cache import _init_db_once
        _init_db_once()

        await _check_and_reserve_budget(2.0, user_id="user_return_a")
        await _check_and_reserve_budget(2.0, user_id="user_return_b")
        # user_a 实际只用了 0.5, 退还 1.5
        await _return_budget(1.5, user_id="user_return_a")
        # user_a 现在 spent = 0.5, 还能 reserve 4.0
        await _check_and_reserve_budget(4.0, user_id="user_return_a")
        # user_b 仍 spent = 2.0, 不能再 reserve 多
        with pytest.raises(HTTPException):
            await _check_and_reserve_budget(3.5, user_id="user_return_b")
