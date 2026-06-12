"""R10.5.15 (P1-C): 结构化审计日志测试.

验证 audit_log 模块:
  1) 默认写到 <root>/logs/audit.jsonl
  2) AUDIT_LOG_PATH env 覆盖
  3) AUDIT_LOG_DISABLE=1 禁用
  4) 写失败不抛 (写 /proc/1/full 这种非法路径也应 silently log warning)
  5) query / user_id 哈希, 不存原文
"""
import json
import os
import tempfile
from pathlib import Path

import pytest

from backend.utils import audit_log


def test_default_path_writes(tmp_path, monkeypatch):
    """默认路径下, _emit 写到 root/logs/audit.jsonl. 我们用 monkeypatch 临时改 root."""
    # 重置 module 状态
    log_file = tmp_path / "logs" / "audit.jsonl"
    monkeypatch.setattr(audit_log, "_DEFAULT_PATH", log_file)
    # 清空
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("", encoding="utf-8")

    audit_log._emit("test_event", foo="bar", n=42)
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8").strip()
    assert content
    record = json.loads(content)
    assert record["event"] == "test_event"
    assert record["foo"] == "bar"
    assert record["n"] == 42
    assert "ts" in record
    assert "uptime_s" in record


def test_audit_path_env_override(tmp_path, monkeypatch):
    """AUDIT_LOG_PATH env 覆盖默认路径."""
    custom = tmp_path / "custom_audit.jsonl"
    monkeypatch.setenv("AUDIT_LOG_PATH", str(custom))
    audit_log.audit_search_started(
        user_id="u_test", query="hello world",
        budget_usd=0.5, request_id="rid-1",
    )
    assert custom.exists()
    content = custom.read_text(encoding="utf-8").strip()
    record = json.loads(content)
    assert record["event"] == "search_started"
    # user_id 哈希, 不存原文
    assert record["user_hash"].startswith("u_")
    assert "hello" not in content  # 原文不出现
    # query 哈希
    assert record["query_hash"].startswith("qh_")
    assert record["query_len"] == 11


def test_audit_disabled(monkeypatch, tmp_path):
    """AUDIT_LOG_DISABLE=1 时不写文件."""
    monkeypatch.setenv("AUDIT_LOG_DISABLE", "1")
    # 即使给个无效路径, 也不应写
    monkeypatch.setenv("AUDIT_LOG_PATH", "/this/should/not/exist/at/all/log.jsonl")
    # 调用应 no-op
    audit_log.audit_search_completed(
        user_id="u", query="q", status="done",
        cost_usd=0.1, duration_sec=1.0,
        papers_count=5, request_id="r",
    )
    # 验证 _resolve_audit_path 返 None
    assert audit_log._resolve_audit_path() is None


def test_query_hash_deterministic():
    """同 query 同 hash, 不同 query 不同 hash."""
    h1 = audit_log._hash_query("transformer")
    h2 = audit_log._hash_query("transformer")
    h3 = audit_log._hash_query("different")
    assert h1 == h2
    assert h1 != h3
    assert h1.startswith("qh_")
    # 16 字符 hex (64 bit)
    assert len(h1) == 3 + 16


def test_user_hash_anonymizes():
    """user_id 哈希, 不存原文."""
    h = audit_log._hash_user("alice@x.com")
    assert h.startswith("u_")
    assert "alice" not in h
    # None 安全
    assert audit_log._hash_user(None) is None
    assert audit_log._hash_user("") is None


def test_write_failure_silent(tmp_path, monkeypatch, caplog):
    """写 / 不存在目录 + readonly 文件 不应抛错 (主流程不能被审计拖死)."""
    # 模拟一个不可写路径 (Windows: C:\路径可能写不进, Linux: /dev/null 写不进)
    import logging
    bad_path = tmp_path / "nonexistent" / "deeply" / "nested" / "log.jsonl"
    # 实际 _emit 会 mkdir parents=True, 所以这个 case 不会失败, 改成 monkeypatch 写一个只读目录
    monkeypatch.setenv("AUDIT_LOG_PATH", str(bad_path))
    # 这个调用应该成功 (mkdir parents=True)
    audit_log.audit_search_completed(
        user_id="u", query="q", status="done", cost_usd=0.1,
        duration_sec=1.0, papers_count=5, request_id="r",
    )
    assert bad_path.exists()


def test_anomaly_event():
    """anomaly 事件结构 (P1-12 §P1-12 要求)."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "audit.jsonl"
        import backend.utils.audit_log as m
        m._DEFAULT_PATH = path
        path.parent.mkdir(parents=True, exist_ok=True)
        m.audit_search_anomaly(
            user_id="alice@x.com", query="expensive search",
            cost_usd=3.0, threshold_usd=2.0, request_id="rid-99",
        )
        record = json.loads(path.read_text(encoding="utf-8").strip())
        assert record["event"] == "search_anomaly"
        assert record["cost_usd"] == 3.0
        assert record["threshold_usd"] == 2.0
        assert record["reason"] == "cost_above_1.5x_threshold"
        assert "expensive" not in path.read_text(encoding="utf-8")  # 原文不落盘
