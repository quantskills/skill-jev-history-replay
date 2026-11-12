"""运行时适配器（`agents/`）必须与实际能力一致。

社区审核把 `agents/` 下的三个适配器列为硬性要求。但"文件存在"不等于
"内容正确"——`openai.yaml` 里声明的脚本、参数、旋钮清单都可能与代码脱节。
这里逐项对账。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml", reason="需要 pyyaml 才能校验 openai.yaml")

REPO_ROOT = Path(__file__).resolve().parents[1]
OPENAI_YAML = REPO_ROOT / "agents" / "openai.yaml"
SCRIPTS = REPO_ROOT / "scripts"


@pytest.fixture(scope="module")
def spec():
    return yaml.safe_load(OPENAI_YAML.read_text(encoding="utf-8"))


def test_adapter_files_exist():
    for name in ("cursor-rule.mdc", "portable-loader.md", "openai.yaml"):
        assert (REPO_ROOT / "agents" / name).is_file(), f"缺适配器 {name}"


def test_declared_scripts_exist(spec):
    """`x-steps` 里声明的每个脚本都必须真实存在。"""
    missing = [
        step["script"] for step in spec["x-steps"]
        if not (REPO_ROOT / step["script"]).is_file()
    ]
    assert missing == [], f"openai.yaml 声明了不存在的脚本：{missing}"


def test_declared_entry_exists(spec):
    entry = spec["x-skill-info"]["entry"]
    assert (REPO_ROOT / entry).is_file(), f"entry 不存在：{entry}"


def test_declared_knobs_match_semantics_registry(spec):
    """`x-attribution-knobs` 必须与 `semantics.KNOB_VALUES` 完全一致。

    多列一个不存在的旋钮会让调用方传一个被忽略的参数；
    少列一个则让调用方以为它不可配。
    """
    from scripts import semantics as sem

    declared = set(spec["x-attribution-knobs"])
    actual = set(sem.KNOB_VALUES)
    assert declared == actual, (
        f"多列：{sorted(declared - actual)}；少列：{sorted(actual - declared)}"
    )


def test_declared_config_keys_match_reference_semantics(spec):
    """`x-semantics-knobs` 必须与 `REFERENCE_SEMANTICS` 的可配置键完全一致。

    此前该清单写 18 项，既不是 23（可配置全集）也不是 10（可消融子集），
    属于历史遗留的手抄版本。
    """
    from scripts import config as cfg

    declared = set(spec["x-semantics-knobs"])
    actual = {k for k in cfg.REFERENCE_SEMANTICS if not k.startswith("_")}
    assert declared == actual, (
        f"多列：{sorted(declared - actual)}；少列：{sorted(actual - declared)}"
    )


def test_attribution_knobs_are_subset_of_configurable(spec):
    """可消融旋钮必须是可配置键的子集——否则归因会去拨一个不存在的参数。"""
    assert set(spec["x-attribution-knobs"]) <= set(spec["x-semantics-knobs"])


def test_version_matches_skill_json(spec):
    """`openai.yaml` 的 version 必须与 `skill.json` 一致。

    此前一个是 0.1.0、一个是 0.13.0——适配器版本长期没跟。
    """
    skill = json.loads((REPO_ROOT / "skill.json").read_text(encoding="utf-8"))
    assert str(spec["info"]["version"]) == str(skill["version"]), (
        f"openai.yaml={spec['info']['version']} skill.json={skill['version']}"
    )


def test_name_matches_repo(spec):
    skill = json.loads((REPO_ROOT / "skill.json").read_text(encoding="utf-8"))
    assert spec["x-skill-info"]["name"] == skill["name"] == REPO_ROOT.name


def test_readme_measured_numbers_match_report():
    """README 的「实例」表必须与当前报告一致。

    此前 README（中/英）写的是一组很早的单日小样本数字
    （1,576 / 168 / 282 / 0.80），而仓库夹具是 14 天，
    读者跑出来的结果完全对不上。
    """
    report_path = REPO_ROOT / "output" / "report.json"
    if not report_path.exists():
        pytest.skip("需要先运行 scripts/build.py")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    by_axis = report["ledger"]["aggregate"]["by_axis"]

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for axis in ("condition", "signal", "wait", "entry", "exit"):
        row = by_axis[axis]
        count = f"{row['comparable']:,}"
        assert count in readme, (
            f"README 未出现 {axis} 轴的实际可比项数 {count}"
        )