"""
backend.auth.admin — CLI 入口 (R10.5.51 cleanup: 单一来源指向 __main__).

支持 `python -m backend.auth.admin {add,remove,list} <user_id>`.
实际实现仍在 `backend.auth.__main__:main()` (跟 `python -m backend.auth`
共享同一入口, 避免双份 CLI 维护).
"""
from backend.auth.__main__ import main

if __name__ == "__main__":
    import sys
    sys.exit(main())