"""
R10.5.93 — Stance / StudyType / KeyQuote 分类器测试

覆盖:
1. ClassifyBatchOutput schema 校验 (合法/非法 stance + study_type)
2. _build_consensus_summary 聚合正确性
3. classify_papers_node 节点:
   - 空 ranked_papers → 直接返回 (不调 LLM)
   - LLM 失败 → 兜底 stance=unsure / study_type=other / key_quote=""
4. SearchState + Paper 模型字段存在
5. SearchResponse 透传 stance_summary
"""
import pytest

from backend.agents.stance_classifier import (
    ClassifyBatchOutput,
    PaperClassify,
    STANCE_VALUES,
    STUDY_TYPE_VALUES,
    _build_consensus_summary,
    classify_papers_node,
)
from backend.api.routes.models import (
    SearchResponse,
    PaperResult,
    make_initial_state,
)
from backend.models.state import SearchState
from backend.shared.paper_model import Paper


# ===== Schema 校验 =====

class TestClassifySchema:
    def test_legal_values_accepted(self):
        """合法 stance + study_type 直接接受"""
        out = ClassifyBatchOutput.model_validate({
            "root": {
                "1": {"stance": "supporting", "study_type": "rct", "key_quote": "test quote"},
                "2": {"stance": "contrasting", "study_type": "meta-analysis", "key_quote": "q2"},
            }
        })
        assert out.root["1"].stance == "supporting"
        assert out.root["1"].study_type == "rct"
        assert out.root["1"].key_quote == "test quote"
        assert out.root["2"].study_type == "meta-analysis"

    def test_invalid_stance_becomes_unsure(self):
        """非法 stance → unsure 兜底"""
        out = ClassifyBatchOutput.model_validate({
            "root": {
                "1": {"stance": "random_garbage", "study_type": "rct", "key_quote": ""},
            }
        })
        assert out.root["1"].stance == "unsure"

    def test_invalid_study_type_becomes_other(self):
        """非法 study_type → other 兜底 (含 alias 归一化)"""
        # Alias 归一化: 'randomized-controlled-trial' → 'rct'
        out = ClassifyBatchOutput.model_validate({
            "root": {
                "1": {"stance": "supporting", "study_type": "randomized-controlled-trial", "key_quote": ""},
                "2": {"stance": "supporting", "study_type": "completely_unknown", "key_quote": ""},
            }
        })
        assert out.root["1"].study_type == "rct"
        assert out.root["2"].study_type == "other"

    def test_stance_constants(self):
        """5 种 stance + 9 种 study_type 枚举稳定"""
        assert "supporting" in STANCE_VALUES
        assert "contrasting" in STANCE_VALUES
        assert "mixed" in STANCE_VALUES
        assert "neutral" in STANCE_VALUES
        assert "unsure" in STANCE_VALUES
        assert "rct" in STUDY_TYPE_VALUES
        assert "meta-analysis" in STUDY_TYPE_VALUES
        assert "systematic-review" in STUDY_TYPE_VALUES


# ===== _build_consensus_summary 聚合 =====

class TestConsensusSummary:
    def test_majority_supporting(self):
        """3 supporting / 1 contrasting → majority=supporting"""
        s = _build_consensus_summary([
            ("supporting", "rct"),
            ("supporting", "meta-analysis"),
            ("supporting", "review"),
            ("contrasting", "rct"),
        ])
        assert s["total"] == 4
        assert s["majority_stance"] == "supporting"
        assert "3" in s["summary"]  # 3/4

    def test_majority_contrasting(self):
        """2 supporting / 3 contrasting → majority=contrasting"""
        s = _build_consensus_summary([
            ("contrasting", "rct"),
            ("contrasting", "rct"),
            ("contrasting", "meta-analysis"),
            ("supporting", "review"),
            ("supporting", "empirical"),
        ])
        assert s["majority_stance"] == "contrasting"

    def test_mixed_dominates(self):
        """mixed >= sup/contra → mixed 文本"""
        s = _build_consensus_summary([
            ("mixed", "rct"),
            ("mixed", "rct"),
            ("supporting", "rct"),
            ("contrasting", "rct"),
        ])
        assert "混合" in s["summary"] or "mixed" in s["summary"].lower()

    def test_all_unsure(self):
        """全 unsure → majority=unsure, summary 简短"""
        s = _build_consensus_summary([
            ("unsure", "other"),
            ("unsure", "other"),
        ])
        assert s["majority_stance"] == "unsure"

    def test_type_counts(self):
        """type_counts 正确累积"""
        s = _build_consensus_summary([
            ("supporting", "rct"),
            ("supporting", "rct"),
            ("supporting", "meta-analysis"),
        ])
        assert s["type_counts"].get("rct") == 2
        assert s["type_counts"].get("meta-analysis") == 1


# ===== classify_papers_node 节点 =====

class TestClassifyNode:
    @pytest.mark.asyncio
    async def test_empty_ranked_papers_short_circuit(self):
        """ranked_papers 空 → 立即返回, 不调 LLM, 不 cost"""
        state = make_initial_state("test query", 3, 2.0, "minimax")
        result = await classify_papers_node(state)
        # 不修改 state (no-op)
        assert result.get("ranked_papers") == state.get("ranked_papers")
        assert result.get("stance_summary") is None

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_unsure(self, monkeypatch):
        """LLM 抛异常 → 走兜底, all papers stance=unsure, study_type=other"""
        from backend.utils.llm_client import call_llm as real_call_llm

        async def boom(*args, **kwargs):
            raise RuntimeError("simulated LLM failure")

        monkeypatch.setattr("backend.agents.stance_classifier.call_llm", boom)

        state = make_initial_state("test query", 3, 2.0, "minimax")
        state["ranked_papers"] = [
            {"paper_id": "a", "title": "A", "abstract": "abstract A", "year": 2024},
            {"paper_id": "b", "title": "B", "abstract": "abstract B", "year": 2023},
        ]

        result = await classify_papers_node(state)
        # 2 篇论文, 全部兜底
        for p in result["ranked_papers"]:
            assert p["stance"] == "unsure"
            assert p["study_type"] == "other"
            assert p["key_quote"] == ""
        # 聚合结果存在
        ss = result["stance_summary"]
        assert ss is not None
        assert ss["total"] == 2
        assert ss["counts"]["unsure"] == 2


# ===== 字段透传 =====

class TestStatePropagation:
    def test_search_state_has_stance_summary_field(self):
        """SearchState TypedDict 声明 stance_summary 字段"""
        # TypedDict 是声明性, 直接看 state.py 字段存在
        from backend.models import state as state_mod
        import inspect
        src = inspect.getsource(state_mod)
        assert "stance_summary" in src
        assert "Optional[dict]" in src

    def test_paper_dataclass_has_new_fields(self):
        """Paper dataclass 加 stance + study_type + key_quote"""
        p = Paper(
            paper_id="x",
            title="t",
            stance="supporting",
            study_type="rct",
            key_quote="quote",
        )
        d = p.to_dict()
        assert d["stance"] == "supporting"
        assert d["study_type"] == "rct"
        assert d["key_quote"] == "quote"

    def test_paper_dataclass_default_empty(self):
        """默认 stance/study_type/key_quote 为空串"""
        p = Paper(paper_id="y", title="t")
        assert p.stance == ""
        assert p.study_type == ""
        assert p.key_quote == ""

    def test_paper_result_model_has_new_fields(self):
        """PaperResult Pydantic 模型加新字段"""
        pr = PaperResult(
            paper_id="z",
            title="t",
            stance="mixed",
            study_type="empirical",
            key_quote="quote",
        )
        assert pr.stance == "mixed"
        assert pr.study_type == "empirical"
        assert pr.key_quote == "quote"

    def test_search_response_accepts_stance_summary(self):
        """SearchResponse 接受 stance_summary 字段"""
        sr = SearchResponse(
            report="",
            ranked_papers=[],
            citation_graph={},
            total_cost_usd=0.0,
            total_tokens_used=0,
            model_usage_summary={},
            iteration=0,
            status="done",
            stance_summary={
                "total": 3,
                "counts": {"supporting": 1, "contrasting": 1, "mixed": 0, "neutral": 0, "unsure": 1},
                "type_counts": {"rct": 1, "other": 2},
                "majority_stance": "supporting",
                "summary": "1/3 papers support",
            },
        )
        assert sr.stance_summary is not None
        assert sr.stance_summary["total"] == 3

    def test_initial_state_has_stance_summary_none(self):
        """make_initial_state 初始化 stance_summary=None"""
        s = make_initial_state("q", 3, 2.0, "minimax")
        assert "stance_summary" in s
        assert s["stance_summary"] is None


# ===== Graph 集成 =====

class TestGraphIntegration:
    def test_classify_papers_in_graph_metadata(self):
        """NODE_METADATA 包含 classify_papers"""
        from backend.workflow.graph import NODE_METADATA
        assert "classify_papers" in NODE_METADATA
        assert NODE_METADATA["classify_papers"]["display_name"] == "立场分类"

    def test_search_routes_have_classify_in_step_map(self):
        """search.py NODE_NAME_TO_STEP 含 classify_papers"""
        from backend.api.routes import search as search_mod
        assert "classify_papers" in search_mod.NODE_NAME_TO_STEP
