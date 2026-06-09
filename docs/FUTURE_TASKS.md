# ScholarFlow 后续任务清单

> **项目**: ScholarFlow — 8 节点多 Agent 学术文献搜索系统
> **创建**: 2026-06-06
> **状态**: 文档归档,后续视需要执行
> **位置**: `docs/FUTURE_TASKS.md` (tracked, 仓库内公共 roadmap)

---

## 0. 总体状态

| 阶段 | 数量 | 完成时间 |
|------|------|---------|
| **P0 必修 bug** | 6 | 2026-06-05 |
| **P1 安全/性能** | 4 | 2026-06-05 |
| **P2 竞争力优化**(双分合并/SSE/缓存/NFKC/DeepSeek) | 5 | 2026-06-05 |
| **单元测试** | 27 | 2026-06-05 |
| **真实 LLM E2E + 浏览器验证** | 2 通道 | 2026-06-05 |
| **总计 commit** | 25 | — |
| **本次会话新增** | 14 项待办 | 本文档 |

**仓库状态**: 58 tracked files, working tree clean, 27/27 测试通过, backend / health 200 + /search 200 + /search/stream SSE 9 事件按序。

---

## 1. 14 条「可以考虑」后续项

> 来源: 本地深度分析与优化指南文档 (内部审计产物, 未入仓)
> 已对每条核对当前代码状态 + 实际影响 + ROI
> **结论: 14 条全部不紧急、不阻塞核心功能**

### 1.1 后端 Bug(3 条)

#### [SKIP] #1 `_DISABLE_HTTP_POOL` 模式连接泄漏
- **位置**: `backend/api/semantic_scholar.py:30-34` + `backend/api/openalex.py:26-29`
- **触发条件**: 开发者显式设置 `_DISABLE_POOL=True` 时
- **影响**: 默认完全安全;只有手动启用调试模式才泄漏 TCP 连接
- **何时重做**: 出现"开发者频繁用 _DISABLE_POOL 调试"的需求时
- **修复成本**: 20 行 (改用 `async with`)

#### [SKIP] #2 Mock 中文论文 URL 404
- **位置**: `backend/api/mock_data.py:828-830`
- **触发条件**: 用户在 mock 模式下点击中文论文链接
- **影响**: 离线演示用,GitHub 链接 404 是已知边界,不影响功能
- **何时重做**: 反馈"用户在 mock 演示中点链接 404 体验差"时
- **修复成本**: 5 行 (改用 arxiv URL 或留空)

#### [SKIP] #3 Mock 数据 `openalex_W003` 与 `ss_041_gan` 重复
- **位置**: `backend/api/mock_data.py:239-247` + `:509-517`
- **触发条件**: 始终存在
- **影响**: `deduplicate_papers` 自动去重,实际输出 57 篇而非 58 篇,用户无感知
- **何时重做**: 永远不需要
- **修复成本**: 5 行 (删除其中一条)

### 1.2 性能(1 条)

#### [SKIP] #4 代理探测改 async 避免阻塞事件循环
- **位置**: `backend/utils/proxy.py:36-41`
- **触发条件**: 冷启动第一次请求早于 lifespan 完成时
- **影响**: 实测阻塞 0.25s,仅 1 次;lifespan 预热后完全消失
- **何时重做**: 出现"冷启动时用户感知卡顿"反馈时
- **修复成本**: 15 行 (改 `asyncio.open_connection`)

### 1.3 代码风格(2 条)

#### [SKIP] #5 Mock 中文 token 估算偏低
- **位置**: `backend/utils/llm_client.py:406-407` (mock 模式 token 计算)
- **触发条件**: LLM_MOCK=true 时
- **影响**: 仅 mock 报告里的 token 数字,实际成本 $0,无业务影响
- **何时重做**: mock 报告需对外展示精确 token 时
- **修复成本**: 10 行 (中文 1.5 token/字 + 英文 0.75 token/词)

#### [SKIP] #6 requirements.txt 上界收窄 + dev 文件
- **位置**: `backend/requirements.txt`
- **触发条件**: 升级时
- **影响**: 核心诉求(防大版本破坏)已通过(commit `41e9dc5` 加了 `<1.0.0` / `<2.0.0`),进一步收窄收益小
- **何时重做**: 项目进入 LTS 维护阶段时
- **修复成本**: 持续维护 (每库跟 changelog)

### 1.4 前端(3 条)

#### [SKIP] #7 缺 `doi` 字段 TypeScript 类型
- **位置**: `frontend/src/types/index.ts`
- **触发条件**: 用户需要导出或引用 DOI 时
- **影响**: 当前通过 `url` 跳转已覆盖用户场景
- **何时重做**: 加"导出 BibTeX"功能时
- **修复成本**: 1 行

#### [SKIP] #8 移动端响应式缺失
- **位置**: `frontend/src/App.tsx` + 3 个 panel
- **触发条件**: 768px 以下屏幕访问时
- **影响**: 桌面优先研究工具,移动端非目标场景
- **何时重做**: 项目定位改为"通用工具"而非"研究工作流"时
- **修复成本**: 50 行 (Tailwind breakpoint 折叠布局)

#### [SKIP] #9 QueryPanel 大量论文时性能(虚拟化)
- **位置**: `frontend/src/components/QueryPanel.tsx:162-200`
- **触发条件**: 论文数 > 100 时
- **影响**: 当前实际返回 < 50 条,问题不存在;引入 `react-window` 反而增加复杂度
- **何时重做**: 决定返回 Top 100+ 论文时
- **修复成本**: 引入 `react-window` (20 行)

### 1.5 测试扩展(2 条)

#### [SKIP] #10 8 个 Agent 节点单测
- **位置**: `backend/agents/*` 各节点
- **触发条件**: 重构 agent 节点时
- **影响**: 节点互相耦合(共享 SearchState + LLM 调用),单测要 mock 整个 LLM 层,边际收益低
- **何时重做**: agent 节点拆分/重构时
- **修复成本**: 1 天 (8 个 agent × 3 case)

#### [SKIP] #11 前端 Vitest/Jest 测试
- **位置**: `frontend/`
- **触发条件**: 持续集成要求前端单测时
- **影响**: UI 价值在可视化(D3 图谱),已有 Playwright 手动验证(`tests/manual/verify_frontend.py`)
- **何时重做**: 接入 CI 且 CI 跑 Playwright 较慢时
- **修复成本**: 引入 vitest + 写测试 (半天)

### 1.6 部署与运维(3 条)

#### [OPTIONAL] #12 Dockerfile + docker-compose
- **位置**: 项目根
- **触发条件**: 新用户希望"一键启动"或 CI/CD 需要标准化环境时
- **影响**: README 已给 `uvicorn` + nginx 完整指引,demo 项目不阻塞;但 docker 化后跨平台一致性更好
- **何时重做**: 出现"用户 fork 后跑不起来"或需要 CI 时
- **修复成本**: 30 行 Dockerfile + 40 行 docker-compose.yml

#### [SKIP] #13 结构化 JSON 日志
- **位置**: `backend/main.py:32` (logger 配置)
- **触发条件**: 接入 ELK / Grafana / Loki 时
- **影响**: 单机运行时 print + logger 已够用
- **何时重做**: 真正上 ELK 时
- **修复成本**: 20 行 (JsonFormatter)

#### [OPTIONAL] #14 GitHub Actions CI
- **位置**: `.github/workflows/`
- **触发条件**: 接受外部 PR 协作者时
- **影响**: 单人项目本地手动验证已够;有外部贡献者时价值显现
- **何时重做**: 项目有外部协作者时
- **修复成本**: 40 行 (lint + test + build pipeline)

---

## 2. 其他未来改进(本会话发现但未列入 14 条)

### 2.1 已知技术债

#### [DEFER] #15 路由单元测试覆盖度可加深
- **现状**: `tests/test_router.py` 已覆盖 8 个 case
- **可加**: 边界条件(avg_relevance 正好 7.0、iteration 边界值等)
- **何时重做**: 路由逻辑调整时
- **修复成本**: 30 分钟

#### [DEFER] #16 mock synthesis 的 regex 对 prompt 格式敏感
- **现状**: `llm_client.py:269-321` `_mock_synthesis` 用正则解析 `**[Paper i]**` 块
- **可加**: 改用 JSON-mode LLM 返回结构化 papers,完全消除正则脆弱性
- **何时重做**: 维护时发现正则解析偶尔漏数据时
- **修复成本**: 1 小时 (改用 LLM 结构化输出)

#### [DEFER] #17 引文图谱 D3 颜色区分度仍可优化
- **现状**: 蓝-绿渐变,色觉障碍用户不友好
- **可加**: 改用 `d3.interpolateRdYlGn` 或 `d3.interpolateViridis`
- **何时重做**: 反馈"图谱颜色看着不分明"时
- **修复成本**: 10 行 (改 colorScale + 补图例)

### 2.2 文档/项目治理

#### [DEFER] #18 API 文档自动生成
- **现状**: `/docs` Swagger 自动生成,但缺 `* /search/stream` 的事件 schema 描述
- **可加**: 在 FastAPI 端点加 `responses` 注解,SSE event 描述
- **何时重做**: 对外发布 API 时
- **修复成本**: 30 分钟

#### [DEFER] #19 国际化(i18n)
- **现状**: 报告默认中文,前端 UI 全中文
- **可加**: i18n 框架(i18next),支持中英双语
- **何时重做**: 用户群国际化时
- **修复成本**: 半天

### 2.3 监控/可观测性

#### [DEFER] #20 /search 流水线的可观测性埋点
- **现状**: 节点完成有 logger,无 metrics
- **可加**: Prometheus 指标(node 耗时直方图、cost/iter 分布、cache hit rate)
- **何时重做**: 真正上生产时
- **修复成本**: 1 天

#### [DEFER] #21 真实 LLM 调用时使用 OpenTelemetry trace
- **现状**: 无分布式追踪
- **可加**: otel-instrument 包装 LLM/API/DB 调用
- **何时重做**: 多服务架构或调试性能问题时
- **修复成本**: 半天

### 2.4 安全/合规

#### [DEFER] #22 添加 SBOM(软件物料清单)
- **现状**: 仅 requirements.txt
- **可加**: `pip-licenses` / `syft` 生成 SBOM,披露依赖许可
- **何时重做**: 企业合规审查时
- **修复成本**: 1 小时

#### [DEFER] #23 加 LICENSE / CONTRIBUTING / SECURITY.md
- **现状**: 仅有顶部 `## License: MIT`
- **可加**: 单独的 `LICENSE` + `CONTRIBUTING.md` + `SECURITY.md` (漏洞报告流程)
- **何时重做**: 对外发布 + 接受 PR 时
- **修复成本**: 1 小时

---

## 3. 何时"翻出本文件"执行

| 触发信号 | 优先重做的项 |
|---------|-------------|
| 新用户反馈"跑不起来" | #12 Docker + #14 CI |
| 反馈"手机上没法用" | #8 移动端响应式 |
| 反馈"图谱颜色看不清" | #17 D3 颜色 + #7 doi 字段 |
| mock 报告偶尔内容缺失 | #16 mock synthesis 改 LLM 结构化输出 |
| 项目进入企业级部署 | #13 JSON 日志 + #20 metrics + #21 OTel + #22 SBOM + #23 LICENSE/CONTRIBUTING |
| 接受外部 PR | #14 CI + #10 Agent 单测 + #11 前端测试 + #23 CONTRIBUTING |
| 反馈"重复查询太贵" | #16 mock synthesis (无关);改 cache TTL + 加 LLM response cache |
| 项目进入 LTS 维护 | #6 requirements 收窄 + #15 路由测试加深 |

---

## 4. 维护说明

- **本文件已 tracked**: 仓库级 public roadmap, 公共可见
- **版本随项目同步更新**: 每次大优化完成后,如有新发现可加到本文件
- **删除已完成的项**: 当 #1-#14 某条被实际执行时,移至"已处理历史"区(本文件第 5 节预留)
- **每季度 review**: 可删去明显不再适用的项(如 #9 如果永远不会返回 100+ 论文)

## 5. 已处理历史(预留)

> 完成某条后,把它从上面 1-4 节移到这里,记录 commit SHA + 完成日期:

(暂无)

---

## Round 5 审计后续 (2026-06-07)

### #24 [DEFER] 多 worker Semaphore 失效 + cache_key 漏 mode 维度 (合并 ARCH-002+ARCH-008)
- **位置**: `backend/agents/search_agent.py:26` + `backend/utils/cache.py:173-192`
- **触发条件**: 部署到 K8s / 启用 gunicorn 多 worker / LLM_MOCK 与 real 模式切换
- **影响**: 单 uvicorn 无问题;4 worker → 实际并发 16,SS API 限流窗口 100/5min 仍可控
- **何时重做**: 启动 K8s 部署时;Redis 缓存 + 集中式 rate-limiter
- **修复成本**: 1 天 (Redis 替代 SQLite 缓存 + distributed Semaphore)

### #25 [DEFER] /health 端点深度健康检查
- **位置**: `backend/main.py:573-580`
- **触发条件**: k8s readinessProbe / livenessProbe 需要真实依赖健康度
- **影响**: 当前 /health 永远返回 ok,K8s rolling update 期间流量切到未就绪 pod
- **何时重做**: 真上 K8s 时
- **修复成本**: 30 行 (检查 SQLite WAL、httpx pool、provider health cache)

### #26 [DEFER] 优雅 shutdown 等待 in-flight SSE
- **位置**: `backend/main.py:230-258` (lifespan)
- **触发条件**: SIGTERM 时正在跑 /search/stream 的请求会被直接中断
- **影响**: 用户长任务(180s)中重启 pod,结果丢失
- **何时重做**: K8s 部署 + 大请求量时
- **修复成本**: 1 小时 (uvicorn `--timeout-graceful-shutdown` + 中间件等待)

### #27 [DEFER] SearchCancelRequest 字段校验 (与 S-4 合并)
- **位置**: `backend/main.py:537-539`
- **触发条件**: 任何人调 /search/cancel
- **影响**: 与 S-4 合并处理;S-4 修了这里就一并修了
- **修复成本**: 包含在 S-4

### #28 [DEFER] 状态机 Literal + TypedDict 护栏 (ARCH-006 / S-7)
- **位置**: `backend/models/state.py:8-18`
- **触发条件**: LangGraph 节点忘写 status 字段时静默漂移
- **影响**: 监控/排障读 status 找 synthesis 完成点会写错
- **何时重做**: 重大 refactor 时一并改 pydantic BaseModel
- **修复成本**: 30 行

### #29 [DEFER] Dockerfile + gunicorn + 优雅 shutdown (ARCH-007)
- **位置**: 整个 repo (零 Dockerfile)
- **触发条件**: 任何脱离单机的部署
- **影响**: K8s 滚动更新期间 in-flight 任务被截断
- **何时重做**: 准备上 K8s 时
- **修复成本**: 半天 (Dockerfile + gunicorn.conf + graceful shutdown)

### #30 [DEFER] 日志结构化 (python-json-logger) (ARCH-010)
- **位置**: `backend/utils/observability.py:47-70`
- **触发条件**: 接入 ELK / Loki / Datadog
- **影响**: 当前 grep '[<rid>]' 拼链,无法按 cost/node/iteration 维度聚合
- **何时重做**: 真上生产时
- **修复成本**: 1 小时 (替换 formatter)

### #31 [DEFER] PERF-007 query_refine 字符串重复构造
- **位置**: `backend/agents/query_refiner.py:25-29`
- **触发条件**: 每次循环重建 top5_summary 字符串
- **影响**: 边际 < 1ms,refine 跑 1-2 次/搜索
- **何时重做**: 性能优化时一并
- **修复成本**: 已并入 Round 5 S-1 修复

### #32 [DEFER] cache_key 加 mode 维度 (ARCH-008)
- **位置**: `backend/utils/cache.py:173-192`
- **触发条件**: 调试时切换 API_MOCK true↔false 可能误命中旧 cache
- **影响**: 看不到 mock 输出;生产 A/B 不同 model 版本会被旧 cache 掩盖
- **何时重做**: 模式切换调试时
- **修复成本**: 1 行 (cache_key 加 mode 维度)

---

## Round 6 审计后续 (2026-06-07)

### #33 [DEFER] SEC-001 prior/earlier 已存在 (打空气)
- **位置**: `backend/utils/sanitize.py:13-37`
- **状态**: Round 6 分类 agent 验证后确认已覆盖,关闭
- **修复成本**: 0

### #34 [DEFER] UX-001 深色模式
- **位置**: `frontend/tailwind.config.js` + 所有组件
- **触发条件**: 用户夜间使用 / 长时间盯屏幕
- **影响**: 学术工具 2024-2026 标配, 当前无 → 用户流失
- **何时重做**: 主要 UI 稳定后大重构
- **修复成本**: 200+ 行 (每个组件加 dark: 前缀)

### #35 [DEFER] UX-003 i18n 完整化
- **位置**: 全部前端组件
- **触发条件**: 国际化 / 海外用户
- **影响**: 当前中英混杂, 不专业
- **何时重做**: 准备多语言时
- **修复成本**: 半天 (建 i18n 字典 + 全部 UI 文案走 t())

### #36 [DEFER] UX-004 键盘快捷键
- **位置**: `frontend/src/components/QueryPanel.tsx` + 全局 keydown
- **触发条件**: 键盘流研究者用户
- **影响**: Ctrl+K 聚焦 / Esc 取消 是 web app 标配
- **何时重做**: 任何 UX 改版时
- **修复成本**: 1 小时

### #37 [DEFER] /docs 生产 gate (ARCH-004)
- **位置**: `backend/main.py` lifespan
- **触发条件**: 部署到生产环境
- **影响**: /openapi.json + /docs 公开泄露 schema 给攻击者
- **何时重做**: 真上 K8s 时
- **修复成本**: 5 行 (EXPOSE_DOCS env)

### #38 [DEFER] cache DB GC
- **位置**: `backend/utils/cache.py`
- **触发条件**: 长跑 30 天后 cache DB 单文件 >100MB
- **影响**: 备份/迁移慢, VACUUM 慢
- **何时重做**: 部署长期跑时
- **修复成本**: 10 行 (定期 DELETE + VACUUM)

### #39 [DEFER] budget SQLite 走 asyncio.to_thread
- **位置**: `backend/main.py:_check_and_reserve_budget`
- **触发条件**: 多 worker 部署 + 高并发
- **影响**: 单进程下同步调用 < 1ms, 无感知
- **何时重做**: 性能优化时
- **修复成本**: 5 行

### #40 [DEFER] /metrics 端点 (R5 已 defer 5 次,继续 defer)
- **位置**: `backend/main.py` + 新增 metrics 模块
- **触发条件**: 部署到生产环境需要 SLO 监控
- **影响**: 无 /metrics → 无 alert / 容量规划
- **何时重做**: 真上生产时
- **修复成本**: 半天 (prometheus_client + 5 个 Counter/Histogram)

### #41 [DEFER] X-Request-ID charset 收紧
- **位置**: `backend/main.py:298-301`
- **状态**: 现状已较严 `^[A-Za-z0-9_\-]+$`, 仍可考虑收紧到纯字母数字
- **修复成本**: 1 行

### #42 [DEFER] GraphPanel StrictMode 双跑
- **位置**: `frontend/src/main.tsx:5-9` + `components/GraphPanel.tsx`
- **触发条件**: dev 模式
- **影响**: 200+ tick, 卡顿 1-2s
- **何时重做**: 改 React 渲染层时
- **修复成本**: 5 行 (useRef guard)

### #43 [DEFER] Dockerfile + docker-compose
- **位置**: 项目根
- **触发条件**: 真生产部署
- **影响**: 无容器化, 部署效率低, 多 worker 配置难
- **何时重做**: 真上 K8s 时
- **修复成本**: 半天 (Dockerfile + compose + 多 worker 配置)

---

## R10.5 审计后续 (2026-06-09)

> **来源**: `D:\Users\桌面\ScholarFlow 架构审计报告XYZ.txt` (14 项 P0-P3) + 真实 LLM live 验证
> **状态**: 5 项已完成 (P0 1.1+1.2+1.3 + P1 2.3+2.4 + X1 白屏 + X2 DB init + X3 user_id 一致)
> **剩余**: 11 项 (审计 P1-P3 + R10.5 残留) — 详见 `docs/HANDOFF.md` 第 2 节

### ✅ 已完成 (R10.5, 4 commits)
- **#44 [DONE] P0 审计 1.1** 删重复 `app.include_router(auth_router)` — `480cfe2`
- **#45 [DONE] P0 审计 1.2** 切循环导入 health→main (`backend/utils/network.py`) — `480cfe2`
- **#46 [DONE] P0 审计 1.3** CVE 白名单 (PYSEC-2024-38 + GHSA-9hjg-9rjm-9j3p) + SECURITY.md — `387917e`
- **#47 [DONE] P1 审计 2.3** `_make_initial_state` 补 `prev_iter_cost_usd` + `top5_summary_cache` — `387917e`
- **#48 [DONE] P1 审计 2.4** auth 端点限流 (5/min;20/hour, per email, 进程内 sliding window) — `387917e`
- **#49 [DONE] R10.5 X1** 真实 LLM 白屏 (ErrorBoundary + EventSource CONNECTING 静默等 + 401 静默兜底) — `7944b47`
- **#50 [DONE] R10.5 X2** DB init 在 lifespan (修复 /auth/login 早于 /search 时 'no such table: users') — `fa50670`
- **#51 [DONE] R10.5 X3** register/login user_id 派生一致 (都走 email sha256) — `fa50670`

### ⏸️ 剩余待做 (按报告优先级)
- **#52 [P0 DEFER] 审计 2.1** 静态 guard 测试 → 行为测试 (解锁 main.py 重构)
  - 位置: `tests/test_budget_lifecycle.py` + `tests/test_cors_hardening.py`
  - 成本: 1-2 天
  - 阻塞所有 main.py 拆分工作
- **#53 [P0 DEFER] 审计 2.2** API Key 不在 URL (EventSource 改 fetch+ReadableStream)
  - 位置: `frontend/src/hooks/useSearch.ts:178-186` + `backend/main.py:497-509`
  - 成本: 半天
- **#54 [P1 DEFER] R10.5 X1 子任务** 前端 `marked.parse` 异步化 (大报告阻塞主线程)
  - 位置: `frontend/src/components/ReportPanel.tsx:34-70`
  - 成本: 2 小时
- **#55 [P2 DEFER] 审计 3.1** SQLite 职责分离 (search_cache / budget_state / users)
  - 触发: K8s 多实例部署
  - 成本: 1 周
- **#56 [P2 DEFER] 审计 3.2** API 版本控制 (`/v1` 前缀)
  - 当前: 已有 `X-API-Version` 响应头 (零破坏起点)
  - 成本: 半天
- **#57 [P2 DEFER] 审计 3.3** LangGraph 解耦 (节点函数从 `StateGraph` 抽到 `dict→dict`)
  - 触发: 升级 langgraph 1.0 (R11+ 评估)
  - 成本: 2-3 天
- **#58 [P2 DEFER] 审计 3.4** 成本表 `MODEL_COST_PER_1M` 提到 `cost_table.yaml` + env 覆盖
  - 成本: 半天
- **#59 [P3 DEFER] 审计 4.1** Python SDK (`scholarflow/client.py` 同步接口)
  - 触发: Zotero/Mendeley 集成
  - 成本: 3 天
- **#60 [P3 DEFER] 审计 4.2** Webhook 模式 (`POST /search {callback_url}`)
  - 触发: 移动端/批量
  - 成本: 1 天
- **#61 [P3 DEFER] 审计 4.3** Mock 模式 UI 徽标 (前端 header + 后端 `/health` mode 字段)
  - 成本: 1 小时
- **#62 [DEFER] 5.1** 中英注释规范 (公开代码英文, 个人记录中文)
  - 成本: 持续
- **#63 [DEFER] R10.5 残留 5.1** SSE 后端检测客户端断开 (`if await request.is_disconnected(): break`)
  - 位置: `backend/main.py:559-602`
  - 成本: 1 小时
- **#64 [DEFER] R10.5 残留 5.3** d3 force simulation >50 节点卡顿 (`alphaDecay` 加速)
  - 位置: `frontend/src/components/GraphPanel.tsx:248-255`
  - 成本: 2 小时

### 🎯 新 AI 接手第 1 周建议路径
```
Day 1: 读 main.py 头部注释 + search.py 完整 + useSearch.ts 完整 + 跑 tests
Day 2-3: 做 #52 静态 guard → 行为测试 (解锁所有 main.py 拆分)
Day 4: 做 #53 + #54 (前端 EventSource 改 fetch + marked 异步)
Day 5: CI 4 job 验证, 收尾 P0
```

详细交接清单见: **`docs/HANDOFF.md`**

---

*End of FUTURE_TASKS.md — 2026-06-06 创建,2026-06-07 追加 Round 5 审计 9 项 + Round 6 审计 11 项, 2026-06-09 追加 R10.5 审计 14 项 (5 done + 11 deferred) + 残留 2 项*

## R8 修复记录 (2026-06-07)

### Reviewer 报告 1 (provider semantic + schema alignment)
- R8: get_provider_config 改 strict=True 默认, 未知 provider raise (config.py:83-150)
- R8: 前端 ProviderInfo 加 verified 字段 (api.ts)
- R8: 前端 SearchResult 加 model_usage_summary 必填 + model_usage 可选 (types/index.ts:72)

### Reviewer 报告 2 (refactor 没收口 + 双 schema + 双 provider + 双状态)
- R8.2: _resolve_provider 加 has_key 过滤, 防止 "name 合法但 has_key=False" 静默回退
- R8.2: ProviderInfo.verified + ProvidersResponse.default_provider 字段补齐
- R8.2: conftest.py 加 autouse _reset_global_state fixture (limiter + in-flight table reset)
- 进度: 6 failed → 5 failed (R8.2 autouse fixture 修了 1 个)
- 残留 5 failed 全是 test_request_id_propagation + test_search_node_semaphore,
  跨文件污染 (test_cors_hardening._purge_backend_modules reload backend.main 后
  sys.modules 跟 fixture 抓的 main_mod 不一致), 留 R8 第 3 批处理

### 当前测试状态 (2026-06-07 R8.2 修后)
- 真实状态: 5 failed / 303 passed / 2 skipped
- 之前本地文档写 "27/27 passed" — 已过时, 真实数字是上面那个
- 5 failed 都是 pre-existing 跨文件状态污染, 单跑全过
