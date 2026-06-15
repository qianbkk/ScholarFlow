"""
backend.auth.__main__ — CLI 工具: 显式管理 admin 白名单 (R10.5.28)

CG.txt 审计 P0 #2 修复: 删 "首个注册用户自动 admin" 后门, 改用 CLI 显式
管理. 持久化到 backend/.cache/admin.sqlite, 跨 worker 共享.

用法:
    python -m backend.auth.admin add <user_id> [--note "说明"]
    python -m backend.auth.admin list
    python -m backend.auth.admin remove <user_id>

示例:
    $ python -m backend.auth.admin add u_abc123def456 --note "初创 admin"
    ✓ admin added: u_abc123def456
    $ python -m backend.auth.admin list
    Admin 白名单 (2):
      - u_abc123def456  (2026-06-15 14:30:12, "初创 admin")
      - u_xyz789        (2026-06-15 14:35:00, "")
    $ python -m backend.auth.admin remove u_abc123def456
    ✓ admin removed: u_abc123def456
"""
from __future__ import annotations

import argparse
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.auth.admin",
        description="ScholarFlow admin 白名单 CLI 工具 (R10.5.28)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    add_p = sub.add_parser("add", help="添加 user_id 进 admin 白名单")
    add_p.add_argument("user_id", help="要加的 user_id (u_xxx 形式)")
    add_p.add_argument("--note", default="", help="可选说明 (e.g. '初创 admin')")

    sub.add_parser("list", help="列出所有 admin user_id")

    rm_p = sub.add_parser("remove", help="移 user_id 出 admin 白名单")
    rm_p.add_argument("user_id", help="要移除的 user_id")

    args = parser.parse_args()

    from backend.utils import admin_store

    if args.cmd == "add":
        if admin_store.add_admin(args.user_id, note=args.note):
            print(f"✓ admin added: {args.user_id}")
            return 0
        print(f"! admin already exists: {args.user_id}")
        return 1
    elif args.cmd == "remove":
        if admin_store.remove_admin(args.user_id):
            print(f"✓ admin removed: {args.user_id}")
            return 0
        print(f"! admin not found: {args.user_id}")
        return 1
    elif args.cmd == "list":
        ids = sorted(admin_store.list_admin_user_ids())
        if not ids:
            print("(空 — 还没显式配置 admin)")
            return 0
        print(f"Admin 白名单 ({len(ids)}):")
        for uid in ids:
            print(f"  - {uid}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
