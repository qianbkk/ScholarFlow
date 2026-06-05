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
"""
import importlib
import os
import sys
from pathlib import Path

import pytest

# Make sure the project root is on sys.path so `backend.*` imports work
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _purge_backend_modules() -> None:
    """Drop every cached `backend.*` module so the next import re-runs
    the module-level ALLOWED_ORIGINS check with fresh env vars."""
    for name in list(sys.modules):
        if name == "backend" or name.startswith("backend."):
            del sys.modules[name]


def test_cors_wildcard_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ALLOWED_ORIGINS=*`` must raise ValueError at import time."""
    monkeypatch.setenv("ALLOWED_ORIGINS", "*")
    _purge_backend_modules()

    with pytest.raises(ValueError, match=r"ALLOWED_ORIGINS must not contain '\*'"):
        importlib.import_module("backend.main")


def test_cors_wildcard_in_list_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ALLOWED_ORIGINS=http://a.com,*`` must also raise (any '*' fails)."""
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://a.com,*")
    _purge_backend_modules()

    with pytest.raises(ValueError, match=r"ALLOWED_ORIGINS must not contain '\*'"):
        importlib.import_module("backend.main")


def test_cors_normal_origins_import_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Normal comma-separated origins import without error and the CORS
    middleware has the explicit (non-wildcard) configuration."""
    monkeypatch.setenv(
        "ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    _purge_backend_modules()

    main_mod = importlib.import_module("backend.main")
    app = main_mod.app

    # Locate the CORSMiddleware on the stack
    cors_mw = None
    for mw in app.user_middleware:
        if mw.cls is None:
            # `cls` is a string in Starlette's middleware list
            continue
        if "CORS" in (getattr(mw.cls, "__name__", "") or ""):
            cors_mw = mw
            break
    # Fallback: scan the built stack
    if cors_mw is None:
        from starlette.middleware.cors import CORSMiddleware as _CORS
        for mw in app.user_middleware:
            cls_obj = mw.cls
            if cls_obj is _CORS or (
                isinstance(cls_obj, type) and issubclass(cls_obj, _CORS)
            ):
                cors_mw = mw
                break

    assert cors_mw is not None, "CORSMiddleware is not registered on the app"
    opts = cors_mw.options

    # Hard-coded allowlist — no wildcards
    assert opts.get("allow_methods") != ["*"], (
        "H8 FAIL: allow_methods is still a wildcard; should be ['GET', 'POST']"
    )
    assert opts.get("allow_headers") != ["*"], (
        "H8 FAIL: allow_headers is still a wildcard; should be a small explicit list"
    )
    assert sorted(opts.get("allow_methods") or []) == ["GET", "POST"], (
        f"allow_methods should be exactly ['GET', 'POST'], got {opts.get('allow_methods')}"
    )
    assert sorted(opts.get("allow_headers") or []) == [
        "Accept", "Cache-Control", "Content-Type",
    ], (
        f"allow_headers should be exactly "
        f"['Accept', 'Cache-Control', 'Content-Type'], got {opts.get('allow_headers')}"
    )

    # allow_origins should be the explicit list, no wildcards
    origins = opts.get("allow_origins") or []
    assert "*" not in origins, f"allow_origins still contains wildcard: {origins}"
    assert "http://localhost:5173" in origins
    assert "http://127.0.0.1:5173" in origins


def test_cors_credentials_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """``allow_credentials`` must remain False (CORS spec disallows it
    with wildcards, and we don't need cookies anyway)."""
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:5173")
    _purge_backend_modules()

    main_mod = importlib.import_module("backend.main")
    app = main_mod.app

    from starlette.middleware.cors import CORSMiddleware as _CORS
    cors_mw = None
    for mw in app.user_middleware:
        cls_obj = mw.cls
        if isinstance(cls_obj, type) and issubclass(cls_obj, _CORS):
            cors_mw = mw
            break

    assert cors_mw is not None
    assert cors_mw.options.get("allow_credentials") is False, (
        "allow_credentials should be False — no cookies / no wildcard needed"
    )
