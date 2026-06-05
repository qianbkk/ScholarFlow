"""
tests/manual/test_frontend_race.py
=================================

Manual Playwright-based test for the H5 + H6 audit findings on
`frontend/src/hooks/useSearch.ts`:

  - H5: EventSource cross-close race — two rapid searches used to cause
        search 1's late `done` event to close search 2's connection.
  - H6: `reset()` did not clear `loading=true`, leaving the submit
        button disabled after a mid-flight reset.

This test exercises the actual React hook via the real frontend dev
server. It does NOT mock the backend; it just drives the UI and
inspects the resulting state.

Pre-reqs (out of band, before running this test):
  - Backend running:  `python -m backend.main`   (or `uvicorn backend.main:app`)
  - Frontend running: `cd frontend && npm run dev`  (Vite on :5173)

Usage:
  python tests/manual/test_frontend_race.py
  (exit 0 = pass, non-zero = fail)

The test is manual (under `tests/manual/`) because it requires a live
frontend + backend; CI does not run it. The unit-level invariants
(closure capture, generation counter) are still enforced in the
static TypeScript build (`npm run build`).
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# UTF-8 on Windows for Chinese text in Playwright logs
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUT_DIR = PROJECT_ROOT / "playwright_runs" / "race_test"
OUT_DIR.mkdir(parents=True, exist_ok=True)

FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://127.0.0.1:5173/")


# ---------------------------------------------------------------------------
# Test 1: H6 — reset() clears `loading=true` so submit button is re-enabled
# ---------------------------------------------------------------------------

async def test_h6_reset_clears_loading(page) -> dict:
    """Click reset mid-search and assert submit button is re-enabled."""
    print("[H6] test_reset_clears_loading: navigating to", FRONTEND_URL)
    await page.goto(FRONTEND_URL, wait_until="domcontentloaded", timeout=30_000)
    await page.wait_for_timeout(1500)

    # Find the search input + submit button
    input_loc = page.locator(
        'input[type="text"], textarea, [contenteditable="true"]'
    ).first
    await input_loc.wait_for(timeout=10_000)
    await input_loc.fill("AlphaFold protein structure prediction")

    submit_btn = page.locator(
        'button:has-text("搜索"), button:has-text("Search"), '
        'button:has-text("开始"), button[type="submit"]'
    ).first
    await submit_btn.wait_for(timeout=5_000)

    # Start a search
    await submit_btn.click()
    print("[H6] search started, waiting briefly for loading=true to take effect...")
    await page.wait_for_timeout(500)

    # Take a screenshot of the loading state
    await page.screenshot(path=str(OUT_DIR / "h6_01_searching.png"))

    # Click reset / clear
    reset_btn = page.locator(
        'button:has-text("清空"), button:has-text("重置"), '
        'button:has-text("Reset"), button:has-text("Clear")'
    ).first
    reset_clicked = False
    try:
        await reset_btn.click(timeout=3_000)
        reset_clicked = True
    except Exception as e:
        print(f"[H6] WARN: could not click reset button ({e}); falling back to "
              "programmatic check on a second short search.")

    # Allow state to settle
    await page.wait_for_timeout(500)
    await page.screenshot(path=str(OUT_DIR / "h6_02_after_reset.png"))

    # Verify submit button is enabled again (H6 invariant)
    is_disabled = await submit_btn.is_disabled()
    print(f"[H6] after reset, submit button disabled = {is_disabled}")
    assert not is_disabled, (
        "H6 FAIL: submit button is still disabled after reset — "
        "`setLoading(false)` is missing in reset()"
    )

    # Verify a NEW search can be started (no stuck loading=true)
    await input_loc.fill("transformer architecture")
    await submit_btn.click(timeout=5_000)
    await page.wait_for_timeout(500)
    await page.screenshot(path=str(OUT_DIR / "h6_03_second_search_started.png"))
    is_disabled_2 = await submit_btn.is_disabled()
    assert is_disabled_2, (
        "H6 FAIL: submit button is NOT disabled after starting a new search — "
        "loading was not set to true on the new search"
    )

    return {
        "test": "H6 reset() clears loading",
        "reset_clicked": reset_clicked,
        "post_reset_disabled": is_disabled,
        "second_search_disabled": is_disabled_2,
    }


# ---------------------------------------------------------------------------
# Test 2: H5 — two rapid searches: search 2 is NOT closed by search 1's events
# ---------------------------------------------------------------------------

async def test_h5_rapid_search_survives(page) -> dict:
    """Fire two searches back-to-back and assert search 2 still completes."""
    print("[H5] test_rapid_search_survives: navigating to", FRONTEND_URL)
    await page.goto(FRONTEND_URL, wait_until="domcontentloaded", timeout=30_000)
    await page.wait_for_timeout(1500)

    input_loc = page.locator(
        'input[type="text"], textarea, [contenteditable="true"]'
    ).first
    await input_loc.wait_for(timeout=10_000)

    submit_btn = page.locator(
        'button:has-text("搜索"), button:has-text("Search"), '
        'button:has-text("开始"), button[type="submit"]'
    ).first
    await submit_btn.wait_for(timeout=5_000)

    # ---- Search 1 ----
    print("[H5] firing search 1: 'transformer attention is all you need'")
    await input_loc.fill("transformer attention is all you need")
    await submit_btn.click()
    # Brief wait so SSE has time to send at least one event
    await page.wait_for_timeout(2_000)
    await page.screenshot(path=str(OUT_DIR / "h5_01_search1_running.png"))

    # ---- Search 2 (rapid, before search 1's done event) ----
    print("[H5] firing search 2 immediately: 'graph neural network'")
    await input_loc.fill("graph neural network")
    await submit_btn.click()
    await page.wait_for_timeout(2_000)
    await page.screenshot(path=str(OUT_DIR / "h5_02_search2_running.png"))

    # ---- Wait for search 2 to actually complete ----
    # Without H5 fix, search 2's EventSource gets closed by search 1's
    # late `done` event via the dynamic `esRef.current` reference, so
    # the page never shows the report. With the fix, search 2's
    # `myEs` closure guard prevents this.
    print("[H5] waiting for search 2 to complete (up to 240s)...")
    t0 = time.time()
    completed = False
    try:
        await page.wait_for_function(
            '''() => {
                const text = document.body.innerText || "";
                return text.includes("研究概述")
                    || text.includes("核心论文")
                    || text.includes("Top");
            }''',
            timeout=240_000,
        )
        completed = True
    except Exception as e:
        print(f"[H5] search 2 did not complete in time: {e}")
    elapsed = time.time() - t0
    print(f"[H5] search 2 completed={completed} elapsed={elapsed:.1f}s")
    await page.screenshot(path=str(OUT_DIR / "h5_03_search2_done.png"), full_page=True)

    # Inspect body text: must NOT contain the search 1 query anymore
    body_text = (await page.locator("body").inner_text()).lower()
    stuck_on_search1 = "transformer attention is all you need" in body_text and "graph neural network" not in body_text

    assert completed and not stuck_on_search1, (
        "H5 FAIL: search 2 was not visible after a rapid second search. "
        "The cross-close race in useSearch.ts is still present (the closure "
        "should capture `myEs` from the local const, not read `esRef.current` "
        "dynamically in the cleanup function)."
    )

    return {
        "test": "H5 two rapid searches",
        "search2_completed": completed,
        "elapsed": round(elapsed, 1),
        "stuck_on_search1": stuck_on_search1,
    }


# ---------------------------------------------------------------------------
# Main: run both tests with one browser
# ---------------------------------------------------------------------------

async def main() -> int:
    from playwright.async_api import async_playwright

    results: list[dict] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await context.new_page()

        # Set a long default timeout so SSE wait_for_function does not time out
        page.set_default_timeout(30_000)

        for test_fn, label in [
            (test_h6_reset_clears_loading, "H6"),
            (test_h5_rapid_search_survives, "H5"),
        ]:
            print("=" * 70)
            print(f"Running {label} test...")
            print("=" * 70)
            try:
                result = await test_fn(page)
                result["status"] = "PASS"
                results.append(result)
            except AssertionError as e:
                print(f"  ASSERTION FAILED: {e}")
                results.append({"test": label, "status": "FAIL", "error": str(e)})
            except Exception as e:
                print(f"  EXCEPTION: {e}")
                results.append({"test": label, "status": "ERROR", "error": str(e)})

        await browser.close()

    # Persist meta
    meta = {
        "frontend_url": FRONTEND_URL,
        "out_dir": str(OUT_DIR),
        "results": results,
        "timestamp": time.time(),
    }
    meta_path = OUT_DIR / "meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"\nMeta saved: {meta_path}")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for r in results:
        status = r.get("status", "?")
        name = r.get("test", "?")
        print(f"  [{status}] {name}")
        if "error" in r:
            print(f"         {r['error']}")

    all_pass = all(r.get("status") == "PASS" for r in results)
    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
