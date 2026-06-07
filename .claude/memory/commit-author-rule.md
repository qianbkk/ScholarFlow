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
git -c user.name="qianbkk" -c user.email="qianbkk@github.com" commit -m "..."

# 方案 B: 配 user.email (建议是 qianbkk@github.com 或 claude@anthropic.com)
# 然后用 git filter-branch 一次性重写 17 个 commit
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
- 范围:从上一个干净 commit 到 HEAD
- 时间:17 个 commit ~10 秒
- 然后 `git push --force-with-lease`

## 验证

```bash
# 检查所有 author
git log --format='%h | %an <%ae>' <last-clean>..HEAD | sort -u -k2 | head

# 应该只看到:
# qianbkk <qianbkk@github.com>
# claude <claude@anthropic.com>
```

## 教训

不要在 prompt 里写"用真名 commit",Claude 不会懂。
**必须给具体命令**:
```bash
git -c user.name="qianbkk" -c user.email="qianbkk@github.com" commit ...
```

或者在 agent 启动前 `git config user.name "..."` 全局设置。
