"""
ScholarFlow retrieval quality evaluation tool
==============================================

Generic F1 (precision/recall) evaluation for the search pipeline.
Supports single-query and batch (test_cases.json) modes.

Usage:
  # Single query
  python eval/f1_score.py --query "transformer attention" \
      --expected "Attention Is All You Need" "BERT"

  # Batch (reads eval/test_cases.json)
  python eval/f1_score.py --batch
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Iterable

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from backend.workflow.graph import search_graph
from backend.config import LLM_PROVIDER, LLM_MOCK, API_MOCK
from backend.utils.sanitize import sanitize_query  # Round 2 MEDIUM-005: eval 入口必须 sanitize

# Round 2 MEDIUM-005: eval 走完整 LLM 链路, 必须限 budget 防止 1 次 eval 耗光全局预算
MAX_EVAL_BUDGET = 5.0

logger = logging.getLogger(__name__)


def compute_f1(retrieved: list[str], relevant: list[str]) -> dict:
    """Standard set-based precision / recall / F1.

    Title matching is case-insensitive and uses the first 60 chars to
    avoid spurious mismatches on subtitle differences.
    """
    ret = {t.lower()[:60] for t in retrieved if t}
    rel = {t.lower()[:60] for t in relevant if t}
    tp = len(ret & rel)
    precision = tp / len(ret) if ret else 0.0
    recall = tp / len(rel) if rel else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return {
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "true_positives": tp,
        "retrieved_count": len(ret),
        "relevant_count": len(rel),
    }


async def run_eval(query: str, expected_titles: list[str], budget: float = 1.0) -> dict:
    """Run a single retrieval evaluation: query -> top papers -> F1 vs expected."""
    # Round 2 MEDIUM-005: 入口处 sanitize (与 main.py 一致), 防止 prompt injection 评估污染
    sanitized = sanitize_query(query)
    if not sanitized:
        logger.warning(f"eval query sanitized to empty, skip: {query[:60]!r}")
        return {
            "precision": 0.0, "recall": 0.0, "f1": 0.0,
            "true_positives": 0, "retrieved_count": 0, "relevant_count": len(expected_titles),
        }
    # Round 2 MEDIUM-005: budget 上限, 防止单次 eval 预留过多预算
    effective_budget = min(MAX_EVAL_BUDGET, max(0.1, float(budget)))
    initial = {
        "original_query": sanitized,
        "sub_queries": [],
        "raw_papers": [],
        "expanded_papers": [],
        "expanded_paper_ids": [],  # CRIT fix from main.py
        "ranked_papers": [],
        "report": "",
        "citation_graph": {},
        "iteration": 0,
        "max_iterations": 2,
        "total_tokens_used": 0,
        "total_cost_usd": 0.0,
        "budget_limit_usd": effective_budget,
        "model_usage": {},
        "status": "decomposing",
        "error": None,
        "provider": None,  # 保持与 SearchState TypedDict 一致
    }
    final = await search_graph.ainvoke(initial)
    retrieved = [p.get("title", "") for p in final.get("ranked_papers", [])[:20]]
    metrics = compute_f1(retrieved, expected_titles)

    print("=" * 60)
    print(f"Provider : {LLM_PROVIDER}  (LLM_MOCK={LLM_MOCK}, API_MOCK={API_MOCK})")
    print(f"Query    : {sanitized}")
    print(f"Expected : {len(expected_titles)} papers")
    print(f"Retrieved: {len(retrieved)} papers")
    print(f"Precision: {metrics['precision']:.3f}")
    print(f"Recall   : {metrics['recall']:.3f}")
    print(f"F1 Score : {metrics['f1']:.3f}")
    print(f"Cost     : ${final.get('total_cost_usd', 0):.4f}")
    print("=" * 60)
    return metrics


async def run_batch() -> list[dict]:
    cases_path = os.path.join(os.path.dirname(__file__), "test_cases.json")
    with open(cases_path, encoding="utf-8") as f:
        cases = json.load(f)
    results = []
    for i, case in enumerate(cases):
        print(f"\n[{i+1}/{len(cases)}] {case['query']}")
        m = await run_eval(case["query"], case["expected_papers"], budget=case.get("budget", 1.0))
        results.append({"query": case["query"], **m})
    if results:
        avg_f1 = sum(r["f1"] for r in results) / len(results)
        avg_p = sum(r["precision"] for r in results) / len(results)
        avg_r = sum(r["recall"] for r in results) / len(results)
        print("\n" + "=" * 60)
        print("Batch Summary")
        print("=" * 60)
        print(f"Cases: {len(results)}")
        print(f"Avg Precision: {avg_p:.3f}")
        print(f"Avg Recall   : {avg_r:.3f}")
        print(f"Avg F1       : {avg_f1:.3f}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ScholarFlow retrieval F1 evaluation")
    parser.add_argument("--query", help="Single search query")
    parser.add_argument("--expected", nargs="+", help="Expected paper titles (space-separated)")
    parser.add_argument("--budget", type=float, default=1.0, help="Per-query budget USD")
    parser.add_argument("--batch", action="store_true", help="Run all cases from eval/test_cases.json")
    args = parser.parse_args()
    if args.batch:
        asyncio.run(run_batch())
    elif args.query and args.expected:
        asyncio.run(run_eval(args.query, args.expected, args.budget))
    else:
        parser.print_help()
