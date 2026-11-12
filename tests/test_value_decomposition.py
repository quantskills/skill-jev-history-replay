"""价值结论拆解：negative 必须能归因到具体旋钮。"""

from __future__ import annotations

import pytest

from scripts import config, semantics as sem
from scripts.value_decomposition import _carry_breakdown, _summary
from scripts.replayer import replay_all

from conftest import make_dataset


BREAKOUT = [10.0] * 15 + [10.2, 10.0, 10.3, 10.1, 10.4, 10.2, 10.5]


def _base():
    s = dict(config.REFERENCE_SEMANTICS)
    s.update({"breakout_window": 5, "warmup_bars": 5, "persistence_bars": 1,
              "wait_bars": 0, "cooldown_bars": 0, "signal_gain_pct": 0.005,
              "take_profit_pct": 0.02, "stop_loss_pct": 0.02, "max_hold_bars": 10})
    return s


def test_naive_and_reference_differ_on_multiple_knobs():
    """拆解的前提是两者确实有多个旋钮不同。"""
    naive = dict(config.REFERENCE_SEMANTICS)
    naive.update(sem.NAIVE_PROFILE)
    ref = dict(config.REFERENCE_SEMANTICS)
    differing = [k for k in sem.KNOB_VALUES if naive.get(k) != ref.get(k)]
    assert len(differing) >= 5, f"只有 {len(differing)} 个旋钮不同，拆解意义不大"
    assert "t_plus_1" in differing


def test_t_plus_1_forces_all_positions_overnight():
    """T+1 打开后，当日不应有任何平仓；全部应为跨日持仓。"""
    data = make_dataset({"A": BREAKOUT, "B": BREAKOUT})
    sem_on = _base()
    sem_on["t_plus_1"] = True

    # 单日数据：T+1 下不可能有当日平仓
    single_day = {"A": {"symbol": "A", "date": "20260101",
                        "bars": make_dataset({"A": BREAKOUT})["A"]["bars"]}}
    replay = replay_all(single_day, sem_on, {"A": 10.0})
    breakdown = _carry_breakdown(replay)
    assert breakdown["same_day"]["n"] == 0, "T+1 下不应出现当日平仓"


def test_t_plus_1_off_allows_same_day_close():
    single_day = {"A": {"symbol": "A", "date": "20260101",
                        "bars": make_dataset({"A": BREAKOUT})["A"]["bars"]}}
    sem_off = _base()
    sem_off["t_plus_1"] = False
    replay = replay_all(single_day, sem_off, {"A": 10.0})
    breakdown = _carry_breakdown(replay)
    assert breakdown["same_day"]["n"] > 0
    assert breakdown["cross_day"]["n"] == 0


def test_summary_shape():
    data = make_dataset({"A": BREAKOUT})
    replay = replay_all(data, _base(), {"A": 10.0})
    s = _summary(replay)
    assert set(s) == {"signals", "closed", "mean_net_pct", "total_net_pct"}
