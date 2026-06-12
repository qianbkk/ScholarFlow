"""
R10.5.15 (P1-C): 结构化审计日志 (P1-12 审计要求).

为什么不直接用 stdlib logging: 审计日志需要结构化字段 (user_id/query_hash/
cost/duration/status) 供 SIEM/ELK 聚合查询, 不是给开发者 debug 用的 free-form
text. 写文件追加 JSONL (一行一事件), 由 SIEM/Logstash 拉走.

设计原则:
  1. 失败静默: 审计日志不能影响主流程 (写失败抛错会让 /search 5xx).
     用 try/except 包, 写失败只 log warning.
  2. 不存 PII: query 内容用 SHA256 哈希, 避免用户隐私泄露到日志系统.
     user_id 用 API key hash (跟 auth.dependencies.issue_key_for_email 风格一致).
  3. 不替代 logger: 现有 logger.info/warning 保留, audit 通道是并行旁路.
  4. 写入异步: 同步 json.dumps + append 耗时 <1ms, 不进 queue (R10.5.15 设计选择).
     若后续压测发现影响 latency, 改 asyncio.Queue + 后台 worker.

触发场景 (P1-12 审计 §P1-12):
  - search_started: 用户提交查询时
  - search_completed: 搜索完成 (status=done/error/budget_exceeded)
  - search_anomaly: cost > BUDGET_LIMIT_USD * 1.5 (异常烧钱)

文件位置: <SCHOLARFLOW_DB_DIR 父目录>/logs/audit.jsonl, 默认 backend/logs/.
环境覆盖: AUDIT_LOG_PATH (绝对路径). 关闭: AUDIT_LOG_PATH="" 或 AUDIT_LOG_DISABLE=1.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 进程级启动时间戳 (跟 /health/detailed 用的同源, 算 uptime)
_START_TIME = time.time()

# 默认路径: <project_root>/logs/audit.jsonl
_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "logs" / "audit.jsonl"


def _resolve_audit_path() -> Optional[Path]:
    """返回当前生效的 audit 日志路径. None = 已禁用."""
    if os.environ.get("AUDIT_LOG_DISABLE", "").lower() in ("1", "true", "yes"):
        return None
    custom = os.environ.get("AUDIT_LOG_PATH", "").strip()
    if custom:
        return Path(custom)
    return _DEFAULT_PATH


def _hash_query(query: str) -> str:
    """SHA256 哈希 query 前 16 字符. 不会反推原文但同 query 同 hash, 便于聚合."""
    return "qh_" + hashlib.sha256((query or "").encode("utf-8")).hexdigest()[:16]


def _hash_user(user_id: Optional[str]) -> Optional[str]:
    if not user_id:
        return None
    return "u_" + hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]


def _emit(event: str, **fields) -> None:
    """写一条 JSONL 审计事件. 失败静默."""
    path = _resolve_audit_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": time.time(),
            "uptime_s": round(time.time() - _START_TIME, 2),
            "event": event,
            **fields,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        # 写失败不影响主流程, 但要 log warning 给运维
        logger.warning(f"[audit_log] write failed: {type(e).__name__}: {e}")


def audit_search_started(
    *,
    user_id: Optional[str],
    query: str,
    budget_usd: float,
    request_id: Optional[str] = None,
) -> None:
    """用户提交搜索时调. query 哈希不存原文 (PII 保护)."""
    _emit(
        "search_started",
        request_id=request_id,
        user_hash=_hash_user(user_id),
        query_hash=_hash_query(query),
        query_len=len(query or ""),
        budget_usd=round(float(budget_usd or 0), 4),
    )


def audit_search_completed(
    *,
    user_id: Optional[str],
    query: str,
    status: str,
    cost_usd: float,
    duration_sec: float,
    papers_count: int,
    request_id: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """搜索完成 (done/error/budget_exceeded) 时调. P1-12 主表."""
    _emit(
        "search_completed",
        request_id=request_id,
        user_hash=_hash_user(user_id),
        query_hash=_hash_query(query),
        status=status,
        cost_usd=round(float(cost_usd or 0), 6),
        duration_sec=round(float(duration_sec or 0), 3),
        papers_count=int(papers_count or 0),
        error=(error or "")[:200] or None,
    )


def audit_search_anomaly(
    *,
    user_id: Optional[str],
    query: str,
    cost_usd: float,
    threshold_usd: float,
    request_id: Optional[str] = None,
) -> None:
    """异常成本时调 (cost > threshold * 1.5). 给 SIEM 告警."""
    _emit(
        "search_anomaly",
        request_id=request_id,
        user_hash=_hash_user(user_id),
        query_hash=_hash_query(query),
        cost_usd=round(float(cost_usd or 0), 6),
        threshold_usd=round(float(threshold_usd or 0), 4),
        reason="cost_above_1.5x_threshold",
    )
