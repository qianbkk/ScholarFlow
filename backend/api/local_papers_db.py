"""
backend.api.local_papers_db
============================

R10.5.28 (CD.txt 隐性问题修复): 演示数据明确身份.

CD.txt 提到: "50-58 篇 mock 论文被当成真实结果" — 旧版 mock_data.py
返回的论文没有明确标识"这是演示数据", 前端 UI 跟真实 Semantic Scholar
/ OpenAlex 结果混在一起显示, 用户不知道哪些是真实 / 哪些是 mock.

本模块提供**薄包装层**:
  - get_local_demo_papers() / search_local_demo() / get_all_local_demo()
    跟 mock_data.py 对应函数同接口, 但 Paper.source = "local_demo",
    Paper.url 加 "?demo=1" 标识, 让前端 ReportPanel / QueryPanel 能
    一眼看出"这是本地演示数据, 非真实检索结果".
  - 内部直接委托给 mock_data.py, **不复制数据**, 行为一致.

调用方:
  - backend.api.services.providers 在 OPEN_DEMO 模式下调用本模块
  - 前端在 paper.source === "local_demo" 时显示 "🧪 本地演示" badge

R10.5.28: 行为完全兼容 — mock_data.py 仍是底层数据源, 本模块是身份层.
若未来需要切换数据源 (e.g. 加载用户上传的本地 PDF), 只换底层即可.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 身份常量: 整个项目里搜 "local_demo" 就能找到所有相关位置
LOCAL_DEMO_SOURCE = "local_demo"


def _tag_as_local_demo(paper) -> "Paper":
    """复制 paper, 改 source / url, 标识"本地演示".

    Paper 是 @dataclass (不是 pydantic), 用 dataclasses.replace 改字段.
    保留所有引用关系 / 评分等内部状态, 仅修改身份字段.
    """
    from dataclasses import replace as _dc_replace
    updates: dict = {"source": LOCAL_DEMO_SOURCE}
    if paper.url:
        sep = "&" if "?" in paper.url else "?"
        updates["url"] = f"{paper.url}{sep}demo=1"
    return _dc_replace(paper, **updates)


def get_all_local_demo() -> list:
    """返全部本地演示论文 (克隆 + 标识 source='local_demo')."""
    from backend.api.mock_data import get_all_mock_papers
    return [_tag_as_local_demo(p) for p in get_all_mock_papers()]


def get_local_demo_papers(limit: int = 50) -> list:
    """返 limit 篇本地演示论文 (按原排序, 标识 source='local_demo')."""
    from backend.api.mock_data import get_mock_papers
    return [_tag_as_local_demo(p) for p in get_mock_papers(limit=limit)]


def search_local_demo(query: str, limit: int = 20) -> list:
    """按 query 检索本地演示论文, 标识 source='local_demo'."""
    from backend.api.mock_data import get_mock_papers
    return [_tag_as_local_demo(p) for p in get_mock_papers(query=query, limit=limit)]


def is_local_demo_paper(paper) -> bool:
    """判断 paper 是否来自本地演示库. 前端 / 测试 / audit log 共用."""
    if paper is None:
        return False
    src: Optional[str] = getattr(paper, "source", None)
    return src == LOCAL_DEMO_SOURCE
