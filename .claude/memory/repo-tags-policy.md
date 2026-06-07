---
name: repo-tags-policy
description: ScholarFlow 仓库必备标签文件清单 - LICENSE/VERSION/CHANGELOG/CONTRIBUTING/CODE_OF_CONDUCT/SECURITY/.editorconfig/.gitattributes/.github
metadata:
  node_type: memory
  type: project
  originSessionId: 84fec3b7-3ad7-4192-a373-7e48ddf349d2
---

# ScholarFlow 仓库标签文件政策

**Why**: 6 轮优化后仓库工程化,补齐 GitHub 主流仓库的标签文件。

**完整清单 (13 个)**:

| 类别 | 文件 | 用途 |
|------|------|------|
| **法律** | `LICENSE` | MIT 完整文本 |
| **法律** | `CODE_OF_CONDUCT.md` | Contributor Covenant v2.1 |
| **法律** | `SECURITY.md` | 漏洞披露 + 硬化总结 |
| **版本** | `VERSION` | 1.0.0 (semver) |
| **版本** | `CHANGELOG.md` | R1-R6 全部变更汇总 |
| **贡献** | `CONTRIBUTING.md` | 含多 agent 开发流程 |
| **GitHub** | `.github/ISSUE_TEMPLATE/bug_report.md` | 严重程度 + 环境字段 |
| **GitHub** | `.github/ISSUE_TEMPLATE/feature_request.md` | 优先级字段 |
| **GitHub** | `.github/ISSUE_TEMPLATE/security.md` | 私有披露 |
| **GitHub** | `.github/PULL_REQUEST_TEMPLATE.md` | 强制 root cause + verification |
| **GitHub** | `.github/CODEOWNERS` | qianbkk 拥有全部 |
| **工具** | `.editorconfig` | Python 4 空格 + TS 2 空格 |
| **工具** | `.gitattributes` | LF 规范化 + 二进制标记 |

## frontmatter 格式

所有 SCHEMA 文件 (CHANGELOG/SECURITY/CONTRIBUTING/CODE_OF_CONDUCT) 用 **Keep a Changelog** + **Semantic Versioning** 格式。

## README 末尾必须有的链接

```markdown
## 📜 License
MIT — see [LICENSE](LICENSE).
当前版本: [VERSION](VERSION) ([CHANGELOG](CHANGELOG.md))

## 📚 文档
- [CONTRIBUTING.md](CONTRIBUTING.md)
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- [SECURITY.md](SECURITY.md)
- [docs/FUTURE_TASKS.md](docs/FUTURE_TASKS.md)
- [.editorconfig](.editorconfig) / [.gitattributes](.gitattributes)
```

## 怎么补齐

发现缺哪个就补哪个,不必一次补齐 13 个。
**优先级**:
1. LICENSE + VERSION + CHANGELOG (法律 + 版本基础)
2. SECURITY + CODE_OF_CONDUCT (安全 + 社区)
3. CONTRIBUTING (开发流程)
4. .editorconfig + .gitattributes (工具链)
5. .github/* 模板 (GitHub UX)

## 教训

README 末尾不能只写"MIT"一行。
完整链接 + 文档索引 = 职业感,与"研究型 demo"区分开。
