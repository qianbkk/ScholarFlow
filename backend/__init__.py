"""ScholarFlow backend package."""
# P3-11 fix (深度审计 §P3-11): 与 VERSION 文件保持单一来源真相 (1.0.1).
# 旧值 1.0.0 滞后于 VERSION 文件, /health 端点 / OpenAPI schema 报旧版本号,
# 依赖版本号做特性开关的下游 (前端版本检查 / CI/CD 灰度) 会失准.
__version__ = "1.0.1"
