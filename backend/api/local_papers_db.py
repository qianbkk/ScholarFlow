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
from dataclasses import replace as _dc_replace
from typing import Optional
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

logger = logging.getLogger(__name__)

# 身份常量: 整个项目里搜 "local_demo" 就能找到所有相关位置
LOCAL_DEMO_SOURCE = "local_demo"


def _tag_as_local_demo(paper) -> "Paper":
    """复制 paper, 改 source / url, 标识"本地演示".

    Paper 是 @dataclass (不是 pydantic), 用 dataclasses.replace 改字段.
    保留所有引用关系 / 评分等内部状态, 仅修改身份字段.
    R10.5.29 (code-review): 用 urlparse 严谨处理 URL, 避免 #fragment 把 ?demo=1
    拼到 fragment 后面变成 'https://x.com/foo#sec?demo=1' (fragment 吃掉 query).
    """
    updates: dict = {"source": LOCAL_DEMO_SOURCE}
    if paper.url:
        updates["url"] = _append_demo_marker(paper.url)
    return _dc_replace(paper, **updates)


def _append_demo_marker(url: str) -> str:
    """URL 末尾追加 ?demo=1 (或 &demo=1 if 已有 query). 用 urlparse 严谨处理
    fragment / 已有 query, 避免 'https://x.com/foo#sec?demo=1' 这种 bug.
    R10.5.29 (simplify): 快路径, 99% mock 论文 URL 是纯 'https://arxiv.org/...'
    无 ? / #, 直接 f-string 拼即可, 避免每次 urlparse 4 个 stdlib 调用 × 50 篇."""
    if "?" not in url and "#" not in url:
        return f"{url}?demo=1"
    parts = urlparse(url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    q["demo"] = "1"
    new_query = urlencode(q)
    # 保留 fragment, query 在 fragment 前面 (URL 规范)
    return urlunparse(parts._replace(query=new_query))


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
