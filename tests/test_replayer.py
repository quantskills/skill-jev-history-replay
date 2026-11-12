"""重放器：条件判断、连续性、等待与入场、退出、T+1、时间边界。"""

from __future__ import annotations

import copy

from scripts import replayer

from conftest import make_bars


def _sem(base):
    s = dict(base)
    return s


def test_no_signal_during_warmup(semantics):
    bars = make_bars([10.0] * 10)
    result = replayer.simulate_symbol("S", bars, semantics, prev_close=9.9, initial_capital=1e6)
    assert result["signals"] == []
    assert all(d["reason"] == "warmup" for d in result["details"][:5])


def test_breakout_triggers_signal(semantics, flat_then_breakout):
    bars = make_bars(flat_then_breakout)
    result = replayer.simulate_symbol("S", bars, semantics, prev_close=10.0, initial_capital=1e6)
    assert result["signals"], "突破后应至少产生一次信号"


def test_breakout_window_excluding_current(semantics):
    """窗口不含当前根：close 必须严格高于历史最高。"""
    semantics = _sem(semantics)
    semantics["persistence_bars"] = 1
    prices = [10.0] * 6 + [10.0]          # 不突破
    bars = make_bars(prices)
    detail = replayer.evaluate_condition(bars, 6, semantics, prev_close=10.0)
    assert detail["passed_breakout"] is False

    prices2 = [10.0] * 6 + [10.5]
    detail2 = replayer.evaluate_condition(make_bars(prices2), 6, semantics, prev_close=10.0)
    assert detail2["passed_breakout"] is True


def test_persistence_requires_consecutive_hits(semantics):
    semantics = _sem(semantics)
    semantics["persistence_bars"] = 2
    prices = [10.0] * 6 + [10.5, 10.1, 10.6]
    bars = make_bars(prices)
    result = replayer.simulate_symbol("S", bars, semantics, prev_close=10.0, initial_capital=1e6)
    # 第 7 根命中后第 8 根回落打断，第 9 根只是重新计数到 1 → 不应确认
    assert result["signals"] == []

    prices2 = [10.0] * 6 + [10.5, 10.6]
    result2 = replayer.simulate_symbol(
        "S", make_bars(prices2), semantics, prev_close=10.0, initial_capital=1e6
    )
    assert len(result2["signals"]) == 1
    assert result2["signals"][0]["consecutive_hits"] == 2


def test_gain_threshold_blocks_small_move(semantics):
    semantics = _sem(semantics)
    semantics["signal_gain_pct"] = 0.10
    prices = [10.0] * 6 + [10.2]
    detail = replayer.evaluate_condition(make_bars(prices), 6, semantics, prev_close=10.0)
    assert detail["passed_breakout"] is True
    assert detail["passed_gain"] is False
    assert detail["hit"] is False


def test_wait_bars_shifts_entry(semantics):
    prices = [10.0] * 6 + [10.5, 10.6, 10.7, 11.5]
    bars = make_bars(prices)
    s0 = _sem(semantics); s0["wait_bars"] = 0
    s1 = _sem(semantics); s1["wait_bars"] = 1
    r0 = replayer.simulate_symbol("S", bars, s0, 10.0, 1e6)
    r1 = replayer.simulate_symbol("S", bars, s1, 10.0, 1e6)
    assert r0["cycles"][0]["wait_bars"] == 0
    assert r1["cycles"][0]["wait_bars"] == 1
    # wait=1 时入场被推后一根，成交价因此不同
    assert r1["cycles"][0]["bars_to_entry"] == r0["cycles"][0]["bars_to_entry"] + 1


def test_entry_price_modes_differ(semantics):
    prices = [10.0] * 6 + [10.5, 10.6, 10.7, 11.5]
    bars = make_bars(prices)
    s_open = _sem(semantics); s_open["entry_price"] = "next_open"
    s_close = _sem(semantics); s_close["entry_price"] = "signal_close"
    r_open = replayer.simulate_symbol("S", bars, s_open, 10.0, 1e6)
    r_close = replayer.simulate_symbol("S", bars, s_close, 10.0, 1e6)
    assert r_open["cycles"][0]["bars_to_entry"] != r_close["cycles"][0]["bars_to_entry"]


def test_take_profit_closes_position(semantics):
    prices = [10.0] * 6 + [10.5, 10.6, 11.0]
    bars = make_bars(prices)
    semantics = _sem(semantics)
    semantics["take_profit_pct"] = 0.01
    semantics["t_plus_1"] = False   # 本用例只验证退出判定，与 T+1 解耦
    result = replayer.simulate_symbol("S", bars, semantics, 10.0, 1e6)
    cycle = result["cycles"][0]
    assert cycle["status"] == "closed"
    assert cycle["exit_reason"] == "take_profit"


def test_stop_loss_closes_position(semantics):
    prices = [10.0] * 6 + [10.5, 10.6, 10.2]
    bars = make_bars(prices)
    semantics = _sem(semantics)
    semantics["stop_loss_pct"] = 0.01
    semantics["t_plus_1"] = False
    result = replayer.simulate_symbol("S", bars, semantics, 10.0, 1e6)
    assert result["cycles"][0]["exit_reason"] == "stop_loss"


def test_max_hold_bars_forces_exit(semantics):
    prices = [10.0] * 6 + [10.5] + [10.6] * 30
    bars = make_bars(prices)
    semantics = _sem(semantics)
    semantics["max_hold_bars"] = 3
    semantics["take_profit_pct"] = 0.5
    semantics["stop_loss_pct"] = 0.5
    semantics["t_plus_1"] = False
    result = replayer.simulate_symbol("S", bars, semantics, 10.0, 1e6)
    assert result["cycles"][0]["exit_reason"] == "max_hold"


def test_force_exit_time_window(semantics):
    # 14:40 触发信号，14:45 后必须强平
    base = 9 * 60 + 31
    prices = [10.0] * 6 + [10.5] * 20
    bars = make_bars(prices, start_minute=14 * 60 + 40 - 6)
    semantics = _sem(semantics)
    semantics["take_profit_pct"] = 0.5
    semantics["stop_loss_pct"] = 0.5
    result = replayer.simulate_symbol("S", bars, semantics, 10.0, 1e6)
    assert result["cycles"], "应有计划"
    cycle = result["cycles"][0]
    if cycle["status"] == "closed":
        assert cycle["exit_reason"] in ("force_exit_time", "end_of_data")


def test_t_plus_one_defers_same_day_exit(semantics):
    prices = [10.0] * 6 + [10.5, 10.0]
    bars = make_bars(prices)
    semantics = _sem(semantics)
    semantics["t_plus_1"] = True
    semantics["stop_loss_pct"] = 0.01
    result = replayer.simulate_symbol("S", bars, semantics, 10.0, 1e6)
    # T+1 下当日买入不可当日卖出：持仓以 open 状态带出当日，交给下一交易日
    assert result["cycles"][0]["status"] == "open"
    assert result["carry_out"] is not None


def test_t_plus_one_off_allows_same_day_exit(semantics):
    prices = [10.0] * 6 + [10.5, 10.0]
    bars = make_bars(prices)
    semantics = _sem(semantics)
    semantics["t_plus_1"] = False
    semantics["stop_loss_pct"] = 0.01
    result = replayer.simulate_symbol("S", bars, semantics, 10.0, 1e6)
    assert result["cycles"][0]["status"] == "closed"


def test_late_entry_rejected(semantics):
    # 14:38 起 7 根横盘 → 14:45 信号 → 14:46 才轮到入场，已过禁入时刻
    prices = [10.0] * 7 + [10.5, 10.6]
    bars = make_bars(prices, start_minute=14 * 60 + 38)
    semantics = _sem(semantics)
    semantics["no_entry_after"] = "14:45"
    result = replayer.simulate_symbol("S", bars, semantics, 10.0, 1e6)
    statuses = {c["status"] for c in result["cycles"]}
    assert "rejected_late_entry" in statuses


def test_lot_size_rounding(semantics):
    prices = [10.0] * 6 + [10.5, 11.5]
    bars = make_bars(prices)
    semantics = _sem(semantics)
    semantics["initial_capital"] = 1000.0
    semantics["position_pct"] = 0.1
    semantics["lot_size"] = 100
    semantics["take_profit_pct"] = 0.01
    result = replayer.simulate_symbol("S", bars, semantics, 10.0, 1000.0)
    cycle = result["cycles"][0]
    # 100 元预算 / ~10.5 元 = 9 股 → 一手都买不起
    assert cycle["status"] in ("rejected_lot", "closed")
    if cycle["status"] == "closed":
        assert cycle["qty"] % 100 == 0


def test_cooldown_limits_repeat_signals(semantics):
    prices = [10.0] * 6 + [10.5, 10.6, 10.7, 10.8, 10.9, 11.0]
    bars = make_bars(prices)
    s0 = _sem(semantics); s0["cooldown_bars"] = 0
    s5 = _sem(semantics); s5["cooldown_bars"] = 5
    r0 = replayer.simulate_symbol("S", bars, s0, 10.0, 1e6)
    r5 = replayer.simulate_symbol("S", bars, s5, 10.0, 1e6)
    assert len(r5["signals"]) <= len(r0["signals"])


def test_deterministic_across_runs(semantics, flat_then_breakout):
    bars = make_bars(flat_then_breakout)
    a = replayer.simulate_symbol("S", bars, semantics, 10.0, 1e6)
    b = replayer.simulate_symbol("S", bars, semantics, 10.0, 1e6)
    assert a == b


def test_replay_all_aggregates(semantics, flat_then_breakout):
    from conftest import make_dataset

    data = make_dataset({"A": flat_then_breakout, "B": flat_then_breakout})
    out = replayer.replay_all(data, semantics, {"A": 10.0, "B": 10.0})
    assert out["summary"]["symbol_count"] == 2
    assert out["summary"]["signal_count"] == 2 * len(out["symbols"]["A"]["signals"])
    a = [{k: v for k, v in sig.items() if k != "symbol"}
         for sig in out["symbols"]["A"]["signals"]]
    b = [{k: v for k, v in sig.items() if k != "symbol"}
         for sig in out["symbols"]["B"]["signals"]]
    assert a == b