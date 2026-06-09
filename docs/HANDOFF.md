# ScholarFlow R10.5+ AI 接手清单

> **目的**: 把审计报告 XYZ + live 验证 + R10.5 已完成项整理成可交接清单,供其他 AI 继续执行。
> **当前 HEAD**: `fa50670` (R10.5 X2+X3 修复,master 已 push)
> **测试基线**: 220 passed / 2 skipped / 0 failed (~99s)
> **Build 基线**: tsc clean / vite build clean / 13 routes
> **审计报告**: `D:\Users\桌面\ScholarFlow 架构审计报告XYZ.txt` (14 项问题)

---

## 0. 当前状态 (2026-06-09)

### ✅ 已完成 (R10.5, 4 commits)
| Commit | 内容 | 阻塞性 |
|---|---|---|
| `7944b47` | 修复真实 LLM 白屏 (ErrorBoundary + EventSource CONNECTING 竞态 + 401 静默) | **P0 用户阻塞** |
| `480cfe2` | 删重复 auth_router 注册 + 切循环导入 health→main | P0 审计 1.1+1.2 |
| `387917e` | CVE 白名单 + SearchState 字段补全 + auth 限流 | P0/P1 审计 1.3/2.3/2.4 |
| `fa50670` | DB init 在 lifespan + register/login user_id 派生一致 | R10.5 X2+X3 (live 发现) |

### ✅ Live 端到端验证通过
- /health 200
- /auth/register → user_id + api_key (sha256 摘要, 不存明文)
- /auth/me + X-API-Key → user info
- 同一 email register / login → **同一 user_id** (X3 一致)
- Search 无 key → 401
- Rate limit 5/min 触发: 第 6 次起 429
- 真实 MiniMax M3 LLM 84.15s 跑通 8 节点, 5 篇真论文 (95k+55k+28k+1k cites)

---

## 1. 接管前必读 (3 个文件)

| 文件 | 用途 |
|---|---|
| `D:\Users\桌面\ScholarFlow 架构审计报告XYZ.txt` | 14 项问题 + 优先级矩阵 — 全部修复项的源头 |
| `docs/FUTURE_TASKS.md` | 历史 deferred 项 (43 条) — 确认是否要做时回查 |
| `SECURITY.md` | CVE 白名单 + 升级路径 — 改 CI/依赖前必读 |

---

## 2. 待做项 (按优先级)

### 🔴 P0 — 真生产部署前必修

#### 2.1 [P0 审计 2.1] 静态 guard 测试 → 行为测试 (技术债根因)
- **位置**:
  - `tests/test_budget_lifecycle.py` (60+ 个 `assert "xxx" in src` 模式)
  - `tests/test_cors_hardening.py` (类似静态扫描)
- **影响**: 锁死重构 — `backend/main.py` 头部注释明确说"为满足静态 guard 而保留内联路由"
- **修复路径** (报告原文):
  ```python
  # 替换静态 guard 为行为测试
  @pytest.mark.asyncio
  async def test_budget_returned_on_pipeline_exception(client, monkeypatch):
      """当 pipeline 抛异常时,预先预留的 budget 必须被归还。"""
      reserved_before = await _read_budget_total()
      monkeypatch.setattr(search_graph, "ainvoke", _make_failing_graph(RuntimeError("x")))
      client.post("/search", json={"query": "test", "budget": 0.5})
      reserved_after = await _read_budget_total()
      assert abs(reserved_after - reserved_before) < 0.01
  ```
- **完成定义**:
  1. 所有 `assert "xxx" in src` 改写为真实行为测试
  2. `backend/main.py` 头部注释删除 "kept inline to satisfy static test guards" 段
  3. `app.include_router(search_router)` 接替内联路由, `main.py` 瘦身
- **成本**: 1-2 天
- **风险**: 高 — 重构可能引发回归,需全程测试守护

#### 2.2 [P0 审计 2.2] API Key 不在 URL 中 (EventSource 兼容)
- **位置**:
  - `frontend/src/hooks/useSearch.ts:178-186` (`?api_key=` query param)
  - `backend/main.py:497-509` (SSE 端 query param 解析)
- **影响**: API Key 进 Nginx 日志/浏览器历史/Referer/CDN 日志 (OWASP API2)
- **修复路径**:
  ```typescript
  // 替换 EventSource 为 fetch streaming
  const response = await fetch(url, {
    headers: { 'X-API-Key': apiKey, 'Accept': 'text/event-stream' }
  });
  const reader = response.body.getReader();
  // 手动解析 SSE 格式
  ```
- **完成定义**:
  1. SSE 端支持 `X-API-Key` header (后端已支持,只缺前端)
  2. 取消 `?api_key=` query param
  3. 验证 X-Request-ID 等其他 header 透传
- **成本**: 半天
- **风险**: 中 — SSE 解析逻辑需要完整测试

---

### 🟡 P1 — 重要改进

#### 2.3 [P1 审计 2.3] _make_initial_state 字段补全
- **状态**: ✅ **R10.5 已修** (`fa50670` 之前的 commit `387917e`)
- **说明**: `prev_iter_cost_usd` + `top5_summary_cache` 已补 None, 对齐 TypedDict

#### 2.4 [P1 审计 2.4] auth 端点加限流
- **状态**: ✅ **R10.5 已修** (进程内 sliding window 5/minute;20/hour, per email)
- **说明**: slowapi + FastAPI 2.12 ForwardRef 问题无法解决, 改函数内手写;单 worker 足够,多 worker 总容量 = N×limit,R11+ 上 Redis

#### 2.5 [R10.5 X1 子任务] 浏览器 EventSource 改 fetch + ReadableStream
- **触发**: 完成 2.2 时合并实施, 一次到位

#### 2.6 [R10.5 X1 子任务] 前端 marked.parse 异步化
- **位置**: `frontend/src/components/ReportPanel.tsx:34-70`
- **影响**: 大 LLM 报告 (50KB+) 同步解析阻塞主线程 ~100-400ms (React StrictMode 双重)
- **修复路径**:
  ```typescript
  // 改用 marked.parse(report, {async: true}) 或 web worker
  const html = useMemo(async () => {
    if (!report) return '';
    try {
      const rawHtml = await marked.parse(report, { async: true });
      // ... DOMPurify
    } catch (e) { ... }
  }, [report]);
  ```
- **成本**: 2 小时
- **风险**: 低 — 局部改动

#### 2.7 [R10.5 验证] GitHub Actions CI 4 job 同步
- **状态**: ✅ CVE 白名单已加 (`387917e`)
- **待做**: 第一次 push 触发 CI 后, 验证 4 job 全绿 (test / security / frontend / docker)
- **成本**: 5 分钟

---

### 🟢 P2 — 中期 (Q3)

#### 2.8 [P2 审计 3.1] SQLite 职责分离
- **路径**: search_cache / budget_state / users 3 张表 → 分离
- **近期**: 连接字符串参数化
- **中期**: Redis 替代 budget + cache
- **长期**: PostgreSQL 存 users
- **成本**: 1 周 (近期 1 天, 中期 1 周)
- **触发**: 准备 K8s 多实例部署

#### 2.9 [P2 审计 3.2] API 版本控制
- **路径**: 所有路由加 `/v1` 前缀, 保留 `/health` 无版本
- **当前**: 已有 `X-API-Version: 1.0.0` 响应头 (R10 做了零破坏起点)
- **升级**: 改路径前缀 + CHANGELOG 兼容性策略
- **成本**: 半天 (前端同步改 baseURL)
- **风险**: 中 — 现有 SDK 集成破,需发 major version

#### 2.10 [P2 审计 3.3] LangGraph 解耦
- **路径**: 节点函数从 `StateGraph` 强依赖改成 `dict → dict` 抽象
- **触发**: 升级 langgraph 1.0 (R11+ 评估中,因 API 破坏)
- **成本**: 2-3 天

#### 2.11 [P2 审计 3.4] 成本表硬编码治理
- **位置**: `backend/utils/llm_client.py` `MODEL_COST_PER_1M`
- **修复**: 提到 `cost_table.yaml`, env 覆盖, README 提供更新脚本
- **成本**: 半天

---

### ⚪ P3 — 长期 (Q4)

#### 2.12 [P3 审计 4.1] Python SDK
- **路径**: `scholarflow/client.py` 同步接口 + BibTeX/Zotero 集成
- **触发**: Zotero/Mendeley 集成目标
- **成本**: 3 天

#### 2.13 [P3 审计 4.2] Webhook 模式
- **路径**: `POST /search {callback_url}` 立即返 `job_id`, 完成 POST 回调
- **触发**: 移动端/批量场景
- **成本**: 1 天

#### 2.14 [P3 审计 4.3] Mock 模式 UI 提示
- **位置**: 前端 header 加 "演示模式" 徽标, 后端 `/health` 加 `mode: "mock"`
- **成本**: 1 小时

---

### 🛠 横切关注点

#### 2.15 [审计 5.1] 注释英文化
- **现状**: 注释/变量名/commits 中英混杂
- **路径**: 新代码规范文档 (公开英文, 个人记录中文), 逐步迁移核心文件
- **成本**: 持续

#### 2.16 [审计 5.2] FUTURE_TASKS.md 死链修复
- **位置**: `README.md` 引用 `docs/FUTURE_TASKS.md` — 实际存在但仓库早期有 `.gitignore docs/` 痕迹
- **状态**: ✅ 已 tracked (R8 修复后)
- **验证**: 链接能点开即可

---

## 3. 接手流程 (新 AI 第一周建议路径)

```
Day 1: 读懂代码
  1. backend/main.py 头部注释 (50 行架构总览)
  2. backend/api/routes/search.py 完整读 (SSE 端点)
  3. frontend/src/hooks/useSearch.ts 完整读 (前端核心)
  4. 跑 tests/ 验证基线 (220 passed)

Day 2: 做 2.1 (静态 guard → 行为测试) — 最有价值, 解锁所有后续重构
  - 1-2 天
  - 完成后 main.py 可瘦身 200+ 行

Day 3-4: 做 2.2 + 2.6 (前端 EventSource 改 fetch + marked 异步)
  - 解决 R10.5 X1 残留风险
  - 半天 + 2 小时

Day 5: CI 4 job 验证
  - push 触发, 修任何 1-2 个 flaky
  - 完成 P0 阶段
```

---

## 4. 测试基线 (220 + 2 skip, 99s)

| 类别 | 数量 | 说明 |
|---|---|---|
| auth_api_key | 16 | API Key + budget_user 隔离 |
| budget_lifecycle | ~40 | 含静态 guard (2.1 目标) |
| cors_hardening | 4 | 含静态 guard |
| export_bibtex_ris | 21 | P0 BibTeX/RIS 导出 |
| cost_tracker | 5 | P0-2 PER_ITER 语义 |
| search_node_semaphore | 5 | SS API 限流 |
| synthesis_grounding | 6 | LLM 防 prompt injection |
| 其他 12 文件 | ~110 | 各 agent + 工具 |
| **总计** | **220 + 2 skip** | |

---

## 5. 关键技术债 (不在审计报告但建议关注)

### 5.1 SSE 重连竞争 (R10.5 X1 修了前端, 后端待补)
- **位置**: `backend/main.py:559-602` (SSE event_generator)
- **场景**: 客户端断开 → 后端仍跑完整个 graph (浪费 cost)
- **修复**: 加 `if await request.is_disconnected(): break` 检查
- **成本**: 1 小时

### 5.2 多 worker 部署的预算原子性
- **现状**: SQLite BEGIN IMMEDIATE 模拟原子, 4 worker 同时写会 lock
- **修复**: 换 Redis INCR/DECR (P2 审计 3.1 子任务)
- **触发**: K8s 部署

### 5.3 graph 渲染 O(N²) tick
- **位置**: `frontend/src/components/GraphPanel.tsx:248-255`
- **场景**: >50 节点时, d3 force simulation 卡顿
- **修复**: `simulation.alphaDecay(0.1)` 加快收敛, 或 forceAtlas2 替代
- **成本**: 2 小时

### 5.4 前端无 i18n
- **现状**: UI 全中文, 变量名中英混杂
- **修复**: i18next + 字典
- **触发**: 海外用户

---

## 6. 不需要做的 (审计误判或已完成)

| 误判项 | 原因 |
|---|---|
| 1.1 auth_router 重复 | ✅ R10.5 已删 |
| 1.2 循环导入 | ✅ R10.5 已抽 `backend/utils/network.py` |
| 1.3 CVE \|\| true | ✅ R10.5 已加 `--ignore-vuln` 白名单 |
| 2.3 SearchState 字段 | ✅ R10.5 已补 |
| 2.4 auth 限流 | ✅ R10.5 已用进程内 sliding window |
| main.py God Object | 仅 2.1 完成后才能拆, 当前依赖静态 guard |

---

## 7. 紧急 Bug 通道 (Live 出现新问题)

如果用户报告**白屏 / 401 静默 / 加载卡住**:
1. 看 `frontend/src/components/ErrorBoundary.tsx` 是否触发
2. 看 `useSearch.ts` `onerror` 是否走 `fetchMe()` 401 分支
3. 看后端 `_init_db_once()` 是否在 lifespan 跑过
4. 看 `register/login` 返的 user_id 是否一致 (X3 修复)

---

*最后更新: 2026-06-09 by R10.5 Fix-X 系列. 任何疑问看 commit message + 审计报告 XYZ.*
