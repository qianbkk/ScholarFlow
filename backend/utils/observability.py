"""
全链路 request_id / correlation_id 工具

每个 HTTP 请求生成唯一 ID, 通过 contextvars 注入 logger,
SearchState 透传到所有 LangGraph 节点, 实现端到端追踪。

设计要点 (Round 2 PERF-007):
  1. contextvars 在 asyncio / 多 worker 间隔离, 不会跨请求串味
  2. middleware 从 header 读取已有 ID (支持上游网关透传) 或生成新 ID
  3. SearchState.request_id 字段透传到所有 LangGraph 节点
  4. RequestIdFilter 自动注入 request_id 到每条日志, 排障时
     `grep '[<rid>]'` 即可捞出整条调用链
"""
import contextvars
import logging
import uuid
from typing import Optional

_request_id_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_id", default=None
)


def new_request_id() -> str:
    """生成新的 request_id (UUID4 hex, 12 字符短 ID)。"""
    return uuid.uuid4().hex[:12]


def set_request_id(rid: Optional[str]) -> None:
    """设置当前上下文 request_id。"""
    _request_id_var.set(rid)


def get_request_id() -> Optional[str]:
    """获取当前上下文 request_id。"""
    return _request_id_var.get()


class RequestIdFilter(logging.Filter):
    """自动附加 request_id 到每条日志。"""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get() or "-"
        return True


def setup_logging() -> None:
    """在应用启动时调用一次, 绑定 filter 到根 logger。

    幂等: 多次调用不会重复添加 handler / filter。
    """
    root = logging.getLogger()
    # 1) 根 logger 上挂一个 RequestIdFilter, 让所有子 logger 的日志
    #    都自动带上 request_id (filter 在 handler 处理前生效)
    if not any(isinstance(f, RequestIdFilter) for f in root.filters):
        root.addFilter(RequestIdFilter())

    # 2) 默认 handler: 带 request_id 的格式化串
    formatter = logging.Formatter(
        "%(asctime)s [%(request_id)s] %(levelname)s %(name)s: %(message)s"
    )
    has_request_id_handler = any(
        getattr(h, "_request_id_formatted", False) for h in root.handlers
    )
    if not has_request_id_handler:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        handler.addFilter(RequestIdFilter())
        handler._request_id_formatted = True  # type: ignore[attr-defined]
        root.addHandler(handler)
