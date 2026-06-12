"""R10.5.16 (/simplify + /code-review 合并修复): user_id 哈希单源.

R10.5.14-15 之前, 5 个 site 各自实现 "u_" + sha256(x).hexdigest()[:12]:
  - backend/auth/dependencies.py
  - backend/api/routes/auth.py (2 处: register + login)
  - backend/utils/audit_log.py (audit 通道)

风险: 切换 hash 长度 / prefix (e.g. 加 version byte 兼容历史) 必须 5 处同步, 漏一处
user_id 在 audit log 跟 auth 表对不上, SIEM 关联查询全错.

R10.5.16: 抽 backend/utils/user_id.py::hash_user_id(email) -> str 单源.
所有 5 个 caller 改成 from backend.utils.user_id import hash_user_id.

注意: 这只覆盖 *email-derived* user_id (跟 auth.dependencies 派生一致).
auth/issues_key 不动 — issue_key_for_email 内部仍用同样 SHA256 模式, 但 key 不
是 user_id 本身, 是另外的 token. 我们的 helper 跟 auth 路径保持一致即可.
"""
from __future__ import annotations

import hashlib


def hash_user_id(email: str | None) -> str | None:
    """从 email 派生 user_id (跟 backend/auth/dependencies.py 派生一致).

    格式: "u_" + sha256(email).hexdigest()[:12]
    None / 空串 → None (audit log 不记录 user_hash 字段).

    替换 5 处重复实现: backend/auth/dependencies.py / backend/api/routes/auth.py
    x2 / backend/utils/audit_log.py. 任何 hash 策略变更只动这里.
    """
    if not email:
        return None
    return "u_" + hashlib.sha256(email.lower().encode("utf-8")).hexdigest()[:12]
