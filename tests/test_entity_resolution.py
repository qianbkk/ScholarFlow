"""测试犀利评论 #2 修复: 实体对齐(DOI + 标题规范化 + Jaccard)"""
from backend.utils.text_utils import deduplicate_papers, _normalize_title, _title_jaccard
from backend.models.paper import Paper


def test_normalize_title():
    assert _normalize_title("Deep Learning for NLP: A Survey") == "deep learning for nlp a survey"
    assert _normalize_title("  CRISPR/Cas9 Gene Editing  ") == "crispr cas9 gene editing"
    assert _normalize_title("Attention Is All You Need.") == "attention is all you need"
    assert _normalize_title("") == ""


def test_jaccard():
    assert _title_jaccard("deep learning for nlp", "deep learning for natural language processing") > 0.4
    assert _title_jaccard("protein structure prediction", "protein folding dynamics") < 0.5
    assert _title_jaccard("a b c", "x y z") == 0.0


def test_dedup_by_doi_with_prefix():
    """S2 和 OpenAlex 的 DOI 都有/无 https://doi.org/ 前缀时应识别为同一篇。"""
    s2 = Paper(
        paper_id="abc123", title="AlphaFold Protein",
        year=2021, citation_count=18000, doi="10.1038/s41586-021-03819-2",
        source="semantic_scholar", references=["bert123"],
    )
    oa = Paper(
        paper_id="W12345", title="alphafold protein",
        year=2021, citation_count=15000, doi="https://doi.org/10.1038/s41586-021-03819-2",
        source="openalex", references=["transformer456"],
    )
    result = deduplicate_papers([s2, oa])
    assert len(result) == 1, f"Expected 1 merged paper, got {len(result)}"
    merged = result[0]
    # citation_count 取较大值
    assert merged.citation_count == 18000
    # source 合并
    assert merged.source == "semantic_scholar+openalex"
    # doi 前缀剥除
    assert merged.doi == "10.1038/s41586-021-03819-2"
    # references 合并
    assert set(merged.references) == {"bert123", "transformer456"}


def test_dedup_by_normalized_title():
    """无 DOI 时,标题规范化匹配。"""
    p1 = Paper(paper_id="a", title="Attention Is All You Need", year=2017, source="ss")
    p2 = Paper(paper_id="b", title="attention is all you need.", year=2017, source="oa")
    p3 = Paper(paper_id="c", title="GPT-3: Language Models are Few-Shot Learners", year=2020, source="ss")
    result = deduplicate_papers([p1, p2, p3])
    assert len(result) == 2


def test_dedup_does_not_merge_different_papers():
    """不同论文不应被误判为同一篇。"""
    p1 = Paper(paper_id="x", title="BERT Pretraining", year=2018, source="ss")
    p2 = Paper(paper_id="y", title="GPT-3 Few-Shot", year=2020, source="oa")
    result = deduplicate_papers([p1, p2])
    assert len(result) == 2


def test_dedup_jaccard_fallback():
    """Jaccard >= 0.80 兜底: 标题词集合高度重合视为同篇。"""
    # 这两个标题核心词几乎完全一致, 只有末尾 "review" 一个词差异
    p1 = Paper(
        paper_id="m",
        title="Graph neural networks for molecular property prediction",
        year=2020, source="ss",
    )
    p2 = Paper(
        paper_id="n",
        title="Graph neural networks for molecular property prediction review",
        year=2020, source="oa",
    )
    result = deduplicate_papers([p1, p2])
    # 7/8 词重叠, jaccard = 7/8 = 0.875 >= 0.80
    assert len(result) == 1, f"Expected 1 (Jaccard fallback), got {len(result)}"


def test_dedup_jaccard_does_not_over_merge():
    """Jaccard < 0.80 时不应合并 (例如同前缀不同论文)。"""
    p1 = Paper(paper_id="x", title="AlphaFold protein structure prediction", year=2021, source="ss")
    p2 = Paper(paper_id="y", title="AlphaFold2 improved multimer modeling", year=2022, source="oa")
    result = deduplicate_papers([p1, p2])
    # AlphaFold vs AlphaFold2 — 核心词不完全一致
    assert len(result) == 2, f"Expected 2, got {len(result)}"


def test_dedup_accepts_dict_input():
    """兼容 dict 输入 (而不是 Paper 对象)。"""
    dict_list = [
        {"paper_id": "a", "title": "Test Paper", "doi": "10.1234/test", "source": "ss"},
        {"paper_id": "b", "title": "test paper.", "doi": "", "source": "oa"},
    ]
    result = deduplicate_papers(dict_list)
    assert len(result) == 1


def test_merge_keeps_longer_abstract():
    """合并时保留更长的 abstract。"""
    short = Paper(
        paper_id="a", title="Test", abstract="Short.", doi="10.1/test", source="ss",
    )
    long_ = Paper(
        paper_id="b", title="test", abstract="A much longer abstract with more content.",
        doi="https://doi.org/10.1/test", source="oa",
    )
    result = deduplicate_papers([short, long_])
    assert len(result) == 1
    assert len(result[0].abstract) > len("Short.")


if __name__ == "__main__":
    test_normalize_title()
    print("[OK] _normalize_title")
    test_jaccard()
    print("[OK] _title_jaccard")
    test_dedup_by_doi_with_prefix()
    print("[OK] dedup_by_doi_with_prefix")
    test_dedup_by_normalized_title()
    print("[OK] dedup_by_normalized_title")
    test_dedup_does_not_merge_different_papers()
    print("[OK] dedup_does_not_merge_different_papers")
    test_dedup_jaccard_fallback()
    print("[OK] dedup_jaccard_fallback")
    test_dedup_accepts_dict_input()
    print("[OK] dedup_accepts_dict_input")
    test_merge_keeps_longer_abstract()
    print("[OK] merge_keeps_longer_abstract")
    print()
    print("=== A2 实体对齐 8/8 测试 全部通过 ===")
