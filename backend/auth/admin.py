"""
backend.auth.admin — R10.5.28 CLI 入口 alias.

让 `python -m backend.auth.admin ...` 跟 `python -m backend.auth.__main__ ...`
都能跑. 前者是更直观的子命令命名.
"""
from backend.auth.__main__ import main

if __name__ == "__main__":
    import sys
    sys.exit(main())
