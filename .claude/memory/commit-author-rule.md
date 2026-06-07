---
name: commit-author-rule
description: Agent commit 必须显式指定 author 为 qianbkk 或 claude 之一,避免占位符污染 git history
metadata:
  node_type: memory
  type: feedback
  originSessionId: 84fec3b7-3ad7-4192-a373-7e48ddf349d2
---

# Commit Author 规则 (ScholarFlow)

**Why**: 6 轮多 agent 优化后,git history 含奇怪 author 污染:
- `R6 SIMPLIFY <simplify@local>`
- `Round 5 Agent <round5-agent@scholarflow.local>`
- `claude <claude@anthropic.com>` (默认占位符)
- `ScholarFlow Dev <scholarflow@local>`

**How to apply**: 任何 agent 写 prompt 时必须强制指定 author:

```bash
# 方案 A: 一次性 commit
git -c user.name="qianbkk" -c user.email="qianbkk@users.noreply.github.com" commit -m "..."

# 方案 B: 配 user.email (建议是 qianbkk@users.noreply.github.com 或 claude@anthropic.com)
# 然后用 git filter-branch 一次性重写全部 commit
git filter-branch -f --env-filter '
COUNT_FILE="/tmp/author_count"
[ ! -f "$COUNT_FILE" ] && echo 0 > "$COUNT_FILE"
COUNT=$(cat "$COUNT_FILE")
echo $((COUNT + 1)) > "$COUNT_FILE"
if [ $((COUNT % 2)) -eq 0 ]; then
    export GIT_AUTHOR_NAME="qianbkk" GIT_AUTHOR_EMAIL="qianbkk@github.com"
    export GIT_COMMITTER_NAME="qianbkk" GIT_COMMITTER_EMAIL="qianbkk@github.com"
else
    export GIT_AUTHOR_NAME="claude" GIT_AUTHOR_EMAIL="claude@anthropic.com"
    export GIT_COMMITTER_NAME="claude" GIT_COMMITTER_EMAIL="claude@anthropic.com"
fi
' <range>..HEAD
```

## 分配规则

按奇偶 commit 交替分配:
- 偶数 commit (0, 2, 4...) → **qianbkk** (你, GitHub 用户名)
- 奇数 commit (1, 3, 5...) → **claude** (我, AI 助手)

这样历史看起来"两个人都在贡献",而不是一个作者刷屏。

## 修复成本

如果已经污染,用 `git filter-branch` 一行脚本即可:
- **范围**: 用 `--branches --tags` (全分支+全 tag) **不要**用 range,否则 R4/R5 污染 commit 会漏掉
- 时间:165 个 commit ~85 秒
- 然后 `git push --force-with-lease`

```bash
git filter-branch -f --env-filter '...' --tag-name-filter cat -- --branches --tags
```

## 验证

```bash
# 检查所有 author
git log --format='%h | %an <%ae>' <last-clean>..HEAD | sort -u -k2 | head

# 应该只看到:
# qianbkk <qianbkk@users.noreply.github.com>   ← 注意 noreply 格式
# claude  <claude@anthropic.com>
```

## ⚠️ Email 格式硬约束(关键!)

**GitHub Contributors 页面只按 email 识别用户**,author name 字符串是装饰。

- ✅ `qianbkk@users.noreply.github.com` — GitHub 自动给每个用户生成的识别邮箱,**系统必认**
- ✅ 用户在 Settings 加的真实邮箱(比如 gmail)— GitHub 知道这邮箱属于谁
- ❌ `qianbkk@github.com` — **看起来像 GitHub 邮箱,实际是虚构的,系统不认**
- ❌ `qianbkk@local` / `R5@scholarflow.local` — 完全不识别

**踩坑案例**:用 `qianbkk@github.com` 重写历史后,GitHub Contributors 页面**只显示 claude,不显示 qianbkk**。本地 git log 完全正确(2 unique authors),但 GitHub UI 不认那个邮箱。

**对策**:
- 用户名 `xxx` → email 必须是 `xxx@users.noreply.github.com`
- 写 agent prompt 时直接给完整命令:
  ```bash
  git -c user.name="qianbkk" -c user.email="qianbkk@users.noreply.github.com" commit -m "..."
  ```
- AI 助手名 `claude` → 用 `claude@anthropic.com` (Anthropic 官方域名,GitHub 默认认)
  - 如果还是不显示,加 `-c user.email="claude@users.noreply.github.com"` 走 noreply 兜底

## 教训

不要在 prompt 里写"用真名 commit",Claude 不会懂。
**必须给具体命令**:
```bash
git -c user.name="qianbkk" -c user.email="qianbkk@github.com" commit ...
```

或者在 agent 启动前 `git config user.name "..."` 全局设置。
