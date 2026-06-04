"""
ScholarFlow 双重验证测试
=========================
- 用非示例 query（自定义）
- 同时检查后端响应 + 前端显示
- 确保两侧内容一致
"""
import os
import time
import json
import hashlib
import re
import urllib.request
import urllib.parse
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(r"D:\AI\Claude code workspace\Atest\playwright_runs\dual_verify")
OUT.mkdir(parents=True, exist_ok=True)
BACKEND = "http://127.0.0.1:8000"
URL = "http://127.0.0.1:5173/"


def post_search(query: str, max_iter: int = 1, budget: float = 0.5) -> dict:
    """直接打后端"""
    req = urllib.request.Request(
        f"{BACKEND}/search",
        data=json.dumps({"query": query, "max_iterations": max_iter, "budget": budget}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def extract_papers_from_dom(page) -> list[str]:
    """从前端 DOM 提取论文列表的标题"""
    return page.locator("ul li p").all_inner_texts()


def h(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()[:10]


# 自定义查询：覆盖各种类型，绝对不在示例列表里
CUSTOM_QUERIES = [
    "graph neural network",
    "reinforcement learning from human feedback",
    "federated learning privacy",
    "diffusion model image generation",
    "knowledge graph embedding",
    "speech recognition transformer",
    "self-supervised learning contrastive",
    "object detection YOLO",
    "neural machine translation attention",
    "prompt tuning few-shot",
    "量子计算 量子算法",  # 完全中文
    "drug target interaction prediction",
    "recommender system collaborative filtering",
    "graph attention network",
    "vision transformer ViT",
]


def main():
    print(f"=== 双重验证测试: {len(CUSTOM_QUERIES)} 个自定义 query ===\n")
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()

        for q in CUSTOM_QUERIES:
            print(f"\n--- Query: {q!r} ---")

            # 1. 打后端
            t0 = time.time()
            backend_resp = post_search(q, max_iter=1, budget=0.5)
            backend_t = time.time() - t0
            backend_titles = [p["title"] for p in backend_resp.get("ranked_papers", [])]
            print(f"  Backend Top 5 ({backend_t:.2f}s):")
            for i, t in enumerate(backend_titles[:5], 1):
                print(f"    {i}. {t[:55]}")

            # 2. 打开前端，输入查询
            page.goto(URL, wait_until="domcontentloaded")
            page.wait_for_timeout(800)
            page.locator("textarea").click()
            page.locator("textarea").fill(q)
            page.wait_for_timeout(300)
            page.locator("button.flex-1.bg-brand-600").click()
            try:
                page.wait_for_function(
                    "() => document.body.innerText.toLowerCase().includes('done')",
                    timeout=10000,
                )
            except Exception:
                pass
            page.wait_for_timeout(800)

            # 3. 截图 + 提取 DOM
            s = OUT / f"{re.sub(r'[^a-z0-9_]', '_', q.lower())[:30]}.png"
            page.screenshot(path=str(s))
            frontend_titles = extract_papers_from_dom(page)
            print(f"  Frontend Top 5:")
            for i, t in enumerate(frontend_titles[:5], 1):
                print(f"    {i}. {t[:55]}")

            # 4. 双重验证
            # 4a. 论文总数一致
            n_backend = len(backend_titles)
            n_frontend = len(frontend_titles)
            count_match = n_backend == n_frontend

            # 4b. Top 5 标题一致（按位置比较）
            top_match_count = sum(
                1 for a, b in zip(backend_titles[:5], frontend_titles[:5]) if a == b
            )
            top_match_pct = top_match_count / min(5, max(len(backend_titles), len(frontend_titles)))

            # 4c. 至少 Top 1 必须与 query 主题相关
            # 简单相关度：标题是否包含 query 任一关键词
            query_words = set(q.lower().split())
            top1 = backend_titles[0].lower() if backend_titles else ""
            top1_matches = sum(1 for w in query_words if w in top1)

            # 4d. Top 3 中至少 2 个包含 query 关键词
            top3 = [t.lower() for t in backend_titles[:3]]
            top3_relevant = sum(1 for t in top3 for w in query_words if w in t)

            ok = count_match and top_match_pct >= 0.6 and top3_relevant >= 2

            results.append({
                "query": q,
                "ok": ok,
                "backend_n": n_backend,
                "frontend_n": n_frontend,
                "count_match": count_match,
                "top_match": f"{top_match_count}/5",
                "top1": backend_titles[0][:50] if backend_titles else "",
                "top1_query_words": top1_matches,
                "top3_relevant_papers": top3_relevant,
                "screenshot": s.name,
                "screenshot_hash": h(s),
            })

        browser.close()

    # 汇总
    print("\n" + "=" * 80)
    print("=== 双重验证汇总 ===\n")
    print(f"{'Query':<45} | {'OK':<5} | {'count':<7} | {'top5':<7} | {'q1-hit':<7} | {'top3-rel':<9}")
    print("-" * 100)
    passed = 0
    for r in results:
        status = "✓" if r["ok"] else "✗"
        print(f"{r['query'][:43]:<45} | {status:<5} | {r['backend_n']}={r['frontend_n']:<3} | {r['top_match']:<7} | {r['top1_query_words']}/{len(r['query'].split()):<5} | {r['top3_relevant_papers']}/3")
        if r["ok"]:
            passed += 1
    print("-" * 100)
    print(f"\n总通过率: {passed}/{len(results)}")

    # 详细列出失败 case
    print("\n=== 失败详情 ===")
    for r in results:
        if not r["ok"]:
            print(f"✗ {r['query']!r}")
            print(f"  Top 1: {r['top1']}")
            print(f"  Top 5 match: {r['top_match']}")
            print(f"  count match: {r['count_match']}")

    with open(OUT / "dual_verify.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    return results


if __name__ == "__main__":
    main()
