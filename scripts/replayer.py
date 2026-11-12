"""确定性重放器：按显式语义把「盯盘条件」还原成逐根判断、信号、计划与执行。

设计原则：
1. 纯函数式，无随机数、无外部服务、无时钟依赖；同一输入必得同一输出。
2. 每一个解释选择都来自 `semantics` 字典，代码里不写死"前 20 根含不含当前根"
   这类隐含约定。
3. 只产出"应发指令"，永不下单。
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from .data_loader import minutes_of


def _decision_time(bar_time: str, bar_timestamp: str) -> str:
    """K线时间戳 → 该根结束后的决策时刻。

    bar_end   : 09:31 这根在 09:31 收盘后可用 → 决策时刻 09:31
    bar_start : 09:31 表示 09:31–09:32 这一段，结束后才能决策 → 09:32
    """
    minute = minutes_of(bar_time)
    if bar_timestamp == "bar_start":
        minute += 1
    hour, rem = divmod(minute, 60)
    if hour >= 24:
        return "23:59"
    return f"{hour:02d}:{rem:02d}"


def _baseline_price(bars: List[Dict[str, Any]], index: int, window: List[Dict[str, Any]],
                    semantics: Dict[str, Any], prev_close: Optional[float]) -> Optional[float]:
    mode = semantics["baseline_price"]
    if mode == "prev_close":
        return prev_close
    if mode == "day_open":
        return bars[0]["open"] if bars else None
    if mode == "window_start":
        return window[0]["open"] if window else None
    return None


def _window(bars: List[Dict[str, Any]], index: int, semantics: Dict[str, Any]) -> List[Dict[str, Any]]:
    n = int(semantics["breakout_window"])
    if semantics["breakout_includes_current"]:
        start = max(0, index - n + 1)
        return bars[start:index + 1]
    start = max(0, index - n)
    return bars[start:index]


def evaluate_condition(bars: List[Dict[str, Any]], index: int, semantics: Dict[str, Any],
                       prev_close: Optional[float]) -> Dict[str, Any]:
    """对第 index 根做条件判断，返回判断明细（供账本逐项对照）。"""
    window = _window(bars, index, semantics)
    bar = bars[index]
    detail: Dict[str, Any] = {
        "index": index,
        "time": _decision_time(bar["time"], semantics["bar_timestamp"]),
        "window_size": len(window),
        "reference": None,
        "baseline": None,
        "gain_pct": None,
        "passed_breakout": False,
        "passed_gain": False,
        "hit": False,
    }
    if len(window) < int(semantics["breakout_window"]):
        detail["reason"] = "warmup"
        return detail

    field = semantics["breakout_field"]
    detail["reference"] = max(item[field] for item in window)
    detail["baseline"] = _baseline_price(bars, index, window, semantics, prev_close)
    if not detail["baseline"] or detail["baseline"] <= 0:
        detail["reason"] = "no_baseline"
        return detail

    detail["gain_pct"] = (bar["close"] - detail["baseline"]) / detail["baseline"]
    detail["passed_breakout"] = bar["close"] > detail["reference"]
    detail["passed_gain"] = detail["gain_pct"] >= semantics["signal_gain_pct"]
    detail["hit"] = detail["passed_breakout"] and detail["passed_gain"]
    if not detail["hit"]:
        detail["reason"] = "breakout_failed" if not detail["passed_breakout"] else "gain_failed"
    return detail


def _consecutive_hits(details: List[Dict[str, Any]]) -> List[bool]:
    streak = 0
    flags: List[bool] = []
    need = 1
    for detail in details:
        streak = streak + 1 if detail["hit"] else 0
        flags.append(streak >= need)
    return flags


def _net_return(entry: float, exit_price: float, semantics: Dict[str, Any]) -> float:
    cost = (semantics["fee_bps"] + semantics["slippage_bps"]) * 2 / 10_000
    return (exit_price - entry) / entry - cost


def simulate_symbol(symbol: str, bars: List[Dict[str, Any]], semantics: Dict[str, Any],
                    prev_close: Optional[float], initial_capital: float) -> Dict[str, Any]:
    """对一个标的做完整重放，返回判断序列与交易周期。"""
    details = [
        evaluate_condition(bars, i, semantics, prev_close) for i in range(len(bars))
    ]

    need = int(semantics["persistence_bars"])
    streak = 0
    signals: List[Dict[str, Any]] = []
    cycles: List[Dict[str, Any]] = []
    last_signal_index = -10**9
    cooldown = int(semantics["cooldown_bars"])
    entry_cutoff = minutes_of(semantics["no_entry_after"])
    force_time = minutes_of(semantics["force_exit_time"])

    for i, detail in enumerate(details):
        streak = streak + 1 if detail["hit"] else 0
        if streak < need:
            continue
        if detail["index"] - last_signal_index < cooldown:
            continue
        last_signal_index = detail["index"]
        signal = {
            "symbol": symbol,
            "index": i,
            "time": detail["time"],
            "reason": "breakout_confirm",
            "consecutive_hits": streak,
            "gain_pct": detail["gain_pct"],
            "reference": detail["reference"],
        }
        signals.append(signal)
        cycles.append(_execute(symbol, bars, signal, semantics, initial_capital,
                               entry_cutoff, force_time))

    closed = [c for c in cycles if c["status"] == "closed"]
    return {
        "symbol": symbol,
        "bar_count": len(bars),
        "details": details,
        "signals": signals,
        "cycles": cycles,
        "closed_count": len(closed),
        "total_net_pct": round(sum(c["net_return_pct"] for c in closed), 6),
    }


def _execute(symbol: str, bars: List[Dict[str, Any]], signal: Dict[str, Any],
             semantics: Dict[str, Any], initial_capital: float,
             entry_cutoff: int, force_time: int) -> Dict[str, Any]:
    """信号 → 等待 → 入场 → 退出。只返回计划与结果，不产生任何副作用。"""
    i = signal["index"]
    wait = int(semantics["wait_bars"])
    # 语义定义（见 references/semantics_matrix.md）：
    #   wait_bars  = 信号后完全空过的根数（这种根不参与成交）
    #   signal_close → 在信号根之后第 wait 根的收盘成交（wait=0 即信号根收盘）
    #   next_open    → 在信号根之后第 wait+1 根的开盘成交
    if semantics["entry_price"] == "signal_close":
        entry_index = i + wait
    else:  # next_open
        entry_index = i + wait + 1

    cycle: Dict[str, Any] = {
        "symbol": symbol,
        "signal_time": signal["time"],
        "signal_index": i,
        "wait_bars": wait,
        "bars_to_entry": None,
        "entry_time": None,
        "entry_price": None,
        "qty": 0,
        "exit_time": None,
        "exit_price": None,
        "exit_reason": None,
        "status": "no_entry_bar",
        "gross_return_pct": None,
        "net_return_pct": None,
    }

    if entry_index >= len(bars):
        cycle["reason"] = "signal_too_late"
        return cycle

    entry_bar = bars[entry_index]
    entry_time = _decision_time(entry_bar["time"], semantics["bar_timestamp"])
    price = entry_bar["open"] if semantics["entry_price"] == "next_open" else bars[i]["close"]
    cycle["bars_to_entry"] = entry_index - i
    cycle["entry_time"] = entry_time
    cycle["entry_price"] = price

    if minutes_of(entry_time) > entry_cutoff:
        cycle["status"] = "rejected_late_entry"
        cycle["reason"] = f"entry {entry_time} 晚于 {semantics['no_entry_after']}"
        return cycle

    lot = int(semantics["lot_size"])
    budget = initial_capital * float(semantics["position_pct"])
    qty = int(math.floor(budget / price / lot)) * lot if price > 0 else 0
    if qty <= 0:
        cycle["status"] = "rejected_lot"
        cycle["reason"] = "可用资金不足一手"
        return cycle
    cycle["qty"] = qty

    stop = float(semantics["stop_loss_pct"])
    take = float(semantics["take_profit_pct"])
    max_hold = int(semantics["max_hold_bars"])

    for j in range(entry_index + 1, len(bars)):
        bar = bars[j]
        bar_minute = minutes_of(_decision_time(bar["time"], semantics["bar_timestamp"]))
        held = j - entry_index

        if held > max_hold:
            _close(cycle, bars[j - 1], semantics, "max_hold", bars, entry_index)
            return cycle
        if bar_minute >= force_time:
            reason = "force_exit_time"
            if _close(cycle, bar, semantics, reason, bars, entry_index):
                return cycle

        if semantics["exit_eval"] == "bar_high_low":
            low_ret = (bar["low"] - price) / price
            high_ret = (bar["high"] - price) / price
            if low_ret <= -stop:
                _set_exit(cycle, bar["time"], price * (1 - stop), "stop_loss", semantics)
                return cycle
            if high_ret >= take:
                _set_exit(cycle, bar["time"], price * (1 + take), "take_profit", semantics)
                return cycle
        else:
            close_ret = (bar["close"] - price) / price
            if close_ret <= -stop:
                _set_exit(cycle, bar["time"], bar["close"], "stop_loss", semantics)
                return cycle
            if close_ret >= take:
                _set_exit(cycle, bar["time"], bar["close"], "take_profit", semantics)
                return cycle

    last = bars[-1]
    if semantics["t_plus_1"]:
        cycle["status"] = "deferred_t_plus_1"
        cycle["reason"] = "当日入场不可当日卖出，窗口内无下一交易日数据"
        return cycle
    _set_exit(cycle, last["time"], last["close"], "end_of_data", semantics)
    return cycle


def _close(cycle: Dict[str, Any], bar: Dict[str, Any], semantics: Dict[str, Any],
           reason: str, bars: List[Dict[str, Any]], entry_index: int) -> bool:
    if semantics["t_plus_1"]:
        cycle["status"] = "deferred_t_plus_1"
        cycle["reason"] = f"{reason} 触发，但 T+1 禁止当日卖出"
        return False
    _set_exit(cycle, bar["time"], bar["close"], reason, semantics)
    return True


def _set_exit(cycle: Dict[str, Any], bar_time: str, price: float, reason: str,
              semantics: Dict[str, Any]) -> None:
    cycle["status"] = "closed"
    cycle["exit_time"] = _decision_time(bar_time, semantics["bar_timestamp"])
    cycle["exit_price"] = round(price, 6)
    cycle["exit_reason"] = reason
    gross = (price - cycle["entry_price"]) / cycle["entry_price"]
    cycle["gross_return_pct"] = round(gross, 8)
    cycle["net_return_pct"] = round(_net_return(cycle["entry_price"], price, semantics), 8)


def replay_all(bars_by_symbol: Dict[str, Dict[str, Any]], semantics: Dict[str, Any],
               prev_closes: Optional[Dict[str, float]] = None,
               initial_capital: Optional[float] = None) -> Dict[str, Any]:
    """对全部标的执行重放。"""
    capital = float(
        initial_capital if initial_capital is not None else semantics["initial_capital"]
    )
    prev_closes = prev_closes or {}
    per_symbol = {}
    for symbol, entry in sorted(bars_by_symbol.items()):
        per_symbol[symbol] = simulate_symbol(
            symbol, entry["bars"], semantics, prev_closes.get(symbol), capital
        )
    total_closed = sum(v["closed_count"] for v in per_symbol.values())
    return {
        "symbols": per_symbol,
        "summary": {
            "symbol_count": len(per_symbol),
            "signal_count": sum(len(v["signals"]) for v in per_symbol.values()),
            "cycle_count": sum(len(v["cycles"]) for v in per_symbol.values()),
            "closed_count": total_closed,
            "total_net_pct": round(
                sum(v["total_net_pct"] for v in per_symbol.values()), 6
            ),
        },
    }