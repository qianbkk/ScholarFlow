"""
backend.api.routes.config
=========================

R10.5.59: /api/v1/config/env — 读取 .env 中已配置的 provider keys + 写入新 key.

SettingsSidebar (左侧常驻) 中 API Key 编辑 UI 调用此端点:
  - GET  → 返回当前 5 个 provider 的 has_key 状态
  - POST → 写入 user-provided key 到项目根 .env (替换对应 provider 行)
          要求鉴权 (登录用户才能修改 .env)

安全性:
  - 必须登录 (Depends(get_current_user))
  - 写入前 .env 自动备份到 .env.bak
  - 仅允许写入预定义 provider 的 key (white-list 防注入)
  - 写入后后端进程需要 reload 才能生效 (R10.5.59 行为: 不自动 reload,
    下次启动或调用方重连时生效; 在 SettingsSidebar 上提示用户)
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

# Provider → env var 映射. 后端 config.py 已经读取这些 key,
# 写入后下次启动或显式 reload 才会生效.
PROVIDER_ENV_MAP = {
    "minimax": "MiniMax_API_KEY",
    "kimi": "KIMI_API_KEY",
    "glm": "GLM_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}

# .env 文件路径 (项目根目录)
def _env_path() -> Path:
    # backend/api/routes/config.py → 向上 3 级到项目根
    return Path(__file__).resolve().parents[3] / ".env"


class EnvKeyStatus(BaseModel):
    provider: str
    env_var: str
    has_key: bool
    masked_preview: Optional[str] = None  # e.g. "sk-cp-4n...xyz123"


class EnvStatusResponse(BaseModel):
    path: str  # .env 文件绝对路径
    keys: list[EnvKeyStatus]


class EnvSetRequest(BaseModel):
    provider: str = Field(..., min_length=2, max_length=32)
    api_key: str = Field(..., min_length=8, max_length=512)


class EnvSetResponse(BaseModel):
    provider: str
    env_var: str
    saved_to: str
    backup: str
    needs_restart: bool = True


def _mask(value: str) -> str:
    """Mask API key: 保留前 6 字符 + 后 4 字符,中间 ... 省略."""
    if len(value) <= 12:
        return "***"
    return f"{value[:6]}...{value[-4:]}"


def _parse_env(path: Path) -> dict[str, str]:
    """简单 .env 解析: KEY=VALUE 行 (忽略注释 + 空行).
    不展开 ${VAR} 也不解析转义,仅作为查找工具.
    大小写敏感 (与 dotenv 行为一致): 重复 key 保留最后一个出现的值 (last-wins).
    """
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
        # 去引号
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        out[key] = val  # last-wins: 重复 key 后者覆盖前者
    return out


def _write_env(path: Path, env_map: dict[str, str]) -> None:
    """重写 .env 文件,保留所有现有行 + 替换 PROVIDER_ENV_MAP 中指定的 key.
    不在 map 中的行原样保留 (包括注释、空行、其他 key)."""
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    seen_in_input: set[str] = set()
    written_keys: set[str] = set()
    new_lines: list[str] = []
    for line in lines:
        m = re.match(r"^([A-Za-z][A-Za-z0-9_]*)\s*=", line)
        if m and m.group(1) in env_map:
            env_var = m.group(1)
            if env_var in seen_in_input:
                # 跳过输入中重复的 key 行 (保留 first occurrence 的位置)
                continue
            seen_in_input.add(env_var)
            # 替换整行: KEY=VALUE (加引号防特殊字符)
            new_lines.append(f'{env_var}="{env_map[env_var]}"')
            written_keys.add(env_var)
        else:
            new_lines.append(line)

    # map 中没出现在原文件的,追加到末尾
    for env_var, val in env_map.items():
        if env_var not in written_keys:
            new_lines.append(f'{env_var}="{val}"')

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


async def get_env_keys_endpoint(
    _user: User = Depends(get_current_user),
) -> EnvStatusResponse:
    """返回当前 5 个 provider 的 key 状态 (masked)."""
    path = _env_path()
    env = _parse_env(path)
    keys = []
    for prov, env_var in PROVIDER_ENV_MAP.items():
        val = env.get(env_var, "")
        keys.append(EnvKeyStatus(
            provider=prov,
            env_var=env_var,
            has_key=bool(val and val.strip() and val.strip() != "your-key-here"),
            masked_preview=_mask(val) if val else None,
        ))
    return EnvStatusResponse(
        path=str(path),
        keys=keys,
    )


async def set_env_key_endpoint(
    req: EnvSetRequest,
    _user: User = Depends(get_current_user),
) -> EnvSetResponse:
    """写入 user-provided key 到 .env. 自动备份 + 白名单 provider."""
    if req.provider not in PROVIDER_ENV_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"provider 必须是 {list(PROVIDER_ENV_MAP.keys())}, 收到 {req.provider!r}",
        )
    env_var = PROVIDER_ENV_MAP[req.provider]
    path = _env_path()

    # 备份 .env (如果存在)
    backup = str(path) + ".bak"
    if path.exists():
        try:
            Path(backup).write_text(path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        except Exception as e:
            logger.warning(f"[config] backup failed: {e}")

    # 读取现有 + 替换 + 写回
    env = _parse_env(path)
    env[env_var] = req.api_key
    try:
        _write_env(path, env)
    except Exception as e:
        logger.exception(f"[config] write_env failed: {e}")
        raise HTTPException(status_code=500, detail=f"写入 .env 失败: {e}")

    # 同步更新 process env (让本次进程立即生效,无需重启)
    os.environ[env_var] = req.api_key

    logger.info(
        f"[config] user={_user.user_id[:8]}*** set {env_var} "
        f"(masked={_mask(req.api_key)}) — backup={backup}"
    )
    return EnvSetResponse(
        provider=req.provider,
        env_var=env_var,
        saved_to=str(path),
        backup=backup,
        needs_restart=False,  # 我们已经更新 os.environ, 大多数 LLM client 会重新读
    )


router = APIRouter(prefix="/config", tags=["config"])
# FastAPI 0.115+ compatibility (跟 routes/admin.py 一致)
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