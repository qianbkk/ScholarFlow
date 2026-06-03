# ScholarFlow — 科研文献智能搜索系统
# CLAUDE CODE 全自动构建文档

---

## 🤖 给 Claude Code 的开场指令

你好！请阅读完本文档所有内容后，按照文末的「开发顺序」从第1步开始，**全自动完成整个项目的初步构建**。遇到细节问题自行判断，不需要询问，直接实现最合理的方案。每完成一个主要步骤后，用一行中文说明完成了什么，然后继续下一步。目标是构建一个可以运行的完整初版系统。

---

## 🎯 项目定位

**ScholarFlow** 是面向研究生科研工作流的自主多Agent学术情报系统。

用户输入一个复杂的学术研究问题，系统通过8个串联LangGraph节点自动完成：
查询理解与分解 → 多源并行检索 → 引文网络扩展 → 三维质检排序 → 自适应迭代优化 → 结构化综述报告 → 引文知识图谱 → 成本追踪汇报

**参赛信息：**
- 第八届中国研究生人工智能创新大赛（开放命题赛题一：生成式大语言模型与智能体，应用创意类）
- 兼报华为赛题三：科研场景下复杂学术查询的智能论文搜索与推荐
- 华为赛题评分：F1 Score(70%) + 运行效率(20%) + 结果结构化(10%)

**核心差异化（写进项目文档的创新点）：**
1. 三维交叉质检：相关性×权威性×一致性三个Agent独立打分
2. 引文链自扩展：沿参考文献自动扩展1-2跳，提升召回率
3. 成本感知多模型路由：批量操作用DeepSeek，复杂推理用Claude
4. 自适应查询迭代：质量不足时自动改写查询词再次搜索
5. D3.js引文知识图谱：可交互的论文关系可视化

---

## 🔧 技术栈

**后端：**
- Python 3.11+
- LangGraph 0.2+（状态机工作流引擎）
- FastAPI + uvicorn（HTTP服务器）
- httpx（异步HTTP，调用学术API）
- anthropic（Claude SDK）
- openai（DeepSeek兼容接口）
- python-dotenv

**前端：**
- React 18 + TypeScript
- Vite（构建工具）
- D3.js v7（引文图谱可视化）
- Tailwind CSS（样式）
- marked（Markdown渲染）

**评测：**
- Python脚本计算F1 Score

---

## 📁 完整文件结构

```
ScholarFlow/
├── CLAUDE.md
├── .env                          # 从环境变量或手动创建，不提交git
├── .env.example
├── .gitignore
├── README.md
├── test_run.py                   # 快速测试脚本
├── backend/
│   ├── __init__.py
│   ├── main.py                   # FastAPI 入口
│   ├── config.py
│   ├── requirements.txt
│   ├── models/
│   │   ├── __init__.py
│   │   ├── paper.py              # Paper 数据类
│   │   └── state.py              # SearchState TypedDict
│   ├── api/
│   │   ├── __init__.py
│   │   ├── semantic_scholar.py   # Semantic Scholar API 客户端
│   │   └── openalex.py           # OpenAlex API 客户端
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── query_decomposer.py   # 节点① 查询分解
│   │   ├── search_agent.py       # 节点② 并行搜索
│   │   ├── citation_expander.py  # 节点③ 引文扩展
│   │   ├── ranker_agent.py       # 节点④ 三维排序
│   │   ├── query_refiner.py      # 节点⑤ 查询优化
│   │   ├── synthesis_agent.py    # 节点⑥ 综述报告
│   │   ├── graph_builder.py      # 节点⑦ 图谱构建
│   │   └── cost_tracker.py       # 节点⑧ 成本汇总
│   ├── workflow/
│   │   ├── __init__.py
│   │   ├── graph.py              # LangGraph 图定义
│   │   └── router.py             # 条件路由函数
│   └── utils/
│       ├── __init__.py
│       ├── llm_client.py         # 多模型路由客户端
│       └── text_utils.py         # 文本工具
├── frontend/
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── index.css
│       ├── types/
│       │   └── index.ts
│       ├── components/
│       │   ├── QueryPanel.tsx     # 左栏：查询输入+论文列表
│       │   ├── ReportPanel.tsx    # 中栏：Markdown报告
│       │   ├── GraphPanel.tsx     # 右栏：D3引文图谱
│       │   └── CostDashboard.tsx  # 顶部：成本看板
│       ├── hooks/
│       │   └── useSearch.ts       # 搜索状态管理
│       └── services/
│           └── api.ts             # 后端API调用
└── eval/
    ├── f1_score.py
    └── test_cases.json
```

---

## ⚙️ 配置文件

### .env.example
```
ANTHROPIC_API_KEY=sk-ant-your-key-here
DEEPSEEK_API_KEY=sk-your-deepseek-key
SEMANTIC_SCHOLAR_API_KEY=your-ss-key-or-leave-empty
OPENALEX_EMAIL=scholar@yourmail.com
BUDGET_LIMIT_USD=2.0
MAX_SEARCH_ITERATIONS=3
```

### .gitignore
```
.env
__pycache__/
*.pyc
.venv/
node_modules/
dist/
*.egg-info/
.DS_Store
```

### backend/config.py
```python
import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
OPENALEX_EMAIL = os.getenv("OPENALEX_EMAIL", "scholar@flow.ai")
BUDGET_LIMIT_USD = float(os.getenv("BUDGET_LIMIT_USD", "2.0"))
MAX_SEARCH_ITERATIONS = int(os.getenv("MAX_SEARCH_ITERATIONS", "3"))
```

### backend/requirements.txt
```
langgraph>=0.2.0
langchain-core>=0.2.0
anthropic>=0.30.0
openai>=1.40.0
fastapi>=0.111.0
uvicorn[standard]>=0.30.0
httpx>=0.27.0
python-dotenv>=1.0.0
pydantic>=2.7.0
```

---

## 📊 数据模型

### backend/models/paper.py
```python
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Paper:
    paper_id: str = ""
    title: str = ""
    abstract: str = ""
    year: int = 0
    authors: list[str] = field(default_factory=list)
    citation_count: int = 0
    venue: str = ""
    doi: str = ""
    url: str = ""
    source: str = ""          # "semantic_scholar" | "openalex"
    is_expanded: bool = False  # 是否来自引文扩展

    # 由 RankerAgent 填写
    relevance_score: float = 0.0   # 语义相关性 0-10
    authority_score: float = 0.0   # 权威性 0-10
    consistency_score: float = 0.0 # 结论一致性 0-10
    final_score: float = 0.0       # 加权综合分

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    def brief(self) -> str:
        """用于LLM提示词的简短描述"""
        authors_str = ", ".join(self.authors[:3])
        if len(self.authors) > 3:
            authors_str += " et al."
        return (
            f"Title: {self.title}\n"
            f"Year: {self.year} | Citations: {self.citation_count} | Venue: {self.venue}\n"
            f"Authors: {authors_str}\n"
            f"Abstract: {self.abstract[:300]}..."
        )
```

### backend/models/state.py
```python
from typing import TypedDict, Optional


class SearchState(TypedDict):
    # 输入
    original_query: str

    # 处理过程（每步更新）
    sub_queries: list[str]
    raw_papers: list[dict]
    expanded_papers: list[dict]
    ranked_papers: list[dict]

    # 输出
    report: str
    citation_graph: dict  # {"nodes": [...], "links": [...]}

    # 迭代控制
    iteration: int
    max_iterations: int

    # 成本追踪
    total_tokens_used: int
    total_cost_usd: float
    budget_limit_usd: float
    model_usage: dict  # {"model-name": {"tokens": int, "cost": float}}

    # 状态机状态
    status: str
    error: Optional[str]
```

---

## 🤖 多模型路由客户端

### backend/utils/llm_client.py

这是最关键的工具类，所有 Agent 通过它调用 LLM。

```python
import anthropic
from openai import AsyncOpenAI
from backend.config import ANTHROPIC_API_KEY, DEEPSEEK_API_KEY

# ===== 路由策略 =====
# 任务类型 -> 模型选择
TASK_MODEL_MAP = {
    "complex_reason":  "claude-sonnet-4-6",   # 查询分解、迭代策略
    "fast_score":      "claude-haiku-4-5-20251001",  # 批量相关性评分
    "batch_filter":    "deepseek-chat",         # 初步过滤，最便宜
    "synthesis":       "claude-sonnet-4-6",   # 综述报告生成
    "refine_strategy": "claude-sonnet-4-6",   # 查询改写策略
}

# 每1000 tokens的成本（美元）
MODEL_COST_PER_1K = {
    "claude-sonnet-4-6":  {"input": 0.003,   "output": 0.015},
    "claude-haiku-4-5-20251001": {"input": 0.00025, "output": 0.00125},
    "deepseek-chat":         {"input": 0.00027, "output": 0.0011},
}

_anthropic = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
_deepseek = AsyncOpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)


def _calc_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rates = MODEL_COST_PER_1K.get(model, MODEL_COST_PER_1K["claude-sonnet-4-6"])
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1000


async def call_llm(
    prompt: str,
    task_type: str = "complex_reason",
    system: str = "You are a helpful academic research assistant.",
    max_tokens: int = 2000,
    json_mode: bool = False,
) -> tuple[str, dict]:
    """
    统一LLM调用入口，自动路由到对应模型。

    Returns:
        (response_text, usage_info)
        usage_info = {
            "model": str,
            "input_tokens": int,
            "output_tokens": int,
            "cost_usd": float
        }
    """
    model = TASK_MODEL_MAP.get(task_type, "claude-sonnet-4-6")

    try:
        if model.startswith("deepseek"):
            resp = await _deepseek.chat.completions.create(
                model="deepseek-chat",
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=max_tokens,
                response_format={"type": "json_object"} if json_mode else {"type": "text"},
            )
            text = resp.choices[0].message.content or ""
            usage = {
                "model": model,
                "input_tokens": resp.usage.prompt_tokens,
                "output_tokens": resp.usage.completion_tokens,
                "cost_usd": _calc_cost(model, resp.usage.prompt_tokens, resp.usage.completion_tokens),
            }

        else:
            resp = await _anthropic.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            text = resp.content[0].text if resp.content else ""
            usage = {
                "model": model,
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
                "cost_usd": _calc_cost(model, resp.usage.input_tokens, resp.usage.output_tokens),
            }

        return text, usage

    except Exception as e:
        # 降级：返回空字符串，不让整条流水线崩溃
        print(f"[llm_client] ERROR ({model}): {e}")
        return "", {"model": model, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}


def merge_usage_into_state(state: dict, usage: dict) -> dict:
    """把单次LLM调用的成本合并到state中，返回更新后的成本字段"""
    model = usage["model"]
    existing = dict(state.get("model_usage", {}))

    if model not in existing:
        existing[model] = {"tokens": 0, "cost": 0.0}
    existing[model]["tokens"] += usage["input_tokens"] + usage["output_tokens"]
    existing[model]["cost"] += usage["cost_usd"]

    return {
        "total_tokens_used": state.get("total_tokens_used", 0) + usage["input_tokens"] + usage["output_tokens"],
        "total_cost_usd": state.get("total_cost_usd", 0.0) + usage["cost_usd"],
        "model_usage": existing,
    }
```

### backend/utils/text_utils.py
```python
def deduplicate_papers(papers: list) -> list:
    """按paper_id和标题前50字符去重"""
    from backend.models.paper import Paper
    seen_ids: set[str] = set()
    seen_titles: set[str] = set()
    result = []
    for p in papers:
        pid = p.paper_id if hasattr(p, "paper_id") else p.get("paper_id", "")
        title_key = (p.title if hasattr(p, "title") else p.get("title", "")).lower()[:50]
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
```

---

## 🔌 学术API客户端

### backend/api/semantic_scholar.py

```python
import httpx
from backend.config import SEMANTIC_SCHOLAR_API_KEY
from backend.models.paper import Paper

BASE_URL = "https://api.semanticscholar.org/graph/v1"
PAPER_FIELDS = "paperId,title,abstract,year,authors,citationCount,venue,externalIds,url"
HEADERS = {"x-api-key": SEMANTIC_SCHOLAR_API_KEY} if SEMANTIC_SCHOLAR_API_KEY else {}
TIMEOUT = 30.0


async def search_papers(query: str, limit: int = 50) -> list[Paper]:
    """搜索论文"""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                f"{BASE_URL}/paper/search",
                params={"query": query, "limit": limit, "fields": PAPER_FIELDS},
                headers=HEADERS,
            )
            if resp.status_code != 200:
                print(f"[SemanticScholar] search error {resp.status_code}: {query}")
                return []
            data = resp.json()

        papers = []
        for item in data.get("data", []):
            if not item.get("paperId") or not item.get("title"):
                continue
            papers.append(Paper(
                paper_id=item["paperId"],
                title=item.get("title", ""),
                abstract=item.get("abstract") or "",
                year=item.get("year") or 0,
                authors=[a.get("name", "") for a in item.get("authors", [])],
                citation_count=item.get("citationCount") or 0,
                venue=item.get("venue") or "",
                doi=item.get("externalIds", {}).get("DOI", "") if item.get("externalIds") else "",
                url=f"https://www.semanticscholar.org/paper/{item['paperId']}",
                source="semantic_scholar",
            ))
        return papers

    except Exception as e:
        print(f"[SemanticScholar] exception: {e}")
        return []


async def get_references(paper_id: str, limit: int = 30) -> list[Paper]:
    """获取一篇论文的参考文献列表"""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                f"{BASE_URL}/paper/{paper_id}/references",
                params={"fields": PAPER_FIELDS, "limit": limit},
                headers=HEADERS,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()

        papers = []
        for item in data.get("data", []):
            cited = item.get("citedPaper", {})
            if not cited.get("paperId") or not cited.get("title"):
                continue
            papers.append(Paper(
                paper_id=cited["paperId"],
                title=cited.get("title", ""),
                abstract=cited.get("abstract") or "",
                year=cited.get("year") or 0,
                authors=[a.get("name", "") for a in cited.get("authors", [])],
                citation_count=cited.get("citationCount") or 0,
                venue=cited.get("venue") or "",
                url=f"https://www.semanticscholar.org/paper/{cited['paperId']}",
                source="semantic_scholar",
                is_expanded=True,
            ))
        return papers

    except Exception as e:
        print(f"[SemanticScholar] references exception: {e}")
        return []
```

### backend/api/openalex.py

```python
import httpx
from backend.config import OPENALEX_EMAIL
from backend.models.paper import Paper

BASE_URL = "https://api.openalex.org"
TIMEOUT = 30.0
SELECT_FIELDS = "id,title,abstract_inverted_index,publication_year,authorships,cited_by_count,primary_location,doi"


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """OpenAlex摘要以倒排索引存储，需重建为原文"""
    if not inverted_index:
        return ""
    positions: dict[int, str] = {}
    for word, pos_list in inverted_index.items():
        for pos in pos_list:
            positions[pos] = word
    return " ".join(positions[i] for i in sorted(positions))


async def search_papers(query: str, limit: int = 50) -> list[Paper]:
    """通过 OpenAlex 搜索论文"""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                f"{BASE_URL}/works",
                params={
                    "search": query,
                    "mailto": OPENALEX_EMAIL,
                    "per-page": limit,
                    "select": SELECT_FIELDS,
                    "filter": "has_abstract:true",
                },
            )
            if resp.status_code != 200:
                print(f"[OpenAlex] search error {resp.status_code}")
                return []
            data = resp.json()

        papers = []
        for item in data.get("results", []):
            # 提取期刊/会议名
            venue = ""
            loc = item.get("primary_location") or {}
            src = loc.get("source") or {}
            venue = src.get("display_name", "")

            abstract = _reconstruct_abstract(item.get("abstract_inverted_index"))
            if not abstract:
                continue

            openalex_id = item.get("id", "")
            papers.append(Paper(
                paper_id=openalex_id,
                title=item.get("title") or "",
                abstract=abstract,
                year=item.get("publication_year") or 0,
                authors=[
                    a.get("author", {}).get("display_name", "")
                    for a in item.get("authorships", [])
                ],
                citation_count=item.get("cited_by_count") or 0,
                venue=venue,
                doi=item.get("doi") or "",
                url=openalex_id,
                source="openalex",
            ))
        return papers

    except Exception as e:
        print(f"[OpenAlex] exception: {e}")
        return []
```

---

## 🤖 8个Agent节点实现

### backend/agents/query_decomposer.py — 节点①

```python
import json
from backend.models.state import SearchState
from backend.utils.llm_client import call_llm, merge_usage_into_state

SYSTEM = (
    "You are an expert academic librarian. "
    "Your job is to decompose complex research queries into precise sub-queries "
    "for searching academic databases like Semantic Scholar and OpenAlex."
)


async def query_decompose_node(state: SearchState) -> SearchState:
    """将用户原始查询分解为多个英文子查询"""

    prompt = f"""Analyze this research query and decompose it into 4-5 focused sub-queries.

Original query: {state['original_query']}

Output JSON format:
{{
    "analysis": "Brief analysis of research intent in Chinese (1-2 sentences)",
    "sub_queries": [
        "sub-query 1 (English, focus on core topic)",
        "sub-query 2 (English, focus on methods)",
        "sub-query 3 (English, focus on applications)",
        "sub-query 4 (English, related technology/context)",
        "sub-query 5 (English, broader background)"
    ],
    "key_terms": ["term1", "term2", "term3"]
}}

Rules:
- All sub-queries MUST be in English (academic databases are English-dominant)
- Each sub-query: 3-8 words, specific enough for academic search
- Cover different angles, avoid repetition
- If original query is Chinese, translate to academic English"""

    text, usage = await call_llm(
        prompt,
        task_type="complex_reason",
        system=SYSTEM,
        max_tokens=800,
        json_mode=True,
    )

    sub_queries = [state["original_query"]]  # fallback
    try:
        result = json.loads(text)
        parsed = result.get("sub_queries", [])
        if parsed:
            sub_queries = [q for q in parsed if isinstance(q, str) and len(q) > 3][:5]
    except Exception as e:
        print(f"[QueryDecomposer] JSON parse error: {e}, raw: {text[:200]}")

    cost_update = merge_usage_into_state(state, usage)

    return {
        **state,
        **cost_update,
        "sub_queries": sub_queries,
        "status": "searching",
    }
```

### backend/agents/search_agent.py — 节点②

```python
import asyncio
from backend.models.state import SearchState
from backend.api import semantic_scholar, openalex
from backend.utils.text_utils import deduplicate_papers


async def search_node(state: SearchState) -> SearchState:
    """并行调用双源API，合并去重"""

    sub_queries = state["sub_queries"]
    if not sub_queries:
        return {**state, "raw_papers": [], "status": "expanding"}

    # 并发搜索：每个子查询同时查两个数据库
    tasks = []
    for q in sub_queries:
        tasks.append(semantic_scholar.search_papers(q, limit=30))
        tasks.append(openalex.search_papers(q, limit=20))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_papers = []
    for result in results:
        if isinstance(result, list):
            all_papers.extend(result)

    # 过滤无摘要论文，然后去重
    all_papers = [p for p in all_papers if p.abstract and len(p.abstract) > 80]
    unique_papers = deduplicate_papers(all_papers)

    # 如果是第二轮及以后，与已有论文合并
    existing_dicts = state.get("ranked_papers", []) or state.get("raw_papers", [])
    if existing_dicts and state.get("iteration", 0) > 0:
        from backend.models.paper import Paper
        existing_papers = [Paper(**p) for p in existing_dicts]
        all_combined = existing_papers + unique_papers
        unique_papers = deduplicate_papers(all_combined)

    print(f"[SearchAgent] Found {len(unique_papers)} unique papers from {len(sub_queries)} queries")

    return {
        **state,
        "raw_papers": [p.to_dict() for p in unique_papers],
        "status": "expanding",
    }
```

### backend/agents/citation_expander.py — 节点③

```python
import asyncio
from backend.models.state import SearchState
from backend.models.paper import Paper
from backend.api import semantic_scholar
from backend.utils.text_utils import deduplicate_papers


async def expand_citations_node(state: SearchState) -> SearchState:
    """获取高引用论文的参考文献，扩展候选池"""

    raw = [Paper(**p) for p in state["raw_papers"]]
    if not raw:
        return {**state, "expanded_papers": [], "status": "ranking"}

    # 选引用数最高的前5篇做引文扩展（只用SS，有结构化引用数据）
    ss_papers = [p for p in raw if p.source == "semantic_scholar" and p.paper_id]
    top = sorted(ss_papers, key=lambda p: p.citation_count, reverse=True)[:5]

    tasks = [semantic_scholar.get_references(p.paper_id, limit=20) for p in top]
    refs_results = await asyncio.gather(*tasks, return_exceptions=True)

    all_papers = list(raw)
    for result in refs_results:
        if isinstance(result, list):
            all_papers.extend(result)

    # 过滤 + 去重
    all_papers = [p for p in all_papers if p.abstract and len(p.abstract) > 80]
    unique = deduplicate_papers(all_papers)

    print(f"[CitationExpander] Expanded to {len(unique)} papers (was {len(raw)})")

    return {
        **state,
        "expanded_papers": [p.to_dict() for p in unique],
        "status": "ranking",
    }
```

### backend/agents/ranker_agent.py — 节点④

```python
import json
import asyncio
from backend.models.state import SearchState
from backend.models.paper import Paper
from backend.utils.llm_client import call_llm, merge_usage_into_state


def _authority_score(citation_count: int) -> float:
    """基于引用数计算权威性（不消耗token）"""
    thresholds = [(1000, 10.0), (500, 9.0), (200, 8.0), (100, 7.5),
                  (50, 7.0), (20, 6.0), (10, 5.0), (5, 4.0), (1, 3.0)]
    for threshold, score in thresholds:
        if citation_count >= threshold:
            return score
    return 2.0


async def _score_relevance(paper: Paper, query: str) -> tuple[float, dict]:
    """单篇论文相关性评分"""
    prompt = f"""Rate how relevant this paper is to the research query.

Query: {query}

Paper: {paper.title}
Abstract (first 250 chars): {paper.abstract[:250]}

Respond with JSON only:
{{"relevance": <number 0-10>, "reason": "<one sentence>"}}"""

    text, usage = await call_llm(prompt, task_type="fast_score", max_tokens=80, json_mode=True)
    try:
        data = json.loads(text)
        score = float(data.get("relevance", 5.0))
        score = max(0.0, min(10.0, score))
    except Exception:
        score = 5.0
    return score, usage


async def rank_node(state: SearchState) -> SearchState:
    """三维评分：相关性(LLM) × 权威性(规则) × 一致性(估算)"""

    papers = [Paper(**p) for p in state.get("expanded_papers", state.get("raw_papers", []))]
    query = state["original_query"]

    if not papers:
        return {**state, "ranked_papers": [], "status": "checking_refine"}

    # 限制处理数量控制成本（最多50篇）
    papers = papers[:50]

    # 并发评分（限制并发数避免API限速）
    semaphore = asyncio.Semaphore(5)

    async def bounded_score(paper: Paper):
        async with semaphore:
            return await _score_relevance(paper, query)

    score_results = await asyncio.gather(*[bounded_score(p) for p in papers])

    total_cost = 0.0
    total_tokens = 0

    for paper, (rel, usage) in zip(papers, score_results):
        paper.relevance_score = rel
        paper.authority_score = _authority_score(paper.citation_count)
        # 一致性：暂时用相关性+权威性的均值作为估算（避免额外LLM调用）
        paper.consistency_score = round((rel + paper.authority_score) / 2, 1)
        # 加权：相关性50%，权威性30%，一致性20%
        paper.final_score = round(
            rel * 0.5 + paper.authority_score * 0.3 + paper.consistency_score * 0.2, 2
        )
        total_cost += usage["cost_usd"]
        total_tokens += usage["input_tokens"] + usage["output_tokens"]

    papers.sort(key=lambda p: p.final_score, reverse=True)
    ranked = papers[:30]

    print(f"[RankerAgent] Ranked {len(ranked)} papers, top score: {ranked[0].final_score if ranked else 0}")

    cost_update = merge_usage_into_state(state, {
        "model": "claude-haiku-4-5-20251001",
        "input_tokens": total_tokens,
        "output_tokens": 0,
        "cost_usd": total_cost,
    })

    return {
        **state,
        **cost_update,
        "ranked_papers": [p.to_dict() for p in ranked],
        "status": "checking_refine",
    }
```

### backend/agents/query_refiner.py — 节点⑤

```python
import json
from backend.models.state import SearchState
from backend.utils.llm_client import call_llm, merge_usage_into_state


async def query_refine_node(state: SearchState) -> SearchState:
    """分析当前结果的不足，生成补充查询词"""

    ranked = state.get("ranked_papers", [])
    iteration = state.get("iteration", 0)

    top5_summary = "\n".join([
        f"- [{p.get('year','')}] {p.get('title','')} (relevance: {p.get('relevance_score',0):.1f})"
        for p in ranked[:5]
    ])

    prompt = f"""You're a research strategy expert. Analyze these search results and identify gaps.

Original query: {state['original_query']}
Search iteration: {iteration + 1}

Current top results:
{top5_summary}

What important aspects are MISSING from these results?
Generate 3 NEW search queries to fill the gaps.

JSON output:
{{
    "gap_analysis": "What's missing (in Chinese, 1-2 sentences)",
    "new_sub_queries": [
        "gap-filling query 1 (English)",
        "gap-filling query 2 (English)",
        "gap-filling query 3 (English)"
    ]
}}"""

    text, usage = await call_llm(
        prompt, task_type="refine_strategy", max_tokens=400, json_mode=True
    )

    new_queries = []
    try:
        result = json.loads(text)
        candidates = result.get("new_sub_queries", [])
        existing = set(state.get("sub_queries", []))
        new_queries = [q for q in candidates if q and q not in existing][:3]
    except Exception as e:
        print(f"[QueryRefiner] parse error: {e}")

    cost_update = merge_usage_into_state(state, usage)

    print(f"[QueryRefiner] Generated {len(new_queries)} new queries for iteration {iteration + 1}")

    return {
        **state,
        **cost_update,
        "sub_queries": new_queries if new_queries else state.get("sub_queries", []),
        "iteration": iteration + 1,
        "status": "searching",
    }
```

### backend/agents/synthesis_agent.py — 节点⑥

```python
from backend.models.state import SearchState
from backend.utils.llm_client import call_llm, merge_usage_into_state

SYSTEM = (
    "你是一位资深科研助手，熟悉学术文献分析和综述写作。"
    "请用中文输出，论文名保持英文原文。"
)


async def synthesize_node(state: SearchState) -> SearchState:
    """生成结构化Markdown综述报告"""

    ranked = state.get("ranked_papers", [])[:20]
    query = state["original_query"]

    if not ranked:
        return {**state, "report": "未检索到相关论文。", "status": "building_graph"}

    papers_text = "\n\n".join([
        f"**[Paper {i+1}]** {p.get('title','')}\n"
        f"Year: {p.get('year','')} | Citations: {p.get('citation_count',0)} | Venue: {p.get('venue','')}\n"
        f"Relevance: {p.get('relevance_score',0):.1f}/10 | URL: {p.get('url','')}\n"
        f"Abstract: {p.get('abstract','')[:400]}"
        for i, p in enumerate(ranked)
    ])

    prompt = f"""根据以下学术论文列表，为研究问题生成一份结构化文献综述报告。

研究问题：{query}

检索论文列表：
{papers_text}

请生成Markdown格式的综述报告，严格包含以下6个部分：

## 研究概述
（2-3句话：该领域的研究现状和主要挑战）

## 核心论文推荐（Top 5）
（每篇：论文名+年份+核心贡献+推荐理由，格式：**论文名** [年份]）

## 研究方向分类
（按研究方法/应用场景/理论基础等分2-4类，每类列出2-4篇论文及一句话说明）

## 关键研究趋势
（列出3个近年重要趋势，每个趋势2-3句话说明）

## 延伸阅读
（简短列表，格式：- [论文名](URL) — 一句话说明）

## 检索说明
（本次检索：数据源、检索轮次、总论文数、评分方法说明）

要求：分析要有实质内容，不要只列清单；中文为主，论文名保持英文。"""

    report, usage = await call_llm(
        prompt,
        task_type="synthesis",
        system=SYSTEM,
        max_tokens=3500,
    )

    cost_update = merge_usage_into_state(state, usage)

    return {
        **state,
        **cost_update,
        "report": report,
        "status": "building_graph",
    }
```

### backend/agents/graph_builder.py — 节点⑦

```python
from backend.models.state import SearchState
import math


def build_graph_node(state: SearchState) -> SearchState:
    """构建D3.js可渲染的引文关系图数据（无LLM调用）"""

    ranked = state.get("ranked_papers", [])[:20]
    node_id_set = {p.get("paper_id", "") for p in ranked if p.get("paper_id")}

    nodes = []
    for i, p in enumerate(ranked):
        pid = p.get("paper_id") or f"paper_{i}"
        cites = p.get("citation_count", 0)
        rel = p.get("relevance_score", 5.0)

        nodes.append({
            "id": pid,
            "index": i,
            "title": p.get("title", "Unknown"),
            "year": p.get("year", 0),
            "citation_count": cites,
            "relevance_score": rel,
            "final_score": p.get("final_score", 0),
            "url": p.get("url", ""),
            "abstract": p.get("abstract", "")[:250],
            "source": p.get("source", ""),
            "is_expanded": p.get("is_expanded", False),
            # 节点大小：基于引用数，log scale，范围 8-35
            "size": round(8 + min(27, math.log1p(cites) * 3.5), 1),
            # 颜色值：0-1，基于相关性分数
            "color_value": round(rel / 10.0, 2),
        })

    # 构建引用边（只处理节点间的关系）
    links = []
    for p in ranked:
        source_id = p.get("paper_id", "")
        if not source_id:
            continue
        for ref_id in p.get("references", []):
            if ref_id in node_id_set and ref_id != source_id:
                links.append({
                    "source": source_id,
                    "target": ref_id,
                    "type": "cites",
                })

    graph = {
        "nodes": nodes,
        "links": links,
        "metadata": {
            "total_papers": len(nodes),
            "total_links": len(links),
            "query": state.get("original_query", ""),
            "search_iterations": state.get("iteration", 0),
        },
    }

    return {**state, "citation_graph": graph, "status": "done"}
```

### backend/agents/cost_tracker.py — 节点⑧

```python
from backend.models.state import SearchState


def track_cost_node(state: SearchState) -> SearchState:
    """成本汇总日志（纯计算，无IO副作用）"""

    total_cost = state.get("total_cost_usd", 0.0)
    total_tokens = state.get("total_tokens_used", 0)

    print("\n" + "=" * 50)
    print("  ScholarFlow 搜索完成 — 成本报告")
    print("=" * 50)
    print(f"  总 Token 使用量 : {total_tokens:,}")
    print(f"  总成本          : ${total_cost:.4f}")
    print(f"  预算上限        : ${state.get('budget_limit_usd', 2.0):.2f}")
    print(f"  搜索迭代轮次    : {state.get('iteration', 0)}")
    print(f"  最终论文数量    : {len(state.get('ranked_papers', []))}")
    print("\n  各模型用量：")
    for model, usage in state.get("model_usage", {}).items():
        print(f"    {model:<40} {usage['tokens']:>8,} tokens  ${usage['cost']:.4f}")
    print("=" * 50 + "\n")

    return {**state, "status": "done"}
```

---

## 🔀 路由与图组装

### backend/workflow/router.py

```python
from backend.models.state import SearchState


def should_refine(state: SearchState) -> str:
    """
    决定是继续迭代优化（refine）还是直接综述（synthesize）。
    返回值必须是 "refine" 或 "synthesize"。
    """
    iteration = state.get("iteration", 0)
    max_iter = state.get("max_iterations", 3)
    cost = state.get("total_cost_usd", 0.0)
    budget = state.get("budget_limit_usd", 2.0)
    ranked = state.get("ranked_papers", [])

    # 强制停止条件
    if iteration >= max_iter:
        print(f"[Router] Max iterations ({max_iter}) reached -> synthesize")
        return "synthesize"

    if budget - cost < 0.3:
        print(f"[Router] Low budget (${cost:.3f}/${budget:.2f}) -> synthesize")
        return "synthesize"

    if len(ranked) < 5:
        print(f"[Router] Too few papers ({len(ranked)}) -> refine")
        return "refine"

    # 质量检查：Top5平均相关性
    top5 = ranked[:5]
    avg_relevance = sum(p.get("relevance_score", 0) for p in top5) / len(top5)

    if avg_relevance >= 7.0 and len(ranked) >= 15:
        print(f"[Router] Good quality (avg_rel={avg_relevance:.1f}, n={len(ranked)}) -> synthesize")
        return "synthesize"

    print(f"[Router] Needs improvement (avg_rel={avg_relevance:.1f}, n={len(ranked)}) -> refine")
    return "refine"
```

### backend/workflow/graph.py

```python
from langgraph.graph import StateGraph, START, END
from backend.models.state import SearchState
from backend.agents.query_decomposer import query_decompose_node
from backend.agents.search_agent import search_node
from backend.agents.citation_expander import expand_citations_node
from backend.agents.ranker_agent import rank_node
from backend.agents.query_refiner import query_refine_node
from backend.agents.synthesis_agent import synthesize_node
from backend.agents.graph_builder import build_graph_node
from backend.agents.cost_tracker import track_cost_node
from backend.workflow.router import should_refine


def build_search_graph():
    graph = StateGraph(SearchState)

    # 注册节点
    graph.add_node("query_decompose", query_decompose_node)
    graph.add_node("search", search_node)
    graph.add_node("expand_citations", expand_citations_node)
    graph.add_node("rank", rank_node)
    graph.add_node("refine", query_refine_node)
    graph.add_node("synthesize", synthesize_node)
    graph.add_node("build_graph", build_graph_node)
    graph.add_node("track_cost", track_cost_node)

    # 主流程边
    graph.add_edge(START, "query_decompose")
    graph.add_edge("query_decompose", "search")
    graph.add_edge("search", "expand_citations")
    graph.add_edge("expand_citations", "rank")

    # 条件分支：优化 or 合成
    graph.add_conditional_edges(
        "rank",
        should_refine,
        {"refine": "refine", "synthesize": "synthesize"},
    )

    # 迭代回路
    graph.add_edge("refine", "search")

    # 输出流程
    graph.add_edge("synthesize", "build_graph")
    graph.add_edge("build_graph", "track_cost")
    graph.add_edge("track_cost", END)

    return graph.compile()


# 全局单例，避免重复构建
search_graph = build_search_graph()
```

---

## 🌐 FastAPI 后端

### backend/main.py

```python
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from backend.workflow.graph import search_graph
from backend.config import BUDGET_LIMIT_USD, MAX_SEARCH_ITERATIONS

app = FastAPI(title="ScholarFlow API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchRequest(BaseModel):
    query: str
    budget: float = BUDGET_LIMIT_USD
    max_iterations: int = MAX_SEARCH_ITERATIONS


class SearchResponse(BaseModel):
    report: str
    ranked_papers: list[dict]
    citation_graph: dict
    total_cost_usd: float
    total_tokens_used: int
    model_usage: dict
    iteration: int
    status: str


@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="查询内容不能为空")

    initial = {
        "original_query": req.query.strip(),
        "sub_queries": [],
        "raw_papers": [],
        "expanded_papers": [],
        "ranked_papers": [],
        "report": "",
        "citation_graph": {},
        "iteration": 0,
        "max_iterations": req.max_iterations,
        "total_tokens_used": 0,
        "total_cost_usd": 0.0,
        "budget_limit_usd": req.budget,
        "model_usage": {},
        "status": "decomposing",
        "error": None,
    }

    try:
        final = await search_graph.ainvoke(initial)
        return SearchResponse(
            report=final.get("report", ""),
            ranked_papers=final.get("ranked_papers", [])[:20],
            citation_graph=final.get("citation_graph", {}),
            total_cost_usd=round(final.get("total_cost_usd", 0.0), 4),
            total_tokens_used=final.get("total_tokens_used", 0),
            model_usage=final.get("model_usage", {}),
            iteration=final.get("iteration", 0),
            status=final.get("status", "done"),
        )
    except Exception as e:
        print(f"[API] /search error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {"status": "ok", "service": "ScholarFlow", "version": "1.0.0"}
```

---

## 🎨 前端规格

### 整体布局（App.tsx）

```
┌────────────────── CostDashboard（顶部固定栏）──────────────────┐
│ Token: X,XXX  |  Cost: $X.XXXX  |  Papers: XX  |  Status: ●  │
├─────────────────┬──────────────────────┬────────────────────────┤
│  QueryPanel     │   ReportPanel        │   GraphPanel           │
│  左栏 25%       │   中栏 45%           │   右栏 30%             │
│                 │                      │                        │
│  查询输入框     │  Markdown 报告       │  D3.js 引文图谱        │
│  参数设置       │  （marked渲染）      │  力导向图              │
│  搜索按钮       │                      │  点击节点 → 摘要浮层   │
│  ───────────   │                      │                        │
│  论文列表       │                      │                        │
│  （可点击跳转） │                      │                        │
└─────────────────┴──────────────────────┴────────────────────────┘
```

### frontend/src/types/index.ts

```typescript
export interface Paper {
  paper_id: string;
  title: string;
  abstract: string;
  year: number;
  authors: string[];
  citation_count: number;
  venue: string;
  url: string;
  source: string;
  is_expanded: boolean;
  relevance_score: number;
  authority_score: number;
  final_score: number;
}

export interface GraphNode {
  id: string;
  title: string;
  year: number;
  citation_count: number;
  relevance_score: number;
  final_score: number;
  url: string;
  abstract: string;
  size: number;
  color_value: number;
  is_expanded: boolean;
}

export interface GraphLink {
  source: string;
  target: string;
  type: string;
}

export interface CitationGraph {
  nodes: GraphNode[];
  links: GraphLink[];
  metadata: { total_papers: number; total_links: number; query: string; search_iterations: number };
}

export interface SearchResult {
  report: string;
  ranked_papers: Paper[];
  citation_graph: CitationGraph;
  total_cost_usd: number;
  total_tokens_used: number;
  model_usage: Record<string, { tokens: number; cost: number }>;
  iteration: number;
  status: string;
}
```

### frontend/src/services/api.ts

```typescript
const API_BASE = 'http://localhost:8000';

export async function searchPapers(
  query: string,
  budget: number = 2.0,
  maxIterations: number = 3
): Promise<SearchResult> {
  const resp = await fetch(`${API_BASE}/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, budget, max_iterations: maxIterations }),
  });
  if (!resp.ok) {
    const err = await resp.json();
    throw new Error(err.detail || 'Search failed');
  }
  return resp.json();
}
```

### D3.js 图谱核心逻辑（GraphPanel.tsx 的关键部分）

```typescript
// 在 useEffect 中执行 D3 渲染
const simulation = d3.forceSimulation<GraphNode>(nodes)
  .force('link', d3.forceLink<GraphNode, GraphLink>(links)
    .id(d => d.id)
    .distance(80)
    .strength(0.5))
  .force('charge', d3.forceManyBody().strength(-200))
  .force('center', d3.forceCenter(width / 2, height / 2))
  .force('collision', d3.forceCollide<GraphNode>().radius(d => d.size + 5));

// 颜色比例尺：低相关性=蓝色，高相关性=绿色
const colorScale = d3.scaleLinear<string>()
  .domain([0, 0.5, 1])
  .range(['#93c5fd', '#60a5fa', '#22c55e']);

// 节点大小：来自 backend graphBuilder 的 size 字段
// 点击节点：弹出摘要浮层（absolute定位的div）
// 悬浮边：显示引用方向箭头（用 defs/marker 定义箭头）
```

---

## 📏 F1 评测框架

### eval/f1_score.py

```python
"""
ScholarFlow F1 评测脚本
用法：
  python eval/f1_score.py --query "transformer attention mechanism" \
    --expected "Attention Is All You Need" "BERT: Pre-training of Deep Bidirectional Transformers"
"""
import argparse
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.workflow.graph import search_graph


def compute_f1(retrieved: list[str], relevant: list[str]) -> dict:
    ret = {t.lower()[:60] for t in retrieved}
    rel = {t.lower()[:60] for t in relevant}
    tp = len(ret & rel)
    fp = len(ret - rel)
    fn = len(rel - ret)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {"precision": round(precision, 3), "recall": round(recall, 3),
            "f1": round(f1, 3), "tp": tp, "fp": fp, "fn": fn}


async def run_eval(query: str, expected_titles: list[str], budget: float = 1.0):
    initial = {
        "original_query": query, "sub_queries": [], "raw_papers": [],
        "expanded_papers": [], "ranked_papers": [], "report": "",
        "citation_graph": {}, "iteration": 0, "max_iterations": 2,
        "total_tokens_used": 0, "total_cost_usd": 0.0,
        "budget_limit_usd": budget, "model_usage": {}, "status": "decomposing", "error": None,
    }
    final = await search_graph.ainvoke(initial)
    retrieved = [p["title"] for p in final.get("ranked_papers", [])[:20]]
    metrics = compute_f1(retrieved, expected_titles)

    print(f"\n{'='*60}")
    print(f"Query   : {query}")
    print(f"Expected: {len(expected_titles)} papers")
    print(f"Retrieved Top-20: {len(retrieved)} papers")
    print(f"\nPrecision : {metrics['precision']:.3f}")
    print(f"Recall    : {metrics['recall']:.3f}")
    print(f"F1 Score  : {metrics['f1']:.3f}")
    print(f"Cost      : ${final.get('total_cost_usd', 0):.4f}")
    print(f"Tokens    : {final.get('total_tokens_used', 0):,}")
    print(f"{'='*60}\n")
    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True, help="搜索查询")
    parser.add_argument("--expected", nargs="+", required=True, help="期望检索到的论文标题列表")
    parser.add_argument("--budget", type=float, default=1.0, help="成本上限（美元）")
    args = parser.parse_args()
    asyncio.run(run_eval(args.query, args.expected, args.budget))
```

### eval/test_cases.json（初始测试用例）

```json
[
  {
    "query": "transformer attention mechanism for natural language processing",
    "expected_papers": [
      "Attention Is All You Need",
      "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
      "GPT-3: Language Models are Few-Shot Learners"
    ]
  },
  {
    "query": "大语言模型在代码生成中的应用",
    "expected_papers": [
      "Evaluating Large Language Models Trained on Code",
      "CodeBERT: A Pre-Trained Model for Programming and Natural Languages",
      "GitHub Copilot AI pair programmer"
    ]
  },
  {
    "query": "multi-agent reinforcement learning coordination",
    "expected_papers": [
      "Multi-Agent Actor-Critic for Mixed Cooperative-Competitive Environments",
      "Emergent Tool Use from Multi-Agent Interaction"
    ]
  }
]
```

---

## 🚀 快速验证脚本

### test_run.py（项目根目录）

```python
"""
快速功能验证脚本，不依赖前端
运行：python test_run.py
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.workflow.graph import search_graph


async def main():
    query = "large language model agent for automated research"
    print(f"Testing ScholarFlow with query: {query}\n")

    initial = {
        "original_query": query,
        "sub_queries": [], "raw_papers": [], "expanded_papers": [],
        "ranked_papers": [], "report": "", "citation_graph": {},
        "iteration": 0, "max_iterations": 1,  # 测试只跑1轮
        "total_tokens_used": 0, "total_cost_usd": 0.0,
        "budget_limit_usd": 0.5,  # 测试用小预算
        "model_usage": {}, "status": "decomposing", "error": None,
    }

    final = await search_graph.ainvoke(initial)

    print("\n===== TEST RESULTS =====")
    print(f"Status: {final['status']}")
    print(f"Papers found: {len(final['ranked_papers'])}")
    print(f"Cost: ${final['total_cost_usd']:.4f}")
    print(f"\nTop 3 papers:")
    for p in final['ranked_papers'][:3]:
        print(f"  [{p['year']}] {p['title'][:70]} (score: {p['final_score']:.1f})")
    print(f"\nReport preview (first 300 chars):")
    print(final['report'][:300])
    print("========================\n")
    print("✅ Test passed!" if final['status'] == 'done' else "⚠️ Check logs above")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 🔢 开发顺序（Claude Code 请严格按此顺序执行）

**第一阶段：后端核心（先把流水线跑通）**

1. 创建完整目录结构和所有空的 `__init__.py` 文件
2. 创建 `.env.example`、`.gitignore`、`README.md`（README 可先写骨架）
3. 实现 `backend/requirements.txt`，然后运行 `pip install -r backend/requirements.txt`
4. 实现 `backend/config.py`
5. 实现 `backend/models/paper.py` 和 `backend/models/state.py`
6. 实现 `backend/utils/llm_client.py`（**关键：完成后写一个简单测试，验证能调通Claude API**）
7. 实现 `backend/utils/text_utils.py`
8. 实现 `backend/api/semantic_scholar.py`
9. 实现 `backend/api/openalex.py`
10. 按节点编号顺序逐个实现8个 agent 文件
11. 实现 `backend/workflow/router.py` 和 `backend/workflow/graph.py`
12. 实现 `test_run.py` 并运行，确保流水线端到端跑通
13. 实现 `backend/main.py`（FastAPI），运行 `uvicorn backend.main:app --reload`，访问 `/health` 确认 200

**第二阶段：前端**

14. 运行 `npm create vite@latest frontend -- --template react-ts`
15. 进入 frontend 目录，安装依赖：`npm install d3 marked @types/d3`
16. 安装 Tailwind CSS：`npm install -D tailwindcss postcss autoprefixer && npx tailwindcss init -p`
17. 按顺序实现：`types/index.ts` → `services/api.ts` → `hooks/useSearch.ts` → 各组件（CostDashboard → QueryPanel → ReportPanel → GraphPanel → App.tsx）
18. 运行 `npm run dev`，访问 `http://localhost:5173` 确认页面可加载

**第三阶段：评测和完善**

19. 实现 `eval/f1_score.py` 和 `eval/test_cases.json`
20. 运行 `python test_run.py` 做完整端到端测试
21. 完善 `README.md`（包含安装步骤、运行说明、架构说明）

---

## ⚠️ 注意事项（Claude Code请仔细阅读）

1. **LangGraph 异步**：包含 I/O 的节点函数必须是 `async def`；纯计算节点（graph_builder、cost_tracker）用同步 `def` 即可
2. **State 更新**：LangGraph 节点返回时用 `{**state, "key": new_value}` 全量返回，不能只返回部分字段
3. **API 错误处理**：所有外部 API 调用必须有 try-except，失败时返回空列表，不能让异常传播导致整条流水线失败
4. **成本累积**：每个调用 LLM 的 agent 都必须调用 `merge_usage_into_state()` 更新成本字段
5. **CORS**：FastAPI 已配置 CORS，前端开发时直接访问 `http://localhost:8000`
6. **D3 + React**：D3 操作 DOM 必须在 `useEffect` 中，使用 `useRef` 获取 SVG 容器，不要直接操作 DOM
7. **DeepSeek**：使用 OpenAI SDK 的兼容接口，`base_url="https://api.deepseek.com"`，`model="deepseek-chat"`
8. **环境变量**：如果 `.env` 不存在，config.py 中的所有值都有默认值，系统不会崩溃（只是功能降级）
9. **前端构建**：Tailwind CSS v3 配置 `content: ["./src/**/*.{ts,tsx}"]`
10. **测试优先**：完成后端后先运行 `test_run.py`，确认流水线通了再做前端

---

## 🎯 验收标准（全部通过才算初版完成）

- [ ] `python test_run.py` 运行成功，status="done"，返回至少5篇论文
- [ ] `uvicorn backend.main:app` 启动，`GET /health` 返回 `{"status":"ok"}`
- [ ] `POST /search` 接口返回完整 JSON（含 report、ranked_papers、citation_graph）
- [ ] 前端页面加载，输入查询后能显示加载状态
- [ ] 前端能渲染 Markdown 报告
- [ ] D3 图谱能渲染（至少显示节点，有边更好）
- [ ] `python eval/f1_score.py --query "..." --expected "..."` 输出 F1 指标
