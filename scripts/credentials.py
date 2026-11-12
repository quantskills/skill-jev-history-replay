"""PandaData 凭证加载（单一实现，供所有需要拉数的脚本共用）。

踩过的坑：
  - `~/.pandadata/pandadata.env` 里的值可能带引号（`export X="abc"`），
    直接 strip 会把引号带进 URL，导致 `unknown url type: "https`。
  - 无凭证时不能抛底层 SDK 异常，要给出结构化错误并返回非零退出码，
    否则脚本崩了却报"成功"。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

ENV_FILE = Path.home() / ".pandadata" / "pandadata.env"

# 契约变量名 → 历史别名
FIELDS = {
    "username": ("PANDA_DATA_USERNAME", "DEFAULT_USERNAME"),
    "zinfoid": ("PANDA_DATA_PASSWORD", "DEFAULT_PASSWORD"),
    "base_url": ("PANDA_DATA_BASE_URL", "JAVA_SERVICE_BASE_URL"),
}


class CredentialError(RuntimeError):
    def __init__(self, code: str, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


def _unquote(value: str) -> str:
    """去掉包裹的引号。`export X="abc"` 读出来是 `"abc"`。"""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _read_env_file(path: Path | None = None) -> Dict[str, str]:
    # 每次调用时解析模块级 ENV_FILE，便于测试重定向
    path = path or ENV_FILE
    if not path.exists():
        return {}
    out: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        out[key.strip()] = _unquote(val)
    return out


def load() -> Dict[str, str]:
    """返回 {username, zinfoid, base_url}；缺失的键为空串。"""
    file_values = _read_env_file()
    resolved: Dict[str, str] = {}
    for name, (primary, fallback) in FIELDS.items():
        value = os.environ.get(primary) or os.environ.get(fallback) or ""
        if not value:
            value = file_values.get(primary) or file_values.get(fallback) or ""
        value = _unquote(value)
        # 回填到环境变量，供 panda_data 自身读取
        if value:
            os.environ.setdefault(primary, value)
        resolved[name] = value
    return resolved


def require() -> Dict[str, str]:
    """全有或抛 CredentialError。"""
    values = load()
    missing = [k for k, v in values.items() if not v]
    if missing:
        raise CredentialError(
            "missing_credentials",
            f"缺少 PandaData 凭证：{missing}",
            hint=("设置环境变量 PANDA_DATA_USERNAME / PANDA_DATA_PASSWORD / "
                  "PANDA_DATA_BASE_URL，或写入 ~/.pandadata/pandadata.env"),
        )
    # base_url 必须是合法 URL，防止引号/空白混入
    if not values["base_url"].startswith(("http://", "https://")):
        raise CredentialError(
            "invalid_base_url",
            f"base_url 不是合法 URL：{values['base_url']!r}",
            hint="检查 ~/.pandadata/pandadata.env 里是否有引号或多余空格",
        )
    return values


def is_available() -> bool:
    try:
        require()
        return True
    except CredentialError:
        return False
