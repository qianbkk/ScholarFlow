"""R10.5.47 测试: Pydantic v2 结构化输出 (query_decompose + ranker).

R10.5.51 cleanup: 删 sync try_parse_with_retry, 改用 async parse_with_retry_async.
原覆盖项 9-11 (sync) 替换为 parse_with_retry_async_* (见下方编号 12-14).

覆盖:
  1. DecomposeOutput 接受合规 JSON, 解析成功
  2. DecomposeOutput 拒绝缺字段, 抛 ValidationError
  3. DecomposeOutput 自动过滤 sub_queries 空串 / 长度 ≤ 3
  4. ConstraintsModel.year_range 范围校验 (1900-2100, lo <= hi)
  5. ConstraintsModel.year_range 越界 抛 ValueError
  6. RankBatchOutput 接受 {"1": {"relevance": 8, "consistency": 7}} 形式
  7. RankBatchOutput 拒绝越界分数 (>10 / <0)
  8. _strip_markdown_fence 正确剥 ```json ... ``` 围栏
  9. parse_with_retry_async: 第一次解析成功, 不调 retry
  10. parse_with_retry_async: 第一次失败 + retry 成功, 返 parsed
  11. parse_with_retry_async: 两次都失败, 返 (None, last_usage)
  12. query_decompose_node: 故意给坏 JSON, 走 fallback 兜底
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ===== 1. DecomposeOutput 接受合规 JSON =====

def test_decompose_output_accepts_valid_json():
    """[R10.5.47] DecomposeOutput 接受合规 JSON, 解析成功."""
    from backend.agents._schemas import DecomposeOutput

    raw = json.dumps({
        "analysis": "用户查询 Transformer 注意力机制",
        "query_type": "simple",
        "sub_queries": ["transformer attention mechanism", "self-attention math"],
        "key_terms": ["transformer", "attention"],
        "constraints": {
            "venues": ["NeurIPS"],
            "year_range": [2020, 2024],
            "methods": ["transformer"],
            "datasets": None,
        },
    })
    obj = DecomposeOutput.model_validate_json(raw)
    assert obj.query_type == "simple"
    assert obj.sub_queries == ["transformer attention mechanism", "self-attention math"]
    assert obj.constraints.venues == ["NeurIPS"]
    assert obj.constraints.year_range == [2020, 2024]
    assert obj.constraints.datasets is None


# ===== 2. DecomposeOutput 拒绝非法 query_type =====

def test_decompose_output_rejects_invalid_query_type():
    """[R10.5.47] query_type 必须是 5 种 + default, 否则 Pydantic 抛 ValidationError."""
    from backend.agents._schemas import DecomposeOutput

    raw = json.dumps({
        "query_type": "totally_invalid",
        "sub_queries": ["x"],
    })
    with pytest.raises(ValidationError):
        DecomposeOutput.model_validate_json(raw)


# ===== 3. sub_queries 自动过滤 =====

def test_decompose_output_filters_empty_sub_queries():
    """[R10.5.47] sub_queries 自动过滤非 str / 空串 / len ≤ 3 元素."""
    from backend.agents._schemas import DecomposeOutput

    raw = json.dumps({
        "sub_queries": [
            "valid query",       # 保留
            "",                  # 空串, 过滤
            "ab",                # 长度 ≤ 3, 过滤
            "   ",               # 全空白, 过滤
            123,                 # 非 str, 过滤
            "another good one",  # 保留
        ],
    })
    obj = DecomposeOutput.model_validate_json(raw)
    assert obj.sub_queries == ["valid query", "another good one"]


# ===== 4. year_range 校验 =====

def test_constraints_year_range_valid():
    """[R10.5.47] year_range 在 [1900, 2100] + lo <= hi 时通过."""
    from backend.agents._schemas import ConstraintsModel

    obj = ConstraintsModel.model_validate({"year_range": [2020, 2024]})
    assert obj.year_range == [2020, 2024]


def test_constraints_year_range_lo_gt_hi_rejected():
    """[R10.5.47] year_range lo > hi 抛 ValueError."""
    from backend.agents._schemas import ConstraintsModel

    with pytest.raises(ValidationError) as exc_info:
        ConstraintsModel.model_validate({"year_range": [2024, 2020]})
    assert "lo > hi" in str(exc_info.value) or "lo" in str(exc_info.value)


def test_constraints_year_range_out_of_bounds_rejected():
    """[R10.5.47] year_range 越界 (< 1900 或 > 2100) 抛 ValueError."""
    from backend.agents._schemas import ConstraintsModel

    with pytest.raises(ValidationError):
        ConstraintsModel.model_validate({"year_range": [1800, 2020]})
    with pytest.raises(ValidationError):
        ConstraintsModel.model_validate({"year_range": [2020, 2200]})


def test_constraints_year_range_wrong_length_rejected():
    """[R10.5.47] year_range 不是 2 元素列表 抛 ValueError."""
    from backend.agents._schemas import ConstraintsModel

    with pytest.raises(ValidationError):
        ConstraintsModel.model_validate({"year_range": [2020]})
    with pytest.raises(ValidationError):
        ConstraintsModel.model_validate({"year_range": [2020, 2021, 2022]})


def test_constraints_year_range_accepts_string_ints():
    """[R10.5.47] year_range 接受字符串数字 (LLM 经常返回 string), 自动转 int."""
    from backend.agents._schemas import ConstraintsModel

    obj = ConstraintsModel.model_validate({"year_range": ["2020", "2024"]})
    assert obj.year_range == [2020, 2024]


# ===== 6. RankBatchOutput 接受合规 =====

def test_rank_batch_output_accepts_valid():
    """[R10.5.47] RankBatchOutput 接受 {"1": {"relevance": 8, "consistency": 7}, ...}."""
    from backend.agents._schemas import RankBatchOutput

    raw = json.dumps({
        "1": {"relevance": 8.5, "consistency": 7.0},
        "2": {"relevance": 6.0, "consistency": 5.5},
    })
    obj = RankBatchOutput.model_validate_json(raw)
    # RootModel: 顶层就是 dict, .root 访问
    assert obj.root["1"].relevance == 8.5
    assert obj.root["1"].consistency == 7.0
    assert obj.root["2"].relevance == 6.0


# ===== 7. RankBatchOutput 拒绝越界分数 =====

def test_rank_batch_output_rejects_out_of_range_scores():
    """[R10.5.47] relevance / consistency 越界 (>10 / <0) 抛 ValidationError."""
    from backend.agents._schemas import RankBatchOutput

    with pytest.raises(ValidationError):
        RankBatchOutput.model_validate_json(json.dumps({
            "1": {"relevance": 15.0, "consistency": 5.0},  # 15 > 10
        }))
    with pytest.raises(ValidationError):
        RankBatchOutput.model_validate_json(json.dumps({
            "1": {"relevance": 5.0, "consistency": -1.0},  # -1 < 0
        }))


# ===== 8. _strip_markdown_fence 围栏处理 =====

def test_strip_markdown_fence():
    """[R10.5.47] _strip_markdown_fence 正确剥 ```json ... ``` 围栏."""
    from backend.agents._schemas import _strip_markdown_fence

    # 完整围栏
    text1 = '```json\n{"key": "value"}\n```'
    assert _strip_markdown_fence(text1) == '{"key": "value"}'

    # 无语言标识
    text2 = '```\n{"key": "value"}\n```'
    assert _strip_markdown_fence(text2) == '{"key": "value"}'

    # 无围栏
    text3 = '{"key": "value"}'
    assert _strip_markdown_fence(text3) == '{"key": "value"}'

    # 含前后空白
    text4 = '  \n```json\n{"k": 1}\n```\n  '
    assert _strip_markdown_fence(text4) == '{"k": 1}'


# ===== 9-11. try_parse_with_retry 行为 =====
# R10.5.51 cleanup: 删 try_parse_with_retry 同步版 (deprecated, 生产都用 async).
# 4 个测试 case 删掉, 行为已被 test_parse_with_retry_async_* (如下) 覆盖.

# ===== 12. parse_with_retry_async 行为 (替代旧的 try_parse_with_retry) =====


@pytest.mark.asyncio
async def test_parse_with_retry_async_first_success():
    """[R10.5.51] 第一次解析成功, 不调 retry."""
    from backend.agents._schemas import DecomposeOutput, parse_with_retry_async

    valid = json.dumps({"sub_queries": ["good query"], "query_type": "simple"})
    call_count = [0]

    async def llm_first_success(prompt, **kwargs):
        call_count[0] += 1
        return valid, {"cost_usd": 0.0}

    obj, usage = await parse_with_retry_async(
        call_llm=llm_first_success,
        prompt="dummy",
        schema=DecomposeOutput,
        system="",
        max_tokens=500,
        task_type="complex_reason",
        timeout=10.0,
        retry_suffix="retry",
        log_tag="test",
        base_usage=None,
    )
    assert obj is not None
    assert usage is not None
    assert obj.query_type == "simple"
    assert call_count[0] == 1, "retry should NOT be called on first success"


@pytest.mark.asyncio
async def test_parse_with_retry_async_retry_success():
    """[R10.5.51] 第一次失败, retry 成功, 返 parsed."""
    from backend.agents._schemas import DecomposeOutput, parse_with_retry_async

    good_retry = json.dumps({"sub_queries": ["retry success"], "query_type": "method"})
    call_count = [0]

    async def llm_retry(prompt, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return "{ not valid json", {"cost_usd": 0.0}
        return good_retry, {"cost_usd": 0.0}

    obj, usage = await parse_with_retry_async(
        call_llm=llm_retry,
        prompt="dummy",
        schema=DecomposeOutput,
        system="",
        max_tokens=500,
        task_type="complex_reason",
        timeout=10.0,
        retry_suffix="strict JSON only",
        log_tag="test",
        base_usage=None,
    )
    assert obj is not None
    assert obj.sub_queries == ["retry success"]
    assert call_count[0] == 2


@pytest.mark.asyncio
async def test_parse_with_retry_async_both_fail():
    """[R10.5.51] 两次都失败, 返 (None, last_usage)."""
    from backend.agents._schemas import DecomposeOutput, parse_with_retry_async

    call_count = [0]

    async def llm_retry(prompt, **kwargs):
        call_count[0] += 1
        return "still garbage", {"cost_usd": 0.0}

    obj, usage = await parse_with_retry_async(
        call_llm=llm_retry,
        prompt="dummy",
        schema=DecomposeOutput,
        system="",
        max_tokens=500,
        task_type="complex_reason",
        timeout=10.0,
        retry_suffix="strict",
        log_tag="test",
        base_usage=None,
    )
    assert obj is None
    assert call_count[0] == 2


# ===== 13. query_decompose_node 集成测试 (故意给坏 JSON) =====

@pytest.mark.asyncio
async def test_query_decompose_fallback_on_bad_json(monkeypatch):
    """[R10.5.47] query_decompose_node 收到坏 JSON, Pydantic 校验失败, 走 fallback.

    旧实现: _extract_json_object 提取坏 JSON, sub_queries 走 _fallback_decompose.
    新实现: Pydantic ValidationError 1 次重试, 再失败 _fallback_decompose.
    测试重点: 不崩溃, 有 sub_queries 返回, constraints 是兜底.
    """
    from backend.agents import query_decomposer
    from backend.utils import llm_client as llm_mod

    call_count = [0]

    async def fake_call_llm(prompt, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            # 第一次: 故意给坏 JSON
            return "{ not valid json garbage", {"model": "test", "tokens": 10, "cost": 0.001}
        else:
            # 第二次 (retry): 还给坏 JSON, 强制走 fallback
            return "still not valid", {"model": "test", "tokens": 10, "cost": 0.001}

    monkeypatch.setattr(query_decomposer, "call_llm", fake_call_llm)
    # Pydantic 解析在 query_decomposer 模块内部, 不需要 monkeypatch 其他

    state = {
        "original_query": "test query",
        "sub_queries": [],
        "raw_papers": [],
        "expanded_papers": [],
        "ranked_papers": [],
        "iteration": 0,
        "max_iterations": 3,
        "total_tokens_used": 0,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 2.0,
        "model_usage": {},
        "status": "decomposing",
        "error": None,
        "provider": "kimi",
        "request_id": "test",
        "top5_summary_cache": None,
        "constraints": None,
        "empty_result_streak": 0,
    }

    result = await query_decomposer.query_decompose_node(state)

    # 验证: 不崩溃, 有 sub_queries (从 fallback), 状态为 searching
    assert "sub_queries" in result
    assert len(result["sub_queries"]) >= 1, (
        f"Fallback should provide ≥1 sub_query, got {result['sub_queries']}"
    )
    assert result["status"] == "searching"
    # call_count == 2: 1 次初次 + 1 次重试
    assert call_count[0] == 2, (
        f"Expected 2 LLM calls (1 initial + 1 retry), got {call_count[0]}"
    )


@pytest.mark.asyncio
async def test_query_decompose_pydantic_success_path(monkeypatch):
    """[R10.5.47] query_decompose_node 收到合规 JSON, Pydantic 解析成功, 不走 retry."""
    from backend.agents import query_decomposer

    call_count = [0]
    valid_json = json.dumps({
        "analysis": "user query analysis",
        "query_type": "survey",
        "sub_queries": ["transformer attention survey", "self-attention variants", "attention efficiency"],
        "key_terms": ["transformer", "attention"],
        "constraints": {
            "venues": ["NeurIPS"],
            "year_range": [2020, 2024],
            "methods": ["transformer"],
            "datasets": None,
        },
    })

    async def fake_call_llm(prompt, **kwargs):
        call_count[0] += 1
        return valid_json, {"model": "test", "tokens": 50, "cost": 0.005}

    monkeypatch.setattr(query_decomposer, "call_llm", fake_call_llm)

    state = {
        "original_query": "transformer attention",
        "sub_queries": [],
        "raw_papers": [],
        "expanded_papers": [],
        "ranked_papers": [],
        "iteration": 0,
        "max_iterations": 3,
        "total_tokens_used": 0,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 2.0,
        "model_usage": {},
        "status": "decomposing",
        "error": None,
        "provider": "kimi",
        "request_id": "test",
        "top5_summary_cache": None,
        "constraints": None,
        "empty_result_streak": 0,
    }

    result = await query_decomposer.query_decompose_node(state)
    # 1 次成功, 不 retry
    assert call_count[0] == 1
    # 6 sub_queries 上限 (survey) → 截到 6
    assert len(result["sub_queries"]) >= 1
    # constraints 应该从 Pydantic 解析得到, 不走 fallback
    assert result["constraints"]["venues"] == ["NeurIPS"]
    assert result["constraints"]["year_range"] == [2020, 2024]
    assert result["constraints"]["query_type"] == "survey"
