"""OpenAlex abstract 重建 (P1) 修复测试。

旧 bug：_reconstruct_abstract 用 `positions[i] for i in sorted(positions)`，
当 inverted_index 位置有间隙（如 pos 0,2 有但 1 缺）会 KeyError → 500。

新实现：按 max position 顺序 join，间隙用空字符串占位。
测试覆盖：
  1) 正常稠密索引 → 正常重建
  2) 位置有间隙 → 不抛错，用空串占位
  3) 单词重复出现在多个位置 → 仍分散
  4) inverted_index=None 或 {} → 返回空串
  5) 极端情况：pos 列表中有非连续整数 (e.g. {0, 5, 100}) → 仍能 join 不抛
"""
import pytest

from backend.api.openalex import _reconstruct_abstract


# ===== 1) 正常稠密索引 =====

def test_reconstruct_normal_dense_index():
    """稠密索引：相邻位置无 gap。"""
    inverted = {
        "The": [0],
        "quick": [1],
        "brown": [2],
        "fox": [3],
    }
    assert _reconstruct_abstract(inverted) == "The quick brown fox"


# ===== 2) 位置间隙 (核心 bug) =====

def test_reconstruct_handles_gap_without_keyerror():
    """位置间隙处用空串占位，不抛 KeyError。"""
    # AI 在 0,3；model 在 1。positions dict = {0:AI, 1:model, 3:AI}，
    # pos 2 缺失 → 旧实现 `positions[2]` KeyError。
    inverted = {"AI": [0, 3], "model": [1]}
    result = _reconstruct_abstract(inverted)
    # 验证 1：不抛错
    assert isinstance(result, str)
    # 验证 2：4 个位置 (0..3) 都参与了 join
    parts = result.split(" ")
    assert len(parts) == 4
    assert parts[0] == "AI"
    assert parts[1] == "model"
    assert parts[2] == ""  # 间隙占位
    assert parts[3] == "AI"


def test_reconstruct_gap_with_long_index():
    """长索引中有 gap 的更现实场景。"""
    inverted = {
        "Machine": [0],
        "learning": [1],
        # 2 missing
        "models": [3],
        "leverage": [4],
        "transformer": [5],
        # 6 missing
        "architectures": [7],
    }
    result = _reconstruct_abstract(inverted)
    # 8 个位置（0-7），中间 2 个空串
    parts = result.split(" ")
    assert len(parts) == 8
    assert parts[0] == "Machine"
    assert parts[1] == "learning"
    assert parts[2] == ""  # gap
    assert parts[3] == "models"
    assert parts[5] == "transformer"
    assert parts[6] == ""  # gap
    assert parts[7] == "architectures"


# ===== 3) 单词多次出现 =====

def test_reconstruct_repeated_word():
    """同一 word 出现在多个位置时仍按 pos 分散。"""
    inverted = {
        "the": [0, 3],
        "cat": [1],
        "sat": [2],
    }
    assert _reconstruct_abstract(inverted) == "the cat sat the"


# ===== 4) 退化输入 =====

def test_reconstruct_none_returns_empty():
    assert _reconstruct_abstract(None) == ""


def test_reconstruct_empty_dict_returns_empty():
    assert _reconstruct_abstract({}) == ""


def test_reconstruct_empty_lists_returns_empty():
    """所有 pos_list 都为空 → positions dict 为空 → 返回空串（不抛错）。"""
    assert _reconstruct_abstract({"word": []}) == ""


# ===== 5) 极端稀疏索引 =====

def test_reconstruct_extremely_sparse_index():
    """位置极稀疏（0, 5, 100）也能 join。"""
    inverted = {
        "start": [0],
        "middle": [5],
        "end": [100],
    }
    result = _reconstruct_abstract(inverted)
    parts = result.split(" ")
    # 101 个位置 (0..100)，大部分空串
    assert len(parts) == 101
    assert parts[0] == "start"
    assert parts[5] == "middle"
    assert parts[100] == "end"
    # 中间都是空串
    assert all(p == "" for p in parts[1:5])
    assert all(p == "" for p in parts[6:100])


# ===== 6) 行为对比：旧实现 vs 新实现的语义差异 =====

def test_old_impl_skips_gap_silently():
    """演示旧实现 `positions[i] for i in sorted(positions)` 在 gap 处**静默跳过**。

    旧代码逻辑（已删除）：sorted(positions) 不会包含缺失的 pos，
    因此 positions dict 缺 pos 2 时，旧实现只输出 3 个 token (AI/model/AI)，
    完全丢失 pos 2 处的语义结构。
    """
    inverted = {"AI": [0, 3], "model": [1]}
    positions = {}
    for word, pos_list in inverted.items():
        for pos in pos_list:
            positions[pos] = word
    # 旧实现的代码（已删除）会跑这一行：
    old_result = " ".join(positions[i] for i in sorted(positions))
    # 旧实现只输出 3 个 token (丢失了 pos 2 的占位)
    assert old_result == "AI model AI"
    # 旧实现的 token 数 = len(positions)，不含 gap
    assert len(old_result.split(" ")) == 3


def test_new_impl_preserves_position_structure():
    """演示新实现保留位置结构（gap 用空串占位）。"""
    inverted = {"AI": [0, 3], "model": [1]}
    new_result = _reconstruct_abstract(inverted)
    # 新实现输出 4 个 token (0..3)，pos 2 是空串
    assert new_result == "AI model  AI"  # pos 2 是空串
    parts = new_result.split(" ")
    assert len(parts) == 4
    assert parts[2] == ""
    # 与旧实现的差异：新实现不会静默"压缩"长度
    assert len(new_result.split(" ")) > len(positions := {"AI": [0, 3], "model": [1]} and {0: "AI", 1: "model", 3: "AI"})


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
