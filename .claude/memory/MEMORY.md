# ScholarFlow Memory 索引

> 项目内方法论/经验库,随 git 跟踪,跨 session 复用。
> 启动时 Claude 自动加载本文件 (前 200 行),具体主题文件按需用 Read 工具读。

## 入口

- [multi-agent-audit-methodology](multi-agent-audit-methodology.md) — **6 阶段闭环方法论 + 真实场景审计价值 + silent overlap 处理 + 闭环优先**
- [commit-author-rule](commit-author-rule.md) — **agent commit 必须指定 author 为 qianbkk / claude, 用 filter-branch 修复历史**
- [repo-tags-policy](repo-tags-policy.md) — **仓库 13 个标签文件清单 + 补齐优先级 + README 末尾规范**

## 全局官方 memory

本机全局 `~/.claude/projects/D--AI-Claude-code-workspace-Atest/memory/` 还有一条:

- `scholarflow-test-methodology.md` — 测试三件套 (mavis-browser + Playwright + Read) 的使用流程

## 跟 `~/.claude/projects/<project>/memory/` 的关系

- **全局 memory**: Claude 自动写, 写到你家目录, 不随仓库, 私人/临时
- **项目内 memory** (本目录): 你显式写, 写进仓库, 团队可读, 持久化

二者并存不冲突。

## 写新 memory 的时机

- 用户明确纠正了 Claude(feedback)
- 项目级决策/约定(project)
- 反复用到的外部资源位置(reference)
- 用户角色/长期偏好(user)

**不需要写**: 单次会话调试细节 / git log 已有的信息 / 暂定不成熟的方案

## 长度上限

- feedback / user: 5-15 行
- project: 30-80 行
- reference: 链接 + 简短说明

超 100 行拆多个文件 + 在本索引加链接。

## 何时更新

每轮 (Round X) 多 agent 优化结束后, 沉淀 1-2 条新 memory。原则:
- 6 阶段中任何"新发现的关键经验"都值得存
- 同一类经验 6 轮已沉淀后, 不重复

## 隐私

如果某条 memory 含 API key / 内部 IP / 私有路径, 放 `.claude/memory/private/` 子目录(已在 .gitignore 排除)。
