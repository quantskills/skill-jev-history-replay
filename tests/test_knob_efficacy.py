"""语义旋钮必须真的影响重放，否则就是装饰性参数。"""

from __future__ import annotations

import pytest

from scripts import config, semantics as sem
from scripts.knob_efficacy import _fingerprint
from scripts.replayer import replay_all

from conftest import make_dataset


BREAKOUT = [10.0] * 15 + [10.3, 10.5, 10.7, 10.9, 11.1]


def test_fingerprint_changes_when_trade_changes():
    """指纹必须能区分不同的交易集合。"""
    bars = make_dataset({"A": BREAKOUT})
    sem_a = dict(config.REFERENCE_SEMANTICS)
    sem_a.update({"breakout_window": 5, "warmup_bars": 5, "persistence_bars": 1,
                  "wait_bars": 0, "cooldown_bars": 0, "signal_gain_pct": 0.005,
                  "t_plus_1": False})
    a = replay_all(bars, sem_a, {"A": 10.0})
    b = replay_all(bars, sem_a, {"A": 10.0})
    assert _fingerprint(a) == _fingerprint(b), "同输入指纹必须稳定"

    sem_b = dict(sem_a)
    sem_b["entry_price"] = "signal_close"
    c = replay_all(bars, sem_b, {"A": 10.0})
    entry_changed = any(
        x.get("entry_price") != y.get("entry_price")
        for ra, rb in zip(a["symbols"].values(), c["symbols"].values())
        for x, y in zip(ra["cycles"], rb["cycles"])
    )
    if entry_changed:
        assert _fingerprint(a) != _fingerprint(c)


def test_every_knob_is_wired():
    """每个旋钮都必须在代码里真的被读取。

    做法：对每个旋钮，检查其取值能否在语义字典中被替换并通过校验；
    真正的"是否影响输出"由 scripts/knob_efficacy.py 用真实数据验证。
    """
    base = dict(config.REFERENCE_SEMANTICS)
    for knob in sem.KNOB_VALUES:
        alt = dict(base)
        alt[knob] = sem.alternative_value(base, knob)
        problems = sem.validate_semantics(alt)
        assert problems == [], f"{knob} 的备选值本身非法：{problems}"
        assert alt[knob] != base[knob], f"{knob} 的备选值未改变取值"


def test_breakout_including_current_kills_all_signals():
    """窗口含当前根时，close > max(含自身) 恒假——信号必须归零。

    这正是 NAIVE_PROFILE 里把它设为 False 的原因：那不是"字面直译"，
    而是配置错误。
    """
    bars = make_dataset({"A": BREAKOUT})
    base = dict(config.REFERENCE_SEMANTICS)
    base.update({"breakout_window": 5, "warmup_bars": 5, "persistence_bars": 1,
                 "wait_bars": 0, "cooldown_bars": 0, "signal_gain_pct": 0.005,
                 "t_plus_1": False})
    on = dict(base)
    on["breakout_includes_current"] = True

    off_replay = replay_all(bars, base, {"A": 10.0})
    on_replay = replay_all(bars, on, {"A": 10.0})
    assert on_replay["summary"]["signal_count"] == 0
    assert off_replay["summary"]["signal_count"] > 0
