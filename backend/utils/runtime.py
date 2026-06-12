"""R10.5.16 (/simplify + /code-review 合并修复): 进程级 runtime 单源.

R10.5.14 之前多个模块 (health.py, audit_log.py) 各自定义 _START_TIME, 出现:
  1) dual sources of truth — 同一进程 2 个 clock, 跨 import 顺序 drift
  2) devops dashboard 对比 /health/detailed.uptime_sec vs audit_log.uptime_s
     时数值不一致, 排查耗时
  3) reload 任何一个模块 (test fixture / hot reload) 都会让 _START_TIME
     提前归零, uptime 失真

R10.5.16: 抽到 backend/utils/runtime.py, 共享进程启动时间戳.

使用:
  from backend.utils.runtime import get_uptime_sec, get_start_time
  elapsed = get_uptime_sec()  # float seconds since process start
"""
from __future__ import annotations

import time

# 进程启动时一次性算, 之后所有模块共享同一个 clock.
# 测试用 importlib.reload 时此常量保留 (Python module reload 重新执行顶层,
# 但 reload 此模块会刷新 — 测试里我们故意 reload 它来重置 uptime, 而不是
# 修改 health.py / audit_log.py).
_START_TIME: float = time.time()


def get_start_time() -> float:
    """进程启动时间戳 (seconds since epoch). 跟 ps -o lstart 一致."""
    return _START_TIME


def get_uptime_sec() -> float:
    """自进程启动以来的秒数, 浮点. /health/detailed 和 audit_log 共用."""
    return time.time() - _START_TIME
