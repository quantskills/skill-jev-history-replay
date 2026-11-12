"""语义旋钮：取值校验、哈希敏感性、替代值确定性。"""

from __future__ import annotations

import pytest

from scripts import config, semantics as sem


def test_reference_semantics_is_valid():
    assert sem.validate_semantics(config.REFERENCE_SEMANTICS) == []


@pytest.mark.parametrize("profile_name", sorted(sem.PROFILES))
def test_profiles_are_valid_on_top_of_reference(profile_name):
    merged = dict(config.REFERENCE_SEMANTICS)
    merged.update(sem.get_profile(profile_name))
    assert sem.validate_semantics(merged) == []


def test_unknown_knob_value_rejected():
    bad = dict(config.REFERENCE_SEMANTICS)
    bad["bar_timestamp"] = "bar_middle"
    problems = sem.validate_semantics(bad)
    assert any("bar_timestamp" in p for p in problems)


def test_negative_threshold_rejected():
    bad = dict(config.REFERENCE_SEMANTICS)
    bad["signal_gain_pct"] = -0.01
    assert any("signal_gain_pct" in p for p in sem.validate_semantics(bad))


def test_bool_knob_rejects_int():
    bad = dict(config.REFERENCE_SEMANTICS)
    bad["t_plus_1"] = 1
    assert any("t_plus_1" in p for p in sem.validate_semantics(bad))


def test_hash_changes_with_each_knob():
    base = sem.semantics_hash(config.REFERENCE_SEMANTICS)
    for knob in sem.KNOB_VALUES:
        trial = dict(config.REFERENCE_SEMANTICS)
        trial[knob] = sem.alternative_value(trial, knob)
        assert sem.semantics_hash(trial) != base, f"{knob} 改变后哈希未变"


def test_hash_stable_for_same_semantics():
    assert sem.semantics_hash(config.REFERENCE_SEMANTICS) == sem.semantics_hash(
        dict(config.REFERENCE_SEMANTICS)
    )


def test_hash_ignores_unrelated_keys():
    a = dict(config.REFERENCE_SEMANTICS)
    b = dict(config.REFERENCE_SEMANTICS)
    b["_hash"] = "ignore-me"
    b["some_future_knob"] = 123
    assert sem.semantics_hash(a) == sem.semantics_hash(b)


def test_alternative_value_is_deterministic_and_different():
    for knob in sem.KNOB_VALUES:
        alt1 = sem.alternative_value(config.REFERENCE_SEMANTICS, knob)
        alt2 = sem.alternative_value(config.REFERENCE_SEMANTICS, knob)
        assert alt1 == alt2
        assert alt1 != config.REFERENCE_SEMANTICS[knob]


def test_get_profile_unknown_raises():
    with pytest.raises(KeyError):
        sem.get_profile("does_not_exist")

def test_code_defaults_match_yaml_config():
    """内置默认值必须与 config/replay_config.yaml 一致。

    两者不一致会造成静默降级：缺 pyyaml 时走默认值，
    评测照跑但配置不同（曾出现 logs_dir 默认 None、
    YAML 为 fixtures/logs，导致悄悄走合成模式）。
    """
    import pathlib

    from scripts import config as cfg

    yaml_path = pathlib.Path(cfg.REPO_ROOT) / "config" / "replay_config.yaml"
    yaml_cfg = cfg._load_yaml_config(yaml_path)
    assert yaml_cfg, "YAML 配置未能加载（测试环境应有 pyyaml 或文件存在）"

    defaults = cfg._DEFAULTS
    diffs = []
    for key, value in yaml_cfg.items():
        if key == "semantics":
            continue
        if key in defaults and defaults[key] != value:
            diffs.append((key, defaults[key], value))
    for key, value in yaml_cfg.get("semantics", {}).items():
        if cfg.REFERENCE_SEMANTICS.get(key) != value:
            diffs.append((f"semantics.{key}", cfg.REFERENCE_SEMANTICS.get(key), value))
    assert diffs == [], f"默认值与 YAML 不一致：{diffs}"


def test_missing_pyyaml_is_reported():
    """缺 pyyaml 属有意降级，但必须留下可查的警告，不能静默。"""
    import builtins
    import importlib
    import sys

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    saved = {m: sys.modules.pop(m) for m in list(sys.modules)
             if m == "yaml" or m.startswith("scripts")}
    builtins.__import__ = fake_import
    try:
        cfg_mod = importlib.import_module("scripts.config")
        cfg_mod.load_config()
        warnings = cfg_mod.load_warnings()
    finally:
        builtins.__import__ = real_import
        sys.modules.update(saved)

    assert warnings, "缺 pyyaml 时必须记录降级原因"
    assert "pyyaml" in warnings[0]
