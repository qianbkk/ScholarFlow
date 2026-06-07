---
name: multi-agent-audit-methodology
description: ScholarFlow 6 轮多 agent 审计 + 优化的完整方法论 - 何时启动审计 agent、分类、执行、simplify、push 的标准化流程
metadata:
  node_type: memory
  type: project
  originSessionId: 84fec3b7-3ad7-4192-a373-7e48ddf349d2
---

# ScholarFlow 多 agent 审计 + 优化方法论

历经 6 轮密集迭代 ~95+ commits 后沉淀的标准化流程。

## 6 阶段闭环

```
1. 多 agent 审计 (3-4 个并行)         — 架构/性能/安全/UX
2. 分类 + 打空气                     — 1 个 agent 合并去重 + 决策
3. 多 agent 优化执行 (4-5 个并行)    — 按文件严格切分
4. 终极 review + 真实 E2E           — 全量 pytest + 真实 LLM
5. 冗余性分析 + /simplify            — 1 个 agent 静态分析
6. git push + README 更新            — 含 6 轮总结
```

每阶段状态必须清晰(pending/in_progress/completed),不跨阶段跳。

## 何时用多 agent

✅ 任务相互独立(无共享文件/共享状态)
✅ 任务量大(总时间 > 5 分钟)
✅ 任务可清晰分割成 3-5 个独立子任务

❌ 单 agent 串行做 5 件事可能比 5 个 agent 并行更快(协调开销)

## 关键经验

### 1. 真实跑场景 ≠ 静态分析
- 第 5 轮跑出 MiniMax 5h 限流真实触发 → 才发现 is_degraded 必须闭环
- 第 5 轮跑出 CJK 注入未拦 → 才发现 sanitize 漏 prior/earlier
- **审计 agent 必须真跑搜索/跑攻击向量**,不是只看代码推测

### 2. silent overlap race condition
- 多个 agent 同时改同一文件 → 后面 agent 的 commit 覆盖前面的
- **6 轮中已 3 次**:M5 useSearch / M2 cancel / M3 model_usage
- **对策**:
  - 任务分配时按文件严格切分(agent A 改 X, agent B 改 Y, **绝不重叠**)
  - agent 提交前看 working tree,有别人暂存的就 `git restore`
  - 接受"协作 agent 互不阻塞"是常态,不强求零冲突

### 3. 闭环优先
- 修一处必暴露另一处(螺旋上升)
- 典型案例:R3 P0-1 节点级预算硬停止 → R5 M-1 is_degraded 顶层信号 → R5 App.tsx 透传
- 任何跨层改动都需要"接力补 commit"

### 4. agent commit author 必须显式指定
- Claude 默认用占位符 `claude <noreply@anthropic.com>` / `R6 SIMPLIFY <simplify@local>`
- **必须在 prompt 里强制**:
  ```bash
  git -c user.name="qianbkk" -c user.email="qianbkk@users.noreply.github.com" commit ...
  ```
  或 `git config user.name "..."` 预 set
- 6 轮结束用 `git filter-branch` 一次性 rewrite 历史
- **Email 必须是 `users.noreply.github.com` 格式**,否则 GitHub Contributors 不识别(见 [commit-author-rule](commit-author-rule.md))

### 5. 5 并发触发 SS API 429
- SS free tier 100 req/5min → 5 个 agent × 5 子查询 = 25+ 请求
- **对策**: 限流同时审计 agent 数 (≤3), 或串行而非并行
- 用户原话:"考虑先暂缓两个,慢慢来不着急"

### 6. 审计临时文件必须清理
- `_sec_test.py` / `audit_round5_temp.py` / `.claude/` 缓存
- **对策**: 任务结束 `rm -f` 这些 untracked 文件,否则污染 working tree

### 7. 用户前端特别加强请求
- "没有对前端进行优化的吗,可以加一下" → 每次审计必加前端 agent
- 必 1+应 2(must + should 至少 3 项前端)

## 文件严格切分原则

每个 agent 任务必须满足:
- **单一目标** (1-3 个文件)
- **明确边界** (不要碰其他文件)
- **可独立验证** (有自己的测试)
- **明确输出** (X 个 commit + 测试数)

7 段式 agent prompt 模板(实战命中率 90%+):
```
1. ROLE          # 你是 X 类型开发者
2. SCOPE         # 限定文件清单
3. BACKGROUND    # 背景
4. TASKS         # 每条精确步骤
5. CONSTRAINTS   # 不要 push / 不要改 docs / 不要加竞争内容
6. STEPS         # read → edit → test → commit
7. FINAL REPORT  # 文件清单 + 测试数 + commit SHAs
```

## 打空气检查

每轮审计发现常含 30-40% 误报:
- 评论者没看代码(可能声称"X 不存在"但其实有)
- 理论性 race condition(需要 6 worker 同时崩溃才触发)
- 推荐已经存在的方案

**对策**: 分类 agent 必须逐项 read 代码验证,打空气降级或关闭

## 真实场景 E2E 价值

每轮 E2E 必跑:
- 全新 query 避免 cache 命中
- 验证 `is_degraded_response` / `model_usage_summary` 等新字段真实出现
- 验证 HTTP 安全头真实返回
- 验证 cancel 端点真不谎报

**E2E 是闭环的最后一公里**,不跑不知道。
