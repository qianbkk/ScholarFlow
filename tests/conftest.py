"""Pytest configuration for ScholarFlow tests.

Ensures project root is on sys.path so `backend.*` imports work,
provides fixtures to force API_MOCK + LLM_MOCK mode for hermetic tests,
and provides an autouse fixture that resets all process-global state
(limiter, budget, request_id, in-flight task table) so tests are
truly isolated regardless of execution order.

R8.2 修复 (reviewer feedback 3.4 - 测试隔离):
  旧实现: 只有 test_budget_lifecycle.py自己手动 limiter.reset() + cache DB tmp_path。
  别的 test (request_id_propagation / search_node_semaphore) 共享同一个 limiter,
  跑过 5 次就 429, 失败表现"随机飘"而非稳定可复现。
  新实现: autouse fixture 强制所有测试在 setup/teardown 阶段 reset 全部进程级状态,
  不依赖具体 test 自己 reset。

R10.5 Fix-P0-B: 测试期默认 OPEN_MODE=true (本地开发后门), 避免
没 X-API-Key 头返 401. 显式设此 env, 等价 CI 跑 .env.example 的
OPEN_MODE=true 默认值. 测 auth 行为的 test 会 monkeypatch 关掉.
"""
import os
import sys

# Ensure project root is importable regardless of where pytest is invoked
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# R10.5 Fix-P0-B: 默认开启 OPEN_MODE, 让现有 16 个 budget lifecycle test
# 不需要 X-API-Key header 也能跑 (R10.5 之前的设计).
# test_auth_api_key.py 显式 monkeypatch 改 OPEN_MODE, 测认证分支.
os.environ.setdefault("OPEN_MODE", "true")

# R10.5.12: 默认 ENVIRONMENT=test — pytest/CI 用, 限流最宽松 (1000/min),
# SCHOLARFLOW_DB_DIR 强制 /tmp (或 Windows TEMP), 不污染 dev/prod 真实数据.
# 本地开发者手跑 `pytest` 也是 test 模式 (不会改 backend/.cache).
# 要手动切到 dev 模式跑后端: 在 shell 里 `export ENVIRONMENT=dev && uvicorn ...`
os.environ.setdefault("ENVIRONMENT", "test")
# 测试数据库目录 — 用 tmp_path 模式, 避免跑测试时锁住 dev 缓存
import tempfile
_TEST_DB_DIR = os.path.join(tempfile.gettempdir(), "scholarflow_test")
os.environ.setdefault("SCHOLARFLOW_DB_DIR", _TEST_DB_DIR)
# R10.5.21: admin 端点测试白名单. 默认 dev-user 可改, 跟 OPEN_MODE=true 一致
# (都是 dev 模式). test_admin_runtime_mode_auth.py 的 admin_client fixture
# 会显式 override 此值测 fail-closed 分支.
os.environ.setdefault("ADMIN_USER_IDS", "dev-user")


import pytest


# ===== Autouse: 全局状态 reset (R8.2 修复) =====

@pytest.fixture(autouse=True)
def _reset_global_state(request):
    """强制每个 test 在 setup/teardown 阶段重置全部进程级状态。

    覆盖的状态:
      1. limiter (slowapi): 限流计数器 5/minute;20/hour, 跑过 5 次就 429
      2. in-flight task table (R6 cancel): /search/cancel 用的全局字典

    用 autouse=True 让所有 test 自动获得隔离, 不用具体 test 自己 reset。
    副作用: 如果某个 test 想保留状态(罕见), 可以用 @pytest.mark.allow_global_state 标记。
    """
    if "allow_global_state" in request.keywords:
        yield
        return

    # ===== Setup: 重置到干净基线 =====
    try:
        import backend.main as main_mod
        if hasattr(main_mod, "limiter"):
            main_mod.limiter.reset()
        if hasattr(main_mod, "_in_flight_searches"):
            main_mod._in_flight_searches.clear()
        # R8.3.2 修复: _PROVIDER_HEALTH_CACHE 是 module-level dict,
        # _get_providers_with_keys() 读它算 has_key。如果前面 test 跑过
        # _verify_provider_key 填了 verified=False, 当前 test 的 has_key 会被
        # 错误算成 False (因为 has_key = env_key_present and verified).
        try:
            from backend.api.services import providers as prov_mod
            if hasattr(prov_mod, "_PROVIDER_HEALTH_CACHE"):
                prov_mod._PROVIDER_HEALTH_CACHE.clear()
        except (ImportError, AttributeError):
            pass
        # R9: routes/search.py 暴露独立 limiter (慢 API decorator 需 module-level binding),
        # main.limiter 跟 routes.search.limiter 是不同实例, 不 reset 会导致
        # 跨 test 累计 → 5min 内的 5/minute 限流计数器残留.
        try:
            from backend.api.routes import search as routes_search
            if hasattr(routes_search, "limiter"):
                routes_search.limiter.reset()
        except (ImportError, AttributeError):
            pass
        # R9: log_throttle._THROTTLES 是 module-level dict, should_log 用
        # 5min 窗口 throttle. 跨 test 累计会导致后续 test 在窗口内被吞掉
        # "expected throttled" 日志断言, 测试飘.
        try:
            from backend.utils import log_throttle
            if hasattr(log_throttle, "_THROTTLES"):
                log_throttle._THROTTLES.clear()
        except (ImportError, AttributeError):
            pass
        # R10.5.51 cleanup: 删 backend.utils.semantic_cache 占位桩 (BACKLOG D-008),
        # 语义缓存不再需要清空. 精确 cache SQLite 已走 gc_cache 自动清理.
        # R10.5.20: runtime_mode 旧版是 in-memory dict, 跨 test 残留会导致
        # "auto" 起始假设被打破. R10.5.51 cleanup (BACKLOG D-007): 删 dict-subclass
        # proxy, 改为显式 set_runtime_mode("auto") 重置 (走 SQLite 共享, 跨 worker 一致).
        try:
            from backend.utils import runtime_mode
            runtime_mode.set_runtime_mode("auto")
            runtime_mode._invalidate_cache()
        except (ImportError, AttributeError):
            pass
        # R10.5.21: admin 鉴权白名单测试默认含 dev-user, 让 R10.5.20 的
        # /admin/runtime-mode POST 测试 (test_runtime_mode_api) 仍能跑通.
        # 任何显式测 fail-closed 的 test (test_admin_runtime_mode_auth) 用
        # admin_client fixture 显式覆盖.
        try:
            from backend.auth import dependencies as auth_deps
            if hasattr(auth_deps, "ADMIN_USER_IDS"):
                auth_deps.ADMIN_USER_IDS = frozenset({"dev-user"})
        except (ImportError, AttributeError):
            pass
        # R10.5.31 (F1): D3 commit 84b6518 在 backend.auth.dependencies 跟
        # backend.api.routes.auth 各放了一份模块级 OPEN_MODE (后者是
        # `from backend.auth.dependencies import OPEN_MODE` 的 snapshot copy),
        # 旧 reset 没覆盖这俩 → D3 test 改 OPEN_MODE=False 后, 状态泄露到
        # 后续 test_auth_api_key / e2e / perf → 14 个 fail.
        #
        # R10.5.34 反向修复: 这里**不强制 reset**回 True, 而是
        # 保留 module-level monkeypatch 的设置. D3 test (test_r10_5_30_d3_session_cookies.py)
        # 自己在 test body 内 set _deps.OPEN_MODE = False, 而 test_auth_api_key 的
        # 4 case (TestGetCurrentUser) 显式 monkeypatch.setattr(dependencies, "OPEN_MODE", True/False).
        # 把这里强制重置为 True 会覆盖 test 自己的设置, 导致 D3 跑出
        # "OPEN_MODE=true 时不支持注册" 错 (CI 2026-06-17 4:32 观察).
        # 取舍: 信任各 test 自己的 setup/teardown 显式控制 OPEN_MODE,
        # autouse 不主动改它.
        # R10.5.31 (F1): tests 用 tmp_path 切 _DB, 跨 test 残留会让后续
        # test 写到旧 path → 'no such table' 或数据串味. reset 回默认
        # cache.sqlite + 清 _DB_INITIALIZED, 让 _init_db_once() 重新走.
        try:
            from backend.utils import cache as _cache_reset
            _cache_reset._DB = _cache_reset._DB_PATHS["cache"]
            _cache_reset._DB_INITIALIZED = False
            _cache_reset._DB_INITIALIZED_PATH = None
        except (ImportError, AttributeError):
            pass
        # R10.5.31 (F2): circuit breaker 是模块级单例 (ss_breaker / oa_breaker),
        # OPEN 状态跨 test 残留会让后续 e2e / perf test 第一个 query 立即
        # 降级 mock → 论文数 0 触发断言或 504 timeout. 强制 reset 到 CLOSED.
        try:
            from backend.utils import runtime_mode as _rt_reset
            # R10.5.51 cleanup (BACKLOG D-007): 删 _runtime_mode_override dict-subclass
            # proxy, 直接调 set_runtime_mode("auto") + _invalidate_cache() 重置.
            _rt_reset.set_runtime_mode("auto")
            _rt_reset._invalidate_cache()
        except (ImportError, AttributeError):
            pass
        try:
            from backend.utils import circuit_breaker as _cb_reset
            for _breaker_name in ("ss_breaker", "oa_breaker"):
                _breaker = getattr(_cb_reset, _breaker_name, None)
                if _breaker is None:
                    continue
                # 兼容两种 API: 内部属性 _state/_failures 或公开 state/failures
                for _attr in ("_state", "state"):
                    if hasattr(_breaker, _attr):
                        setattr(_breaker, _attr, getattr(_cb_reset, "CircuitState", type("S", (), {"CLOSED": "CLOSED"})).CLOSED if hasattr(_cb_reset, "CircuitState") else "CLOSED")
                        break
                for _attr in ("_failures", "_failure_count", "failures"):
                    if hasattr(_breaker, _attr):
                        try:
                            setattr(_breaker, _attr, 0)
                        except (AttributeError, TypeError):
                            pass
                        break
                for _attr in ("_opened_at", "opened_at"):
                    if hasattr(_breaker, _attr):
                        try:
                            setattr(_breaker, _attr, 0.0)
                        except (AttributeError, TypeError):
                            pass
                        break
        except (ImportError, AttributeError):
            pass
    except (ImportError, AttributeError):
        pass

    yield  # 跑 test 本身

    # ===== Teardown: 再 reset 一次, 避免泄露到下一个 test =====
    try:
        import backend.main as main_mod
        if hasattr(main_mod, "limiter"):
            main_mod.limiter.reset()
        if hasattr(main_mod, "_in_flight_searches"):
            main_mod._in_flight_searches.clear()
        try:
            from backend.api.services import providers as prov_mod
            if hasattr(prov_mod, "_PROVIDER_HEALTH_CACHE"):
                prov_mod._PROVIDER_HEALTH_CACHE.clear()
        except (ImportError, AttributeError):
            pass
        try:
            from backend.api.routes import search as routes_search
            if hasattr(routes_search, "limiter"):
                routes_search.limiter.reset()
        except (ImportError, AttributeError):
            pass
        try:
            from backend.utils import log_throttle
            if hasattr(log_throttle, "_THROTTLES"):
                log_throttle._THROTTLES.clear()
        except (ImportError, AttributeError):
            pass
        # R10.5.31 (F1+F2): 跟 setup 段同步 reset OPEN_MODE / _DB / breaker,
        # 避免最后一个 test 跑完留的脏状态污染 (D3 state pollution 根因).
        # R10.5.34 反向修复: setup 段不动 OPEN_MODE (让 D3 test module-level
        # os.environ["OPEN_MODE"]="false" 跟 test body 内 monkeypatch 生效),
        # teardown 段**强制 reset 回 True** 兜底, 防止下一个 test 拿到上次的 False.
        # 之前我注释掉 teardown 段, 导致 CI 27677520680 D3 跑时 OPEN_MODE 仍 True.
        try:
            from backend.auth import dependencies as _auth_deps_teardown
            from backend.api.routes import auth as _auth_routes_teardown
            _auth_deps_teardown.OPEN_MODE = True
            _auth_routes_teardown.OPEN_MODE = True
        except (ImportError, AttributeError):
            pass
        try:
            from backend.utils import runtime_mode as _rt_teardown
            # R10.5.43: 跟 setup 段同步, 用 proxy API 而不是替换 dict.
            _rt_teardown.set_runtime_mode("auto")
            _rt_teardown._invalidate_cache()
        except (ImportError, AttributeError):
            pass
        try:
            from backend.utils import cache as _cache_teardown
            _cache_teardown._DB = _cache_teardown._DB_PATHS["cache"]
            _cache_teardown._DB_INITIALIZED = False
            _cache_teardown._DB_INITIALIZED_PATH = None
        except (ImportError, AttributeError):
            pass
        try:
            from backend.utils import circuit_breaker as _cb_teardown
            for _breaker_name in ("ss_breaker", "oa_breaker"):
                _breaker = getattr(_cb_teardown, _breaker_name, None)
                if _breaker is None:
                    continue
                for _attr in ("_state", "state"):
                    if hasattr(_breaker, _attr):
                        try:
                            setattr(_breaker, _attr, "CLOSED")
                        except (AttributeError, TypeError):
                            pass
                        break
                for _attr in ("_failures", "_failure_count", "failures"):
                    if hasattr(_breaker, _attr):
                        try:
                            setattr(_breaker, _attr, 0)
                        except (AttributeError, TypeError):
                            pass
                        break
                for _attr in ("_opened_at", "opened_at"):
                    if hasattr(_breaker, _attr):
                        try:
                            setattr(_breaker, _attr, 0.0)
                        except (AttributeError, TypeError):
                            pass
                        break
        except (ImportError, AttributeError):
            pass
    except (ImportError, AttributeError):
        pass


# ===== Existing: force_mock_api =====

@pytest.fixture
def force_mock_api(monkeypatch):
    """Patch API_MOCK and LLM_MOCK flags on all relevant modules so tests
    don't hit the network or external LLM providers.

    `backend.config` uses `load_dotenv(override=True)`, so the .env file will
    override any env-var we set before the import. Instead, we flip the
    module-level constants after import.

    LLM_MOCK is re-exported by `backend.config` and re-imported by
    `backend.utils.llm_client` (the actual decision point in `call_llm`).
    We patch both so that whichever module is looked up at call time, the
    mock short-circuit fires — preventing accidental real-LLM traffic when
    a developer happens to have API keys configured locally.

    R10.5.31 (F2): 旧版只 patch 4 个模块级常量, 但 is_runtime_mock() 还
    读 SQLite runtime_mode_state + env. 之前 test 调过
    set_runtime_mode("real") 把 override 改 real → 当前 test 走真 API
    → e2e 170s + perf 504. 强 reset SQLite override + patch is_runtime_mock
    函数返 True, 双保险.
    """
    import backend.api.semantic_scholar as ss_mod
    import backend.api.openalex as oa_mod
    import backend.config as cfg_mod
    import backend.utils.llm_client as llm_mod
    import backend.utils.runtime_mode as rt_mod

    monkeypatch.setattr(ss_mod, "API_MOCK", True)
    monkeypatch.setattr(oa_mod, "API_MOCK", True)
    monkeypatch.setattr(cfg_mod, "LLM_MOCK", True)
    monkeypatch.setattr(llm_mod, "LLM_MOCK", True)
    # R10.5.31 (F2): 双保险 — 设 runtime_mode 让 is_runtime_mock() 返 True.
    # 注: ss_mod / oa_mod 顶部 `from backend.utils.runtime_mode import
    # is_runtime_mock` 拿的是函数引用, monkeypatch rt_mod.is_runtime_mock
    # 不会同步过去. 改 SQLite-backed mode 是唯一对所有 caller 都生效的方式.
    # R10.5.51 cleanup (BACKLOG D-007): 删 dict-subclass proxy, 改显式 set_runtime_mode.
    rt_mod.set_runtime_mode("mock")
    rt_mod._invalidate_cache()
    return monkeypatch
