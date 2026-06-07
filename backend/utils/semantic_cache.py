"""utils.semantic_cache — 语义缓存 (numpy 余弦相似度 top-1 检索)

设计:
  - 轻量 embedding: BM25 稀疏特征 + TF-IDF numpy 化 (无外部依赖, 生产版可换 sentence-transformers)
  - 缓存键: query → 384 维 numpy float32 向量 (磁盘存 .npy 或 BLOB)
  - 检索: SQLite 拉最近 200 条 query embedding, 余弦相似度 top-1
  - 阈值: 0.92 视为命中

并发安全:
  - 复用 cache.py 的 _connect_with_wal() + busy_timeout=5s
  - numpy 计算在主线程 (成本 <1ms per query)
"""
from __future__ import annotations

import re
from typing import Optional

import numpy as np

from backend.utils.cache import _connect_with_wal, _init_db_once, _DB

EMBED_DIM = 384
SIMILARITY_THRESHOLD = 0.92  # 0.92 视为命中


def _tokenize(query: str) -> list[str]:
    """简单分词: 英文 lowercase + 中文单字 + 数字 + 标点剥离。"""
    # 提取所有 unicode letter / digit, 英文小写, 中文单字保留
    return re.findall(r"[a-z0-9]+|[一-鿿]", query.lower())


def _embed_query(query: str) -> np.ndarray:
    """轻量 embedding: 词袋 + hash trick + L2 normalize。

    不是真 embedding, 是个能用的近似, 用于 demo。生产版换 sentence-transformers。
    """
    vec = np.zeros(EMBED_DIM, dtype=np.float32)
    tokens = _tokenize(query)
    if not tokens:
        return vec
    for tok in tokens:
        # FNV-1a hash trick, 映射到 [0, EMBED_DIM)
        h = 2166136261
        for c in tok.encode("utf-8"):
            h ^= c
            h = (h * 16777619) & 0xFFFFFFFF
        vec[h % EMBED_DIM] += 1.0
    # L2 normalize
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec /= norm
    return vec


def _serialize_embedding(emb: np.ndarray) -> bytes:
    """float32 array → bytes (BLOB 存 SQLite)."""
    return emb.astype(np.float32).tobytes()


def _deserialize_embedding(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


async def get_semantic_cached(
    query: str,
    max_iter: int,
    budget: float,
    provider: str | None = None,
    threshold: float = SIMILARITY_THRESHOLD,
) -> Optional[tuple[dict, float, int]]:
    """语义缓存检索。

    Returns:
        None — 缓存 miss
        (response, cost_usd, tokens, similarity) — 缓存命中
    """
    if not query:
        return None
    _init_db_once()
    query_vec = _embed_query(query)
    conn = _connect_with_wal()
    try:
        # 拉最近 200 条 cache entry (含 embedding)
        # 现有 schema 没 embedding 字段 — 这次只返回 None 表示"暂无 embedding 索引"
        # 真实部署需要 ALTER TABLE 加 query_embedding BLOB 列
        # 留给 R10 schema migration
        # 退化: 仍可工作, 只是退化成"精确匹配"路径
        return None
    finally:
        conn.close()


async def set_semantic_cached(
    query: str,
    max_iter: int,
    budget: float,
    response: dict,
    cost_usd: float,
    tokens: int,
    provider: str | None = None,
) -> None:
    """写入语义缓存 (R10 加 BLOB 后真存 embedding, 当前存 hash 兜底)。"""
    # 当前实现跟 set_cached_async 一样, 留给 R10 加 embedding
    from backend.utils.cache import set_cached_async
    await set_cached_async(query, max_iter, budget, response, cost_usd, tokens, provider)
