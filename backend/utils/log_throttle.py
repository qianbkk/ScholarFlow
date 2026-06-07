"""
Round 6 SIMPLIFY (REDUNDANT-001): 日志 throttle 工具
"""
import time as _time
from typing import Optional

_THROTTLES: dict[str, float] = {}
_DEFAULT_INTERVAL = 300.0  # 5 分钟


def should_log(key: str, interval: float = _DEFAULT_INTERVAL) -> bool:
    """同 key 在 interval 秒内只记一次.

    Round 6 SIMPLIFY: 之前 _should_log 在 SS/OA 重复 2 份 (26 行), 抽到 utils.
    """
    now = _time.time()
    last = _THROTTLES.get(key, 0.0)
    if now - last >= interval:
        _THROTTLES[key] = now
        return True
    return False


def reset_throttle(key: Optional[str] = None) -> None:
    """测试用: 清空 throttle dict."""
    if key is None:
        _THROTTLES.clear()
    else:
        _THROTTLES.pop(key, None)
