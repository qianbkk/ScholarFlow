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
    """
    import backend.api.semantic_scholar as ss_mod
    import backend.api.openalex as oa_mod
    import backend.config as cfg_mod
    import backend.utils.llm_client as llm_mod

    monkeypatch.setattr(ss_mod, "API_MOCK", True)
    monkeypatch.setattr(oa_mod, "API_MOCK", True)
    monkeypatch.setattr(cfg_mod, "LLM_MOCK", True)
    monkeypatch.setattr(llm_mod, "LLM_MOCK", True)
    return monkeypatch
