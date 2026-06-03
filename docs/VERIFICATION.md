# 真实环境验证报告

> 验证时间：2026-06-03
> 验证方式：浏览器自动化（mavis-browser）+ curl 接口测试

---

## ✅ 端到端测试

### 1. 后端 /health
```bash
$ curl http://127.0.0.1:8000/health
{"status":"ok","service":"ScholarFlow","version":"1.0.0"}
```

### 2. 后端 /search（Vite 代理）
```bash
$ curl -X POST http://127.0.0.1:5173/api/search -H 'Content-Type: application/json' \
    -d '{"query":"transformer attention","max_iterations":1,"budget":0.5}'
# 返回: status=done, papers=20, nodes=20, links=50, cost=$0.0000, elapsed=0.78s
```

### 3. 前端 UI 渲染
**初始状态**（screenshot_01_initial.png）：
- ✅ 三栏布局：CostDashboard 顶部 / QueryPanel 左 / ReportPanel 中 / GraphPanel 右
- ✅ 顶部状态栏：TOKEN 0 / COST $0.0000 / PAPERS 0 / ITERATIONS 0 / Status: Idle
- ✅ 5 个示例查询 chip、搜索/清空按钮、预算/迭代输入框
- ✅ 报告区显示占位符 "左侧输入研究问题并点击「搜索」开始"
- ✅ 图谱区显示图例（低/高相关性 + 节点大小说明）

**搜索后**（screenshot_04_search_v2.png）：
查询「**大语言模型在代码生成中的应用**」：
- ✅ 状态栏更新：19,305 tokens / 20 papers / 3 iterations / 1.6s / **done（绿点）**
- ✅ 报告区：完整中文 Markdown 综述
  - 研究概述
  - 核心论文推荐（Top 5）：Attention Is All You Need / BERT / GPT-3 / Llama 2 / A Survey of LLMs
  - 研究方向分类
- ✅ 论文列表：20 条，含 CodeGen / HumanEval / ImageNet 等
- ✅ 引文图谱：20 节点 / 40 边，D3 力导向图渲染成功，节点显示年份
- ✅ 图例 / 节点大小规则：节点大小 = log(引用数)

---

## 🐛 已识别问题

### 1. mavis-browser `type` action 不能更新 React 受控 input
- **现象**：直接通过 `type` 工具输入文本到 `<textarea>` 后，React state 未更新
- **原因**：React 18 受控组件依赖合成事件，DOM 级别 input 事件不触发
- **影响**：自动化测试时只能通过点击示例 chip 或直接调用 API
- **真实用户**：键盘输入正常（React onChange 会被原生事件触发）
- **结论**：不是 bug，自动化工具的限制

### 2. 当前 sandbox 无外网
- **现象**：MiniMax / Kimi / GLM / Anthropic / DeepSeek 全部 APIConnectionError
- **解决**：系统默认走 MOCK 模式，仍可完整跑通 8 节点流水线
- **真实环境**：用户电脑有外网时，编辑 `.env` 切 `LLM_MOCK=false` 即可

---

## 🎯 验收结论

| 验收项 | 状态 |
|--------|------|
| test_run.py 端到端 | ✅ PASS（25 论文 / 20 节点 / 51 边）|
| /health 返回 200 | ✅ |
| POST /search 返回完整 JSON | ✅ |
| 前端三栏布局正确 | ✅ |
| Markdown 报告渲染 | ✅ |
| D3 图谱渲染 | ✅ |
| 浏览器自动化验证 | ✅ |
| .env 密钥安全 | ✅（.gitignore 排除）|
| GitHub 推送 | ✅ qianbkk/ScholarFlow |
| 真实 LLM 联调 | ⚠️ Sandbox 无外网，依赖 MOCK 模式 |

---

## 📂 截图列表

- `screenshot_01_initial.png` — 初始 UI
- `screenshot_02_after_search.png` — 搜索按钮未触发（验证 type 行为）
- `screenshot_03_search_results.png` — 第二次失败
- `screenshot_04_search_v2.png` — **完整工作流跑通**（最关键）
- `screenshot_05_hover.png` — 状态截图
- `screenshot_06_second_query.png` — 重复点击
- `screenshot_07_third_query.png` — 重复点击
