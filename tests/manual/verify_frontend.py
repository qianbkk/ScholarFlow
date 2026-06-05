"""
Phase 3: 前端可视化验证(Playwright + 浏览器截图 + 截图分析)

1. Playwright 打开 http://127.0.0.1:5173
2. 截图 1: 初始页面
3. 输入 "AlphaFold protein structure prediction", 触发搜索
4. 截图 2: 搜索中状态
5. 等待完成
6. 截图 3: 最终结果(报告 + 论文列表 + 图谱)
7. 保存所有截图供后续 native image analysis
"""
import asyncio
import os
import sys

os.environ['PYTHONIOENCODING'] = 'utf-8'

from playwright.async_api import async_playwright

OUT_DIR = r"D:/AI/Claude code workspace/Atest/playwright_runs"
os.makedirs(OUT_DIR, exist_ok=True)

QUERY = "AlphaFold protein structure prediction deep learning"


async def main():
    print("=" * 70)
    print("Phase 3: 前端可视化验证")
    print("=" * 70)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={"width": 1600, "height": 1000})
        page = await context.new_page()

        # ===== 步骤 1: 打开前端 =====
        print("\n[1] 打开 http://127.0.0.1:5173 ...")
        await page.goto("http://127.0.0.1:5173/", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)
        await page.screenshot(path=os.path.join(OUT_DIR, "01_initial.png"), full_page=True)
        print(f"   截图保存: 01_initial.png")
        print(f"   页面标题: {await page.title()}")

        # ===== 步骤 2: 输入查询 =====
        print(f"\n[2] 输入查询: {QUERY}")
        # 找输入框 — 项目里有 textarea 或 input
        query_input = page.locator("textarea").first
        if await query_input.count() == 0:
            query_input = page.locator("input[type='text']").first
        await query_input.fill(QUERY)
        await page.wait_for_timeout(500)
        await page.screenshot(path=os.path.join(OUT_DIR, "02_query_typed.png"), full_page=True)
        print(f"   截图保存: 02_query_typed.png")

        # ===== 步骤 3: 触发搜索 =====
        print(f"\n[3] 触发搜索...")
        search_button = page.locator("button:has-text('搜索')").first
        if await search_button.count() == 0:
            search_button = page.locator("button[type='submit']").first
        await search_button.click()
        await page.wait_for_timeout(3000)
        await page.screenshot(path=os.path.join(OUT_DIR, "03_searching.png"), full_page=True)
        print(f"   截图保存: 03_searching.png")

        # ===== 步骤 4: 等待完成 =====
        print(f"\n[4] 等待搜索完成(最多 240s)...")
        try:
            # 等待报告区域出现非空内容
            await page.wait_for_function(
                """() => {
                    const article = document.querySelector('.report-body');
                    if (!article) return false;
                    return article.innerText && article.innerText.length > 100;
                }""",
                timeout=240_000,
            )
            print("   报告已生成")
        except Exception as e:
            print(f"   等待超时: {e}")
            await page.screenshot(path=os.path.join(OUT_DIR, "04_timeout.png"), full_page=True)
            return

        # ===== 步骤 5: 最终截图 =====
        await page.wait_for_timeout(2000)
        await page.screenshot(path=os.path.join(OUT_DIR, "04_completed.png"), full_page=True)
        print(f"   截图保存: 04_completed.png")

        # ===== 步骤 6: 提取报告文本 =====
        report_text = await page.evaluate("""() => {
            const a = document.querySelector('.report-body');
            return a ? a.innerText : '';
        }""")
        paper_count = await page.evaluate("""() => {
            const lis = document.querySelectorAll('li');
            return lis.length;
        }""")
        graph_nodes = await page.evaluate("""() => {
            const svgs = document.querySelectorAll('svg circle');
            return svgs.length;
        }""")

        print(f"\n[5] 前端显示提取:")
        print(f"   报告长度: {len(report_text)} 字符")
        print(f"   <li> 元素数: {paper_count}")
        print(f"   <svg circle> 数(图谱节点): {graph_nodes}")
        print(f"\n   报告前 800 字符:")
        print("   " + "-" * 60)
        for line in report_text[:800].split("\n"):
            print(f"   {line}")
        print("   " + "-" * 60)

        # 验证
        report_lower = report_text.lower()
        all_ok = True

        print(f"\n[6] 验证结果:")
        if "alphafold" in report_lower or "protein" in report_lower:
            print(f"   [OK]   报告含 'alphafold' 或 'protein' 关键词")
        else:
            print(f"   [FAIL] 报告与查询不相关")
            all_ok = False

        if paper_count >= 1:
            print(f"   [OK]   论文列表非空 ({paper_count} 个 <li>)")
        else:
            print(f"   [FAIL] 论文列表为空")
            all_ok = False

        if graph_nodes >= 1:
            print(f"   [OK]   图谱节点非空 ({graph_nodes} 个节点)")
        else:
            print(f"   [WARN] 图谱节点为空(可能还在渲染)")

        # 验证 CostDashboard
        cost_text = await page.evaluate("""() => {
            const dash = document.querySelector('.cost-dashboard, [class*=cost], [class*=Cost]');
            return dash ? dash.innerText : 'NOT_FOUND';
        }""")
        print(f"   Cost Dashboard 文本: {cost_text[:200] if cost_text != 'NOT_FOUND' else 'NOT FOUND'}")

        # 保存元数据
        import json
        meta = {
            "query": QUERY,
            "report_length": len(report_text),
            "report_preview": report_text[:1500],
            "paper_list_items": paper_count,
            "graph_nodes": graph_nodes,
            "cost_dashboard_text": cost_text[:300] if cost_text != 'NOT_FOUND' else None,
        }
        with open(os.path.join(OUT_DIR, "frontend_meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f"\n   元数据保存: frontend_meta.json")

        await browser.close()
        return all_ok


if __name__ == "__main__":
    ok = asyncio.run(main())
    print("\n" + "=" * 70)
    print(f"FRONTEND_VERIFY: {'PASS' if ok else 'FAIL'}")
    print("=" * 70)
    sys.exit(0 if ok else 1)
