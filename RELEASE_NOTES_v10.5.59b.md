# R10.5.59b — 左侧常驻 Settings + About tab + API Key 编辑

> 发布日期: 2026-06-21 · Tag: `v10.5.59b` · 贡献者: [@qianbkk](https://github.com/qianbkk)
>
> 在 R10.5.59 基础上的增量:左侧常驻设置菜单 + 关于 tab + API Key 可视化编辑 + README 重写 + .claude/ 入仓规则

## 🌟 Highlights

- 🍔 **左侧常驻 Settings 菜单** — 取代弹窗式 SettingsDrawer;可在 48px 与 220px 之间收起/展开,展开时显示完整 4 分组(语言 / 主题 / 运行时模式 / API Key),收起时显示精简 icon rail;状态持久化到 localStorage
- 📑 **About tab 作为第 5 个 tab** — 关于项目 / 快捷键 / 更新日志从 SettingsDrawer 移出,作为独立的可切换 tab,跟 查询/报告/图谱/历史 并列
- 🔑 **API Key 可视化编辑 + .env 持久化** — 后端 `/api/v1/config/env` GET/POST 端点,自动备份 `.env.bak`、白名单 5 个 provider(MiniMax/Kimi/GLM/Anthropic/DeepSeek)、同时更新 `os.environ` 让当前进程立即生效
- 📖 **README 全面重写** — 融合 `create-readme` + `readme-blueprint-generator` 两个 GitHub Copilot 技能的结构:Highlights / Quickstart / 架构图 / 8 节点流水线 / 配置表 / 目录树 / API 表格 / 快捷键 / i18n / Release notes
- 🔒 **.claude/ 入 .gitignore** — 整个 `.claude/` 目录(含 skills 和 memory)不再入仓

## 📦 Changes

### Frontend (R10.5.59b)

- **新增** `frontend/src/components/SettingsSidebar.tsx` (~230 LOC) — 左侧常驻可收起菜单
- **新增** `frontend/src/components/AboutView.tsx` (~80 LOC) — 第 5 个 tab
- **删除** `frontend/src/components/SettingsDrawer.tsx` — 弹窗版本
- `App.tsx` — 改为 `SettingsSidebar` + 主体 marginLeft 偏移布局
- `TopNav.tsx` — 删 ☰ hamburger 按钮 + 删中/EN 切换(移入 sidebar) + 加 'about' tab
- `useStore.ts` — 删 `settingsDrawerOpen`,加 `settingsCollapsed`(localStorage 持久化) + ViewId 加 'about'
- `i18n/index.ts` — 加 `sidebar.*`(8 key)+ `about.*`(15 key)+ `topbar.*`(5 key)
- `CommandPalette.tsx` — 调 `actions.toggleSettingsCollapsed` 替代 `openSettingsDrawer`

### Backend (R10.5.59b)

- **新增** `backend/api/routes/config.py` (~140 LOC) — `/api/v1/config/env` GET 列表 + POST 写入
- `backend/main.py` — 挂载 config_router

### 文档 / 仓库

- `README.md` — 全面重写 (Highlights / 架构 / 8 节点流水线 / 快捷键 / i18n / 5 版本 Release / 完整目录树)
- `RELEASES.md` — 加 R10.5.59b 章节
- `RELEASE_NOTES_v10.5.59b.md` (新建) — 本文件
- `.gitignore` — 加 `.claude/` 整目录忽略 (取代原 `.claude/memory/`)
- `git rm --cached .claude/skills/impeccable/` — 解除之前误入仓的所有 skill 文件

## ✅ Verification

- `npx tsc --noEmit`: **0 errors**
- `npm run build`: 620 modules, 2.21s, index 108.23 kB (gzip 31.72 kB)
- 后端 `/api/v1/config/env` 端到端测试:
  - GET 返回 5 个 provider 状态 + masked preview
  - POST 写入 in-place (count stays 1, 不重复) + 自动备份 .env.bak + 更新 os.environ
- 通过 vite proxy (5173 → 8000) 同样正常工作
- `SettingsSidebar` 收起/展开 4 分组渲染正确
- `AboutView` 5 个 tab 切换无误

## 🔗 Links

- 📖 [Documentation](https://github.com/qianbkk/ScholarFlow#readme)
- 🔖 [Previous: R10.5.59](https://github.com/qianbkk/ScholarFlow/releases/tag/v10.5.59)
- 🐛 [Report Issues](https://github.com/qianbkk/ScholarFlow/issues)
- 📜 [License: MIT](https://github.com/qianbkk/ScholarFlow/blob/master/LICENSE)

---

**Full Changelog**: https://github.com/qianbkk/ScholarFlow/compare/v10.5.59...v10.5.59b