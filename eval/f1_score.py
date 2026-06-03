"""
ScholarFlow F1 评测脚本
========================
用法：
  python eval/f1_score.py --query "transformer attention mechanism" \
    --expected "Attention Is All You Need" "BERT: Pre-training of Deep Bidirectional Transformers"

或批量跑：
  python eval/f1_score.py --batch
"""
import argparse
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.workflow.graph import search_graph


def compute_f1(retrieved: list[str], relevant: list[str]) -> dict:
    """基于标题前 60 字符的集合 F1。"""
    ret = {(t or "").lower()[:60] for t in retrieved if t}
    rel = {(t or "").lower()[:60] for t in relevant if t}
    ret.discard("")
    rel.discard("")
    tp = len(ret & rel)
    fp = len(ret - rel)
    fn = len(rel - ret)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


async def run_one(query: str, expected_titles: list[str], budget: float = 1.0, max_iter: int = 1) -> dict:
    initial = {
        "original_query": query,
        "sub_queries": [],
        "raw_papers": [],
        "expanded_papers": [],
        "ranked_papers": [],
        "report": "",
        "citation_graph": {},
        "iteration": 0,
        "max_iterations": max_iter,
        "total_tokens_used": 0,
        "total_cost_usd": 0.0,
        "budget_limit_usd": budget,
        "model_usage": {},
        "status": "decomposing",
        "error": None,
    }
    t0 = time.time()
    final = await search_graph.ainvoke(initial)
    elapsed = time.time() - t0

    retrieved = [p.get("title", "") for p in final.get("ranked_papers", [])[:20]]
    metrics = compute_f1(retrieved, expected_titles)

    print(f"\n{'=' * 60}")
    print(f"Query        : {query}")
    print(f"Expected     : {len(expected_titles)} papers")
    print(f"Retrieved    : {len(retrieved)} papers (top-20)")
    print(f"")
    print(f"Precision    : {metrics['precision']:.3f}")
    print(f"Recall       : {metrics['recall']:.3f}")
    print(f"F1 Score     : {metrics['f1']:.3f}")
    print(f"")
    print(f"TP / FP / FN : {metrics['tp']} / {metrics['fp']} / {metrics['fn']}")
    print(f"Cost         : ${final.get('total_cost_usd', 0):.4f}")
    print(f"Tokens       : {final.get('total_tokens_used', 0):,}")
    print(f"Elapsed      : {elapsed:.2f}s")
    print(f"{'=' * 60}\n")
    return metrics


async def run_batch(test_cases_file: str) -> list[dict]:
    with open(test_cases_file, "r", encoding="utf-8") as f:
        cases = json.load(f)
    results = []
    for i, case in enumerate(cases, 1):
        print(f"\n>> [{i}/{len(cases)}] {case['query']}")
        m = await run_one(case["query"], case.get("expected_papers", []), max_iter=1, budget=0.5)
        m["query"] = case["query"]
        results.append(m)
    # 汇总
    if results:
        avg_f1 = sum(r["f1"] for r in results) / len(results)
        avg_p = sum(r["precision"] for r in results) / len(results)
        avg_r = sum(r["recall"] for r in results) / len(results)
        print(f"\n{'#' * 60}")
        print(f"#  批量评测汇总 (n={len(results)})")
        print(f"#  Avg Precision: {avg_p:.3f}")
        print(f"#  Avg Recall   : {avg_r:.3f}")
        print(f"#  Avg F1       : {avg_f1:.3f}")
        print(f"{'#' * 60}\n")
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", help="单条评测查询")
    parser.add_argument("--expected", nargs="+", help="期望命中的论文标题列表")
    parser.add_argument("--budget", type=float, default=0.5, help="成本上限 USD")
    parser.add_argument("--max-iter", type=int, default=1, help="最大迭代轮次")
    parser.add_argument("--batch", action="store_true", help="跑 eval/test_cases.json 全部用例")
    parser.add_argument("--cases", default=os.path.join(os.path.dirname(__file__), "test_cases.json"))
    args = parser.parse_args()

    if args.batch:
        asyncio.run(run_batch(args.cases))
        return

    if not args.query or not args.expected:
        parser.print_help()
        print("\n[ERROR] 必须提供 --query 和 --expected，或使用 --batch")
        sys.exit(1)

    asyncio.run(run_one(args.query, args.expected, args.budget, args.max_iter))


if __name__ == "__main__":
    main()
