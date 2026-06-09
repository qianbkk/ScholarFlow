"""
utils.cache — 查询结果 SQLite 缓存（避免重复跑流水线）
====================================================

- 同一 query + max_iterations + budget 在 TTL 内直接返回上次结果
- TTL 默认 24h，可由环境变量 CACHE_TTL_SECONDS 控制
- 整个缓存可通过环境变量 ENABLE_SEARCH_CACHE=false 关闭
- 缓存文件存放在 backend/.cache/search_cache.sqlite（已在 .gitignore 中）

并发安全（犀利评论 #10 修复）：
- 启用 WAL（Write-Ahead Logging）模式 — 支持多 reader + 1 writer 并发
- busy_timeout=5s — 等待锁释放而非立即抛 OperationalError
- OperationalError 时指数退避重试 — Gunicorn 多 worker 部署不再 500

H4 修复：async 变体（get_cached_async / set_cached_async）：
- 旧实现的 time.sleep(0.05 * 2**attempt) 在 async 调用栈中会阻塞事件循环
- 新实现的 asyncio.sleep + asyncio.to_thread 把 SQLite I/O 和退避 sleep 都 offload

P1 修复：cache_key 加 provider 维度（跨 provider 同 query 缓存隔离）。
P1 修复：_init_db_once 标志位（避免每次 get_cached_async/set_cached_async 都做 schema 检查）。

R7 评估 (reviewer feedback: "为何不用 aiosqlite"):
- 当前实现线程安全: 每次 op 都 _connect_with_wal() 新建连接 + 操作完 conn.close(),
  不跨线程共享 connection, 所以 check_same_thread=False 都不需要 (Python sqlite3 默认
  check_same_thread=True 只在跨线程持有同一 connection 时才会炸)。
- 但 aiosqlite 确实是 Python 生态共识: 1) 真正的 async 路径, 不用 to_thread; 2) 避免
  任何"看似 OK 实则边界 case 会炸"的隐患; 3) Gunicorn 多 worker + 多 host 部署时更稳。
- 本轮 R7 不改: aiosqlite 重构涉及 4 个函数签名 + 5 个测试 fixture + 5 个 commit 依赖,
  风险/收益比不划算。R8 计划: 替换 async 栈为 aiosqlite 单栈, 配合 SQLAlchemy 2.0
  async session (跟未来 R5 ARCH-008 cache_key mode 维度 + K8s 多 worker 一并上)。
- 当前已知限制: to_thread 把 SQLite I/O 扔到默认 ThreadPoolExecutor, 高并发下
  线程池排队会抵消部分 offload 收益。生产环境建议显式设 loop.default_executor =
  ThreadPoolExecutor(max_workers=32) (FastAPI lifespan 阶段)。

R9 清理: 删除同步版 get_cached / set_cached (R8 审计报告 — 死代码,生产从未调用)
和同步 retry helper _retry_sqlite_op (async 版 _retry_sqlite_op_async 仍保留)。
只剩 async 公共 API: get_cached_async / set_cached_async。

R10 增量 (M-D P0-D): 加 query_embedding BLOB 列 (语义缓存 / numpy cos-sim 检索)
- 旧 cache 表自动 ALTER TABLE ADD COLUMN (Python 端 idempotent ALTER, 只在缺列时加)
- 新表直接在 CREATE TABLE 里加列
- semantic_cache.py 读 query_embedding BLOB 时 numpy 余弦相似度 top-1
- BLOB 缺失时退化到精确匹配路径 (get_semantic_cached 返 None)
- _set_cached_sync 改用命名列 INSERT, 加新列时无需改 INSERT 语句

R10.5 Fix-X7: 删 query_embedding 列的代码路径.  semantic_cache.py 已
成占位桩 (Fix-E), 真实 embedding 留 R11.  新建表不再带 query_embedding
列, ALTER TABLE 迁移代码删除 (旧表里这列保留不动, 不影响功能).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import time
from pathlib import Path


_cache_logger = logging.getLogger(__name__)

_CACHE_DIR = Path(__file__).parent.parent / ".cache"
_CACHE_DIR.mkdir(exist_ok=True)

# R10.5 Fix-P0-3 (P0-3 审计 X.md §3.1 + AAA.txt P0-3): 连接字符串参数化.
# 默认行为 (向后兼容): search_cache + budget + auth 三类表共用同一 SQLite 文件
# backend/.cache/search_cache.sqlite. 这是 R10.5 之前的设计, 所有现有测试 / 部署依赖.
#
# 升级路径 (env var 启用):
#   - SCHOLARFLOW_DB_DIR=/path/to/dir  → 强制 3 类表分文件:
#       search_cache.sqlite / budget.sqlite / auth.sqlite
#   - 是 K8s 横向扩展的前置条件 (不同表不再争同一写锁).
#
# 中期方案 (R10.6+): Redis 替代 budget/auth 状态, 保留 SQLite 只存 search_cache
# 长期方案 (R11+): PostgreSQL 存 user/auth, 跨多实例共享.
#
# R10.5 simplify: 单源 filename table (避免两个 dict 重复); 路径在模块导入时
# 一次性解析 + 缓存 (避免每次 _connect_with_wal 都 os.environ.get + mkdir).
_FILENAMES = {"cache": "search_cache.sqlite", "budget": "budget.sqlite", "auth": "auth.sqlite"}


def _init_db_paths() -> dict[str, Path]:
    """根据 env 一次性解析 3 类表路径. 模块导入时跑一次."""
    override_dir = os.environ.get("SCHOLARFLOW_DB_DIR")
    if override_dir:
        d = Path(override_dir)
        d.mkdir(parents=True, exist_ok=True)
        return {role: d / filename for role, filename in _FILENAMES.items()}
    default = _CACHE_DIR / _FILENAMES["cache"]
    # 默认: 三类表共用 search_cache.sqlite (向后兼容)
    return {role: default for role in _FILENAMES}


_DB_PATHS: dict[str, Path] = _init_db_paths()
_DB = _DB_PATHS["cache"]  # 兼容旧 _DB 引用 (tests/ monkeypatch)

# 并发安全：5s 等待锁超时（Gunicorn 多 worker 写同一文件时不会立即抛 lock 错）
_BUSY_TIMEOUT_MS = 5000
# OperationalError 重试上限（指数退避 50ms / 100ms / 200ms）
_MAX_RETRIES = 3

# P1 修复：_init_db_once 标志位，避免每个 cache 操作都跑一次 schema 检查。
# 旧实现：get_cached_async / set_cached_async 都会调 _init_db()，
# 每次都做 SELECT sqlite_master + PRAGMA table_info + CREATE TABLE 检查，浪费 ~2-5ms。
# 新实现：进程内仅首次跑 _init_db()，后续直接跳过。
# 同时记录上次 init 的 DB 路径：如果 monkeypatch / test fixture 切换了
# _DB 到新路径（例如测试隔离用 tmp_path），下次访问会自动 re-init。
_DB_INITIALIZED = False
_DB_INITIALIZED_PATH: str | None = None


def _connect_with_wal(role: str | None = None) -> sqlite3.Connection:
    """建立支持 WAL 并发模式的 SQLite 连接.

    Args:
        role: 表角色. None (默认) = 用模块级 _DB 变量 (向后兼容, 测试可 monkeypatch).
              "cache" / "budget" / "auth" = 查 _DB_PATHS 缓存. 路径在模块导入时
              一次性解析 + 缓存, 这里只是 dict lookup.

    Returns:
        sqlite3.Connection — 每次返回新连接（避免跨线程持有同一连接）
    """
    # 向后兼容: 测试 monkeypatch cache_mod._DB (legacy fixture) 切到 tmp_path.
    # 旧 _DB 引用反映 monkeypatch, _DB_PATHS 是模块导入时缓存的不可变副本.
    # 当 _DB != _DB_PATHS["cache"] 时, 优先 _DB (test fixture 模式).
    if role is not None and _DB == _DB_PATHS["cache"]:
        # 生产: 走 _DB_PATHS (避免每次 env lookup)
        db_path = _DB_PATHS[role]
    else:
        # 测试 fixture 模式 或 role=None: 用模块级 _DB 变量
        db_path = _DB
    conn = sqlite3.connect(str(db_path), timeout=_BUSY_TIMEOUT_MS / 1000)
    # WAL 模式是持久化的（写入数据库文件 header），只需设置一次
    # 但每次连接都执行 PRAGMA 是无害的（PRAGMA 是幂等的）
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    # WAL + 多进程下，建议 NORMAL 同步级别（性能 / 安全平衡点）
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _init_db() -> None:
    """初始化 cache 表 + WAL 模式。幂等。

    H8 修复：旧 schema 在 search_cache 表里存了完整 query 文本，
    配合 query_hash 暴露了"哪些 query 被搜过 + 返回了哪些结果"。
    Cache 文件一旦泄露（read 权限错误、备份文件、CI artifact），
    攻击者直接拿到所有用户查询历史和报告内容。新 schema 只存
    `query_hash`（不可逆 SHA-256 摘要）+ 响应。
    """
    conn = _connect_with_wal()
    try:
        # ===== 检测旧 schema 并就地迁移 =====
        # 三种情况：
        #   a) 表不存在         → 直接 CREATE 新表
        #   b) 表存在但带 query 列 → 迁移：建新表 + 拷数据 + DROP + RENAME
        #   c) 表存在且无 query 列 → 什么都不做（幂等）
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='search_cache'"
        )
        table_exists = cur.fetchone() is not None

        if table_exists:
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(search_cache)").fetchall()
            }
            if "query" in cols:
                # 旧表带 query 列：CREATE 新表 → 拷无 query 数据 → DROP → RENAME
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS search_cache_new (
                        query_hash TEXT PRIMARY KEY,
                        response_json TEXT NOT NULL,
                        cost_usd REAL NOT NULL,
                        tokens INTEGER NOT NULL,
                        created_at REAL NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO search_cache_new
                        (query_hash, response_json, cost_usd, tokens, created_at)
                    SELECT query_hash, response_json, cost_usd, tokens, created_at
                    FROM search_cache
                    """
                )
                conn.execute("DROP TABLE search_cache")
                conn.execute("ALTER TABLE search_cache_new RENAME TO search_cache")
                # SQLite DROP TABLE 不会实际擦除数据页 — query 文本仍残留在
                # 释放的 page 中直到 VACUUM 重建整个文件。这里必须 VACUUM
                # 才能让原始 query 文本真正从磁盘文件中消失 (H8 隐私目标)。
                # 注意: VACUUM 不能在事务内执行,先 commit 再调。
                conn.commit()
                conn.execute("VACUUM")
                import logging
                logging.getLogger(__name__).info(
                    "[cache] H8 migration: dropped `query` column + VACUUM "
                    "to scrub original query text from disk (privacy hardening)"
                )
            # Fix-X7: 删除 R10 M-D P0-D 引入的 query_embedding BLOB 列
            # 迁移. semantic_cache.py 已成占位桩, 真实 embedding 留 R11,
            # 现在加这个 ALTER TABLE 反而让维护者困惑"为什么有这个列".
            # 现有表里的 query_embedding 列保留不动 (不影响功能, NULL 默认值)
            # — 但不再有代码向它写入或读取, 也不会新建表加这列.
        else:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS search_cache (
                    query_hash TEXT PRIMARY KEY,
                    response_json TEXT NOT NULL,
                    cost_usd REAL NOT NULL,
                    tokens INTEGER NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
        # R10.5 Fix-P0-B: 多用户 + API Key 认证.
        # users 表: api_key_hash (sha256, 不存明文) + display_name + created_at.
        # budget_user 表: 替代原 budget_state 单 global 行的 per-user 余额.
        # OPEN_MODE=true 时所有用户共享 'dev-user' 虚拟账户, 行为跟旧版一致.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                api_key_hash TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS budget_user (
                user_id TEXT PRIMARY KEY,
                spent_usd REAL NOT NULL DEFAULT 0.0,
                reserved_usd REAL NOT NULL DEFAULT 0.0,
                last_reset_hour INTEGER NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _init_db_once() -> None:
    """P1 优化：首次初始化后跳过 schema 检查。

    旧实现：每次 get_cached_async/set_cached_async 都跑 _init_db() — 每次 ~2-5ms 的
    SELECT sqlite_master + PRAGMA table_info 检查。在 /search 高频调用场景下
    累积开销可观。新实现：进程内模块级标志 _DB_INITIALIZED 保证 _init_db()
    只在首次调用时执行。

    DB 路径变更自纠正：若测试 fixture / monkeypatch 切换了 _DB 到新路径
    （典型场景：test_cache_no_query_text 用 tmp_path 隔离 DB），下次调用
    会检测到 _DB 路径与上次 init 不同，自动 re-init。这样测试可以独立
    切 DB 而不必关心 _DB_INITIALIZED 状态。

    注意：
      - 线程安全：CPython GIL 下 bool 赋值是原子的，单进程多线程场景无竞争。
      - 进程隔离：每个 worker 进程独立维护 _DB_INITIALIZED，跨进程仍会
        各跑一次（一次/进程 = 可接受）。
      - schema migration 路径：仍由 _init_db() 自身处理（首次调用检测旧
        schema 并就地迁移），所以保留幂等性。
    """
    global _DB_INITIALIZED, _DB_INITIALIZED_PATH
    if _DB_INITIALIZED and _DB_INITIALIZED_PATH == str(_DB):
        return
    _init_db()
    _DB_INITIALIZED = True
    _DB_INITIALIZED_PATH = str(_DB)


def cache_key(
    query: str,
    max_iterations: int,
    budget: float,
    provider: str | None = None,
) -> str:
    """P1 修复：cache_key 增加 provider 维度，跨 LLM provider 同 query 不再串。

    旧实现：只 hash (query, max_iterations, budget)，导致用 kimi 搜的缓存结果
    被 glm/anthropic 等 provider 误命中。修复后：相同 query 在不同 provider 下
    生成不同 cache key，避免跨 provider 缓存污染。

    向后兼容：provider 参数默认 None → 拼成 "default"，与旧 key 行为不同
    （旧 key 字符串里没有 provider 段）。这是一个**有意的破坏** — 旧 cache
    行（如果有）会被视为新 key 失效，触发一次重算。考虑到旧 key 没有 provider
    信息，保留旧 key 反而会跨 provider 污染，所以这里接受一次失效。

    Fix-X5: 取消 R10.5 Fix-L 的 0.5 USD 分桶 (PPP 报告建议, 但跟 router
    决策的剩余预算触发条件冲突: budget 1.3 可能 1 轮完成, 1.7 可能 2 轮,
    同 query 同 key 会拿到 1 轮结果污染 1.7 轮预期). 改用精确 budget (cents):
      - 1.30 → 130, 1.70 → 170, 1.99 → 199
      - 同 budget + 同 query + 同 provider → 命中 (跟分桶前一样)
      - 不同 budget → 不同 key (语义正确, 牺牲少量命中率换语义安全)
    """
    # 精确到分 (cents), 避免浮点 hash 不一致
    budget_cents = round(budget * 100)
    return hashlib.sha256(
        f"{query.strip().lower()}|{max_iterations}|{budget_cents}|{provider or 'default'}".encode()
    ).hexdigest()[:32]


# ===== H4 修复：async 同步辅助函数（offload 阻塞 I/O 到线程） =====

async def _retry_sqlite_op_async(sync_fn, *args, **kwargs):
    """async 版：把 sync_fn 放到线程池跑，退避用 asyncio.sleep（不阻塞事件循环）。

    H4 修复：旧实现 get_cached_async 的 time.sleep(0.05 * 2**attempt) 在 async
    调用栈中会阻塞事件循环最长 350ms。改用 asyncio.sleep 后事件循环可继续
    处理其他请求。
    """
    for attempt in range(_MAX_RETRIES):
        try:
            return await asyncio.to_thread(sync_fn, *args, **kwargs)
        except sqlite3.OperationalError as e:
            if attempt < _MAX_RETRIES - 1:
                await asyncio.sleep(0.05 * (2 ** attempt))
                continue
            _cache_logger.warning(
                f"[cache] {sync_fn.__name__} failed after {_MAX_RETRIES} retries: {e}"
            )
            return None
    return None


def _get_cached_sync(key: str, ttl_seconds: int):
    """同步 SQLite cache 读。被 get_cached_async 通过 asyncio.to_thread 调用。"""
    _init_db_once()
    conn = _connect_with_wal()
    try:
        row = conn.execute(
            "SELECT response_json, cost_usd, tokens, created_at "
            "FROM search_cache WHERE query_hash=?",
            (key,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    if time.time() - row[3] > ttl_seconds:
        return None
    return json.loads(row[0]), row[1], row[2]


def _set_cached_sync(key: str, response: dict, cost_usd: float, tokens: int) -> None:
    """同步 SQLite cache 写。被 set_cached_async 通过 asyncio.to_thread 调用。

    H8 修复：不再接受 `query` 参数 — query 文本不落盘，cache 里只存 hash。
    M-D 修复：用命名列 INSERT 而不是 VALUES (?,?,?,?,?), 加新列(如 query_embedding)
    时无需改 SQL — 当前 INSERT 只写 5 个非 BLOB 列, query_embedding 留 NULL。
    """
    _init_db_once()
    payload = (
        key,
        json.dumps(response, ensure_ascii=False),
        cost_usd,
        tokens,
        time.time(),
    )
    conn = _connect_with_wal()
    try:
        # 命名列 INSERT: 加新列时 (如 query_embedding) 不需要改这里,
        # 新列默认 NULL,semantic_cache.py 后续可以 UPDATE 补 BLOB
        conn.execute(
            "INSERT OR REPLACE INTO search_cache "
            "(query_hash, response_json, cost_usd, tokens, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            payload,
        )
        conn.commit()
    finally:
        conn.close()


# ===== H4 修复：async 变体 — 不阻塞事件循环 =====

async def get_cached_async(
    query: str,
    max_iterations: int,
    budget: float,
    ttl_seconds: int | None = None,
    provider: str | None = None,
):
    """async 公共 API：把 SQLite I/O 放到线程池，retry 退避用 asyncio.sleep。

    R9 清理后唯一保留的 cache 读 API（同步版 get_cached 已删）。
    改用 asyncio.to_thread + asyncio.sleep 后，重试期间事件循环可继续处理其他请求。
    """
    if os.getenv("ENABLE_SEARCH_CACHE", "true").lower() != "true":
        return None
    if ttl_seconds is None:
        ttl_seconds = int(os.getenv("CACHE_TTL_SECONDS", "86400"))

    key = cache_key(query, max_iterations, budget, provider)
    # 退避重试逻辑抽到 _retry_sqlite_op_async (Round N SIMPLIFY)
    return await _retry_sqlite_op_async(_get_cached_sync, key, ttl_seconds)


async def set_cached_async(
    query: str,
    max_iterations: int,
    budget: float,
    response: dict,
    cost_usd: float,
    tokens: int,
    provider: str | None = None,
) -> None:
    """async 公共 API：把 SQLite I/O 放到线程池，retry 退避用 asyncio.sleep。

    R9 清理后唯一保留的 cache 写 API（同步版 set_cached 已删）。

    H8 修复：query 文本不再传递给 _set_cached_sync（只 cache_key 用来算 hash）。
    """
    if os.getenv("ENABLE_SEARCH_CACHE", "true").lower() != "true":
        return
    key = cache_key(query, max_iterations, budget, provider)
    # 退避重试逻辑抽到 _retry_sqlite_op_async (Round N SIMPLIFY)
    await _retry_sqlite_op_async(
        _set_cached_sync, key, response, cost_usd, tokens,
    )
