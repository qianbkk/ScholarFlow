"""
犀利评论后: 随机方向真实 LLM E2E 验证
========================================

测试目标: 验证经过犀利评论修复后,系统对多个随机方向的查询仍能:
1. 跑通 8 节点流水线
2. 检索到相关论文 (不出现"硬编码 Transformer"现象)
3. 报告内容与查询强相关
4. 论文列表无重复 (实体对齐生效)
5. 引文图谱结构合理 (向后+向前扩展)
6. 成本在合理范围内 (real LLM 单次 < $0.5)

执行: python tests/manual/verify_random_queries.py
"""
import asyncio
import json
import os
import random
import sys
import time

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.path.insert(0, r'D:/AI/Claude code workspace/Atest')

# 8 个真实研究方向,覆盖不同学科,用于随机验证
RANDOM_QUERIES = [
    "AlphaFold protein structure prediction deep learning",
    "CRISPR Cas9 gene editing mechanism",
    "transformer attention mechanism NLP",
    "graph neural network molecular property prediction",
    "diffusion model image generation",
    "reinforcement learning game playing",
    "federated learning privacy preserving",
    "large language model reasoning chain of thought",
]


async def run_one_query(query: str, idx: int, total: int) -> dict:
    """单条查询的完整 E2E 验证。"""
    print(f"\n[{idx}/{total}] Query: {query!r}")

    from backend.workflow.graph import search_graph

    initial = {
        "original_query": query,
        "sub_queries": [],
        "raw_papers": [],
        "expanded_papers": [],
        "ranked_papers": [],
        "report": "",
        "citation_graph": {},
        "iteration": 0,
        "max_iterations": 1,
        "total_tokens_used": 0,
        "total_cost_usd": 0.0,
        "budget_limit_usd": 0.3,
        "model_usage": {},
        "status": "decomposing",
        "error": None,
        "expanded_paper_ids": [],
    }

    t0 = time.time()
    try:
        final = await asyncio.wait_for(search_graph.ainvoke(initial), timeout=200.0)
    except asyncio.TimeoutError:
        return {"query": query, "ok": False, "error": "timeout > 200s"}
    except Exception as e:
        return {"query": query, "ok": False, "error": f"{type(e).__name__}: {e}"}

    elapsed = time.time() - t0
    report = final.get("report", "")
    ranked = final.get("ranked_papers", [])
    graph = final.get("citation_graph", {})
    cost = final.get("total_cost_usd", 0)

    # ===== 验证条件 =====
    issues = []
    if not report or len(report) < 200:
        issues.append("report_too_short")
    if not ranked:
        issues.append("no_ranked_papers")
    if not graph.get("nodes"):
        issues.append("no_graph_nodes")

    # 报告必须含 query 核心词 (例如 "alphafold" / "protein" 用于 AlphaFold 查询)
    query_keywords = [w.lower() for w in query.split() if len(w) > 3][:3]
    report_lower = report.lower()
    keyword_hits = sum(1 for kw in query_keywords if kw in report_lower)
    if keyword_hits < 1:
        issues.append(f"no_query_keywords_in_report (checked: {query_keywords})")

    # 论文标题去重检查 (犀利评论 #2 修复验证)
    titles = [p.get("title", "").lower()[:50] for p in ranked]
    if len(titles) != len(set(titles)):
        issues.append(f"duplicate_titles_in_output (n={len(titles)}, unique={len(set(titles))})")

    # 成本检查
    if cost > 0.5:
        issues.append(f"cost_too_high (${cost:.4f})")

    ok = not issues
    print(f"   [{'OK' if ok else 'FAIL'}] {elapsed:.1f}s | ${cost:.4f} | "
          f"report={len(report)}c | ranked={len(ranked)} | graph_nodes={len(graph.get('nodes',[]))} | "
          f"kw_hits={keyword_hits}/{len(query_keywords)} | dup={len(titles)-len(set(titles))}")
    if issues:
        for iss in issues:
            print(f"      - {iss}")
    return {
        "query": query,
        "ok": ok,
        "issues": issues,
        "elapsed_seconds": round(elapsed, 1),
        "cost_usd": round(cost, 4),
        "report_length": len(report),
        "ranked_count": len(ranked),
        "graph_nodes": len(graph.get("nodes", [])),
        "graph_edges": len(graph.get("links", [])),
    }


async def main():
    # 打乱顺序避免顺序依赖
    random.seed(42)
    queries = RANDOM_QUERIES.copy()
    random.shuffle(queries)

    print("=" * 70)
    print(f"犀利评论后 随机方向 E2E 验证 (共 {len(queries)} 条)")
    print("=" * 70)

    results = []
    for i, q in enumerate(queries, 1):
        r = await run_one_query(q, i, len(queries))
        results.append(r)

    # ===== 汇总 =====
    print("\n" + "=" * 70)
    print("汇总")
    print("=" * 70)
    n_pass = sum(1 for r in results if r["ok"])
    n_fail = sum(1 for r in results if not r["ok"])
    total_cost = sum(r.get("cost_usd", 0) for r in results)
    total_time = sum(r.get("elapsed_seconds", 0) for r in results)
    print(f"  PASS: {n_pass}/{len(results)}")
    print(f"  FAIL: {n_fail}/{len(results)}")
    print(f"  TOTAL COST: ${total_cost:.4f}")
    print(f"  TOTAL TIME: {total_time:.1f}s (avg {total_time/len(results):.1f}s/query)")

    # 保存报告
    out = "D:/AI/Claude code workspace/Atest/playwright_runs/random_e2e_report.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "queries_total": len(results),
            "queries_passed": n_pass,
            "queries_failed": n_fail,
            "total_cost_usd": total_cost,
            "total_time_seconds": total_time,
            "results": results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n详细报告: {out}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
