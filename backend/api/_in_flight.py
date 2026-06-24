"""backend.api._in_flight — 进程内 in-flight 搜索任务登记表.

R10.5.98 (simplify 审计): 原本 main.py 和 search.py 各自定义了
`_in_flight_searches` dict, search.py 写入本地 dict, main.py 的 lifespan
shutdown drain + 5min GC 都操作 main.py 的 dict (永远是空) — 只有
/search/cancel 真的工作. 提取到共享模块, 两边统一引用同一份.

API:
  - register(req_id, task)       注册 in-flight task
  - unregister(req_id)           完成后清理 (或 GC stale)
  - cancel(req_id)               中止 (搜索端点调用)
  - get(req_id) -> Task | None   取 task (cancel 前判断)
  - snapshot() -> list[tuple]    lifespan shutdown drain 用
  - gc_stale(ttl_sec)            周期 GC 异常路径跳过 finally 的死引用
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

_in_flight_searches: dict[str, asyncio.Task] = {}
_in_flight_searches_age: dict[str, float] = {}


def register(req_id: str, task: asyncio.Task) -> None:
    _in_flight_searches[req_id] = task
    _in_flight_searches_age[req_id] = time.time()


def unregister(req_id: str) -> None:
    _in_flight_searches.pop(req_id, None)
    _in_flight_searches_age.pop(req_id, None)


def cancel(req_id: str) -> bool:
    """取消指定 request_id 的搜索任务. 返 True 表示有任务可取消."""
    task = _in_flight_searches.get(req_id)
    if task is not None and not task.done():
        task.cancel()
        return True
    return False


def get(req_id: str) -> Optional[asyncio.Task]:
    return _in_flight_searches.get(req_id)


def snapshot() -> list[tuple[str, asyncio.Task]]:
    """lifespan shutdown drain: 取当前所有 in-flight task 的快照."""
    return list(_in_flight_searches.items())


def gc_stale(ttl_sec: float = 600.0) -> int:
    """周期清理 1 小时前不活跃的 entry (异常路径跳过 finally 的兜底).

    返回清理掉的 entry 数.
    """
    now = time.time()
    stale = [
        rid for rid in _in_flight_searches
        if _in_flight_searches_age.get(rid, now) < now - ttl_sec
    ]
    for rid in stale:
        _in_flight_searches.pop(rid, None)
        _in_flight_searches_age.pop(rid, None)
    return len(stale)


def clear() -> None:
    """测试用: 清空所有 in-flight 注册."""
    _in_flight_searches.clear()
    _in_flight_searches_age.clear()