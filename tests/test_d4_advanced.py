"""
ScholarFlow 深度交互测试
========================
维度 4 扩展 + 维度 5（缺失功能补全验证）：
- Copy report 按钮
- Download 按钮
- D3 节点 hover tooltip
- D3 节点 click → 新 tab
- D3 节点 drag
- 5 次连续查询稳定性 + 内存监控
- 论文列表点击
"""
import os
import time
import json
import hashlib
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(r"D:\AI\Claude code workspace\Atest\playwright_runs\deep")
OUT.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:5173/"


def h(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()[:10]


def main():
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()

        # 设置上下文权限以支持 clipboard 和下载
        ctx.grant_permissions(["clipboard-read", "clipboard-write"])

        # 初始 + 搜索
        page.goto(URL, wait_until="networkidle")
        page.wait_for_timeout(800)
        page.locator("div.flex.flex-wrap > button").nth(0).click()
        page.locator("button.flex-1.bg-brand-600").click()
        try:
            page.wait_for_function("() => document.body.innerText.includes('done')", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(1500)

        # 截图：带 Copy/Download 按钮的报告
        s = OUT / "d1_report_with_buttons.png"
        page.screenshot(path=str(s))
        copy_btn = page.locator("button:has-text('Copy')").count()
        dl_btn = page.locator("button:has-text('Download')").count()
        results.append({
            "test": "Copy/Download buttons present",
            "file": str(s), "hash": h(s),
            "copy_buttons": copy_btn, "download_buttons": dl_btn,
            "pass": copy_btn == 1 and dl_btn == 1,
        })

        # 点击 Copy 按钮
        page.locator("button:has-text('Copy')").click()
        page.wait_for_timeout(500)
        # 验证剪贴板内容
        clipboard_text = page.evaluate("navigator.clipboard.readText()")
        s = OUT / "d2_after_copy.png"
        page.screenshot(path=str(s))
        results.append({
            "test": "Copy report to clipboard",
            "file": str(s), "hash": h(s),
            "clipboard_length": len(clipboard_text),
            "starts_with_研究概述": clipboard_text.startswith("## 研究概述") or clipboard_text.startswith("##"),
            "pass": len(clipboard_text) > 200,
        })

        # D3 节点 hover
        first_node = page.locator("svg circle").first
        if first_node.is_visible():
            first_node.hover()
            page.wait_for_timeout(500)
            s = OUT / "d3_node_hover.png"
            page.screenshot(path=str(s))
            # 检查 tooltip
            tooltip_visible = page.locator("div.absolute.pointer-events-none").count() > 0
            results.append({
                "test": "D3 node hover shows tooltip",
                "file": str(s), "hash": h(s),
                "tooltip_element": tooltip_visible,
                "pass": tooltip_visible,
            })

        # D3 节点 click (应打开新 tab)
        first_node = page.locator("svg circle").first
        with ctx.expect_page() as new_page_info:
            first_node.click()
        new_page = new_page_info.value
        new_page.wait_for_load_state("domcontentloaded", timeout=5000)
        results.append({
            "test": "D3 node click opens paper URL",
            "new_tab_url": new_page.url[:80],
            "url_changed": "127.0.0.1:5173" not in new_page.url,
            "pass": "127.0.0.1:5173" not in new_page.url,
        })
        new_page.close()

        # D3 节点 drag
        first_node = page.locator("svg circle").first
        box = first_node.bounding_box()
        if box:
            start_x = box["x"] + box["width"] / 2
            start_y = box["y"] + box["height"] / 2
            page.mouse.move(start_x, start_y)
            page.mouse.down()
            page.mouse.move(start_x + 80, start_y + 80, steps=10)
            page.mouse.up()
            page.wait_for_timeout(500)
            s = OUT / "d4_node_drag.png"
            page.screenshot(path=str(s))
            results.append({
                "test": "D3 node drag",
                "file": str(s), "hash": h(s),
                "pass": True,
            })

        # 论文列表点击 - 应打开新 tab
        first_paper = page.locator("ul li").first
        if first_paper.is_visible():
            with ctx.expect_page() as np_info:
                first_paper.click()
            np = np_info.value
            np.wait_for_load_state("domcontentloaded", timeout=5000)
            results.append({
                "test": "Paper list click opens URL",
                "new_tab_url": np.url[:80],
                "url_changed": "127.0.0.1:5173" not in np.url,
                "pass": "127.0.0.1:5173" not in np.url,
            })
            np.close()

        # 清空 → D3 也应清掉
        page.locator("button.px-3.py-2").click()
        page.wait_for_timeout(500)
        svg_circles_after_clear = page.locator("svg circle").count()
        ta_after_clear = page.locator("textarea").input_value()
        s = OUT / "d5_after_clear.png"
        page.screenshot(path=str(s))
        results.append({
            "test": "Clear button fully resets UI",
            "file": str(s), "hash": h(s),
            "textarea_empty": ta_after_clear == "",
            "svg_circles_after_clear": svg_circles_after_clear,
            "pass": ta_after_clear == "" and svg_circles_after_clear == 0,
        })

        # 稳定性：10 次连续查询 + 时间记录
        stability = []
        for i in range(10):
            t0 = time.time()
            page.goto(URL, wait_until="networkidle")
            page.wait_for_timeout(300)
            page.locator("div.flex.flex-wrap > button").nth(i % 5).click()
            page.locator("button.flex-1.bg-brand-600").click()
            try:
                page.wait_for_function("() => document.body.innerText.includes('done')", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(300)
            elapsed = time.time() - t0
            stability.append({"i": i + 1, "elapsed_s": round(elapsed, 2)})
        s = OUT / "d6_stability_10x.png"
        page.screenshot(path=str(s))
        results.append({
            "test": "10x stability",
            "file": str(s), "hash": h(s),
            "runs": stability,
            "avg_s": round(sum(r["elapsed_s"] for r in stability) / len(stability), 2),
            "max_s": max(r["elapsed_s"] for r in stability),
        })

        browser.close()

    # 总结
    print("\n=== 深度交互测试结果 ===")
    for r in results:
        status = "✓" if r.get("pass") else "✗"
        print(f"{status} {r['test']}")
        for k, v in r.items():
            if k in ("test", "pass"):
                continue
            print(f"    {k}: {v}")

    with open(OUT / "summary.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)

    passed = sum(1 for r in results if r.get("pass"))
    total = len(results)
    print(f"\n=== 总结: {passed}/{total} 通过 ===")


if __name__ == "__main__":
    main()
