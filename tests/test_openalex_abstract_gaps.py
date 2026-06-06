"""OpenAlex abstract 间隙 (P1) 修复测试。

旧 bug：_reconstruct_abstract 用 `positions[i] for i in sorted(positions)`，
当 inverted_index 位置有间隙（如 pos 0,2 有但 1 缺）会 KeyError → 500。

新实现：按 max position 顺序 join，间隙用空字符串占位。

测试覆盖：
  1) test_reconstruct_handles_gap: 位置间隙 (AI@[0,2], model@[1]) → 不 KeyError
  2) test_reconstruct_dense_index_normal: 稠密索引仍正常重建
  3) test_reconstruct_handles_sparse_index: 极稀疏索引 ([0, 5, 100]) 不抛
  4) test_reconstruct_empty_input: None/{} → ""
  5) test_reconstruct_preserves_word_at_position: 同词多个位置仍分散
"""
import pytest

from backend.api.openalex import _reconstruct_abstract


# ===== 1) 位置间隙 (核心 bug) =====

def test_reconstruct_handles_gap():
    """位置间隙处用空串占位，不抛 KeyError。

    AI 在 pos 0, 3; model 在 pos 1; pos 2 缺失。
    旧实现: positions[2] KeyError
    新实现: 间隙用 "" 占位
    """
    inverted = {"AI": [0, 3], "model": [1]}
    result = _reconstruct_abstract(inverted)

    # 验证: 不抛错
    assert isinstance(result, str)
    # 验证: 4 个位置都参与 join
    parts = result.split(" ")
    assert len(parts) == 4, (
        f"4 个位置 (0..3) 应 join 成 4 段, 实际 {len(parts)}: {parts}"
    )
    # 验证: 内容正确（间隙为 ""）
    assert parts[0] == "AI"
    assert parts[1] == "model"
    assert parts[2] == ""  # 间隙占位
    assert parts[3] == "AI"


# ===== 2) 稠密索引 (回归) =====

def test_reconstruct_dense_index_normal():
    """稠密索引 (无间隙) 仍正常重建 — 证明修复不破坏正常路径。"""
    inverted = {
        "The": [0],
        "quick": [1],
        "brown": [2],
        "fox": [3],
    }
    assert _reconstruct_abstract(inverted) == "The quick brown fox"


# ===== 3) 极稀疏索引 =====

def test_reconstruct_handles_sparse_index():
    """位置极稀疏（0, 5, 100）也能 join，不抛。"""
    inverted = {
        "start": [0],
        "middle": [5],
        "end": [100],
    }
    result = _reconstruct_abstract(inverted)
    parts = result.split(" ")
    # 101 个位置 (0..100)
    assert len(parts) == 101, (
        f"极稀疏索引应 join 101 段 (0..100), 实际 {len(parts)}"
    )
    assert parts[0] == "start"
    assert parts[5] == "middle"
    assert parts[100] == "end"
    # 间隙都是空串
    assert all(p == "" for p in parts[1:5])
    assert all(p == "" for p in parts[6:100])


# ===== 4) 退化输入 =====

def test_reconstruct_none_returns_empty():
    """None 输入 → 空串 (不抛错)。"""
    assert _reconstruct_abstract(None) == ""


def test_reconstruct_empty_dict_returns_empty():
    """空 dict → 空串。"""
    assert _reconstruct_abstract({}) == ""


def test_reconstruct_empty_lists_returns_empty():
    """所有 pos_list 都空 → 空串。"""
    assert _reconstruct_abstract({"word": []}) == ""


# ===== 5) 同词多个位置仍分散 =====

def test_reconstruct_preserves_word_at_position():
    """同 word 出现在多个 position 时仍按 pos 分散 (不合并去重)。"""
    inverted = {
        "the": [0, 3],
        "cat": [1],
        "sat": [2],
    }
    assert _reconstruct_abstract(inverted) == "the cat sat the"


# ===== 6) 长索引 + 多间隙 =====

def test_reconstruct_long_index_with_multiple_gaps():
    """长索引 + 多间隙 — 更现实的真实 OpenAlex 数据场景。"""
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
    parts = result.split(" ")
    assert len(parts) == 8, f"8 个位置 (0..7) 应 join 8 段, 实际 {len(parts)}"
    assert parts[0] == "Machine"
    assert parts[1] == "learning"
    assert parts[2] == ""  # gap
    assert parts[3] == "models"
    assert parts[4] == "leverage"
    assert parts[5] == "transformer"
    assert parts[6] == ""  # gap
    assert parts[7] == "architectures"


if __name__ == "__main__":
    import sys
    sys.path.insert(0, "D:/AI/Claude code workspace/Atest")
    pytest.main([__file__, "-v"])
