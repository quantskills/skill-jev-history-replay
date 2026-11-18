"""文档里的「自检项数 / 用例总数 / Python 下限」必须以实测为唯一真相。

这三处此前都漂过：`validation_evidence.md` 写 71 项（实际 84）、写 293 passed、
以及 `skill.json` 的 `runtime` 与自检门槛各说各话。这类数字一旦过期，读者照抄的就是
错的验收标准，所以不允许靠人工回忆维护。
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_verify_claims_count_matches_docs():
    out = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "verify_claims.py")],
        cwd=REPO, capture_output=True, text=True,
    ).stdout
    m = re.search(r"checks:\s*(\d+)/(\d+)", out)
    assert m, f"verify_claims 未输出 checks N/N：{out[-200:]}"
    actual = int(m.group(1))
    doc = re.search(r"当前覆盖 \*\*(\d+) 项\*\*", _read("references/validation_evidence.md"))
    assert doc, "文档里找不到「当前覆盖 N 项」这句话"
    assert int(doc.group(1)) == actual, (
        f"文档写 {doc.group(1)} 项，verify_claims 实际 {actual} 项"
    )


def test_collected_test_count_matches_docs():
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "tests", "--collect-only", "-q"],
        cwd=REPO, capture_output=True, text=True,
    ).stdout
    m = re.search(r"(\d+) tests? collected", out)
    assert m, f"未能从 --collect-only 解析用例数：{out[-200:]}"
    actual = int(m.group(1))
    text = _read("references/validation_evidence.md")
    stated = {int(n) for n in re.findall(r"(\d+) passed", text)}
    assert actual in stated, (
        f"实收集 {actual} 条，文档提到的 passed 数字是 {sorted(stated)} —— 已过期"
    )


def test_runtime_floor_agrees_across_all_four_sites():
    """`skill.json` / `env_check.py` / `SKILL.md` / CI 矩阵的下限必须是同一个数。

    这条断言取代了原先的「floor 不得高于 3.9」：那个方向把**自我放宽**当成正确，
    结果 `runtime` 说 >=3.9，而 `env_check` 在 3.9 判 blocked、SKILL.md 写 ≥3.10、
    CI 矩阵没有 3.9、本机 3.9 也装不了 pytest（套件一条都跑不了）。
    「能 import」不等于「受支持」；支持范围只能等于**被验证过**的范围。
    """
    runtime = json.loads(_read("skill.json"))["runtime"]
    declared = re.match(r"python>=(\d+)\.(\d+)", runtime)
    assert declared, f"runtime 格式异常：{runtime}"
    declared_floor = (int(declared.group(1)), int(declared.group(2)))

    env_src = _read("scripts/env_check.py")
    enforced = re.search(r"sys\.version_info >= \((\d+), (\d+)\)", env_src)
    assert enforced, "env_check.py 里找不到解释器门槛"
    enforced_floor = (int(enforced.group(1)), int(enforced.group(2)))

    ci = _read(".github/workflows/validate.yml")
    matrix = re.search(r"python-version:\s*\[([^\]]+)\]", ci)
    assert matrix, "CI 里没有 python 版本矩阵"
    tested = sorted(tuple(int(x) for x in re.findall(r"\d+", v))
                    for v in re.findall(r'"([0-9.]+)"', matrix.group(1)))
    ci_floor = tested[0]

    skill_md = _read("SKILL.md")
    assert "Python ≥ 3.10" in skill_md, "SKILL.md 前置检查必须写明受支持的下限"

    assert declared_floor == enforced_floor == ci_floor, (
        f"下限三处不一致：skill.json={declared_floor} env_check={enforced_floor} CI={ci_floor}"
    )


def test_unverified_interpreter_is_not_claimed_as_supported():
    """3.9.6 可以 import 全部脚本，但不能被写成受支持环境。"""
    import py_compile
    import tempfile

    for path in sorted((REPO / "scripts").glob("*.py")):
        with tempfile.NamedTemporaryFile(suffix=".pyc", delete=False) as fh:
            py_compile.compile(str(path), cfile=fh.name, doraise=True)

    text = _read("references/validation_evidence.md")
    assert "不作为受支持环境" in text or "不是受支持运行环境" in text, (
        "文档必须说清 3.9.6 的可 import 不等于受支持，否则读者会以为装 3.9 就能验收"
    )
