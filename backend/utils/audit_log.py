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

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# R10.5.16 (/simplify + /code-review 合并修复): uptime 改从 runtime 单源拿.
# 之前模块级 _START_TIME = time.time() 跟 health.py 各算一份, import 顺序不同
# 会 drift, devops 对比两个 endpoint 的 uptime 会发现不一致. 现在共用.
from backend.utils.runtime import get_uptime_sec  # noqa: E402
# R10.5.16: user_id 哈希改用 user_id.hash_user_id 单源 (跟 auth 路径一致).
# 之前 5 处 _hash_user 重复实现, 任何 hash 策略变更都得 5 处同步.
from backend.utils.user_id import hash_user_id as _hash_user  # noqa: E402
# R10.5.17: query 哈希改用 text_utils.hash_query 单源.
# 之前 audit_log 跟 semantic_cache 各算一份, 策略可能 drift (大小写/截位).
from backend.utils.text_utils import hash_query as _hash_query_text  # noqa: E402

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
    """R10.5.17: 委托给 backend.utils.text_utils.hash_query 单源.
    保留这个 wrapper 是为了不破坏外部调用."""
    return _hash_query_text(query)


def _emit(event: str, **fields) -> None:
    """写一条 JSONL 审计事件. 失败静默."""
    path = _resolve_audit_path()
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": time.time(),
            "uptime_s": round(get_uptime_sec(), 2),
            "event": event,
            **fields,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    # R10.5.17: 收窄 except 到 (OSError, TypeError). 旧 except Exception 会
    # 吞掉编程 bug (KeyError, AttributeError) — 字段重命名 / dict 构造错
    # 时主流程静默走, audit log 缺数据, SIEM 看着正常实际漏事件.
    except (OSError, TypeError) as e:
        # 写失败 (磁盘满 / 权限 / 编码) 不影响主流程, 但要 log warning 给运维
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
