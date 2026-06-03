"""
ScholarFlow E2E 视觉验证脚本
============================
用 Playwright 驱动浏览器，每步用 React 友好的方式触发，
并对每张截图用 Read 工具做视觉识别校验。
"""
import os
import sys
import time
import json
import hashlib
from pathlib import Path
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:5173/"
OUT_DIR = Path(r"D:\AI\Claude code workspace\Atest\playwright_runs")
OUT_DIR.mkdir(exist_ok=True)


def hash_image(p: Path) -> str:
    """快速判断图片是否相同：MD5 头 8 字节"""
    return hashlib.md5(p.read_bytes()).hexdigest()[:8]


def main():
    queries = [
        ("initial", None, None),                              # 初始状态
        ("q1_transformer", "button-nth:1", None),            # 第一个建议
        ("q2_chinese", "button-nth:2", None),                # 第二个建议（中文）
        ("q3_multiagent", "button-nth:3", None),             # 第三个建议
        ("q4_rag", "button-nth:4", None),                    # 第四个建议
        ("q5_typed", None, "large language model reasoning"),  # 手动输入
    ]

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        for name, button_nth, typed_text in queries:
            step = {"name": name, "events": []}
            if name == "initial":
                page.goto(URL, wait_until="networkidle")
                page.wait_for_timeout(1000)
            else:
                # 如果是输入文本：先 clear 再 type
                if typed_text:
                    page.locator("textarea").click()
                    page.wait_for_timeout(200)
                    page.locator("textarea").fill("")
                    page.wait_for_timeout(100)
                    page.locator("textarea").type(typed_text, delay=10)
                    page.wait_for_timeout(300)
                    step["events"].append(f"typed: {typed_text}")
                elif button_nth:
                    idx = int(button_nth.split(":")[1]) - 1
                    # 用 nth(index) 直接选第 N 个建议按钮
                    btns = page.locator("div.flex.flex-wrap > button")
                    count = btns.count()
                    if idx < count:
                        btns.nth(idx).click()
                        page.wait_for_timeout(300)
                        step["events"].append(f"clicked suggestion #{idx+1}")

                # 点搜索
                page.locator("button.flex-1.bg-brand-600").click()
                step["events"].append("clicked search button")

                # 等待结果（最多 10s）
                try:
                    page.wait_for_function(
                        "document.body.innerText.includes('done') || document.body.innerText.includes('Done')",
                        timeout=10000
                    )
                except Exception as e:
                    step["events"].append(f"timeout waiting for done: {e}")
                page.wait_for_timeout(800)

            # 截图
            screenshot_path = OUT_DIR / f"{name}.png"
            page.screenshot(path=str(screenshot_path), full_page=False)
            h = hash_image(screenshot_path)
            size = screenshot_path.stat().st_size

            # 收集页面关键文本
            body_text = page.locator("body").inner_text()[:2000]
            step["screenshot"] = str(screenshot_path)
            step["hash"] = h
            step["size"] = size
            step["body_preview"] = body_text[:500]
            results.append(step)
            print(f"[{name}] hash={h} size={size} | events={step['events']}")

        browser.close()

    # 检查：每张截图必须不同
    print("\n=== 截图差异性校验 ===")
    hashes = [r["hash"] for r in results]
    unique = len(set(hashes))
    print(f"总截图: {len(results)} 张, 唯一 hash: {unique} 个")
    if unique == len(results):
        print("[PASS] 所有截图都不相同 (每步 UI 状态确实在变化)")
    else:
        print("[WARN] 有重复截图！")
        for r in results:
            print(f"  {r['name']:20s} hash={r['hash']} size={r['size']}")

    # 输出 JSON 报告
    with open(OUT_DIR / "results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    return results


if __name__ == "__main__":
    main()
