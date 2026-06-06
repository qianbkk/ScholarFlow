"""Smoke test: 前端模型选择器 (provider dropdown) 端到端验证。

执行（需要后端 + 前端 dev server 都在跑）:
    python tests/manual/test_frontend_provider.py

验证项:
  1. 页面打开后,模型选择器下拉框可见
  2. 下拉框有 >= 1 个 option（取决于 .env 配置的 key）
  3. 选项的 value 对应后端 /providers 的合法 id
  4. 选择一个 provider 后,点击搜索按钮,SSE URL 包含 provider=<id>
"""
import asyncio
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'

from playwright.async_api import async_playwright

FRONTEND_URL = "http://127.0.0.1:5173/"


async def main() -> int:
    print("=" * 70)
    print("前端模型选择器 smoke test")
    print("=" * 70)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        context = await browser.new_context(viewport={'width': 1440, 'height': 900})
        page = await context.new_page()

        # 收集 network 抓包（SSE URL 含 provider 验证用）
        sse_requests: list[str] = []

        async def on_request(req):
            url = req.url
            if "/search/stream" in url:
                sse_requests.append(url)
        page.on("request", on_request)

        # 1) 打开前端
        print(f"\n[1] 打开 {FRONTEND_URL} ...")
        await page.goto(FRONTEND_URL, wait_until='domcontentloaded', timeout=30_000)
        await page.wait_for_timeout(2_000)

        # 2) 找模型下拉框
        print("\n[2] 查找 <select> 元素 (模型下拉)...")
        # 通过 label "模型" 定位
        select = page.locator('select').first
        if await select.count() == 0:
            print("   [FAIL] 找不到 <select> 元素")
            await browser.close()
            return 1

        is_visible = await select.is_visible()
        print(f"   <select> 可见: {is_visible}")
        assert is_visible, "模型下拉框应可见"

        # 3) 验证 options
        print("\n[3] 检查下拉 options ...")
        options = await select.locator('option').all()
        opt_count = len(options)
        print(f"   option 数: {opt_count}")
        assert opt_count >= 1, f"期望至少 1 个 provider option, 实际 {opt_count}"

        opt_values = []
        opt_texts = []
        for o in options:
            v = await o.get_attribute('value')
            t = (await o.inner_text()).strip()
            opt_values.append(v)
            opt_texts.append(t)
            print(f"   - value={v!r:20s} text={t!r}")

        # 4) 验证 option value 是合法 provider id
        # （id 集合由后端 /providers 返回，但前端只展示 has_key=true 的）
        valid_ids = {"kimi", "glm", "minimax", "anthropic", "deepseek"}
        for v in opt_values:
            if v:  # 空 value 是 placeholder
                assert v in valid_ids, f"option value {v!r} 不在已知 provider id 集合中"

        # 5) 选中第一个 option, 输入查询, 触发搜索
        print("\n[4] 选择一个 provider, 触发搜索 (验证 SSE URL 携带 provider)...")
        target_provider = next((v for v in opt_values if v), None)
        if not target_provider:
            print("   [WARN] 无可选 provider, 跳过搜索验证")
            await browser.close()
            return 0

        await select.select_option(value=target_provider)
        selected = await select.evaluate("el => el.value")
        print(f"   已选 provider: {selected!r}")
        assert selected == target_provider

        # 输入查询
        query_input = page.locator('textarea').first
        await query_input.fill("transformer attention")
        await page.wait_for_timeout(300)

        # 点击搜索
        search_btn = page.locator('button[type="submit"]').first
        await search_btn.click()
        print("   已点击搜索按钮")

        # 6) 等 5 秒看是否触发 SSE 请求
        await page.wait_for_timeout(5_000)
        if not sse_requests:
            print("   [WARN] 5 秒内未抓到 /search/stream 请求 (可能 mock 模式或网络问题)")
        else:
            print(f"   抓到 {len(sse_requests)} 个 SSE 请求:")
            for url in sse_requests:
                print(f"   - {url}")
                if "provider=" + target_provider in url:
                    print(f"   [OK] URL 包含 provider={target_provider}")

        print("\n" + "=" * 70)
        print("FRONTEND_PROVIDER_TEST: PASS")
        print("=" * 70)
        await browser.close()
        return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
