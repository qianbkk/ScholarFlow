"""
ScholarFlow 端到端冒烟测试
============================
不依赖前端，直接驱动 LangGraph 工作流。

运行：python test_run.py
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.workflow.graph import search_graph
from backend.utils.llm_client import _self_test
from backend.config import LLM_PROVIDER, BUDGET_LIMIT_USD, MAX_SEARCH_ITERATIONS


async def main():
    query = "large language model agent for automated research"
    print(f"\n=== ScholarFlow 冒烟测试 ===")
    print(f"Provider : {LLM_PROVIDER}")
    print(f"Query    : {query}\n")

    # Step 1: LLM 自检
    print("--- 1) LLM 客户端自检 ---")
    try:
        _, usage = await _self_test()
        if usage.get("error"):
            print(f"[!] LLM provider 暂不可用: {usage.get('error')}")
            print("    系统将使用离线兜底策略继续运行\n")
        else:
            print(f"[OK] LLM provider 可用 (model={usage.get('model')})\n")
    except Exception as e:
        print(f"[!] LLM 自检异常: {e}\n")

    # Step 2: 跑完整流水线
    print("--- 2) 驱动 LangGraph 工作流 ---")
    # R10.5.17: 复用 make_initial_state, 18 行 dict 消失.
    from backend.api.routes.models import make_initial_state
    initial = make_initial_state(
        query,
        max_iterations=1,         # 测试只跑 1 轮
        budget=0.5,                # 测试用小预算
        provider=None,
    )

    t0 = time.time()
    try:
        final = await search_graph.ainvoke(initial)
        elapsed = time.time() - t0
    except Exception as e:
        print(f"[X] 工作流执行异常: {e}")
        import traceback
        traceback.print_exc()
        return

    # Step 3: 汇总结果
    print(f"\n--- 3) 结果汇总 (耗时 {elapsed:.1f}s) ---")
    print(f"Status           : {final.get('status')}")
    print(f"Sub-queries      : {len(final.get('sub_queries', []))}")
    print(f"Raw papers       : {len(final.get('raw_papers', []))}")
    print(f"Expanded papers  : {len(final.get('expanded_papers', []))}")
    print(f"Ranked papers    : {len(final.get('ranked_papers', []))}")
    print(f"Iterations       : {final.get('iteration', 0)}")
    print(f"Total cost       : ${final.get('total_cost_usd', 0):.4f}")
    print(f"Total tokens     : {final.get('total_tokens_used', 0):,}")
    print(f"Citation graph   : {len(final.get('citation_graph', {}).get('nodes', []))} nodes, "
          f"{len(final.get('citation_graph', {}).get('links', []))} links")

    if final.get("ranked_papers"):
        print("\nTop 3 papers:")
        for p in final["ranked_papers"][:3]:
            print(f"  - [{p.get('year','')}] {p.get('title','')[:70]} "
                  f"(score={p.get('final_score',0):.1f}, rel={p.get('relevance_score',0):.1f}, "
                  f"cite={p.get('citation_count',0)})")

    if final.get("report"):
        print(f"\nReport preview ({len(final['report'])} chars):")
        print("-" * 60)
        print(final["report"][:500])
        print("-" * 60)

    # 验收
    passed = (
        final.get("status") == "done"
        and len(final.get("ranked_papers", [])) >= 1
        and final.get("report", "")
    )

    print("\n" + "=" * 60)
    if passed:
        print("[PASS] 测试通过！ScholarFlow 初版可运行")
        if len(final.get("ranked_papers", [])) < 5:
            print("       (提示: 排序论文数 < 5，下一轮测试可考虑增加子查询或调高预算)")
    else:
        print("[WARN] 测试未完全通过，请检查上述日志")
    print("=" * 60)

    return final


if __name__ == "__main__":
    asyncio.run(main())
