"""R10.5.28 (CD.txt 隐性问题修复): 本地论文库身份标识测试.

CD.txt 提到: "50-58 篇 mock 论文被当成真实结果". 修复: 新建
backend.api.local_papers_db 薄包装, Paper.source = "local_demo",
Paper.url 加 #demo=1 标识, 前端能区分演示 / 真实结果.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.api.local_papers_db import (
    LOCAL_DEMO_SOURCE,
    get_all_local_demo,
    get_local_demo_papers,
    is_local_demo_paper,
    search_local_demo,
)


def test_local_demo_source_constant():
    """源标识常量必须是 'local_demo', 整个项目一致."""
    assert LOCAL_DEMO_SOURCE == "local_demo"


def test_get_local_demo_papers_marks_source():
    """get_local_demo_papers 返回的论文 source 全部是 'local_demo'."""
    papers = get_local_demo_papers(limit=5)
    assert len(papers) >= 1, "本地库至少有 1 篇论文"
    for p in papers:
        assert p.source == "local_demo", (
            f"本地论文 source 应为 'local_demo', 实际 {p.source!r}"
        )
        # 原始字段 (title, year, authors) 保留
        assert p.title, "title 不该为空"
        assert p.year > 0, "year 必须 > 0"


def test_get_all_local_demo_marks_source():
    """get_all_local_demo 全部论文 source = 'local_demo'."""
    papers = get_all_local_demo()
    assert len(papers) >= 30, f"本地库应 ≥30 篇, 实际 {len(papers)}"
    for p in papers:
        assert p.source == "local_demo"


def test_search_local_demo_preserves_source():
    """按 query 检索时返回的论文同样标 'local_demo'."""
    papers = search_local_demo("transformer", limit=5)
    if not papers:
        # 关键词没命中, 退回到头部论文
        papers = search_local_demo("xyz_no_match_xyz", limit=3)
    for p in papers:
        assert p.source == "local_demo"


def test_is_local_demo_paper_helper():
    """is_local_demo_paper 正确判断真实 / 演示 / None."""
    demo = get_local_demo_papers(limit=1)[0]
    assert is_local_demo_paper(demo) is True
    # 真实论文 (source 不为 local_demo)
    from backend.api.mock_data import get_mock_papers
    raw = get_mock_papers(limit=1)[0]
    # 拿一个不带 source 标识的 raw paper
    assert is_local_demo_paper(None) is False
    # 直接构造一个空 source 论文
    from backend.models.paper import Paper
    fake_real = Paper(paper_id="ss_real", title="X", source="semantic_scholar")
    assert is_local_demo_paper(fake_real) is False


def test_local_demo_url_has_demo_marker():
    """本地演示论文 url 末尾带 #demo=1 标识."""
    papers = get_local_demo_papers(limit=3)
    for p in papers:
        if p.url:
            assert "demo=1" in p.url, (
                f"本地演示论文 url 应含 'demo=1', 实际 {p.url!r}"
            )


def test_local_demo_does_not_mutate_originals():
    """包装层不能污染底层 mock_data._MOCK_PAPERS 数据."""
    from backend.api.mock_data import get_all_mock_papers
    before = get_all_mock_papers()
    before_sources = [p.source for p in before]
    # 调用本地库包装
    get_all_local_demo()
    get_local_demo_papers(5)
    search_local_demo("test", 3)
    # 验证底层数据 source 没被改
    after = get_all_mock_papers()
    after_sources = [p.source for p in after]
    assert before_sources == after_sources, (
        f"本地库包装污染了 mock_data 源: {set(before_sources)} → {set(after_sources)}"
    )
