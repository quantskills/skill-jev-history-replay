"""CI 配置必须本身合法。

这条测试的来源：`.github/workflows/validate.yml` 曾因
`name: Unit tests (slow: verdict discrimination)` 里的冒号没加引号
而变成无效 YAML——整条流水线从来没跑起来过，却一直以为它在跑。
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="需要 pyyaml 才能校验 CI 配置")

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "validate.yml"


def test_workflow_is_valid_yaml():
    assert WORKFLOW.exists(), "缺少 CI 工作流文件"
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "工作流顶层必须是映射"


def test_workflow_has_expected_steps():
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = data["jobs"]["test"]["steps"]
    names = [s.get("name") or s.get("uses", "") for s in steps]
    joined = " | ".join(names)

    required = [
        "Full alignment run",
        "Unit tests (fast)",
        "Verify validation-doc claims",
        "Per-trade price / return audit",
        "Knob efficacy",
        "Data quality audit",
    ]
    for needle in required:
        assert needle in joined, f"CI 缺少步骤：{needle}"


def test_build_runs_before_tests():
    """per_day 校验要读 output/ledger.jsonl，build 必须排在 tests 之前。"""
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = data["jobs"]["test"]["steps"]
    order = []
    for s in steps:
        run = (s.get("run") or "")
        name = s.get("name") or ""
        if "scripts/build.py" in run:
            order.append("build")
        elif "pytest" in run:
            order.append("tests")
    assert "build" in order and "tests" in order
    assert order.index("build") < order.index("tests"), (
        f"build 必须在 tests 之前，实际顺序：{order}"
    )


def test_every_run_step_has_a_command():
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for s in data["jobs"]["test"]["steps"]:
        if "run" in s:
            assert str(s["run"]).strip(), f"步骤 {s.get('name')} 的 run 为空"
