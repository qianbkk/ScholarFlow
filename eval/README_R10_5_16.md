# eval/ 评测数据说明 (R10.5.16)

## test_cases.json

35 个 case,每个 case 字段:

| 字段 | 类型 | 用途 |
|---|---|---|
| `query` | str | 用户查询原文 |
| `expected_papers` | list[str] | F1 评测金标 (paper titles) |
| `budget` | float | 单次预算上限 USD (默认 0.5) |
| `domain` | str | **R10.5.16 起为未来 R11+ 接入, 暂无 consumer** — 22 类领域标签, 计划在 f1_score.py 按域分组输出 (类似 GLUE/SQuAD leaderboard 风格). |

R10.5.16 (/simplify + /code-review 合并): `domain` 字段保留为 schema 的一部分 (R10.5.14 扩字段时统一加了), 暂未被任何代码读取 (R10.5.16 verify 确认). 选保留而非删除, 因为:
  - 删后 R11+ 再加回来要 diff 35 行 (vs 一次性加 1 段 f1_score.py)
  - 字段已通过 JSONSchema 隐式表达, 改了破坏向后兼容
  - R10.5.16 测试套件没断言缺字段, 保留零风险

如要立即激活 `domain` 字段, 在 eval/f1_score.py 加:
```python
domain_groups = {}
for case in cases:
    d = case.get("domain", "default")
    domain_groups.setdefault(d, []).append(case["query"])
# 按域报告每组 F1 + 全局 F1
```

## f1_score.py

R10.5.16 fix: 初始 state 补 `constraints: None` (跟 SearchState TypedDict 对齐, 防止后续 strict reader 读 state['constraints'] 时 KeyError).

## 新加 caller 同步

R10.5.16: 3 个非主路径 caller 同步补 `constraints: None`:
  - eval/f1_score.py
  - test_run.py
  - tests/manual/verify_random_queries.py
