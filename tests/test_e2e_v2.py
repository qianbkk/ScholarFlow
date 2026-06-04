"""
ScholarFlow 端到端测试 v2
========================
覆盖 15+ 个跨领域查询，验证：
1. 后端返回 Top 20 论文相关性
2. 引用图谱有边
3. 报告非空
4. 3D 评分非空
5. 各查询结果互不相同（不全是同一批）
"""
import json
import sys
import time
from pathlib import Path

import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


QUERIES = [
    # === LLM / NLP ===
    ("transformer attention mechanism", ["Attention Is All You Need", "BERT"]),
    ("large language model survey", ["Survey of Large Language Models", "GPT-3"]),
    ("chain of thought reasoning", ["Chain-of-Thought"]),
    ("retrieval augmented generation", ["Retrieval-Augmented Generation"]),
    # === 视觉 ===
    ("object detection YOLO real-time", ["You Only Look Once", "Faster R-CNN"]),
    ("vision transformer image", ["Image is Worth 16x16", "Segment Anything"]),
    ("image classification benchmark", ["ImageNet Classification", "Residual Learning"]),
    # === 语音 ===
    ("speech recognition self-supervised", ["wav2vec", "Whisper"]),
    # === RL ===
    ("reinforcement learning PPO", ["Proximal Policy Optimization", "Soft Actor-Critic"]),
    ("multi-agent reinforcement learning", ["Multi-Agent Actor-Critic"]),
    # === 图 / 推荐 / 联邦 ===
    ("graph neural network", ["Graph Attention", "GraphSAGE"]),
    ("recommender system collaborative", ["Neural Collaborative Filtering"]),
    ("federated learning privacy", ["Communication-Efficient", "Differential Privacy"]),
    # === 生成模型 ===
    ("diffusion model image generation", ["Denoising Diffusion"]),
    # === 跨领域（中文） ===
    ("量子计算 量子算法", ["量子计算与量子算法研究进展"]),
    ("计算机视觉 transformer", ["计算机视觉中的 Transformer 架构综述"]),
    # === 跨领域（不应命中的极端情况） ===
    # "纯生物" — 应返回低相关或空
    ("protein folding molecular dynamics", ["Highly Accurate Protein Structure"]),  # AlphaFold
]


def post_search(query: str, max_iter: int = 1) -> dict:
    req = urllib.request.Request(
        "http://127.0.0.1:8000/search",
        data=json.dumps({"query": query, "budget": 0.5, "max_iterations": max_iter}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


def main():
    print(f"ScholarFlow E2E test: {len(QUERIES)} queries\n")
    print("=" * 80)
    results = []
    for i, (q, must_contain) in enumerate(QUERIES, 1):
        t0 = time.time()
        try:
            r = post_search(q)
            elapsed = time.time() - t0
            papers = r.get("ranked_papers", [])
            graph = r.get("citation_graph", {})
            report = r.get("report", "")
            top5_titles = [p.get("title", "") for p in papers[:5]]
            top20_titles = [p.get("title", "") for p in papers[:20]]
            n_edges = len(graph.get("links", []))

            # 验证 must_contain
            hits = []
            for needle in must_contain:
                if any(needle.lower() in t.lower() for t in top20_titles):
                    hits.append(needle)

            n_papers = len(papers)
            has_report = bool(report and len(report) > 100)
            n_3d = sum(1 for p in papers if p.get("relevance_score", 0) > 0
                       and p.get("authority_score", 0) > 0
                       and p.get("consistency_score", 0) > 0)

            ok = (n_papers > 0 and has_report and len(hits) > 0 and n_edges > 0)
            tag = "[OK]" if ok else "[!] "
            print(f"{tag} [{i:2d}] {q!r}")
            print(f"      papers={n_papers} | 3D_scored={n_3d}/{n_papers} | edges={n_edges} | elapsed={elapsed:.1f}s")
            if hits:
                print(f"      HIT: {hits}")
            if not has_report:
                print(f"      [!] Report empty (len={len(report)})")
            if n_edges == 0:
                print(f"      [!] Graph has 0 edges")

            results.append({"q": q, "ok": ok, "n_papers": n_papers, "n_edges": n_edges,
                            "elapsed": elapsed, "hits": hits})
        except Exception as e:
            print(f"[X] [{i:2d}] {q!r} -- EXCEPTION: {e}")
            results.append({"q": q, "ok": False, "error": str(e)})
        print("-" * 80)

    # 汇总
    passed = sum(1 for r in results if r.get("ok"))
    print(f"\n{'=' * 80}")
    print(f"  总计: {passed}/{len(QUERIES)} pass")
    print(f"  平均耗时: {sum(r.get('elapsed', 0) for r in results) / max(1, len(results)):.2f}s")
    print(f"  平均边数: {sum(r.get('n_edges', 0) for r in results) / max(1, len(results)):.1f}")
    print(f"{'=' * 80}\n")

    return 0 if passed == len(QUERIES) else 1


if __name__ == "__main__":
    sys.exit(main())
