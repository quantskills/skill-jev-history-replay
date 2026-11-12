"""文档里提到的脚本必须存在且可执行。

来源：`references/data_access.md` 曾整篇是别的 skill 的模板，
里面反复出现 `scripts/fixture_generator.py`——而本 skill 根本没有这个文件。
读者照着文档跑会直接报"文件不存在"。

这条测试把"文档提到的脚本"与"实际存在的脚本"对齐。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
DOCS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "SKILL.md",
    REPO_ROOT / "INSTALL.md",
    REPO_ROOT / "references" / "api_guide.md",
    REPO_ROOT / "references" / "data_access.md",
    REPO_ROOT / "references" / "log_contract.md",
    REPO_ROOT / "references" / "validation_evidence.md",
]

# 允许引用但不在 scripts/ 下的（例如示例路径）
ALLOWED_MISSING = set()


def _referenced_scripts() -> dict:
    """只收集**作为命令或路径使用**的脚本引用。

    规则：`python3 scripts/x.py` 或行内代码 ``scripts/x.py``。
    正文里的普通提及（如"曾写着 fixture_generator.py"）不计入——
    那是反例说明，不是让读者去执行。
    """
    command = re.compile(r"python3?\s+scripts/([a-z0-9_]+\.py)")
    inline_code = re.compile(r"`scripts/([a-z0-9_]+\.py)")
    found: dict = {}
    for doc in DOCS:
        if not doc.exists():
            continue
        text = doc.read_text(encoding="utf-8")
        for regex in (command, inline_code):
            for match in regex.finditer(text):
                found.setdefault(match.group(1), set()).add(doc.name)
    return found


def test_all_documented_scripts_exist():
    referenced = _referenced_scripts()
    assert referenced, "文档里没有提到任何脚本？"
    missing = {
        name: sorted(docs) for name, docs in referenced.items()
        if not (SCRIPTS / name).exists() and name not in ALLOWED_MISSING
    }
    assert missing == {}, (
        "文档引用了不存在的脚本：\n"
        + "\n".join(f"  scripts/{n}（出现于 {d}）" for n, d in missing.items())
    )


def test_every_script_has_a_docstring():
    """每个脚本都要有模块 docstring，说明用途。"""
    missing = []
    for path in sorted(SCRIPTS.glob("*.py")):
        if path.name == "__init__.py":
            continue
        text = path.read_text(encoding="utf-8")
        if not text.lstrip().startswith('"""'):
            missing.append(path.name)
    assert missing == [], f"以下脚本缺模块 docstring：{missing}"


def test_scripts_are_importable():
    """所有脚本至少要能被解析（语法正确）。"""
    import ast

    failures = []
    for path in sorted(SCRIPTS.glob("*.py")):
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            failures.append(f"{path.name}: {exc}")
    assert failures == [], failures
