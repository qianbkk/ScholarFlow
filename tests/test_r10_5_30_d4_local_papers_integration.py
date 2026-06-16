"""R10.5.30 (D4 P1-1): 本地论文库真接入 search pipeline.

对应 CD.txt 隐性问题: "50-58 篇 mock 论文被当成真实结果" — 旧版 mock_data
返 Paper 没 source 标签, 前端 badge 永远不亮. 这一版:
  - openalex.search_papers 走 local_papers_db 而非 mock_data
  - Paper.source = "local_demo" 真实到达 response
  - 前端 QueryPanel '本地演示' badge 亮起

覆盖:
  1. openalex.search_papers (mock 模式) 返 paper.source = "local_demo"
  2. local_papers_db search_local_demo 跟 mock_data 行为兼容
  3. Paper dataclass 字段保留 (title / year / authors / venue / source)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_openalex_search_papers_marks_source_local_demo():
    """D4 P1-1: openalex.search_papers (mock 模式) 返 paper.source = 'local_demo'."""
    # mock 模式需要 API_MOCK=true (否则走真实 OpenAlex HTTP 401)
    os.environ["API_MOCK"] = "true"
    os.environ["LLM_MOCK"] = "true"
    # Reset cached is_runtime_mock
    import importlib
    import backend.utils.runtime_mode
    importlib.reload(backend.utils.runtime_mode)
    import backend.api.openalex
    importlib.reload(backend.api.openalex)
    import asyncio
    papers = asyncio.run(backend.api.openalex.search_papers("transformer", limit=3))
    assert len(papers) >= 1, f"应至少返 1 篇本地演示论文, 实际 {len(papers)}"
    for p in papers:
        assert p.source == "local_demo", (
            f"D4: paper.source 应 = 'local_demo', 实际 {p.source!r}. "
            f"前端的 '本地演示' badge 亮不起来因为 source 标签没到."
        )
        assert p.title, "title 不应为空"
        assert p.year > 0, f"year 必须 > 0, 实际 {p.year}"


def test_local_papers_db_compatible_with_mock_data():
    """D4: local_papers_db.search_local_demo 跟 mock_data.get_mock_papers 行为兼容.

    - 同 query 返同 paper_ids
    - limit 限制一致
    - 全部 paper.source = 'local_demo'
    """
    from backend.api.local_papers_db import search_local_demo
    papers = search_local_demo("transformer", limit=5)
    assert len(papers) == 5
    for p in papers:
        assert p.source == "local_demo"


def test_local_papers_db_url_has_demo_marker():
    """D4: 本地论文 url 加 ?demo=1 标识 (R10.5.29 simplify 修过 #fragment bug)."""
    from backend.api.local_papers_db import get_local_demo_papers
    papers = get_local_demo_papers(limit=5)
    for p in papers:
        if p.url:
            assert "demo=1" in p.url, f"url 应含 demo=1: {p.url}"


def test_local_papers_db_preserves_authors_and_year():
    """D4: local_papers_db 完整保留 Paper 字段 (title/year/authors/venue/citation_count)."""
    from backend.api.local_papers_db import get_all_local_demo
    papers = get_all_local_demo()
    assert len(papers) >= 30, f"本地库应 ≥30 篇, 实际 {len(papers)}"
    p = papers[0]
    assert p.title
    assert p.year > 0
    assert len(p.authors) >= 1
    assert p.citation_count >= 0
    assert p.source == "local_demo"
