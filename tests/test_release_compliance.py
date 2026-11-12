"""发布合规：社区审核会检查的硬性内容。

panda-builder 把 5 平台运行时适配器列为硬性要求；发布规则还要求
README 免责声明覆盖四个要点、INSTALL 覆盖五个平台、不含占位符与敏感信息。
这些以前只在 SKILL.md 里列着，CI 只检查了"文件存在"，没人验内容。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
README_ZH = REPO_ROOT / "README.md"
README_EN = REPO_ROOT / "README.en.md"
INSTALL = REPO_ROOT / "INSTALL.md"
SKILL = REPO_ROOT / "SKILL.md"


def test_readme_has_disclaimer_with_all_four_points():
    """免责声明必须覆盖：研究用途 / 不保证收益 / 风险边界 / 非官方背书。"""
    zh = README_ZH.read_text(encoding="utf-8")
    en = README_EN.read_text(encoding="utf-8")

    for term in ("免责声明", "不构成", "不保证收益", "风险", "非官方背书"):
        assert term in zh, f"中文 README 免责声明缺「{term}」"
    for term in ("Disclaimer", "not investment advice",
                 "No performance guarantee", "Risk boundary",
                 "No official endorsement"):
        assert term in en, f"英文 README 免责声明缺「{term}」"


def test_install_covers_five_platforms():
    inst = INSTALL.read_text(encoding="utf-8")
    for platform in ("Claude Code", "Codex", "Cursor", "Hermes", "OpenClaw"):
        assert platform in inst, f"INSTALL.md 未覆盖 {platform}"


def test_licenses_use_spdx_identifier():
    """许可证必须写 SPDX 的 `GPL-3.0-only`，不是 `GPL-3.0` / `GPLv3`。"""
    skill = json.loads((REPO_ROOT / "skill.json").read_text(encoding="utf-8"))
    assert skill["license"] == "GPL-3.0-only"

    front = SKILL.read_text(encoding="utf-8").split("---")[1]
    assert "license: GPL-3.0-only" in front, "SKILL.md frontmatter 缺 SPDX license"

    first = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8").splitlines()[0]
    assert "GNU GENERAL PUBLIC LICENSE" in first


def test_skill_name_is_consistent_everywhere():
    """仓库名 / skill.json / SKILL.md frontmatter 三处 name 必须一致。"""
    skill = json.loads((REPO_ROOT / "skill.json").read_text(encoding="utf-8"))
    front = SKILL.read_text(encoding="utf-8").split("---")[1]
    match = re.search(r"^name:\s*(\S+)\s*$", front, re.MULTILINE)
    assert match, "SKILL.md frontmatter 缺 name"
    assert skill["name"] == match.group(1) == REPO_ROOT.name


def test_no_placeholders_left():
    """不得残留 TODO / 待补充 / <your-...> 之类的占位内容。"""
    files = [README_ZH, README_EN, INSTALL, SKILL,
             REPO_ROOT / "skill.json"]
    files += sorted((REPO_ROOT / "agents").glob("*"))
    files += sorted((REPO_ROOT / "references").glob("*.md"))

    pattern = re.compile(r"\bTODO\b|\bFIXME\b|\bTBD\b|待补充|<your[-_]")
    hits = []
    for path in files:
        if not path.is_file():
            continue
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{path.name}:{lineno}: {line.strip()[:60]}")
    assert hits == [], "发现占位内容：\n" + "\n".join(hits)


def test_no_credentials_or_internal_addresses():
    """文档与配置里不得出现真实凭证值、内网地址或私人邮箱。"""
    files = [README_ZH, README_EN, INSTALL, SKILL,
             REPO_ROOT / "skill.json"]
    files += sorted((REPO_ROOT / "agents").glob("*"))
    files += sorted((REPO_ROOT / "references").glob("*.md"))
    files += [REPO_ROOT / "config" / "replay_config.yaml"]

    cred = re.compile(r"ZINFOID_[0-9]+Q\s*[=:]\s*['\"][^'\"]{6,}")
    internal = re.compile(r"https?://(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)")
    email = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-z]{2,}")
    # `git@github.com:org/repo.git` 是 SSH clone 地址，不是私人邮箱。
    scp_git = re.compile(r"^git@[a-zA-Z0-9.-]+$")

    problems = []
    for path in files:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, rx in (("凭证值", cred), ("内网地址", internal), ("邮箱", email)):
            for m in rx.finditer(text):
                hit = m.group(0)
                if label == "邮箱" and scp_git.match(hit):
                    continue
                problems.append(f"{path.name}: {label} {hit[:40]}")
    assert problems == [], "发现敏感信息：\n" + "\n".join(problems)


def test_entry_script_exists():
    skill = json.loads((REPO_ROOT / "skill.json").read_text(encoding="utf-8"))
    assert (REPO_ROOT / skill["entry_script"]).is_file()
    assert (REPO_ROOT / skill["entrypoint"]).is_file()