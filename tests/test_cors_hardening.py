"""Tests for H8 part 1: CORS hardening in backend/main.py.

The audit found two issues:

  1. ``allow_methods=["*"]`` and ``allow_headers=["*"]`` widen the CSRF
     surface — if a deployment typo sets ``ALLOWED_ORIGINS=*``, any
     website can hit the API.
  2. No validation that ``ALLOWED_ORIGINS`` doesn't contain ``"*"``.

The fix:
  * Replaced wildcards with explicit allow-lists.
  * Fail-fast at startup if ``ALLOWED_ORIGINS`` contains ``"*"``.

These tests verify:
  * Importing ``backend.main`` with ``ALLOWED_ORIGINS=*`` raises
    ``ValueError``.
  * A normal ``ALLOWED_ORIGINS`` value imports cleanly.
  * The ``CORSMiddleware`` is configured with explicit
    ``allow_methods`` / ``allow_headers`` (no wildcards).

R8.3 重构 (reviewer feedback 3.4 - test isolation):
  旧实现用 _purge_backend_modules() + importlib.import_module 重新加载 backend.main。
  reload 失败 (ALLOWED_ORIGINS=* 抛 ValueError) 时, sys.modules["backend.main"] 留下
  半成品模块, 后续 test_request_id / test_search_node_semaphore 的 TestClient 拿到
  旧模块对象, 旧 limiter 被填到 5/5 触发 429。
  新实现: 用 subprocess 完全隔离, 每次启 Python 解释器, 不污染主进程 sys.modules。
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# Make sure the project root is on sys.path so the subprocess can find backend.*
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run_in_subprocess(allowed_origins: str) -> subprocess.CompletedProcess:
    """在隔离的 subprocess 跑 'import backend.main', 捕获 stdout/stderr/returncode。

    不用主进程 sys.modules, 不污染当前 pytest 会话。
    传 ALLOWED_ORIGINS env var 控制 backend.main 模块级 guard。
    """
    code = textwrap.dedent(f"""
        import os
        os.environ['ALLOWED_ORIGINS'] = {allowed_origins!r}
        try:
            import backend.main
            print('OK_IMPORT')
        except ValueError as e:
            print(f'RAISED_VALUE_ERROR:{{e}}')
            sys.exit(1)
    """)
    env = {**os.environ, "ALLOWED_ORIGINS": allowed_origins}
    return subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(PROJECT_ROOT),
        timeout=30,
    )


# ===== CORS wildcard guard =====

def test_cors_wildcard_raises_value_error():
    """``ALLOWED_ORIGINS=*`` must raise ValueError at import time."""
    result = _run_in_subprocess("*")
    assert result.returncode != 0, (
        f"subprocess 应该 raise ValueError 但 exit 0. "
        f"stdout: {result.stdout!r}, stderr: {result.stderr!r}"
    )
    assert "ALLOWED_ORIGINS must not contain" in (result.stdout + result.stderr), (
        f"raise 时的错误信息应包含 'ALLOWED_ORIGINS must not contain', "
        f"got: {result.stdout!r} + {result.stderr!r}"
    )


def test_cors_wildcard_in_list_raises():
    """``ALLOWED_ORIGINS=http://a.com,*`` must also raise (any '*' fails)."""
    result = _run_in_subprocess("http://a.com,*")
    assert result.returncode != 0, (
        f"subprocess 应该 raise ValueError 但 exit 0. "
        f"stdout: {result.stdout!r}, stderr: {result.stderr!r}"
    )
    assert "ALLOWED_ORIGINS must not contain" in (result.stdout + result.stderr), (
        f"raise 时的错误信息应包含 'ALLOWED_ORIGINS must not contain', "
        f"got: {result.stdout!r} + {result.stderr!r}"
    )


# ===== Normal CORS 配置 (用 AST + 静态检查, 不 reload) =====

def test_main_py_source_has_explicit_allowlists():
    """Static check: main.py 源码里 cors 配置必须是 explicit allow-list, 不允许 wildcard。"""
    main_path = PROJECT_ROOT / "backend" / "main.py"
    src = main_path.read_text(encoding="utf-8")
    assert 'allow_methods=["*"]' not in src, (
        "H8 FAIL: backend/main.py still has `allow_methods=['*']`"
    )
    assert 'allow_headers=["*"]' not in src, (
        "H8 FAIL: backend/main.py still has `allow_headers=['*']`"
    )
    assert "ALLOWED_ORIGINS must not contain" in src, (
        "H8 FAIL: backend/main.py is missing the ALLOWED_ORIGINS wildcard guard"
    )
    # 必须是显式列表, 而不是空 (空 = 拒绝所有 CORS)
    # main.py 里 cors 配置用双引号, 例 allow_methods=["GET", "POST"]
    assert '"GET"' in src and '"POST"' in src, (
        "H8 FAIL: allow_methods 应该显式列出 GET/POST"
    )
    assert "Accept" in src and "Content-Type" in src, (
        "H8 FAIL: allow_headers 应该显式列出 Accept/Content-Type/Cache-Control"
    )


def test_main_py_source_has_credentials_disabled():
    """Static check: main.py 源码里 allow_credentials 必须是 False。"""
    main_path = PROJECT_ROOT / "backend" / "main.py"
    src = main_path.read_text(encoding="utf-8")
    # 搜索 CORSMiddleware 配置块里的 allow_credentials
    assert "allow_credentials=False" in src, (
        "H8 FAIL: backend/main.py should have allow_credentials=False"
    )
