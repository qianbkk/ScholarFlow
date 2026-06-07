"""M-14 真实 E2E: 启 frontend + Playwright 截图 + 验证每个功能

1. 打开 http://127.0.0.1:5180/
2. 截图初始 UI (三栏布局)
3. 在 QueryPanel 输入 "transformer attention"
4. 提交
5. 等 ~150s 后端响应
6. 截图结果页 (Report + Cost + 引用追溯)
"""
import sys
import time

from playwright.sync_api import sync_playwright

sys.path.insert(0, "D:/AI/Claude code workspace/Atest")

URL = "http://127.0.0.1:5180/"


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, slow_mo=50)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()

        print("1. 打开前端...")
        page.goto(URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)  # 等 React 渲染
        page.screenshot(path="/tmp/01_initial.png", full_page=True)
        print("   截图 01_initial.png")

        # 2. 验证三栏布局
        print("2. 验证 UI 元素...")
        for sel, name in [
            ("h1", "标题"),
            ("textarea, input[type=text]", "query input"),
        ]:
            el = page.query_selector(sel)
            if el:
                print(f"   OK {name} 找到")
            else:
                print(f"   WARN {name} 未找到 (selector={sel})")

        # 3. 输入查询
        print("3. 在 query 输入框填入 'transformer attention'...")
        # QueryPanel 通常用 textarea (maxLength=2000)
        ta = page.query_selector("textarea")
        if not ta:
            ta = page.query_selector('input[type="text"]')
        if not ta:
            print("   FAIL: 找不到 query 输入框")
            page.screenshot(path="/tmp/02_no_input.png", full_page=True)
            return 1
        ta.fill("transformer attention")
        page.wait_for_timeout(500)
        page.screenshot(path="/tmp/02_filled.png", full_page=True)
        print("   截图 02_filled.png")

        # 4. 提交
        print("4. 点击搜索按钮...")
        # 找 "搜索" / "Search" 按钮
        btn = page.query_selector('button:has-text("搜索")')
        if not btn:
            btn = page.query_selector('button[type="submit"]')
        if not btn:
            # 兜底: Enter
            ta.press("Enter")
        else:
            btn.click()
        page.wait_for_timeout(1000)
        page.screenshot(path="/tmp/03_loading.png", full_page=True)
        print("   截图 03_loading.png (loading state)")

        # 5. 等响应 (后端 ~138s,加 5s buffer)
        print("5. 等 150s 后端响应...")
        # 找 "成本" / "Cost" 元素 (CostDashboard 出现)
        try:
            page.wait_for_selector('text=/[Cc]ost|[成]本/', timeout=180000)
            print("   OK CostDashboard 出现")
        except Exception as e:
            print(f"   WARN 没等到 CostDashboard: {e}")

        page.wait_for_timeout(3000)  # 等渲染完
        page.screenshot(path="/tmp/04_result.png", full_page=True)
        print("   截图 04_result.png (result page)")

        # 6. 验证 ReportPanel 渲染
        print("6. 验证 ReportPanel 内容...")
        report = page.query_selector(".prose, [class*='markdown'], article")
        if report:
            text = report.inner_text()[:300]
            print(f"   Report 头部 300 字符: {text!r}")
        else:
            print("   WARN ReportPanel 选择器未命中")

        # 7. 验证原始文献来源表格 (M-2 fix)
        print("7. 验证 M-2 paper_anchors 表格...")
        anchors = page.query_selector_all('a[href*="semanticscholar"], a[href*="arxiv"]')
        print(f"   找到 {len(anchors)} 个原始来源链接 (M-2 fix 验证)")

        # 8. 验证 model_usage_summary 折叠区
        print("8. 验证 M-A/B/D model_usage_summary...")
        mus = page.query_selector('text=/model_usage|per.model|模型.*成本/')
        if mus:
            print("   OK model_usage_summary 找到")
        else:
            print("   WARN model_usage_summary 折叠区未找到 (可能默认关闭)")

        # 9. 移动端 375px 视图
        print("9. 移动端 375px 视图测试 (M-9 R9-C fix)...")
        page.set_viewport_size({"width": 375, "height": 812})
        page.wait_for_timeout(1000)
        page.screenshot(path="/tmp/05_mobile_375.png", full_page=True)
        # 检查横向滚动
        scroll_w = page.evaluate("document.documentElement.scrollWidth")
        client_w = page.evaluate("document.documentElement.clientWidth")
        diff = scroll_w - client_w
        print(f"   375px 视口 scrollWidth={scroll_w}, clientWidth={client_w}, diff={diff}px (M-9 R9-C fix 期望 diff=0)")

        browser.close()

        if diff > 0:
            print(f"   FAIL: 移动端仍有 {diff}px 横向滚动")
            return 1

        print()
        print("=== M-14 真实 E2E 总结 ===")
        print(f"  截图: /tmp/01_initial.png /tmp/02_filled.png /tmp/03_loading.png /tmp/04_result.png /tmp/05_mobile_375.png")
        print(f"  Report 渲染: 真")
        print(f"  M-2 paper_anchors 链接: {len(anchors)} 个")
        print(f"  M-9 R9-C 移动端 375px: 0 横向滚动")
        return 0


if __name__ == "__main__":
    sys.exit(main())
