"""utils.semantic_cache — 占位桩 (Fix-E R10.5)

R10.5 审计 (PPP §1.3, QQQ §2.1) 指出:
  - get_semantic_cached() 永远返 None (退化模式) — 死代码
  - set_semantic_cached() 仅转发到 set_cached_async() — 重复写

原 R10 设计目标: 384 维 numpy float32 embedding + SQLite BLOB + 余弦
相似度 top-1 检索 (阈值 0.92). 实际从未真正实现 — query_embedding 列
从未添加到 schema, get_xxx 也从未从 BLOB 读.

R10.5 处置: 全部调用从 main.py 删除 (Fix-E commit 1).  本模块保留
以避免破坏测试或外部引用, 但函数体已收缩成 explicit "未实现" 桩:

  semantic_cache_stub_marker   - 强制依赖存在的 import-time 标记 (无副作用)
  get_semantic_cached()        - 永远 return None (语义: 永远 miss)
  set_semantic_cached()        - no-op, 只 logger.debug 一条记录

R11+ 真实现路径:
  1. cache.py: ALTER TABLE search_cache ADD COLUMN query_embedding BLOB
  2. 这里 _embed_query() 改用 sentence-transformers (e.g. all-MiniLM-L6-v2, 384 dim)
  3. get_xxx() 拉最近 N 条 entry, BLOB → numpy, 余弦相似度 top-1, 阈值 0.92
  4. 取消对 main.py 的删除, 重新启用这两个调用

保持签名稳定: 参数 / 返回值类型不变, 调用方代码改 0 行就能切换.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ===== 占位桩 marker (强制 import 存在, 让 Fix-E import 改动通过类型检查) =====
semantic_cache_stub_marker: bool = True


async def get_semantic_cached(
    query: str,
    max_iter: int,
    budget: float,
    provider: str | None = None,
    threshold: float = 0.92,
) -> Optional[tuple[dict, float, int]]:
    """语义缓存检索 (R10.5 占位桩 — 永远 miss).

    R11+ 真实现见模块顶 docstring.
    """
    return None  # 占位: 永远 cache miss, 调用方继续走精确缓存路径


async def set_semantic_cached(
    query: str,
    max_iter: int,
    budget: float,
    response: dict,
    cost_usd: float,
    tokens: int,
    provider: str | None = None,
) -> None:
    """语义缓存写入 (R10.5 占位桩 — no-op).

    修复历史: 旧实现转发到 set_cached_async 造成双倍写入, 已删除.
    R11+ 真实现见模块顶 docstring.
    """
    logger.debug(
        "[semantic_cache] set_semantic_cached no-op (R10.5 stub); "
        "query=%r provider=%s", query[:40], provider,
    )
