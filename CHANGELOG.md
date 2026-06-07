# Changelog

All notable changes to ScholarFlow will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- 6 轮多 agent 审计 + 优化 (~95+ commits)
- R6: in-flight task table + cancel 真取消
- R6: model_usage_summary 白名单 (去除 MiniMax-M3 等内部名)
- R6: TypedDict 显式声明 top5_summary_cache
- R6: denylist 加 jailbreak/DAN/developer mode
- R6: 日志 throttle 5 分钟 (log_throttle 抽 utils)
- R5: 节点级预算硬停止 SSE 事件 (budget_exceeded)
- R5: HTTP 7 个安全头 (CSP / HSTS / X-Frame-Options 等)
- R5: 6 维 sanitize (NFKC + 同形字 + 注入词 + 数学字母)
- R4: 真实 LLM E2E + 浏览器识图验证
- R3: degraded banner + 真 cancel 按钮
- R2: 跨 worker 预算 BEGIN IMMEDIATE + 归还 + 节点级硬停止
- R1: 多 provider 路由 + 模型选择器

### Changed
- R6: search_agent 250→125 papers (50% API 配额节省)
- R6: useSearch 假进度 4Hz→1Hz (75% re-render 减少)
- R5: synthesis 25→15 papers + abstract 400→200 字符
- R5: 论文数 response 20→25 (闭环 synthesis agent)
- R5: model_usage 字段白名单

### Fixed
- R6: 9 个 flaky 测试 (ContextVar 隔离)
- R6: cancel 谎报成功 (改返 cancelled=False 当无 in-flight)
- R5: cancel 端点真调闭环
- R5: X-Request-ID DoS 校验 (长度 + charset)
- R4: cache_key 跨 provider 隔离
- R3: cache_key 跨 provider 调用点
- R3: budget 异常路径 try/finally 兜底

### Security
- R5: HTTP 安全头 7 个
- R5: 422 不回显 input
- R5: CJK prompt 注入 denylist
- R4: X-Request-ID DoS

## [0.1.0] - 2024-Q4

### Added
- 初始 8 节点 LangGraph 流水线 (decompose → search → expand → rank → refine/synthesize → graph → cost)
- Semantic Scholar + OpenAlex 双源检索
- 三维打分 (relevance / consistency / authority)
- SQLite WAL 缓存
- mock 模式 + 真实 LLM 模式
- React + TypeScript 前端三栏布局
- FastAPI 后端

[Unreleased]: https://github.com/qianbkk/ScholarFlow/compare/v1.0.0...HEAD
[0.1.0]: https://github.com/qianbkk/ScholarFlow/releases/tag/v0.1.0
