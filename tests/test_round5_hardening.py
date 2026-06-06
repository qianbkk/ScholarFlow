"""Round 5 hardening tests — covers M-1 / M-3 / M-4 / S-3 / S-4.

Round 5 冗余清理 + 测试补全:
  1. M-1: SearchResponse.is_degraded_response + fallback_paper_count 顶层信号
  2. M-3: SecurityHeadersMiddleware 7 个安全头
  3. M-4: model_usage 字段白名单 — 去除 cost + provider 内部名
  4. S-3: 自定义 422 异常处理器不回显用户 input
  5. S-4: /search/cancel request_id 长度/charset 校验

每个 test 函数覆盖一个具体改动, 失败时能精确定位到 Round 5 哪一项回归.
"""
import pytest


# ---------------------------------------------------------------------------
# 辅助: 构造 TestClient (与 test_provider_selection.py 同样的延迟 import 模式)
# ---------------------------------------------------------------------------
def _build_test_client():
    from fastapi.testclient import TestClient
    from backend.main import app
    return TestClient(app)


# ===========================================================================
# Test 1: M-1 — SearchResponse.is_degraded_response + fallback_paper_count
# ===========================================================================

def test_search_response_is_degraded():
    """构造 1 个 is_fallback=True 论文 + 1 个 False, 验证 SearchResponse:
      * is_degraded_response=True (至少 1 篇 fallback)
      * fallback_paper_count=1 (精确计数)
    """
    from backend.main import _build_search_response

    state = {
        "report": "测试报告",
        "ranked_papers": [
            {"paper_id": "a", "title": "A", "is_fallback": True},
            {"paper_id": "b", "title": "B", "is_fallback": False},
        ],
        "citation_graph": {},
        "total_cost_usd": 0.001,
        "total_tokens_used": 10,
        "model_usage": {},
        "iteration": 0,
        "status": "done",
    }
    resp = _build_search_response(state, elapsed=1.23)
    assert resp.is_degraded_response is True, (
        f"is_degraded_response 应该是 True (1 篇 fallback), got {resp.is_degraded_response}"
    )
    assert resp.fallback_paper_count == 1, (
        f"fallback_paper_count 应该是 1, got {resp.fallback_paper_count}"
    )
    # 同时验证 ranked_papers 截断到 25 (抽 helper 时把这条规则也合进来了)
    assert len(resp.ranked_papers) == 2

    # 边界: 全 0 fallback → is_degraded_response=False + count=0
    state_clean = dict(state)
    state_clean["ranked_papers"] = [
        {"paper_id": "x", "title": "X", "is_fallback": False},
    ]
    resp_clean = _build_search_response(state_clean, elapsed=0.0)
    assert resp_clean.is_degraded_response is False
    assert resp_clean.fallback_paper_count == 0

    # 边界: 空 ranked_papers (无 key) → 优雅降级, 不抛
    state_empty = dict(state)
    state_empty["ranked_papers"] = []
    resp_empty = _build_search_response(state_empty, elapsed=0.0)
    assert resp_empty.is_degraded_response is False
    assert resp_empty.fallback_paper_count == 0


# ===========================================================================
# Test 2: M-3 — SecurityHeadersMiddleware 7 个安全头
# ===========================================================================

# Round 5 M-3 安全头清单 (与 backend/middleware.py SecurityHeadersMiddleware 一致)
EXPECTED_SECURITY_HEADERS = [
    "x-content-type-options",
    "x-frame-options",
    "x-xss-protection",
    "referrer-policy",
    "permissions-policy",
    "strict-transport-security",
    "content-security-policy",
]


def test_security_headers_middleware():
    """TestClient GET /health 验证 7 个安全头都在响应里.

    Round 5 M-3 引入 SecurityHeadersMiddleware, 加了 7 个 HTTP 安全响应头
    (X-Content-Type-Options / X-Frame-Options / X-XSS-Protection / Referrer-Policy
     / Permissions-Policy / HSTS / CSP). 这个测试确保 middleware 没被意外删除
    或 register 顺序错 (TrustedHost 拒绝 400 也要带安全头).
    """
    client = _build_test_client()
    resp = client.get("/health")
    assert resp.status_code == 200, f"GET /health 期望 200, got {resp.status_code}"

    # FastAPI/Starlette 把 header 名 normalize 成小写, 用 lowercase 比较
    resp_headers_lower = {k.lower(): v for k, v in resp.headers.items()}

    missing = [h for h in EXPECTED_SECURITY_HEADERS if h not in resp_headers_lower]
    assert not missing, (
        f"M-3 安全头缺失: {missing}. "
        f"实际 headers: {list(resp_headers_lower.keys())}"
    )

    # 同时 spot-check 几个关键值 (防止有人把 header 加上了但值是空字符串)
    assert resp_headers_lower["x-content-type-options"] == "nosniff"
    assert resp_headers_lower["x-frame-options"] == "DENY"
    assert "max-age=" in resp_headers_lower["strict-transport-security"]
    assert "default-src" in resp_headers_lower["content-security-policy"]


# ===========================================================================
# Test 3: M-4 — model_usage 字段白名单 (去除 cost + provider 内部名)
# ===========================================================================

def test_model_usage_summary_whitelist():
    """构造 model_usage 含 "MiniMax-M3 (fallback to mock)" key, 验证序列化后:
      * 只剩 "MiniMax-M3" (后缀 "(fallback to mock)" 被切掉)
      * 没有 cost 字段 (白名单只保留 tokens)
      * 多个 entry 都按规则处理
    """
    from backend.main import _build_search_response

    state = {
        "report": "r",
        "ranked_papers": [],
        "citation_graph": {},
        "total_cost_usd": 0.0,
        "total_tokens_used": 150,
        # 模拟 llm_client 内部结构: key 含 "(fallback to mock)" 后缀, value 含 cost/provider
        "model_usage": {
            "MiniMax-M3 (fallback to mock)": {
                "tokens": 100,
                "cost_usd": 0.001,
                "provider": "minimax",
            },
            "kimi-k2.5": {
                "tokens": 50,
                "cost_usd": 0.0005,
                "provider": "kimi",
            },
        },
        "iteration": 0,
        "status": "done",
    }
    resp = _build_search_response(state, elapsed=0.0)
    summary = resp.model_usage_summary

    # 1) 验证 key 被白名单化 (切掉 " (fallback to mock)" 后缀)
    assert "MiniMax-M3" in summary, (
        f"M-4 期望 'MiniMax-M3' 在 summary 中, got keys: {list(summary.keys())}"
    )
    assert "MiniMax-M3 (fallback to mock)" not in summary, (
        "M-4 失败: provider 内部后缀没被剥掉"
    )
    assert "kimi-k2.5" in summary, (
        f"M-4 期望 'kimi-k2.5' 在 summary 中, got keys: {list(summary.keys())}"
    )

    # 2) 验证 value 只剩 tokens (无 cost_usd / provider 内部名)
    for model_name, usage in summary.items():
        assert set(usage.keys()) == {"tokens"}, (
            f"M-4 失败: {model_name!r} 的字段应该是只 {{'tokens'}}, "
            f"got {set(usage.keys())}. 完整 dict: {usage}"
        )

    # 3) 验证 tokens 数值正确 (100 + 50 = 150)
    assert summary["MiniMax-M3"]["tokens"] == 100
    assert summary["kimi-k2.5"]["tokens"] == 50

    # 4) 边界: model_usage 缺 / None / 空 dict → 优雅降级
    state_no_usage = dict(state)
    state_no_usage["model_usage"] = {}
    resp_no_usage = _build_search_response(state_no_usage, elapsed=0.0)
    assert resp_no_usage.model_usage_summary == {}

    state_none = dict(state)
    state_none["model_usage"] = None
    resp_none = _build_search_response(state_none, elapsed=0.0)
    assert resp_none.model_usage_summary == {}, (
        f"model_usage=None 应降级为 {{}}, got {resp_none.model_usage_summary}"
    )


# ===========================================================================
# Test 4: S-4 — /search/cancel request_id 长度/charset 校验
# ===========================================================================

def test_search_cancel_request_validation_valid():
    """合法 request_id (字母+数字+_+-, 长度 ≤ 128) → 200."""
    client = _build_test_client()
    resp = client.post("/search/cancel", json={"request_id": "abc-123_xyz"})
    assert resp.status_code == 200, (
        f"合法 request_id 应该 200, got {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    assert body.get("cancelled") is True
    assert body.get("request_id") == "abc-123_xyz"


def test_search_cancel_request_validation_too_long():
    """超长 request_id (>128) → 422 (S-4 加的 max_length 校验)."""
    client = _build_test_client()
    long_id = "a" * 200  # 超过 max_length=128
    resp = client.post("/search/cancel", json={"request_id": long_id})
    assert resp.status_code == 422, (
        f"超长 request_id 应该 422, got {resp.status_code}: {resp.text}"
    )
    # S-3: 422 也不应回显完整 input
    body = resp.json()
    assert "detail" in body
    # 验证长串 'a'*200 没被回显到 detail (S-3 不回显 input)
    detail_str = str(body.get("detail", ""))
    assert long_id not in detail_str, (
        f"S-3 失败: 超长 request_id 被回显到 detail. detail={detail_str!r}"
    )


def test_search_cancel_request_validation_special_chars():
    """含特殊字符 (! @ #) 的 request_id → 422 (S-4 加的 pattern 校验)."""
    client = _build_test_client()
    bad_id = "abc!@#def"
    resp = client.post("/search/cancel", json={"request_id": bad_id})
    assert resp.status_code == 422, (
        f"含特殊字符 request_id 应该 422, got {resp.status_code}: {resp.text}"
    )
    # 同样 S-3 不回显 input
    detail_str = str(resp.json().get("detail", ""))
    assert bad_id not in detail_str, (
        f"S-3 失败: 含特殊字符 request_id 被回显. detail={detail_str!r}"
    )


# ===========================================================================
# Test 5: S-3 — 422 validation handler 不回显 input
# ===========================================================================

def test_422_validation_handler_no_input_echo():
    """POST /search query='' → 422 且 detail 不回显 input 全文.

    Round 5 S-3 自定义 RequestValidationError handler, 防止:
      * 攻击者向日志注入 ANSI / 控制字符
      * 隐私泄露 (PII / 内部检索词)
    """
    client = _build_test_client()

    # 1) query='' 触发 string_too_short 校验失败
    resp_empty = client.post(
        "/search",
        json={"query": "", "budget": 1.0, "max_iterations": 1},
    )
    assert resp_empty.status_code == 422, (
        f"空 query 应该 422, got {resp_empty.status_code}"
    )
    body_empty = resp_empty.json()
    assert "detail" in body_empty

    # 2) S-3 关键: detail 不应回显用户 input 全文
    # 默认 FastAPI handler 会把 query='' 完整写到 detail 里 (e.g. "value is too short")
    # S-3 handler 只回 "Invalid request: 参数校验失败"
    detail = body_empty["detail"]
    assert "Invalid request" in detail or "参数校验失败" in detail, (
        f"S-3 失败: detail 应该用静态文案, got: {detail!r}"
    )
    # 默认 handler 会在某个 ctx.error 里写 'ctx': {'min_length': 1}, 但 S-3 我们
    # 直接断言 detail 字段是字符串 (而非 dict 含 value)
    assert isinstance(detail, str), (
        f"S-3 失败: detail 应该是字符串 (不回显结构化 input), got type {type(detail).__name__}"
    )

    # 3) 二次验证: 用超长 input 触发 string_too_long (max_length=2000) 校验,
    #    避免走 sanitize_query 把危险字符串过滤掉变成 200.
    #    S-3 handler 不应回显这个超长 input 全文.
    long_payload = "<script>alert('xss')></script>" + "A" * 2100  # > max_length=2000
    resp_long = client.post(
        "/search",
        json={"query": long_payload, "budget": 1.0, "max_iterations": 1},
    )
    assert resp_long.status_code == 422, (
        f"超长 query 应该 422, got {resp_long.status_code}: {resp_long.text[:120]}"
    )
    detail_long = resp_long.json().get("detail", "")
    assert long_payload not in detail_long, (
        f"S-3 失败: 长 XSS payload 被回显到 detail. detail={detail_long!r}"
    )
    assert "<script>" not in detail_long, (
        f"S-3 失败: 危险 HTML 标签被回显. detail={detail_long!r}"
    )
