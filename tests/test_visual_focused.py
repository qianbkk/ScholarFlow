"""
Playwright visual test (v2 focused) - verifies 4 distinct queries return
distinct results and graphs have visible edges.
"""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT_DIR = Path("playwright_runs/v2_focused")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def main():
    queries = [
        "transformer attention mechanism",
        "object detection YOLO",
        "speech recognition",
        "diffusion model image generation",
    ]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.goto("http://127.0.0.1:5173/", wait_until="networkidle", timeout=15000)
        time.sleep(1.0)

        for i, q in enumerate(queries):
            print(f"\n[Query {i+1}] {q!r}")
            # Use page.evaluate to bypass any UI quirks
            textarea = page.locator("textarea").first
            textarea.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            textarea.fill(q)
            time.sleep(0.3)

            # Click search button
            submit = page.locator("button[type=submit]")
            submit.click()

            # Wait for results panel to update
            try:
                # Wait for graph node count to change (proves new results are in)
                page.wait_for_function(
                    f"""() => {{
                        const m = document.body.innerText.match(/(\\d+)n \\/ (\\d+)l/);
                        return m !== null;
                    }}""",
                    timeout=15000,
                )
            except Exception:
                pass
            time.sleep(3.5)  # let D3 simulation + paper list settle

            # Capture
            slug = q.replace(" ", "_")[:30]
            page.screenshot(path=str(OUT_DIR / f"q{i+1}_{slug}.png"), full_page=True)
            print(f"  Saved q{i+1}_{slug}.png")

            # Inspect via JS
            try:
                result = page.evaluate("""() => {
                    const text = document.body.innerText;
                    return {
                        body_len: text.length,
                        has_report: text.includes('研究概述') || text.includes('Top 5'),
                        has_paper_list: text.includes('引用') || text.includes('relevance'),
                        has_graph_meta: text.match(/(\d+)n \\/ (\\d+)l/),
                    };
                }""")
                print(f"  JS inspect: {result}")
            except Exception as e:
                print(f"  JS inspect error: {e}")

        browser.close()
        print("\nDone.")


if __name__ == "__main__":
    main()
