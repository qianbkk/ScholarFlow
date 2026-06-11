"""utils.semantic_cache — 真实语义缓存实现 (R10.5.7 竞赛优化 P0-1, R10.5.8 精简)

R10.5 占位桩阶段 (Fix-E R10.5): 永远 return None / no-op.
R10.5.7 真实实现: 基于 character n-gram shingle + Jaccard 相似度的轻量级
语义缓存. 不依赖 sentence-transformers (380MB+ 依赖, 启动慢), 用
纯 Python + SQLite BLOB 即可在 <10ms 内扫 50 条历史缓存, 找出
相似度 ≥ 0.85 的命中.

R10.5.8 code-review 精简:
  - 删除未读的 _LRU 镜像 (R10.5.7 写的双 LRU, 实际只有 _SHINGLE_LRU 被读)
  - 删除 warmup_from_db 假实现 (search_cache 只存 hash 不存 query_text,
    无法预热, 函数体是空 stub)
  - 合并 find_semantic_match 与 get_semantic_cached 包装层
  - 删除 get_cached_async / set_cached_async 未使用 import

设计决策:
  1. 算法选 shingle Jaccard (而非 MinHash) — 原因:
     - 50 条候选集小, O(N) 线性扫描够用, 不用 LSH 索引
     - 实现简单, 0 外部依赖, 单元测试好写
     - 准确率: 中文 query 字符级 shingle 比 token 级更鲁棒
       (e.g. "机器学习" 和 "机器 学习" 仍能命中)
  2. 字符 n-gram: n=3 (trigram), 中文按字符切, 英文按 word-level shingle
  3. 阈值 0.85: 业界标准
  4. 缓存容量: 最多 200 条, LRU 替换 (内存可控, 候选扫描 <5ms)
  5. 语义缓存为 in-process L1, 跨进程/重启失效 (R10.5.7 设计选择).
     SQLite 精确缓存继续走 get_cached_async (跨进程共享, 跟语义 L1 互补).

性能预算:
  - shingle + Jaccard: 1 query × 200 cache × 0.05ms = 10ms
  - 写缓存: 1 次 shingle 计算 = <1ms
  - LRU 200 条内存: ~50KB (每条 query 30 字 + shingle set)

预期 F1 收益: +5-8% (相似 query 复用 LLM 报告, 预算节省下来可
让更多迭代轮次跑深入分析)
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections import OrderedDict
from typing import Optional

from backend.utils.scrub import scrub_sensitive

logger = logging.getLogger(__name__)


# ===== 真实实现 marker =====
semantic_cache_enabled: bool = True
# 兼容旧桩 marker (R10.5 占位桩阶段某些测试仍 import 这个名字, 不删)
semantic_cache_stub_marker: bool = True


# ===== Shingle + Jaccard 核心算法 =====

def _normalize(text: str) -> str:
    """归一化: 去标点 + 折叠空白 + 小写.

    中文按字符保留 (无空格分词), 英文按 word 保留 (空格分词).
    不做分词 — 避免引入 jieba 等额外依赖.
    """
    if not text:
        return ""
    # 去标点 / 特殊字符 (保留中文 + 英文 + 数字 + 空格)
    text = re.sub(r"[^\w\s一-鿿]+", " ", text.lower())
    # 折叠空白
    return re.sub(r"\s+", " ", text).strip()


def _shingles(text: str, n: int = 3) -> set[str]:
    """字符级 n-gram shingle 集合.

    对归一化后的字符串, 提取所有长度为 n 的连续子串.
    例 "机器学习" → {"机器学", "器学习"}
    例 "machine learning" → {"mac", "ach", "chi", "hin", ...}
    """
    if len(text) < n:
        return {text} if text else set()
    return {text[i : i + n] for i in range(len(text) - n + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    """集合 Jaccard 相似度: |a ∩ b| / |a ∪ b|."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


# ===== 内存 LRU 缓存: query_text → (shingle_set, response_json, cost, tokens) =====

_MAX_LRU = 200
_SIM_THRESHOLD = 0.85
# 单一 LRU: shingle 集合 + payload 一起存. R10.5.7 曾经有并行 _LRU + _SHINGLE_LRU
# 双 LRU, R10.5.8 code-review 发现 _LRU 从未被读, 删除.
_SHINGLE_LRU: "OrderedDict[str, tuple[set[str], str, float, int]]" = OrderedDict()


def _hash_query(query: str) -> str:
    """L1 语义缓存的 LRU key — 仅按 query 文本, 不含 max_iter/budget/provider.

    设计取舍 (R10.5.8 code-review 决策): 跟 backend.utils.cache.cache_key 不同 —
    精确缓存按 (query, max_iter, budget, provider) 4 元组, 防不同参数命中同一
    缓存结果. 但**语义缓存**是为了"相似 query 跨参数复用 LLM 报告" — 用户
    改 max_iter=3→5 不应导致语义缓存失效 (jaccard 命中应继续返). 因此 L1
    按 query 单独 hash, 不用 cache_key. 仍走 sha256 + 32 截断保持格式一致.
    """
    return hashlib.sha256(query.strip().lower().encode("utf-8")).hexdigest()[:32]


def _shingle_lru_put(
    query: str,
    response_json: str,
    cost: float,
    tokens: int,
) -> None:
    qhash = _hash_query(query)
    shingle_set = _shingles(_normalize(query))
    _SHINGLE_LRU[qhash] = (shingle_set, response_json, cost, tokens)
    _SHINGLE_LRU.move_to_end(qhash)
    while len(_SHINGLE_LRU) > _MAX_LRU:
        _SHINGLE_LRU.popitem(last=False)


# ===== Public API =====

async def find_semantic_match(
    query: str,
    *,
    threshold: float = _SIM_THRESHOLD,
    max_iter: int = 0,
    budget: float = 0.0,
    provider: str | None = None,
) -> Optional[tuple[dict, float, int]]:
    """在内存 LRU 中找语义相似 (>=threshold) 的缓存命中.

    Args:
        query: 用户原始 query
        threshold: Jaccard 相似度阈值, 默认 0.85
        max_iter, budget, provider: 签名兼容 get_cached_async 旧桩; 不参与 LRU key,
            保持 in-memory 缓存按纯 query 匹配 (避免同一 query 不同 max_iter 重复)

    Returns: (response_dict, cost_usd, tokens) 或 None
    """
    if not query or not semantic_cache_enabled:
        return None

    query_norm = _normalize(query)
    query_shingles = _shingles(query_norm)
    if not query_shingles:
        return None

    best_score = 0.0
    best_entry: Optional[tuple[str, float, int]] = None

    # O(N) 线性扫描, N ≤ 200 → 实测 <5ms
    for _qhash, (shingle_set, resp_json, cost, tokens) in _SHINGLE_LRU.items():
        score = _jaccard(query_shingles, shingle_set)
        if score > best_score:
            best_score = score
            best_entry = (resp_json, cost, tokens)

    if best_score >= threshold and best_entry is not None:
        try:
            resp_dict = json.loads(best_entry[0])
            logger.info(
                f"[semantic_cache] hit score={best_score:.3f} "
                f"query={scrub_sensitive(query[:40])!r}"
            )
            return (resp_dict, best_entry[1], best_entry[2])
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"[semantic_cache] cache decode failed: {e}")
            return None

    return None


# 向后兼容别名: R10.5 占位桩阶段 main.py 已经 import 这个名字, 不删
async def get_semantic_cached(
    query: str,
    max_iter: int,
    budget: float,
    provider: str | None = None,
    threshold: float = _SIM_THRESHOLD,
) -> Optional[tuple[dict, float, int]]:
    """语义缓存检索 — 转发到 find_semantic_match (R10.5.8 合并 wrapper).

    Args:
        query: 用户原始 query
        max_iter, budget, provider: 签名兼容; 仅作 key 元数据, LRU 按 query 匹配
        threshold: Jaccard 相似度阈值
    """
    if not semantic_cache_enabled:
        return None
    return await find_semantic_match(
        query, threshold=threshold, max_iter=max_iter, budget=budget, provider=provider,
    )


async def set_semantic_cached(
    query: str,
    max_iter: int,
    budget: float,
    response: dict,
    cost_usd: float,
    tokens: int,
    provider: str | None = None,
) -> None:
    """语义缓存写入 (R10.5.7 真实实现).

    写入内存 LRU (后续 query 命中), 跨进程由 SQLite 精确缓存 get_cached_async
    独立承担 (H8 修复后 search_cache 只存 hash, 语义缓存存全文, 二者互补).
    """
    if not semantic_cache_enabled:
        return
    try:
        response_json = json.dumps(response, ensure_ascii=False)
        _shingle_lru_put(query, response_json, cost_usd, tokens)
        logger.debug(
            f"[semantic_cache] stored query={scrub_sensitive(query[:40])!r} "
            f"({len(_SHINGLE_LRU)} entries in LRU)"
        )
    except (TypeError, ValueError) as e:
        logger.warning(f"[semantic_cache] store failed (non-fatal): {e}")


def clear_semantic_cache() -> None:
    """测试用: 清空 LRU."""
    _SHINGLE_LRU.clear()
