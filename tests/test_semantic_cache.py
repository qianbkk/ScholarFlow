"""R10.5.7 P0-1 语义缓存单元测试.

覆盖:
  1. 字符 trigram shingle 提取 (中文 / 英文 / 短串)
  2. Jaccard 相似度边界 (空 / 完全相同 / 完全不交 / 部分重叠)
  3. 归一化 (标点 / 大小写 / 多空格折叠)
  4. LRU 写入 + 读出
  5. 语义检索: 相似 query 命中, 不相似 query 不命中
  6. 阈值调整 (threshold 参数)
  7. clear_semantic_cache 清空
  8. 并发安全: 同时写 N 条后, 查询都 OK
"""
from __future__ import annotations

import asyncio
import pytest

from backend.utils import semantic_cache as sc


@pytest.fixture(autouse=True)
def _clear_lru():
    """每个测试前后清空 LRU, 避免污染."""
    sc.clear_semantic_cache()
    yield
    sc.clear_semantic_cache()


# ===== 归一化 =====

def test_normalize_strips_punctuation_and_lowercases():
    assert sc._normalize("Hello, World!") == "hello world"
    assert sc._normalize("机器学习 (ML)") == "机器学习 ml"
    assert sc._normalize("  multiple   spaces  ") == "multiple spaces"


def test_normalize_empty():
    assert sc._normalize("") == ""
    assert sc._normalize(None) == ""  # type: ignore


# ===== Shingle =====

def test_shingles_chinese_trigrams():
    # "机器学习" → 长度 4, n=3 → 2 个 trigram
    s = sc._shingles("机器学习", n=3)
    assert s == {"机器学", "器学习"}


def test_shingles_english_word_level():
    # 字符级 n-gram: "machine learning" → 多个 3-gram
    s = sc._shingles("machine learning", n=3)
    assert "mac" in s
    assert "ach" in s
    assert "ne " in s
    assert " le" in s


def test_shingles_short_text_keeps_as_single_shingle():
    # 长度 < n 时, 整串作为 1 个 shingle
    assert sc._shingles("hi", n=3) == {"hi"}


def test_shingles_empty():
    assert sc._shingles("") == set()


# ===== Jaccard =====

def test_jaccard_identical_is_one():
    a = {"a", "b", "c"}
    assert sc._jaccard(a, a) == 1.0


def test_jaccard_disjoint_is_zero():
    a = {"a", "b", "c"}
    b = {"x", "y", "z"}
    assert sc._jaccard(a, b) == 0.0


def test_jaccard_partial():
    a = {"a", "b", "c", "d"}
    b = {"c", "d", "e", "f"}
    # 交集 2, 并集 6 → 0.333
    assert abs(sc._jaccard(a, b) - 2 / 6) < 0.01


def test_jaccard_empty_set_is_zero():
    assert sc._jaccard(set(), {"a"}) == 0.0
    assert sc._jaccard({"a"}, set()) == 0.0


# ===== find_semantic_match =====

@pytest.mark.asyncio
async def test_semantic_match_exact_returns_entry():
    resp = {"status": "done", "report": "test"}
    await sc.set_semantic_cached("机器学习", 3, 1.0, resp, 0.5, 100)
    hit = await sc.find_semantic_match("机器学习")
    assert hit is not None
    r, cost, tokens = hit
    assert r == resp
    assert cost == 0.5
    assert tokens == 100


@pytest.mark.asyncio
async def test_semantic_match_similar_chinese_above_threshold():
    """中文相似 query: 加空格 / 改字序, 应仍能命中."""
    resp = {"status": "done"}
    await sc.set_semantic_cached("深度学习在图像识别中的应用", 3, 1.0, resp, 0.5, 100)

    # 改一个字 "中" 去掉: trigram 实际 Jaccard ≈ 0.615 (字符级 trigram
    # 对中文 1 字差异敏感, 因为 trigram 长度 = 3, 改 1 字破坏 3 个 trigram)
    # 0.5 阈值能命中, 0.7 阈值会 miss
    hit = await sc.find_semantic_match("深度学习在图像识别的应用", threshold=0.5)
    assert hit is not None, "相似 query (Jaccard ≈ 0.62) 应在 0.5 阈值下命中"

    # 阈值过严时不应命中
    miss = await sc.find_semantic_match("深度学习在图像识别的应用", threshold=0.99)
    assert miss is None, "Jaccard ≈ 0.62 的 query 在 0.99 阈值下应 miss"


@pytest.mark.asyncio
async def test_semantic_match_dissimilar_returns_none():
    resp = {"status": "done"}
    await sc.set_semantic_cached("transformer self-attention", 3, 1.0, resp, 0.5, 100)
    # 完全不同 query: 字符级 0 重叠
    hit = await sc.find_semantic_match("蛋白质结构预测的新方法", threshold=0.5)
    assert hit is None


@pytest.mark.asyncio
async def test_semantic_match_threshold_filtering():
    resp = {"status": "done"}
    await sc.set_semantic_cached("alpha fold 蛋白质结构预测", 3, 1.0, resp, 0.5, 100)
    # 中等相似 (~50% 字符重叠): 高阈值 miss, 低阈值 hit
    miss = await sc.find_semantic_match("alpha fold 预测", threshold=0.99)
    assert miss is None
    hit = await sc.find_semantic_match("alpha fold 预测", threshold=0.5)
    assert hit is not None


@pytest.mark.asyncio
async def test_semantic_cache_lru_eviction():
    """LRU 容量上限测试 — 写满后旧的应被弹出, 总条目数受 cap 限制.

    注: LRU 弹出的旧 query, 如果跟剩余 query 字符级仍高相似, 语义匹配可能
    命中剩余 query (这是预期行为, 不是 bug). 这里的测试只用长度很不同的 query
    避免误判.
    """
    original_max = sc._SHINGLE_LRU_MAX
    sc._SHINGLE_LRU_MAX = 3  # 临时调小
    try:
        # 写 5 条, 字符完全不重叠, 避免 Jaccard 误命中
        queries = [
            "alphafold protein structure",
            "transformer attention mechanism",
            "graph neural network molecular",
            "retrieval augmented generation survey",
            "reinforcement learning multi agent",
        ]
        for i, q in enumerate(queries):
            await sc.set_semantic_cached(q, 3, 1.0, {"id": i}, 0.1, 50)
        assert len(sc._SHINGLE_LRU) == 3, "LRU 容量应被 cap 在 3"
        # 验证: 最新的 reinforcement learning multi agent 应能命中
        hit = await sc.find_semantic_match("reinforcement learning multi agent", threshold=0.5)
        assert hit is not None, "最新写入的 query 应能命中"
    finally:
        sc._SHINGLE_LRU_MAX = original_max


@pytest.mark.asyncio
async def test_semantic_cache_disabled_returns_none():
    sc.semantic_cache_enabled = False
    try:
        await sc.set_semantic_cached("机器学习", 3, 1.0, {"x": 1}, 0.1, 10)
        hit = await sc.find_semantic_match("机器学习")
        assert hit is None
    finally:
        sc.semantic_cache_enabled = True


@pytest.mark.asyncio
async def test_semantic_cache_concurrent_writes():
    """并发写 N 条, 查询都能命中."""
    n = 20
    await asyncio.gather(*[
        sc.set_semantic_cached(f"concurrent_query_{i}", 3, 1.0, {"i": i}, 0.1, 50)
        for i in range(n)
    ])
    assert len(sc._SHINGLE_LRU) == min(n, sc._SHINGLE_LRU_MAX)
    # 抽样查几条
    for i in [0, 10, 19]:
        hit = await sc.find_semantic_match(f"concurrent_query_{i}")
        assert hit is not None
        r, _, _ = hit
        assert r["i"] == i


@pytest.mark.asyncio
async def test_semantic_cache_punct_normalization():
    """标点差异不应让相似 query 漏命中."""
    resp = {"x": 1}
    await sc.set_semantic_cached("transformer, attention, mechanism", 3, 1.0, resp, 0.1, 10)
    # 标点不同, 单词相同 → trigram 大量重叠
    hit = await sc.find_semantic_match("transformer attention mechanism")
    assert hit is not None


def test_clear_semantic_cache_resets_lru():
    # 同步测试 clear: 验证空操作 + 不会抛错
    sc._SHINGLE_LRU["fake"] = (set(), "{}", 0.0, 0)
    sc._LRU["fake"] = ("{}", 0.0, 0, 0.0)
    sc.clear_semantic_cache()
    assert len(sc._SHINGLE_LRU) == 0
    assert len(sc._LRU) == 0
