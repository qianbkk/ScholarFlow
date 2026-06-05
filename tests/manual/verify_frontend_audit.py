"""
犀利评论后: 前端浏览器控制 + Playwright 截图 + 视觉验证
============================================================

测试目标:
1. 打开 ScholarFlow 前端 (http://127.0.0.1:5173/)
2. 截图初始页面 (状态: ready)
3. 触发一次真实 LLM 搜索 (基于 C1 验证过的 query)
4. 等搜索完成, 截图结果页
5. 视觉验证: 报告内容、论文列表、图谱节点、成本 dashboard

执行: python tests/manual/verify_frontend_audit.py
"""
import asyncio
import base64
import json
import os
import sys
import time

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.path.insert(0, r'D:/AI/Claude code workspace/Atest')

OUT_DIR = "D:/AI/Claude code workspace/Atest/playwright_runs/audit"
os.makedirs(OUT_DIR, exist_ok=True)


async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        context = await browser.new_context(viewport={'width': 1440, 'height': 900})
        page = await context.new_page()

        # 1) 打开初始页
        print("[1] 打开 http://127.0.0.1:5173/ ...")
        await page.goto('http://127.0.0.1:5173/', wait_until='domcontentloaded', timeout=30000)
        await page.wait_for_timeout(2000)
        title = await page.title()
        print(f"    页面标题: {title}")
        await page.screenshot(path=f'{OUT_DIR}/c2_01_initial.png')
        print(f"    截图: c2_01_initial.png")

        # 2) 找到查询输入框并输入
        print("[2] 输入查询: AlphaFold protein structure prediction")
        input_elem = page.locator('input[type="text"], textarea, [contenteditable="true"]').first
        await input_elem.fill('AlphaFold protein structure prediction deep learning')
        await page.wait_for_timeout(500)
        await page.screenshot(path=f'{OUT_DIR}/c2_02_query_typed.png')
        print(f"    截图: c2_02_query_typed.png")

        # 3) 触发搜索
        print("[3] 触发搜索...")
        # 尝试找到搜索按钮 (text=搜索, Search, 查询)
        search_btn = page.locator('button:has-text("搜索"), button:has-text("Search"), button:has-text("开始"), button[type="submit"]').first
        try:
            await search_btn.click(timeout=5000)
        except Exception:
            # 兜底: 按 Enter
            await input_elem.press('Enter')
        print(f"    已点击搜索按钮/Enter")
        await page.wait_for_timeout(3000)
        await page.screenshot(path=f'{OUT_DIR}/c2_03_searching.png')
        print(f"    截图: c2_03_searching.png")

        # 4) 等搜索完成(最多 240s)
        print("[4] 等待搜索完成(最多 240s)...")
        t0 = time.time()
        completed = False
        report_text = ""
        try:
            # 等报告区域出现
            await page.wait_for_function(
                '''() => {
                    const text = document.body.innerText || "";
                    return text.includes("研究概述") || text.includes("Top") || text.includes("核心论文");
                }''',
                timeout=240_000,
            )
            completed = True
            elapsed = time.time() - t0
            print(f"    报告区域出现, 等待了 {elapsed:.1f}s")
        except Exception as e:
            print(f"    超时或失败: {e}")
            elapsed = time.time() - t0

        # 5) 截图完成页
        await page.screenshot(path=f'{OUT_DIR}/c2_04_completed.png', full_page=True)
        print(f"    截图: c2_04_completed.png (full_page)")

        # 6) 提取页面内容
        print("[5] 前端显示提取...")
        try:
            report_text = await page.locator('body').inner_text()
        except Exception as e:
            print(f"    提取文本失败: {e}")
            report_text = ""

        # 找报告区域
        try:
            report_section = await page.locator('[class*="report"], [class*="markdown"], pre, code').first.inner_text()
        except Exception:
            report_section = ""

        # 找论文列表
        try:
            li_count = await page.locator('li').count()
        except Exception:
            li_count = 0

        # 找图谱节点 (svg circle)
        try:
            svg_circle_count = await page.locator('svg circle').count()
        except Exception:
            svg_circle_count = 0

        # 7) 验证
        print(f"    报告长度: {len(report_text)} 字符")
        print(f"    <li> 元素数: {li_count}")
        print(f"    <svg circle> 数: {svg_circle_count}")

        report_lower = report_text.lower()
        checks = []
        if "alphafold" in report_lower or "protein" in report_lower:
            checks.append(("[OK]", "报告含 'alphafold' 或 'protein' 关键词"))
        else:
            checks.append(("[FAIL]", "报告未含查询关键词"))
        if li_count >= 10:
            checks.append(("[OK]", f"论文列表非空 ({li_count} 个 <li>)"))
        else:
            checks.append(("[FAIL]", f"论文列表 < 10 ({li_count})"))
        if svg_circle_count >= 5:
            checks.append(("[OK]", f"图谱节点非空 ({svg_circle_count} 节点)"))
        else:
            checks.append(("[WARN]", f"图谱节点较少 ({svg_circle_count})"))
        # 反向断言: 不应仍是硬编码 Transformer 模板
        if "Attention Is All You Need" in report_text and "alphafold" not in report_lower:
            checks.append(("[FAIL]", "报告仍是硬编码 Transformer 模板"))
        else:
            checks.append(("[OK]", "报告不是硬编码 Transformer 模板"))

        # 找 Cost Dashboard
        cost_text_found = False
        try:
            cost_text_found = (
                "总成本" in report_text or "成本" in report_text or "Cost" in report_text
            )
        except Exception:
            pass
        if cost_text_found:
            checks.append(("[OK]", "成本 dashboard 可见"))
        else:
            checks.append(("[INFO]", "成本 dashboard 未在页面文本中找到(可能折叠)"))

        # 报告前 800 字符
        print()
        print("=" * 70)
        print("报告前 800 字符")
        print("=" * 70)
        snippet = (report_section or report_text)[:800]
        print(snippet)
        print("=" * 70)

        print()
        print("[6] 验证结果:")
        for status, msg in checks:
            print(f"   {status} {msg}")

        # 8) 保存 meta
        meta = {
            "url": "http://127.0.0.1:5173/",
            "query": "AlphaFold protein structure prediction deep learning",
            "elapsed_seconds": round(elapsed, 1),
            "completed": completed,
            "report_length": len(report_text),
            "li_count": li_count,
            "svg_circle_count": svg_circle_count,
            "checks": [{"status": s, "msg": m} for s, m in checks],
        }
        with open(f'{OUT_DIR}/frontend_meta.json', 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(f"\nMeta saved: {OUT_DIR}/frontend_meta.json")

        await browser.close()
        ok = completed and all(s in ("[OK]", "[INFO]", "[WARN]") for s, _ in checks)
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
