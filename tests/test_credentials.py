"""凭证解析：引号、别名、缺失时的结构化错误。

来源：`~/.pandadata/pandadata.env` 里的值带双引号（`export X="abc"`），
直接 strip 会把引号带进 URL，导致 `unknown url type: "https`。
oos_check.py 曾因此在无有效凭证时抛底层 SDK 异常，且退出码为 0。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts import credentials


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    """构造一个临时的 env 文件并重定向 HOME。"""
    home = tmp_path / "home"
    (home / ".pandadata").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(credentials, "ENV_FILE", home / ".pandadata" / "pandadata.env")
    for key in ("PANDA_DATA_USERNAME", "PANDA_DATA_PASSWORD",
                "PANDA_DATA_BASE_URL", "DEFAULT_USERNAME",
                "DEFAULT_PASSWORD", "JAVA_SERVICE_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    return home / ".pandadata" / "pandadata.env"


def test_quoted_values_are_unquoted(env_file):
    env_file.write_text(
        'export DEFAULT_USERNAME="13800138000"\n'
        'export DEFAULT_PASSWORD=\'secret\'\n'
        'export JAVA_SERVICE_BASE_URL="https://example.com"\n',
        encoding="utf-8",
    )
    values = credentials.load()
    assert values["username"] == "13800138000"
    assert values["zinfoid"] == "secret"
    assert values["base_url"] == "https://example.com"
    assert not values["base_url"].startswith('"')


def test_unquoted_values_still_work(env_file):
    env_file.write_text(
        "DEFAULT_USERNAME=bob\n"
        "DEFAULT_PASSWORD=pw\n"
        "JAVA_SERVICE_BASE_URL=https://x.test\n",
        encoding="utf-8",
    )
    values = credentials.load()
    assert values == {"username": "bob", "zinfoid": "pw",
                      "base_url": "https://x.test"}


def test_missing_credentials_raise_structured_error(env_file):
    env_file.write_text("", encoding="utf-8")
    with pytest.raises(credentials.CredentialError) as exc:
        credentials.require()
    assert exc.value.code == "missing_credentials"
    assert "username" in exc.value.message


def test_quoted_url_is_rejected(env_file):
    """双引号残留必须被识别为非法 URL，而不是带到下游崩在 SDK 里。"""
    env_file.write_text(
        'DEFAULT_USERNAME=bob\nDEFAULT_PASSWORD=pw\n'
        'JAVA_SERVICE_BASE_URL="https://x.test\n',   # 只有左引号
        encoding="utf-8",
    )
    with pytest.raises(credentials.CredentialError) as exc:
        credentials.require()
    assert exc.value.code == "invalid_base_url"


def test_is_available_false_without_credentials(env_file):
    env_file.write_text("", encoding="utf-8")
    assert credentials.is_available() is False


def test_env_vars_take_priority(env_file, monkeypatch):
    env_file.write_text(
        "DEFAULT_USERNAME=fileuser\nDEFAULT_PASSWORD=pw\n"
        "JAVA_SERVICE_BASE_URL=https://file.test\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PANDA_DATA_USERNAME", "envuser")
    assert credentials.load()["username"] == "envuser"
