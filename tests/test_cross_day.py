"""跨日持仓传递（T+1 真实形态）。

A 股 T+1 意味着：当天买入的仓位当天卖不掉，必须把持仓带到下一交易日。
单日夹具下这条规则会让所有周期都无法收官——这本身是正确行为，
但必须有测试固定住"跨日能结算"这条路径，否则重放器会在真实多日场景下静默失效。
"""

from __future__ import annotations

from conftest import make_bars

from scripts import config, replayer


def _sem(**over):
    s = dict(config.REFERENCE_SEMANTICS)
    s.update({
        "breakout_window": 5, "warmup_bars": 5, "persistence_bars": 1,
        "wait_bars": 0, "cooldown_bars": 0, "signal_gain_pct": 0.005,
        "take_profit_pct": 0.02, "stop_loss_pct": 0.02, "max_hold_bars": 100,
        "no_entry_after": "14:45", "force_exit_time": "14:45",
        "t_plus_1": True,
    })
    s.update(over)
    return s


def _dataset(days):
    """days: [(date, prices)] → 多日 bars 结构。"""
    out = {}
    for date, prices in days:
        out[f"S@{date}"] = {
            "symbol": "S", "date": date, "bars": make_bars(prices),
        }
    return out


def test_t_plus_1_position_carries_to_next_day_and_closes():
    """第一天买入被 T+1 锁定，第二天开盘后止盈应正常收官。"""
    sem = _sem()
    data = _dataset([
        ("20260101", [10.0] * 6 + [10.5] * 4),
        ("20260102", [10.5] * 3 + [10.9] * 5),
    ])
    out = replayer.replay_all(data, sem, {"S@20260101": 10.0, "S@20260102": 10.5})
    assert out["summary"]["signal_count"] >= 1
    assert out["summary"]["closed_count"] >= 1, "次日应能收官"

    carried = [
        c for c in out["symbols"]["S"]["cycles"] if c.get("carried_from_previous_day")
    ]
    assert carried, "应有一条由前一日带过来的周期"
    assert carried[0]["exit_reason"] in ("take_profit", "stop_loss", "force_exit_time", "max_hold")


def test_position_open_at_end_is_reported_not_silently_closed():
    sem = _sem()
    data = _dataset([("20260101", [10.0] * 6 + [10.5] * 4)])
    out = replayer.replay_all(data, sem, {"S@20260101": 10.0})
    assert out["summary"]["closed_count"] == 0
    assert out["summary"]["open_count"] >= 1
    open_cycles = [c for c in out["symbols"]["S@20260101"]["cycles"]
                   if c["status"] == "open"]
    assert open_cycles[0]["reason"].startswith("当日入场")


def test_t_plus_1_off_closes_same_day():
    sem = _sem(t_plus_1=False)
    data = _dataset([("20260101", [10.0] * 6 + [10.5] * 4)])
    out = replayer.replay_all(data, sem, {"S@20260101": 10.0})
    assert out["summary"]["closed_count"] >= 1


def test_all_exit_paths_respect_t_plus_1_for_same_bar():
    """同一天内四条退出路径都不能绕过 T+1。"""
    for exit_eval in ("bar_close", "bar_high_low"):
        sem = _sem(exit_eval=exit_eval, stop_loss_pct=0.001, take_profit_pct=0.001)
        data = _dataset([("20260101", [10.0] * 6 + [9.0, 11.0, 9.0])])
        out = replayer.replay_all(data, sem, {"S@20260101": 10.0})
        for cycle in out["symbols"]["S@20260101"]["cycles"]:
            if cycle.get("carried_from_previous_day"):
                continue
            assert cycle["status"] == "open", (
                f"{exit_eval} 下 T+1 被绕过：{cycle}"
            )


def test_multi_day_merges_cycles_and_keeps_per_day_detail():
    sem = _sem()
    data = _dataset([
        ("20260101", [10.0] * 6 + [10.5] * 4),
        ("20260102", [10.5] * 3 + [10.9] * 5),
    ])
    out = replayer.replay_all(data, sem, {"S@20260101": 10.0, "S@20260102": 10.5})
    symbol_result = out["symbols"]["S"]
    assert "per_day" in symbol_result
    assert len(symbol_result["per_day"]) == 2
    # 第一天 10 根、第二天 8 根
    assert symbol_result["bar_count"] == 18


def test_single_day_behaviour_unchanged():
    """单日输入不应因为跨日逻辑而改变。"""
    sem = _sem(t_plus_1=False)
    data = {"S": {"symbol": "S", "date": "20260101",
                  "bars": make_bars([10.0] * 6 + [10.5] * 4)}}
    out = replayer.replay_all(data, sem, {"S": 10.0})
    assert list(out["symbols"]) == ["S"]
    assert out["summary"]["closed_count"] >= 1