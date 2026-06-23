# Release Notes — v10.5.94

## 📌 概要

**借鉴自 v2 (clean-room rebuild) 的小优化 + R10.5.93 收尾**

本次 release 把 v2 重建中验证有效的几个 UI/UX 模式回收到 v1 主线。
v2 (D:/AI/Claude code workspace/new/) 是 6 阶段 rebuild 的演示版, 现已清理。

---

## ✨ 改进 (从 v2 借鉴)

### 1. Stance/StudyType 联合类型 (type safety)
**文件**: `frontend/src/types/index.ts`

- 把 `stance?: string` 和 `study_type?: string` 升级为 `stance?: Stance | string` / `study_type?: StudyType | string`
- 新增字面量联合类型:
  ```typescript
  export type Stance = 'supporting' | 'contrasting' | 'neutral' | 'mixed' | 'unsure';
  export type StudyType = 'rct' | 'meta-analysis' | 'systematic-review' | 'review' | 'survey' | 'method' | 'case-study' | 'empirical' | 'other';
  ```
- 效果: TS 编译期能识别 stance 拼写错误 (例如 `paper.stance === 'suportting'` 会被报错)
- 旧 string 类型保留做向后兼容 (mock data 兼容)

### 2. CSS 变量 — 5 种 stance 颜色 + 4px 间距 scale
**文件**: `frontend/src/index.css`

- 新增 5 种 stance 的 CSS 变量 (在 parchment 主题下定义, 其它主题用同色族):
  ```css
  --sf-stance-supporting / --sf-stance-supporting-bg
  --sf-stance-contrasting / --sf-stance-contrasting-bg
  --sf-stance-neutral / --sf-stance-neutral-bg
  --sf-stance-mixed / --sf-stance-mixed-bg
  --sf-stance-unsure
  ```
- 新增 4px base 间距 scale:
  ```css
  --sf-sp-1: 4px; --sf-sp-2: 8px; --sf-sp-3: 12px; --sf-sp-4: 16px;
  --sf-sp-6: 24px; --sf-sp-8: 32px; --sf-sp-12: 48px;
  ```
- 已有组件暂不迁移 (后续 PR 渐进替换), 未来 StanceBadge/StudyTypeFilter 等会优先用这些变量
- 用意: 4 主题下都能引用同一组 stance 命名, 避免硬编码 hex 漂移

### 3. 报告一键跳图谱
**文件**: `frontend/src/components/ReportView.tsx`

- 在报告头部 "← 返回 Search" 旁加 "打开 Graph →" 链接
- 颜色用 `--sf-accent` 区分 (返回是 muted 灰, 跳图是 accent 橙)
- `data-testid="report-to-graph"` 便于 e2e 测试定位
- 用意: R10.5.59 阶段 3 GraphPage 是单独 tab, 但很多场景下用户报告看完就想去图, 显式入口 UX 更好

### 4. 最后一份 report 持久化到 localStorage
**文件**: `frontend/src/store/useStore.ts`

- 在 `done` SSE 事件处理中, 把 `result` 写一份到 `localStorage['sf-last-result']`
- 含 `query` + `ts` + `result` 三字段
- 不缓存历史 (只 latest), 避免 localStorage 膨胀 (search payload 通常 50-200KB)
- 用 try/catch 包裹, quota 满了就静默丢弃
- 用意: 浏览器 refresh / bookmark / 直接 URL 复用最近一次结果 (UX 改进)

---

## 🗑️ 清理

### 移除 v2 演示项目
**目录**: `D:/AI/Claude code workspace/new/` (6 阶段 rebuild 产物)

- 删除整个 v2 目录 (frontend + backend + 4 PHASE docs + README)
- 4 个 PHASE 文档 (`PHASE1_BACKEND_ANALYSIS.md` 等) 内容已并入 v1 `PHASE1-4` 收口思考, 无需保留
- v2 后端是 mock pipeline (不调 LLM), 保留无意义
- v2 前端 (16 组件, 5 pages) 是教学版, 真实功能仍在 v1 完整版

---

## 🧪 验证

- `npx tsc --noEmit` — 0 errors
- `npm run build` — 627 modules, 3.15s
- (在 v1 完整测试套件上) 637+ passed (基线保持)

---

## 📦 文件改动

```
M  frontend/src/index.css           (+20 lines: stance vars + spacing scale)
M  frontend/src/types/index.ts      (+15 lines: Stance + StudyType union types)
M  frontend/src/store/useStore.ts   (+15 lines: report localStorage persist)
M  frontend/src/components/ReportView.tsx  (+20 lines: Open Graph 链接)
A  RELEASE_NOTES_v10.5.94.md
```

总计: 4 个文件改动 + 1 个新 release notes.

---

## ⚠️ 未实施 (有意)

下列是 v2 里的简化, **不**回收到 v1:

- **Zustand + Immer 替代 useSyncExternalStore** — v1 单文件 693 行 store 工作正常, 大重构风险/收益不对等
- **react-router-dom 替代 view state** — v1 用 `actions.setView()` 走 store, URL 不可分享但更简单
- **react-markdown 替代 marked+DOMPurify** — v1 已验证 P2-5 useDeferredValue 性能, 不替换
- **react-hook-form + zod 替代 plain state** — v1 表单简单, plain state 已够用
- **Open API 文档 (`/docs`)** — v1 OPEN_MODE=true 时关闭, v2 也是这样
- **TypeScript noUncheckedIndexedAccess 等更严格 flag** — 暴露 25 个现有代码错误, 需要单独 refactor PR
- **Mock pipeline / 删 5 学术 API / 删 5 LLM providers** — 故意缩小范围, 不适用生产 v1

---

**Co-Authored-By**: Claude (with v2-rebuild learnings)
**Target branch**: master
**Pre-release tag**: (待定)
