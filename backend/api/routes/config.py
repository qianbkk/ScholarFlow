"""
backend.api.routes.config
=========================

R10.5.59b: /api/v1/config/env — 多模型 API Key 管理 (上限 10 个).

每个 provider (minimax / kimi / glm / anthropic / deepseek) 最多 2 个 key
(round-robin 负载均衡, 1 个 fallback). 总上限 10 keys 全局.

存储格式 (项目根 .env):
  MiniMax_API_KEY="<primary>"
  MiniMax_API_KEY_2="<secondary>"

  或带 alias (前端 UI 显示):
  MiniMax_API_KEY_PRIMARY="sk-cp-4n..."
  MiniMax_API_KEY_SECONDARY="sk-test-2..."

SettingsSidebar 调用:
  GET  → 所有 provider 的 keys 列表 + masked_preview + alias
  POST → 新增一个 key (provider + alias + api_key)
  PUT  → 修改已有 key (provider + alias + api_key)
  DELETE → 删除指定 key (provider + alias)

安全性:
  - 必须登录 (Depends(get_current_user))
  - 写入前 .env 自动备份 .env.bak
  - 仅允许写入预定义 provider (white-list)
  - 同步更新 os.environ 让当前进程立即生效
"""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.auth.dependencies import User, get_current_user

logger = logging.getLogger(__name__)

# Provider 元数据 (id, label, env_var_pattern, default_alias)
# env_var_pattern: provider 的 primary key env var 名字 (无后缀, alias 由前端给)
PROVIDERS = {
    "minimax":   {"label": "MiniMax",   "env_var": "MiniMax_API_KEY",   "model_id": "minimax",   "color": "#c2410c"},
    "kimi":      {"label": "Kimi",      "env_var": "KIMI_API_KEY",      "model_id": "kimi",      "color": "#0e7490"},
    "glm":       {"label": "GLM",       "env_var": "GLM_API_KEY",       "model_id": "glm",       "color": "#7c3aed"},
    "anthropic": {"label": "Anthropic", "env_var": "ANTHROPIC_API_KEY", "model_id": "anthropic", "color": "#d97706"},
    "deepseek":  {"label": "DeepSeek",  "env_var": "DEEPSEEK_API_KEY",  "model_id": "deepseek",  "color": "#0f766e"},
}

# 上限: 全局 10 个, 单 provider 2 个 (primary + fallback).
MAX_KEYS_PER_PROVIDER = 2
MAX_KEYS_GLOBAL = 10

# .env 文件路径 (项目根目录)
def _env_path() -> Path:
    return Path(__file__).resolve().parents[3] / ".env"


def _mask(value: str) -> str:
    """Mask API key: 保留前 6 字符 + 后 4 字符,中间 ... 省略."""
    if len(value) <= 12:
        return "***"
    return f"{value[:6]}...{value[-4:]}"


def _parse_env(path: Path) -> dict[str, str]:
    """解析 .env → {KEY: VALUE}, last-wins."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Za-z][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        out[key] = val
    return out


def _backup_env(path: Path) -> str:
    """备份 .env → .env.bak, 返 backup path."""
    backup = str(path) + ".bak"
    if path.exists():
        try:
            Path(backup).write_text(path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        except Exception as e:
            logger.warning(f"[config] backup failed: {e}")
    return backup


# ===== Pydantic 模型 =====

class KeyEntry(BaseModel):
    """单个 API key 条目."""
    provider: str          # "minimax" / "kimi" / ...
    env_var: str           # "MiniMax_API_KEY" (alias 嵌入 env_var 后缀)
    alias: str             # "primary" / "secondary" / "minimax-1" / 用户自定
    masked_preview: Optional[str] = None
    is_active: bool = True  # False = 已废弃但保留在 .env


class ProviderKeys(BaseModel):
    provider: str
    label: str
    env_var_prefix: str    # "MiniMax_API_KEY"
    model_id: str          # "minimax"
    color: str
    keys: list[KeyEntry]   # 0-2 条


class EnvStatusResponse(BaseModel):
    path: str
    max_keys_global: int
    max_keys_per_provider: int
    providers: list[ProviderKeys]


class EnvSetRequest(BaseModel):
    """新增或修改一个 key."""
    provider: str = Field(..., min_length=2, max_length=32)
    alias: str = Field(..., min_length=1, max_length=64, description="alias 标识, e.g. 'primary', 'minimax-1', 'prod-east'")
    api_key: str = Field(..., min_length=8, max_length=512)


class EnvSetResponse(BaseModel):
    provider: str
    env_var: str
    alias: str
    saved_to: str
    backup: str


class EnvDeleteRequest(BaseModel):
    provider: str = Field(..., min_length=2, max_length=32)
    alias: str = Field(..., min_length=1, max_length=64)


class EnvDeleteResponse(BaseModel):
    deleted: bool
    provider: str
    alias: str


# ===== Provider-scoped env var 命名 =====

def _env_var_for(provider: str, alias: str) -> str:
    """生成 env var 名字. 'minimax' + 'primary' → 'MiniMax_API_KEY' (no suffix).

    Aliases 'primary' / '1' / 'default' 不加后缀 (向后兼容旧 .env 格式).
    其他 alias 加 _<ALIAS_UPPER> 后缀.
    """
    base = PROVIDERS[provider]["env_var"]
    normalized = alias.lower().strip()
    if normalized in ("primary", "1", "default", ""):
        return base
    # 把 alias 转成 env-safe: 替换非 alphanumeric 为 _
    suffix = re.sub(r"[^A-Za-z0-9_]", "_", alias.upper())
    return f"{base}_{suffix}"


def _parse_alias_from_env_var(provider: str, env_var: str) -> str:
    """从 env_var 提取 alias. 'MiniMax_API_KEY' → 'primary', 'MiniMax_API_KEY_FALLBACK' → 'fallback'."""
    base = PROVIDERS[provider]["env_var"]
    if env_var == base:
        return "primary"
    if env_var.startswith(base + "_"):
        return env_var[len(base) + 1:].lower()
    return env_var  # unknown suffix


# ===== 解析 provider 的 keys =====

def _read_provider_keys(env: dict[str, str], provider_id: str) -> list[KeyEntry]:
    """从 env dict 提取指定 provider 的所有 keys (按 alias 排序)."""
    base = PROVIDERS[provider_id]["env_var"]
    out: list[KeyEntry] = []
    for env_var, val in env.items():
        if env_var == base or env_var.startswith(base + "_"):
            alias = _parse_alias_from_env_var(provider_id, env_var)
            out.append(KeyEntry(
                provider=provider_id,
                env_var=env_var,
                alias=alias,
                masked_preview=_mask(val) if val else None,
                is_active=bool(val),
            ))
    # primary 排第一
    out.sort(key=lambda k: (0 if k.alias == "primary" else 1, k.alias))
    return out


def _count_global_keys(env: dict[str, str]) -> int:
    """统计 .env 中所有 *_API_KEY 数量."""
    n = 0
    for prov in PROVIDERS:
        n += len(_read_provider_keys(env, prov))
    return n


# ===== 端点 =====

async def get_env_keys_endpoint(
    _user: User = Depends(get_current_user),
) -> EnvStatusResponse:
    """返回所有 provider 的 keys 列表 + masked preview."""
    path = _env_path()
    env = _parse_env(path)
    providers = []
    for prov_id, info in PROVIDERS.items():
        keys = _read_provider_keys(env, prov_id)
        providers.append(ProviderKeys(
            provider=prov_id,
            label=info["label"],
            env_var_prefix=info["env_var"],
            model_id=info["model_id"],
            color=info["color"],
            keys=keys,
        ))
    return EnvStatusResponse(
        path=str(path),
        max_keys_global=MAX_KEYS_GLOBAL,
        max_keys_per_provider=MAX_KEYS_PER_PROVIDER,
        providers=providers,
    )


async def set_env_key_endpoint(
    req: EnvSetRequest,
    _user: User = Depends(get_current_user),
) -> EnvSetResponse:
    """新增或修改 (provider, alias) 对应的 api key.

    - alias='primary' → 写入 PROVIDER_API_KEY (无后缀, 向后兼容)
    - 其他 alias → 写入 PROVIDER_API_KEY_<ALIAS>
    - 已存在则替换; 不存在则新增 (检查全局 ≤10 / 单 provider ≤2)
    """
    if req.provider not in PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"provider 必须是 {list(PROVIDERS.keys())}, 收到 {req.provider!r}",
        )

    path = _env_path()
    env = _parse_env(path)

    # 检查全局数量上限
    target_env_var = _env_var_for(req.provider, req.alias)
    if target_env_var not in env:
        # 是新增, 检查数量
        current_global = _count_global_keys(env)
        if current_global >= MAX_KEYS_GLOBAL:
            raise HTTPException(
                status_code=400,
                detail=f"全局上限 {MAX_KEYS_GLOBAL} 个 key 已满, 删一个再加",
            )
        current_provider = len(_read_provider_keys(env, req.provider))
        if current_provider >= MAX_KEYS_PER_PROVIDER:
            raise HTTPException(
                status_code=400,
                detail=f"{req.provider} 上限 {MAX_KEYS_PER_PROVIDER} 个 key 已满",
            )

    # 备份 + 写回
    backup = _backup_env(path)
    env[target_env_var] = req.api_key
    try:
        _write_env(path, env)
    except Exception as e:
        logger.exception(f"[config] write_env failed: {e}")
        raise HTTPException(status_code=500, detail=f"写入 .env 失败: {e}")

    # 同步更新 process env
    os.environ[target_env_var] = req.api_key
    # primary alias 同时设 PROVIDER_API_KEY (兼容旧 .env 读法)
    if req.alias.lower() in ("primary", "1", "default", ""):
        os.environ[PROVIDERS[req.provider]["env_var"]] = req.api_key

    logger.info(
        f"[config] user={_user.user_id[:8]}*** set "
        f"{target_env_var} alias={req.alias!r} masked={_mask(req.api_key)}"
    )
    return EnvSetResponse(
        provider=req.provider,
        env_var=target_env_var,
        alias=req.alias,
        saved_to=str(path),
        backup=backup,
    )


async def delete_env_key_endpoint(
    req: EnvDeleteRequest,
    _user: User = Depends(get_current_user),
) -> EnvDeleteResponse:
    """删除指定 (provider, alias) 的 key."""
    if req.provider not in PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"provider 必须是 {list(PROVIDERS.keys())}, 收到 {req.provider!r}",
        )
    path = _env_path()
    env = _parse_env(path)
    target_env_var = _env_var_for(req.provider, req.alias)
    if target_env_var not in env:
        raise HTTPException(
            status_code=404,
            detail=f"{target_env_var} 不存在 (alias={req.alias!r})",
        )

    backup = _backup_env(path)
    del env[target_env_var]
    try:
        _write_env(path, env)
    except Exception as e:
        logger.exception(f"[config] delete failed: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {e}")

    # 同步清理 os.environ
    os.environ.pop(target_env_var, None)
    if req.alias.lower() in ("primary", "1", "default", ""):
        os.environ.pop(PROVIDERS[req.provider]["env_var"], None)

    logger.info(
        f"[config] user={_user.user_id[:8]}*** deleted "
        f"{target_env_var} alias={req.alias!r}"
    )
    return EnvDeleteResponse(
        deleted=True,
        provider=req.provider,
        alias=req.alias,
    )


def _write_env(path: Path, env_map: dict[str, str]) -> None:
    """重写 .env 文件: 保留所有行 (包括注释 + 非 managed keys), 替换 managed keys."""
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    # 计算所有 managed keys (5 个 provider × *_API_KEY + *_API_KEY_<SUFFIX>)
    all_managed_prefixes = {info["env_var"] for info in PROVIDERS.values()}

    def is_managed(env_var: str) -> bool:
        for prefix in all_managed_prefixes:
            if env_var == prefix or env_var.startswith(prefix + "_"):
                return True
        return False

    seen: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        m = re.match(r"^([A-Za-z][A-Za-z0-9_]*)\s*=", line)
        if m and is_managed(m.group(1)):
            env_var = m.group(1)
            if env_var in seen:
                continue  # 跳过重复
            seen.add(env_var)
            if env_var in env_map:
                new_lines.append(f'{env_var}="{env_map[env_var]}"')
            # 如果 env_var 在输入 env_map 中不存在 (被删除了), 跳过 (不写入)
        else:
            new_lines.append(line)

    # append new managed keys not in original file
    for env_var, val in env_map.items():
        if env_var not in seen and is_managed(env_var):
            new_lines.append(f'{env_var}="{val}"')

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


router = APIRouter(prefix="/config", tags=["config"])
router.on_startup = []  # type: ignore[attr-defined]
router.on_shutdown = []  # type: ignore[attr-defined]
router.add_api_route(
    "/env", get_env_keys_endpoint, methods=["GET"],
    response_model=EnvStatusResponse,
)
router.add_api_route(
    "/env", set_env_key_endpoint, methods=["POST"],
    response_model=EnvSetResponse,
)
router.add_api_route(
    "/env", delete_env_key_endpoint, methods=["DELETE"],
    response_model=EnvDeleteResponse,
)