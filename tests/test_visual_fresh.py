"""
Visual test v3 - one fresh browser session per query for clean results.
"""
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT_DIR = Path("playwright_runs/v3_fresh")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def run_query(browser, query: str, idx: int):
    """Fresh page for each query to ensure clean state."""
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    page.goto("http://127.0.0.1:5173/", wait_until="networkidle", timeout=15000)
    time.sleep(1.0)

    # Type query and submit
    textarea = page.locator("textarea").first
    textarea.fill(query)
    time.sleep(0.3)
    page.locator("button[type=submit]").click()

    # Wait for results to be visible
    try:
        page.wait_for_selector(".report-body", timeout=15000)
    except Exception as e:
        print(f"  [!] wait_for_selector failed: {e}")
    time.sleep(3.0)  # let paper list + graph render

    # Inspect via JS - what are the top 3 paper titles in the left list?
    papers = page.evaluate("""() => {
        const items = document.querySelectorAll('aside ul li p');
        return Array.from(items).slice(0, 5).map(p => p.innerText);
    }""")

    print(f"[Q{idx}] {query!r}")
    for i, t in enumerate(papers, 1):
        print(f"    {i}. {t[:60]}")
    slug = query.replace(" ", "_")[:25]
    page.screenshot(path=str(OUT_DIR / f"q{idx}_{slug}.png"), full_page=True)
    print(f"    saved q{idx}_{slug}.png")
    context.close()


def main():
    queries = [
        "transformer attention mechanism",
        "object detection YOLO",
        "speech recognition",
        "diffusion model image generation",
        "graph neural network",
    ]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for i, q in enumerate(queries, 1):
            run_query(browser, q, i)
        browser.close()
        print("\nDone.")


if __name__ == "__main__":
    main()
