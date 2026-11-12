"""差异账本：五轴对齐、配对唯一性、单边缺失与差异分类。"""

from __future__ import annotations

from scripts.aligner import aggregate_rows, align_symbol, compare_conditions


def _detail(time, hit, reason=""):
    return {"index": 0, "time": time, "hit": hit, "reason": reason,
            "window_size": 20, "reference": 10.0, "baseline": 10.0, "gain_pct": 0.01,
            "passed_breakout": hit, "passed_gain": hit}


def test_condition_match_row():
    rows = compare_conditions("S", [_detail("09:31", True)],
                              [{"ts": "09:31", "minute": 571, "hit": True}], 1)
    assert len(rows) == 1
    assert rows[0]["status"] == "match"


def test_condition_divergent_row():
    rows = compare_conditions("S", [_detail("09:31", True)],
                              [{"ts": "09:31", "minute": 571, "hit": False}], 1)
    assert rows[0]["status"] == "divergent"
    assert rows[0]["jev"] is False


def test_condition_missing_log_record_is_one_sided():
    rows = compare_conditions("S", [_detail("09:31", True)], [], 1)
    assert rows[0]["status"] == "jev_missing"


def test_condition_time_shift_detected():
    rows = compare_conditions("S", [_detail("09:31", True)],
                              [{"ts": "09:32", "minute": 572, "hit": True}], 1)
    statuses = {r["status"] for r in rows}
    assert "time_shifted" in statuses


def test_time_shift_does_not_reuse_precisely_matched_record():
    """一次判断只能记一行，不能既算精确匹配又算时间错位。"""
    rows = compare_conditions(
        "S",
        [_detail("09:31", True), _detail("09:32", True)],
        [{"ts": "09:31", "minute": 571, "hit": True}],
        1,
    )
    matched = [r for r in rows if r["status"] == "match"]
    shifted = [r for r in rows if r["status"] == "time_shifted"]
    assert len(matched) == 1
    assert len(shifted) == 0
    assert any(r["status"] == "jev_missing" for r in rows)


def _replay(cycles, signals=None):
    return {
        "symbol": "S",
        "bar_count": 240,
        "details": [],
        "signals": signals or [],
        "cycles": cycles,
        "closed_count": sum(1 for c in cycles if c["status"] == "closed"),
        "total_net_pct": 0.0,
    }


def _cycle(signal_time="09:40", entry_time="09:41", exit_time="09:50",
           reason="take_profit", status="closed"):
    return {
        "symbol": "S", "signal_time": signal_time, "signal_index": 9,
        "wait_bars": 0, "bars_to_entry": 1, "entry_time": entry_time,
        "entry_price": 10.0, "qty": 1000, "exit_time": exit_time,
        "exit_price": 10.5, "exit_reason": reason, "status": status,
        "gross_return_pct": 0.05, "net_return_pct": 0.048,
    }


def test_signal_axis_pairs_one_to_one():
    signals = [{"symbol": "S", "index": 9, "time": "09:40", "reason": "x",
                "consecutive_hits": 2, "gain_pct": 0.01, "reference": 10.0}]
    logs = {"condition": [],
            "signal": [{"ts": "09:40", "minute": 580, "symbol": "S"}],
            "plan": [], "fill": []}
    out = align_symbol("S", _replay([_cycle()], signals), logs, 1, 5.0)
    signal_rows = [r for r in out["rows"] if r["axis"] == "signal"]
    assert len(signal_rows) == 1
    assert signal_rows[0]["status"] == "match"


def test_cycle_axes_produce_entry_and_exit_rows():
    cycle = _cycle()
    logs = {"condition": [], "signal": [],
            "plan": [{"ts": "09:41", "minute": 581, "symbol": "S",
                      "entry_time": "09:41", "entry_price": 10.0,
                      "wait_bars": 0, "exit_time": "09:50", "exit_reason": "take_profit"}],
            "fill": []}
    out = align_symbol("S", _replay([cycle]), logs, 1, 5.0)
    axes = {r["axis"] for r in out["rows"]}
    assert {"entry", "exit"} <= axes
    assert all(r["status"] == "match" for r in out["rows"] if r["axis"] in ("entry", "exit"))


def test_exit_reason_mismatch_flagged():
    cycle = _cycle(reason="take_profit")
    logs = {"condition": [], "signal": [],
            "plan": [{"ts": "09:41", "minute": 581, "symbol": "S",
                      "entry_time": "09:41", "entry_price": 10.0,
                      "exit_time": "09:50", "exit_reason": "stop_loss"}],
            "fill": []}
    out = align_symbol("S", _replay([cycle]), logs, 1, 5.0)
    exit_rows = [r for r in out["rows"] if r["axis"] == "exit" and r["field"] == "reason"]
    assert exit_rows and exit_rows[0]["status"] == "divergent"
    assert out["decision_changes"], "退出原因不同必须记入决策改变"


def test_trade_added_when_replay_only():
    logs = {"condition": [], "signal": [], "plan": [], "fill": []}
    out = align_symbol("S", _replay([_cycle()]), logs, 1, 5.0)
    assert any("trade_added" in c["changes"] for c in out["decision_changes"])


def test_trade_missing_when_log_only():
    logs = {"condition": [], "signal": [],
            "plan": [{"ts": "09:41", "minute": 581, "symbol": "S",
                      "entry_time": "09:41", "entry_price": 10.0}],
            "fill": []}
    out = align_symbol("S", _replay([]), logs, 1, 5.0)
    assert any("trade_missing" in c["changes"] for c in out["decision_changes"])


def test_aggregate_rates_exclude_one_sided():
    rows = {"S": [
        {"axis": "condition", "symbol": "S", "time": "09:31", "status": "match"},
        {"axis": "condition", "symbol": "S", "time": "09:32", "status": "divergent"},
        {"axis": "condition", "symbol": "S", "time": "09:33", "status": "jev_missing"},
    ]}
    agg = aggregate_rows(rows)
    assert agg["total"]["comparable"] == 2
    assert agg["total"]["match_rate"] == 0.5
    assert agg["total"]["one_sided"] == 1
    assert agg["total"]["divergence_items"] == 1


def test_aggregate_empty_is_none_rate():
    agg = aggregate_rows({"S": []})
    assert agg["total"]["match_rate"] is None


def test_every_axis_exposes_match_and_divergent_even_when_zero():
    """每个轴都必须给出 `match` / `divergent`，零也要写。

    文档写的是"每个轴：match / divergent / one_sided"。但 `by_axis`
    原先只存真实出现过的状态名——某轴恰好没有冲突时 `divergent`
    这个键整个消失，读者按 `row["divergent"]` 取值会直接 KeyError，
    而 `comparable == match + divergent` 也无法校验。
    """
    rows = {"S": [
        {"axis": "condition", "symbol": "S", "time": "09:31", "status": "match"},
        {"axis": "signal", "symbol": "S", "time": "09:31", "status": "jev_missing"},
    ]}
    by_axis = aggregate_rows(rows)["by_axis"]
    for axis in ("condition", "signal", "wait", "entry", "exit"):
        row = by_axis[axis]
        assert "match" in row, f"{axis} 轴缺 match"
        assert "divergent" in row, f"{axis} 轴缺 divergent"
        assert "one_sided" in row, f"{axis} 轴缺 one_sided"
        assert row["comparable"] == row["match"] + row["divergent"]
        if row["comparable"]:
            assert abs(row["match_rate"] - row["match"] / row["comparable"]) < 1e-3


def test_pairing_tolerance_exceeds_verdict_tolerance():
    """配对容差必须大于判定容差，否则"差 2 分钟"会被误记成单边缺失。"""
    from scripts.aligner import _pair_cycles
    cycles = [{"entry_time": "09:33", "signal_time": "09:33"}]
    plans = [{"ts": "09:31", "minute": 571, "entry_time": "09:31",
              "exit_time": "09:31"}]
    pairs = _pair_cycles(cycles, plans, tol_minutes=1, time_field="exit_time")
    assert pairs[0]["log"] is not None, "超出判定容差但应能配上"


def _tolerance_view(exit_time):
    cyc = {"signal_time": "09:35", "entry_time": "09:36", "entry_price": 10.0,
           "exit_time": exit_time, "exit_price": 11.0,
           "exit_reason": "take_profit", "status": "closed"}
    return {"details": [], "signals": [{"time": "09:35", "price": 10.0}],
            "cycles": [cyc], "exit_cycles": [cyc]}


def _tolerance_logs():
    return {
        "condition": [],
        "signal": [{"ts": "09:35", "minute": 575, "signal": "buy"}],
        "plan": [{"ts": "09:36", "minute": 576, "plan": "enter", "symbol": "S",
                  "entry_time": "09:36", "entry_price": 10.0,
                  "exit_time": "09:40", "exit_reason": "take_profit"}],
        "fill": [],
    }


def test_verdict_tolerance_actually_changes_verdict():
    """`time_tolerance_minutes` 必须真正参与判定，而不只是影响配对半径。

    此前四处判定都写死 `"match" if gap == 0`，于是把容差从 0 调到 5
    结果**一模一样**；文档还把这种"四档一致"解释成"退出时刻差是整分钟的
    离散值、工时点比较天然精确"——把一个参数没生效的 bug 说成了结论。
    """
    logs = _tolerance_logs()

    def exit_status(tol):
        rows = align_symbol("S", _tolerance_view("09:43"), logs, tol, 5.0)["rows"]
        return [r["status"] for r in rows
                if r["axis"] == "exit" and r.get("field") == "time"][0]

    # 退出时刻差 3 分钟
    assert exit_status(0) == "divergent"
    assert exit_status(2) == "divergent"
    assert exit_status(3) == "match", "容差 3 分钟应刚好容忍 3 分钟的差"
    assert exit_status(5) == "match"


def test_entry_and_signal_axes_honour_tolerance():
    """entry / signal 轴同样必须受容差控制。

    注意信号轴的配对半径就是 `tol`：差 2 分钟且 tol=0 时配不上，
    结果是 `replay_only`（单边缺失），而不是 `divergent`。
    这两种都是"没对上"，但语义不同，断言要按实际口径写。
    """
    logs = _tolerance_logs()
    logs["signal"] = [{"ts": "09:37", "minute": 577, "signal": "buy"}]  # 差 2 分钟

    def signal_status(tol):
        rows = align_symbol("S", _tolerance_view("09:40"), logs, tol, 5.0)["rows"]
        return [r["status"] for r in rows if r["axis"] == "signal"][0]

    assert signal_status(0) == "replay_only"   # 配对半径内没有记录
    assert signal_status(1) == "replay_only"
    assert signal_status(2) == "match", "tol=2 时应配上且时点差在容差内"


def test_nearest_fallback_pairs_far_apart_records():
    """容差外也应配上最近的记录，标为低置信，而不是单边缺失。"""
    from scripts.aligner import _pair_cycles
    cycles = [{"exit_time": "09:53", "signal_time": "09:53"}]
    plans = [{"ts": "09:31", "minute": 571, "exit_time": "09:31"}]
    pairs = _pair_cycles(cycles, plans, tol_minutes=1, time_field="exit_time")
    assert pairs[0]["log"] is not None
    assert pairs[0].get("low_confidence_pairing") is True


def test_entry_axis_ignores_exit_plans():
    """退出类计划带 entry_time，不能混进入场候选池。"""
    logs = {"condition": [], "signal": [],
            "plan": [{"ts": "09:31", "minute": 571, "symbol": "S",
                      "plan": "exit", "entry_time": "09:31",
                      "exit_time": "09:31", "exit_reason": "stop_loss"}],
            "fill": []}
    out = align_symbol("S", _replay([]), logs, 1, 5.0)
    entry_rows = [r for r in out["rows"] if r["axis"] == "entry"]
    assert entry_rows == [], "退出计划不应产生入场轴行"
