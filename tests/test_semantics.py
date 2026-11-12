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