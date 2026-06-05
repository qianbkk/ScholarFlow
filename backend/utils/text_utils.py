"""文本与论文去重工具。"""
import json
import re
from typing import Iterable, Optional


def deduplicate_papers(papers: Iterable) -> list:
    """按 paper_id 和标题前 50 字符去重。"""
    from backend.models.paper import Paper

    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    result = []

    for p in papers:
        pid = p.paper_id if hasattr(p, "paper_id") else p.get("paper_id", "")
        title = p.title if hasattr(p, "title") else p.get("title", "")
        title_key = (title or "").lower()[:50]

        if pid and pid in seen_ids:
            continue
        if title_key and title_key in seen_titles:
            continue

        if pid:
            seen_ids.add(pid)
        if title_key:
            seen_titles.add(title_key)
        result.append(p)

    return result


def truncate(text: str, max_len: int) -> str:
    """安全截断字符串，超长时附加省略号。"""
    if not text:
        return ""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def extract_json_object(text: str) -> Optional[dict]:
    """从 LLM 输出文本中提取第一个 JSON 对象。"""
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None
