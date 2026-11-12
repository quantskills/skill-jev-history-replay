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


def test_readme_trees_list_every_script():
    """README（中/英）的 `scripts/` 目录树必须列全所有脚本。

    来源：README 的树曾缺 7 个脚本（data_loader / adapt_logs / credentials /
    trade_audit / knob_efficacy / value_decomposition），英文版缺失更多。
    读者照树去找会找不到文件。
    """
    actual = {p.name for p in SCRIPTS.glob("*.py") if p.name != "__init__.py"}
    tree_line = re.compile(r"^[│├└─\s]+([a-z_]+\.py)\s", re.MULTILINE)

    problems = {}
    for name in ("README.md", "README.en.md"):
        doc = REPO_ROOT / name
        if not doc.exists():
            problems[name] = ["文件不存在"]
            continue
        listed = set(tree_line.findall(doc.read_text(encoding="utf-8")))
        missing = sorted(actual - listed)
        if missing:
            problems[name] = f"未列出：{missing}"
    assert problems == {}, problems


def test_defect_ledger_count_matches_rows():
    """证据文档第 6 节标题里的缺陷数，必须等于表里实际的行数。

    这类"标题写 N 项"的描述最容易在追加条目后忘了改。
    """
    doc = REPO_ROOT / "references" / "validation_evidence.md"
    text = doc.read_text(encoding="utf-8")

    match = re.search(r"## 6\. 验证中发现并修复的缺陷（(\d+) 项）", text)
    assert match, "找不到第 6 节的缺陷数标题"
    claimed = int(match.group(1))

    start = text.index("## 6. 验证中发现并修复的缺陷")
    end = text.index("## 7. 错误路径")
    rows = re.findall(r"^\| (\d+) \|", text[start:end], re.MULTILINE)

    assert claimed == len(rows), (
        f"标题写 {claimed} 项，表里实际 {len(rows)} 行"
    )
    assert [int(r) for r in rows] == list(range(1, claimed + 1)), (
        "编号不连续或有重复"
    )


def test_evidence_table_lists_every_test_file():
    """`validation_evidence.md` 的测试清单必须与 `tests/` 实际文件一一对应。

    这条是防漂移的：前面已经有两次文档写着「4 例」而实际只有 3 例、
    以及新增测试文件后表格没跟上。数字本身由 `verify_claims` 与 pytest
    输出对账，这里只守住「有没有漏列」。
    """
    doc = REPO_ROOT / "references" / "validation_evidence.md"
    listed = set(re.findall(r"\| `(test_[a-z0-9_]+\.py)` \|", doc.read_text(encoding="utf-8")))
    actual = {p.name for p in (REPO_ROOT / "tests").glob("test_*.py")}

    assert actual - listed == set(), f"测试文件未在证据文档中列出：{sorted(actual - listed)}"
    assert listed - actual == set(), f"证据文档列了不存在的测试文件：{sorted(listed - actual)}"


def test_evidence_table_counts_match_collection():
    """证据文档里每个测试文件的用例数，必须等于 pytest 实际收集到的数量。

    此前表格整体失真（8 个文件的数字与实际不符），
    而 `verify_claims` 只对账关键指标、不检查这张表。
    这里用 pytest 自己的 `--collect-only` 作为唯一真相，
    避免"手数 def 个数"被参数化、fixture 影响。
    """
    import subprocess
    import sys

    doc = REPO_ROOT / "references" / "validation_evidence.md"
    claimed = {
        name: int(count)
        for name, count in re.findall(
            r"\| `(test_[a-z0-9_]+\.py)` \| (\d+) \|",
            doc.read_text(encoding="utf-8"),
        )
    }
    assert claimed, "证据文档里没有测试清单表格？"

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]

    actual: dict = {}
    for line in proc.stdout.splitlines():
        if not line.startswith("tests/"):
            continue
        name = line.split("::", 1)[0].split("/", 1)[1]
        actual[name] = actual.get(name, 0) + 1

    mismatches = {
        name: (claimed[name], actual.get(name))
        for name in sorted(set(claimed) | set(actual))
        if claimed.get(name) != actual.get(name)
    }
    assert mismatches == {}, (
        "证据文档的用例数与实际收集不一致（文档, 实际）：\n"
        + "\n".join(f"  {n}: {c} vs {a}" for n, (c, a) in mismatches.items())
    )
