"""
ScholarFlow 6 维度综合测试
============================
1. 核心功能完整性
2. 边界与错误处理
3. 后端 API 全覆盖
4. D3 图谱交互
5. 可能需要的功能
6. 长期稳定性
"""
import os
import sys
import json
import time
import hashlib
import subprocess
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright, Page, expect

ROOT = Path(r"D:\AI\Claude code workspace\Atest")
OUT = ROOT / "playwright_runs" / "comprehensive"
OUT.mkdir(parents=True, exist_ok=True)

URL = "http://127.0.0.1:5173/"
BACKEND = "http://127.0.0.1:8000"


def h(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()[:10]


# ============ 维度 3: 后端 API 测试 ============
def test_backend_api() -> dict:
    """3 维度：后端 API 全覆盖"""
    results = {"dim": 3, "tests": []}

    def post(path, body, raw=False):
        req = urllib.request.Request(
            f"{BACKEND}{path}",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    # 健康检查
    try:
        with urllib.request.urlopen(f"{BACKEND}/health") as r:
            data = json.loads(r.read())
            ok = r.status == 200 and data.get("status") == "ok"
            results["tests"].append({
                "name": "GET /health", "ok": ok,
                "detail": f"status={r.status}, body={data}"
            })
    except Exception as e:
        results["tests"].append({"name": "GET /health", "ok": False, "detail": str(e)})

    # 正常查询
    for q in ["transformer attention", "code generation", "RAG"]:
        code, body = post("/search", {"query": q, "max_iterations": 1, "budget": 0.5})
        try:
            d = json.loads(body)
            ok = code == 200 and d.get("status") == "done" and len(d.get("ranked_papers", [])) > 0
            detail = f"papers={len(d.get('ranked_papers', []))}, nodes={len(d.get('citation_graph', {}).get('nodes', []))}, cost=${d.get('total_cost_usd', 0):.4f}, t={d.get('elapsed_seconds')}s"
        except Exception:
            ok = False
            detail = f"status={code}"
        results["tests"].append({"name": f"POST /search query='{q}'", "ok": ok, "detail": detail})

    # 错误处理
    cases = [
        ("empty query", {"query": "", "max_iterations": 1, "budget": 0.5}, 422),  # pydantic min_length=1
        ("whitespace only", {"query": "   ", "max_iterations": 1, "budget": 0.5}, 400),  # 业务校验: 400
        ("budget=0", {"query": "test", "max_iterations": 1, "budget": 0}, 422),  # pydantic ge=0.1
        ("budget=20.5", {"query": "test", "max_iterations": 1, "budget": 20.5}, 422),  # 超出 max=20
        ("max_iter=0", {"query": "test", "max_iterations": 0, "budget": 0.5}, 422),
        ("max_iter=6", {"query": "test", "max_iterations": 6, "budget": 0.5}, 422),
        ("super long query", {"query": "x" * 3000, "max_iterations": 1, "budget": 0.5}, 422),  # max 2000
        ("special chars", {"query": "<script>alert(1)</script>", "max_iterations": 1, "budget": 0.5}, 200),  # mock 命中
        ("emoji query", {"query": "🤖🚀💡", "max_iterations": 1, "budget": 0.5}, 200),
        ("chinese", {"query": "大语言模型 综述", "max_iterations": 1, "budget": 0.5}, 200),
    ]
    for name, body, expected_code in cases:
        code, resp = post("/search", body)
        ok = code == expected_code
        try:
            d = json.loads(resp)
            detail = f"expected={expected_code}, got={code}, papers={len(d.get('ranked_papers', []))}"
        except Exception:
            detail = f"expected={expected_code}, got={code}"
        results["tests"].append({"name": f"validation: {name}", "ok": ok, "detail": detail})

    return results


# ============ 维度 1 & 2 & 4: 浏览器端 ============
def test_browser_full() -> list[dict]:
    """1, 2, 4 维度：浏览器端综合测试"""
    out = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(URL, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 维度 1.1: 初始状态截图
        s = OUT / "01_initial.png"
        page.screenshot(path=str(s))
        out.append({"name": "01_initial_state", "file": str(s), "hash": h(s), "size": s.stat().st_size})

        # 维度 1.2: 5 个不同建议按钮 → 5 张不同截图
        for i in range(5):
            page.goto(URL, wait_until="networkidle")
            page.wait_for_timeout(500)
            btns = page.locator("div.flex.flex-wrap > button")
            btns.nth(i).click()
            page.wait_for_timeout(200)
            page.locator("button.flex-1.bg-brand-600").click()
            try:
                page.wait_for_function(
                    "() => document.body.innerText.includes('done') || document.body.innerText.includes('Done')",
                    timeout=15000
                )
            except Exception:
                pass
            page.wait_for_timeout(500)
            s = OUT / f"01_suggestion_{i+1}.png"
            page.screenshot(path=str(s))
            # 提取状态 - 用 header 限定
            header = page.locator("header")
            status_text = header.inner_text().replace("\n", " | ")
            out.append({
                "name": f"01_suggestion_{i+1}",
                "file": str(s), "hash": h(s), "size": s.stat().st_size,
                "status_bar": status_text,
            })

        # 维度 1.3: 自定义输入
        page.goto(URL, wait_until="networkidle")
        page.wait_for_timeout(500)
        page.locator("textarea").click()
        page.locator("textarea").fill("graph neural network for drug discovery")
        page.locator("button.flex-1.bg-brand-600").click()
        try:
            page.wait_for_function("() => document.body.innerText.includes('done')", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(500)
        s = OUT / "01_custom_typed.png"
        page.screenshot(path=str(s))
        out.append({"name": "01_custom_typed_query", "file": str(s), "hash": h(s), "size": s.stat().st_size})

        # 维度 1.4: 清空按钮
        page.locator("button.px-3.py-2").click()  # 清空
        page.wait_for_timeout(300)
        ta_value = page.locator("textarea").input_value()
        s = OUT / "01_after_clear.png"
        page.screenshot(path=str(s))
        out.append({"name": "01_after_clear", "file": str(s), "hash": h(s), "size": s.stat().st_size,
                    "textarea_value": ta_value, "ok": ta_value == ""})

        # 维度 2: 边界测试
        edge_cases = [
            ("02_empty_disabled", "only_empty", ""),
            ("02_whitespace", "whitespace", "   "),
            ("02_long_query", "long", "x" * 500),
            ("02_special_chars", "special", "<>\"'&`!@#$%^*()"),
            ("02_chinese_long", "chinese", "深度学习 自然语言处理 综述 预训练模型"),
        ]
        for name, _, text in edge_cases:
            page.goto(URL, wait_until="networkidle")
            page.wait_for_timeout(500)
            if text:
                page.locator("textarea").click()
                page.locator("textarea").fill(text)
                page.wait_for_timeout(200)
            # 查搜索按钮是否 disabled
            is_disabled = page.locator("button.flex-1.bg-brand-600").is_disabled()
            s = OUT / f"{name}.png"
            page.screenshot(path=str(s))
            out.append({
                "name": name, "file": str(s), "hash": h(s), "size": s.stat().st_size,
                "input": text, "search_disabled": is_disabled,
            })

        # 维度 4: D3 图谱交互
        page.goto(URL, wait_until="networkidle")
        page.wait_for_timeout(500)
        btns = page.locator("div.flex.flex-wrap > button")
        btns.nth(0).click()
        page.locator("button.flex-1.bg-brand-600").click()
        try:
            page.wait_for_function("() => document.body.innerText.includes('done')", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(1500)  # 等 D3 稳定

        # 数 SVG 节点数
        node_count = page.locator("svg circle").count()
        link_count = page.locator("svg line").count()
        s = OUT / "04_d3_graph.png"
        page.screenshot(path=str(s))
        out.append({
            "name": "04_d3_graph_render", "file": str(s), "hash": h(s), "size": s.stat().st_size,
            "svg_circles": node_count, "svg_lines": link_count,
        })

        # 维度 5: 可能需要的功能 - 检查是否有 export/copy/主题切换
        feature_check = {
            "copy_button": page.locator("button:has-text('Copy')").count(),
            "download_button": page.locator("button:has-text('Download')").count(),
            "theme_toggle": page.locator("[class*='theme'], [class*='dark']").count(),
            "loading_visible": page.locator("[class*='animate-spin']").count(),
        }
        out.append({"name": "05_feature_check", **feature_check})

        # 维度 6: 稳定性 - 5 次连续查询
        stability_results = []
        for i in range(5):
            t0 = time.time()
            page.goto(URL, wait_until="networkidle")
            page.wait_for_timeout(300)
            page.locator("div.flex.flex-wrap > button").nth(i % 5).click()
            page.locator("button.flex-1.bg-brand-600").click()
            try:
                page.wait_for_function("() => document.body.innerText.includes('done')", timeout=15000)
            except Exception:
                pass
            elapsed = time.time() - t0
            # 提取 papers count
            paper_text = page.locator("div.flex-1.overflow-y-auto > div.px-4").first.inner_text()
            stability_results.append({"i": i+1, "elapsed": round(elapsed, 2)})
        s = OUT / "06_stability_5x.png"
        page.screenshot(path=str(s))
        out.append({"name": "06_stability_5_consecutive", "file": str(s), "hash": h(s), "size": s.stat().st_size,
                    "runs": stability_results})

        browser.close()
    return out


def main():
    print("=== 维度 3: 后端 API 测试 ===")
    api_results = test_backend_api()
    for t in api_results["tests"]:
        status = "✓" if t["ok"] else "✗"
        print(f"  {status} {t['name']}: {t['detail']}")

    print("\n=== 维度 1/2/4: 浏览器端测试 ===")
    browser_results = test_browser_full()
    for r in browser_results:
        print(f"  {r['name']}: hash={r.get('hash','?')} size={r.get('size',0)}b", end="")
        for k in ("token", "papers", "iterations", "input", "search_disabled",
                  "svg_circles", "svg_lines", "textarea_value"):
            if k in r:
                print(f" {k}={r[k]}", end="")
        print()

    # 报告
    with open(OUT / "summary.json", "w", encoding="utf-8") as f:
        json.dump({"api": api_results, "browser": browser_results},
                  f, ensure_ascii=False, indent=2, default=str)
    print(f"\n=== 汇总写入 {OUT / 'summary.json'} ===")

    # 检查 pass rate
    api_passed = sum(1 for t in api_results["tests"] if t["ok"])
    api_total = len(api_results["tests"])
    print(f"\nAPI pass rate: {api_passed}/{api_total}")


if __name__ == "__main__":
    main()
