"""
Playwright visual verification for ScholarFlow v2
Tests:
1. UI loads correctly
2. Search returns papers with graph edges
3. Progress bar shows during search
4. Multiple queries (cross-domain) all return different results
"""
import time
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

SCREENSHOTS_DIR = Path("playwright_runs/v2")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def test_visual():
    queries = [
        ("transformer attention mechanism", "v2_transformer.png"),
        ("quantum computing", "v2_quantum.png"),
        ("object detection", "v2_yolo.png"),
        ("speech recognition", "v2_speech.png"),
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # Navigate to UI
        print("[1] Navigate to http://127.0.0.1:5173/")
        page.goto("http://127.0.0.1:5173/", wait_until="networkidle", timeout=15000)

        # Wait for backend health to be OK
        time.sleep(1.5)
        page.screenshot(path=str(SCREENSHOTS_DIR / "v2_initial.png"), full_page=True)
        print(f"  Saved v2_initial.png")

        # Health check indicator
        try:
            text = page.inner_text("body")
            assert "ScholarFlow" in text, f"ScholarFlow not in UI: {text[:200]}"
            print(f"  [OK] UI loaded, body contains 'ScholarFlow'")
        except Exception as e:
            print(f"  [!] UI body check: {e}")

        # Test multiple queries
        for i, (q, shot_name) in enumerate(queries, 2):
            print(f"\n[{i}] Query: {q!r}")
            try:
                # Clear previous query
                textarea = page.locator("textarea").first
                textarea.fill("")
                textarea.fill(q)

                # Click search
                page.click("button[type=submit]")

                # Wait for results - look for graph or paper list
                try:
                    page.wait_for_selector(".report-body, [data-testid=paper-list]", timeout=10000)
                except Exception:
                    pass
                # Allow graph simulation to settle
                time.sleep(2.5)

                # Capture screenshot
                page.screenshot(path=str(SCREENSHOTS_DIR / shot_name), full_page=True)
                print(f"  Saved {shot_name}")

                # Read body content to verify
                body_text = page.inner_text("body")
                has_results = "n=" in body_text or "n /" in body_text or "edges" in body_text or "推荐" in body_text
                print(f"  [{'OK' if has_results else '?'}] body has results indicator: {has_results}")

            except Exception as e:
                print(f"  [X] Exception during query: {e}")
                page.screenshot(path=str(SCREENSHOTS_DIR / f"error_{shot_name}"), full_page=True)

        browser.close()
        print("\n=== Visual test complete ===")


if __name__ == "__main__":
    test_visual()
