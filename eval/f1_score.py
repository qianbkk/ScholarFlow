"""
ScholarFlow F1 评测脚本 (PaSa 风格)
====================================

参考华为赛题三的 PaSa benchmark 评测方法：
  - 每个 query 的 "相关论文集" 扩充到 5-10 篇
  - 报告 Recall@K (K=5, 10, 20) 而非单一 F1
  - 使用模糊标题匹配（前 60 字符 + 子串匹配）
  - 与基线对比 (Random top-20 / Single-source baseline)

用法：
  python eval/f1_score.py --query "transformer" --expected "Attention Is All You Need" ...
  python eval/f1_score.py --batch
"""
import argparse
import asyncio
import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.workflow.graph import search_graph


# ============================================================
# 标题匹配（兼容不同 API 的标题细节差异）
# ============================================================

def _normalize_title(t: str) -> str:
    """归一化：去标点、去多余空格、转小写。"""
    import re
    t = (t or "").lower()
    t = re.sub(r"[^\w\s一-鿿]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _is_match(retrieved_title: str, expected_title: str) -> bool:
    """模糊匹配：前 60 字符 OR 子串 OR 关键词重合度 >= 50%。"""
    r = _normalize_title(retrieved_title)
    e = _normalize_title(expected_title)
    if not r or not e:
        return False
    # 1) 前 60 字符完全相同
    if r[:60] == e[:60]:
        return True
    # 2) 任一方向包含
    if r in e or e in r:
        return True
    # 3) 关键词重合度
    r_words = set(r.split())
    e_words = set(e.split())
    if not r_words or not e_words:
        return False
    overlap = len(r_words & e_words)
    smaller = min(len(r_words), len(e_words))
    if smaller > 0 and overlap / smaller >= 0.5:
        return True
    return False


def match_titles(retrieved: list[str], expected: list[str]) -> set[str]:
    """返回 expected 中被命中的标题集合。"""
    matched = set()
    for exp in expected:
        for ret in retrieved:
            if _is_match(ret, exp):
                matched.add(exp)
                break
    return matched


# ============================================================
# 评测指标
# ============================================================

def compute_metrics(retrieved_titles: list[str], expected_titles: list[str], k_values: list[int] = (5, 10, 20)) -> dict:
    """PaSa 风格指标：Recall@K, Precision@K, F1, nDCG@K."""
    n_relevant = len(expected_titles)
    if n_relevant == 0:
        return {"recall@5": 0, "recall@10": 0, "recall@20": 0, "precision@5": 0, "precision@10": 0, "precision@20": 0, "f1@20": 0, "ndcg@10": 0, "tp": 0, "fp": 0, "fn": 0}

    top_k_results: dict[int, set[str]] = {}
    for k in k_values:
        top_k_titles = retrieved_titles[:k]
        top_k_results[k] = match_titles(top_k_titles, expected_titles)

    # TP = 命中的相关论文数
    tp = len(top_k_results[max(k_values)])
    fp = min(max(k_values), len(retrieved_titles)) - tp
    fn = n_relevant - tp

    # Recall@K, Precision@K
    metrics = {"tp": tp, "fp": fp, "fn": fn, "n_relevant": n_relevant}
    for k in k_values:
        n_hit = len(top_k_results[k])
        metrics[f"recall@{k}"] = round(n_hit / n_relevant, 3)
        metrics[f"precision@{k}"] = round(n_hit / k, 3) if k > 0 else 0
        if metrics[f"recall@{k}"] + metrics[f"precision@{k}"] > 0:
            metrics[f"f1@{k}"] = round(
                2 * metrics[f"recall@{k}"] * metrics[f"precision@{k}"]
                / (metrics[f"recall@{k}"] + metrics[f"precision@{k}"]), 3
            )
        else:
            metrics[f"f1@{k}"] = 0.0

    # 总体 F1 (基于 top-20)
    p20 = metrics[f"precision@20"]
    r20 = metrics[f"recall@20"]
    metrics["f1@20"] = round(2 * p20 * r20 / (p20 + r20), 3) if (p20 + r20) > 0 else 0.0

    # nDCG@10
    import math
    dcg = 0.0
    for i, title in enumerate(retrieved_titles[:10]):
        for exp in expected_titles:
            if _is_match(title, exp):
                dcg += 1.0 / math.log2(i + 2)
                break
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(n_relevant, 10)))
    metrics["ndcg@10"] = round(dcg / idcg, 3) if idcg > 0 else 0.0
    return metrics


# ============================================================
# 基线
# ============================================================

def random_baseline(all_papers: list[str], expected: list[str], k: int = 20) -> dict:
    """随机选取 K 篇作为基线。"""
    sample = random.sample(all_papers, min(k, len(all_papers)))
    return compute_metrics(sample, expected)


def single_source_baseline(retrieved_ss: list[str], retrieved_oa: list[str], expected: list[str], k: int = 20) -> dict:
    """单源 vs 双源对比。"""
    return {
        "ss_only": compute_metrics(retrieved_ss[:k], expected),
        "oa_only": compute_metrics(retrieved_oa[:k], expected),
    }


# ============================================================
# 跑一次
# ============================================================

async def run_one(query: str, expected_titles: list[str], budget: float = 0.5, max_iter: int = 1) -> dict:
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
    metrics = compute_metrics(retrieved, expected_titles)

    # 随机基线（如果 mock 数据可用）
    try:
        from backend.api.mock_data import get_all_mock_papers
        all_mock_titles = [p.title for p in get_all_mock_papers()]
        baseline = random_baseline(all_mock_titles, expected_titles, k=20)
    except Exception:
        baseline = {}

    print(f"\n{'=' * 64}")
    print(f"Query        : {query}")
    print(f"Expected     : {len(expected_titles)} relevant papers")
    print(f"Retrieved    : {len(retrieved)} papers (top-20)")
    print(f"")
    print(f"Recall@5     : {metrics['recall@5']:.3f}    (out of {len(expected_titles)} relevant)")
    print(f"Recall@10    : {metrics['recall@10']:.3f}")
    print(f"Recall@20    : {metrics['recall@20']:.3f}")
    print(f"")
    print(f"Precision@10 : {metrics['precision@10']:.3f}")
    print(f"Precision@20 : {metrics['precision@20']:.3f}")
    print(f"F1@20        : {metrics['f1@20']:.3f}")
    print(f"nDCG@10      : {metrics['ndcg@10']:.3f}")
    print(f"")
    print(f"TP / FP / FN : {metrics['tp']} / {metrics['fp']} / {metrics['fn']}")
    if baseline:
        print(f"vs Random    : R@20 = {baseline.get('recall@20', 0):.3f} (baseline)")
    print(f"")
    print(f"Cost         : ${final.get('total_cost_usd', 0):.4f}")
    print(f"Tokens       : {final.get('total_tokens_used', 0):,}")
    print(f"Graph edges  : {len(final.get('citation_graph', {}).get('links', []))}")
    print(f"Elapsed      : {elapsed:.2f}s")
    print(f"{'=' * 64}\n")
    metrics["query"] = query
    metrics["elapsed"] = elapsed
    metrics["cost"] = final.get("total_cost_usd", 0)
    metrics["tokens"] = final.get("total_tokens_used", 0)
    return metrics


# ============================================================
# 批量
# ============================================================

async def run_batch(test_cases_file: str) -> list[dict]:
    with open(test_cases_file, "r", encoding="utf-8") as f:
        cases = json.load(f)
    results = []
    for i, case in enumerate(cases, 1):
        print(f"\n>> [{i}/{len(cases)}] {case['query']}")
        m = await run_one(case["query"], case.get("expected_papers", []), max_iter=1, budget=0.5)
        results.append(m)
    if results:
        n = len(results)
        print(f"\n{'#' * 64}")
        print(f"#  批量评测汇总 (n={n})")
        print(f"#  Avg Recall@5   : {sum(r['recall@5'] for r in results) / n:.3f}")
        print(f"#  Avg Recall@10  : {sum(r['recall@10'] for r in results) / n:.3f}")
        print(f"#  Avg Recall@20  : {sum(r['recall@20'] for r in results) / n:.3f}")
        print(f"#  Avg Precision@10: {sum(r['precision@10'] for r in results) / n:.3f}")
        print(f"#  Avg F1@20      : {sum(r['f1@20'] for r in results) / n:.3f}")
        print(f"#  Avg nDCG@10    : {sum(r['ndcg@10'] for r in results) / n:.3f}")
        print(f"#  Avg Latency    : {sum(r.get('elapsed', 0) for r in results) / n:.2f}s")
        print(f"#  Avg Cost       : ${sum(r.get('cost', 0) for r in results) / n:.4f}")
        print(f"{'#' * 64}\n")
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
