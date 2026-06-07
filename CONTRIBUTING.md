# Contributing to ScholarFlow

Thank you for your interest in contributing! 🎉

## Development Setup

```bash
git clone https://github.com/qianbkk/ScholarFlow.git
cd ScholarFlow
cp .env.example .env
# 编辑 .env 填入 LLM API keys
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..

# 启动后端
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

# 启动前端 (新 terminal)
cd frontend && npm run dev

# 跑测试
python -m pytest tests/ -q
```

## Code Style

- **Python**: PEP 8 + type hints, 优先 dataclass 而非 TypedDict
- **TypeScript**: strict mode, 不用 `any`, 组件 props 必填字段用 interface
- **Commits**: 1 个 commit 1 个 fix, message 含 root cause + verification
- **测试**: 每个 fix 至少 1 个单测, E2E 真实 LLM 验证

## Pull Request Process

1. Fork repo + 创建 feature branch (`git checkout -b feature/xxx`)
2. 写代码 + 写测试 (`python -m pytest tests/ -q` 全过)
3. 写 commit (commit message 含 root cause + verification + refs)
4. 推送并开 PR,标题用 `feat:` / `fix:` / `refactor:` / `docs:` / `chore:` 前缀
5. 等 CI 通过 + 1 个 reviewer approve

## Multi-Agent Development

本项目采用 6 轮多 agent 审计 + 优化流程:

1. **审计阶段**: 3 个并行 agent(架构/性能/安全) 跑真实场景
2. **分类阶段**: 1 个 agent 合并去重 + 打空气 + 必/可/不分类
3. **执行阶段**: 4-5 个 agent 按文件切分并行执行
4. **review 阶段**: 全量测试 + 真实 LLM E2E + 浏览器识图
5. **简化阶段**: 冗余性分析 + /simplify
6. **push 阶段**: 全部验证后 push

新增功能或修复,请遵循相同的"独立 commit + 文件严格切分"原则,避免并发 agent 互相冲突。

## DCO Sign-Off (Developer Certificate of Origin 1.1)

本项目采用 [DCO 1.1](https://developercertificate.org/) 而非传统 CLA。所有 commit
必须包含 `Signed-off-by:` 行证明你有权贡献该代码:

```
Signed-off-by: Your Name <your.email@example.com>
```

### 设置 git 自动 sign-off

```bash
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
git config --local format.signOff true  # 本仓库已设
```

### commit 时加 sign-off

```bash
git commit -s -m "feat: 新功能描述"
# 或
git commit --signoff -m "feat: 新功能描述"
```

### 为什么不用 cla-assistant.io

传统 CLA (Contributor License Agreement) 需要法律实体签署, 流程重, 不适合学术开源项目。
DCO 是 Linux Kernel / Git / Docker 等 200+ 项目使用的轻量替代, 1 行 sign-off 即可
证明贡献者有权贡献代码。

## Code of Conduct

请友好、包容、专注技术。所有 PR 都基于代码质量评审,与作者身份无关。

## Community

- 💬 [GitHub Discussions](https://github.com/qianbkk/ScholarFlow/discussions) — 提问 / 想法 / 学术反馈
- 🐛 [Issue Tracker](https://github.com/qianbkk/ScholarFlow/issues) — Bug 报告
- 🎓 [Academic Feedback](.github/ISSUE_TEMPLATE/academic_feedback.md) — 检索质量反馈

> R10+ 计划：把 Discussion categories 进一步细分（学术 / 工程 / 安全），目前先用 GitHub 内置 categories。

## License

贡献的代码按 [MIT License](LICENSE) 发布。
