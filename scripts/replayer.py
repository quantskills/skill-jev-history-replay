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
                    prev_close: Optional[float], initial_capital: float,
                    carry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """对一个标的的**一个交易日**做完整重放。

    Args:
        carry: 上一交易日的未平持仓（T+1 场景）。含 entry_index_prev /
               entry_price / qty / signal_time / bars_held。为空表示当日开盘
               无持仓。

    当日开盘若有隔夜持仓，先处理它（止损/止盈/强平），再处理当日的信号。
    这正是 A 股 T+1 的真实形态：当天买的当天卖不掉，必须把持仓带到下一交易日。
    """
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

    if carry:
        cycles.append(_carry_forward(carry, symbol, bars, semantics, force_time))

    for i, detail in enumerate(details):
        streak = streak + 1 if detail["hit"] else 0
        if streak < need:
            continue
        if detail["index"] - last_signal_index < cooldown:
            continue
        # 上一笔仍在场（含隔夜持仓）时不叠加新仓，避免同一标的重复开仓
        if any(c["status"] in ("closed", "open") and c.get("exit_time") is None
               for c in cycles):
            if any(c["status"] == "open" for c in cycles):
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
    open_positions = [c for c in cycles if c["status"] == "open"]
    return {
        "symbol": symbol,
        "bar_count": len(bars),
        "details": details,
        "signals": signals,
        "cycles": cycles,
        "closed_count": len(closed),
        "open_count": len(open_positions),
        "total_net_pct": round(sum(c["net_return_pct"] for c in closed), 6),
        "carry_out": _carry_of(open_positions[-1]) if open_positions else None,
    }


def _carry_of(cycle: Dict[str, Any]) -> Dict[str, Any]:
    """打包跨日持仓。

    关键：把周期的**对象本身**一并带过去。一笔交易只有一个周期对象，
    次日收盘时在原地补上退出信息，而不是新建一条。
    否则入场日的周期永远停在 open，退出轴就永远配不上。
    """
    return {
        "cycle": cycle,
        "entry_price": cycle["entry_price"],
        "qty": cycle["qty"],
        "signal_time": cycle["signal_time"],
        "bars_held": cycle.get("bars_held", 0),
        "pending_exit_reason": cycle.get("pending_exit_reason"),
    }


def _carry_forward(carry: Dict[str, Any], symbol: str, bars: List[Dict[str, Any]],
                   semantics: Dict[str, Any], force_time: int) -> Dict[str, Any]:
    """把昨天的未平持仓在今天处理掉。

    复用 carry 里的原周期对象：入场信息保持不动，只在退出时补上
    exit_time / exit_price / exit_reason，并把跨日事实标记出来。
    """
    price = float(carry["entry_price"])
    cycle: Dict[str, Any] = carry.get("cycle") or {
        "symbol": symbol,
        "signal_time": carry.get("signal_time"),
        "signal_index": -1,
        "wait_bars": 0,
        "bars_to_entry": None,
        "entry_time": None,
        "entry_price": price,
        "qty": carry.get("qty", 0),
        "exit_time": None,
        "exit_price": None,
        "exit_reason": None,
        "status": "open",
        "gross_return_pct": None,
        "net_return_pct": None,
    }
    cycle["carried_from_previous_day"] = True
    cycle["bars_held"] = int(carry.get("bars_held") or cycle.get("bars_held") or 0)
    stop = float(semantics["stop_loss_pct"])
    take = float(semantics["take_profit_pct"])
    max_hold = int(semantics["max_hold_bars"])

    for j, bar in enumerate(bars):
        held = cycle["bars_held"] + j + 1
        if held > max_hold:
            _set_exit(cycle, bar["time"], bar["open"], "max_hold", semantics)
            return cycle
        if minutes_of(_decision_time(bar["time"], semantics["bar_timestamp"])) >= force_time:
            _set_exit(cycle, bar["time"], bar["close"], "force_exit_time", semantics)
            return cycle
        if semantics["exit_eval"] == "bar_high_low":
            if (bar["low"] - price) / price <= -stop:
                _set_exit(cycle, bar["time"], price * (1 - stop), "stop_loss", semantics)
                return cycle
            if (bar["high"] - price) / price >= take:
                _set_exit(cycle, bar["time"], price * (1 + take), "take_profit", semantics)
                return cycle
        else:
            if (bar["close"] - price) / price <= -stop:
                _set_exit(cycle, bar["time"], bar["close"], "stop_loss", semantics)
                return cycle
            if (bar["close"] - price) / price >= take:
                _set_exit(cycle, bar["time"], bar["close"], "take_profit", semantics)
                return cycle

    # 次日仍未触发任何退出：继续带到下一个交易日
    cycle["bars_held"] = cycle["bars_held"] + len(bars)
    return cycle


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
        cycle["_last_index"] = j
        bar_minute = minutes_of(_decision_time(bar["time"], semantics["bar_timestamp"]))
        held = j - entry_index

        # 所有退出路径都经过 _exit_or_defer，保证 T+1 在止损/止盈/强平/超时
        # 四条分支上行为一致。曾经止损止盈绕过 T+1 检查，导致同一天里
        # 强平被推迟、止损却能当日成交——同一个约束两条路径两种结果。
        if held > max_hold:
            if _exit_or_defer(cycle, bars[j - 1], bars[j - 1]["close"],
                              "max_hold", semantics):
                return cycle
            return cycle
        if bar_minute >= force_time:
            if _exit_or_defer(cycle, bar, bar["close"], "force_exit_time", semantics):
                return cycle

        if semantics["exit_eval"] == "bar_high_low":
            low_ret = (bar["low"] - price) / price
            high_ret = (bar["high"] - price) / price
            if low_ret <= -stop:
                price_out = price * (1 - stop)
                if _exit_or_defer(cycle, bar, price_out, "stop_loss", semantics):
                    return cycle
                return cycle
            if high_ret >= take:
                price_out = price * (1 + take)
                if _exit_or_defer(cycle, bar, price_out, "take_profit", semantics):
                    return cycle
                return cycle
        else:
            close_ret = (bar["close"] - price) / price
            if close_ret <= -stop:
                if _exit_or_defer(cycle, bar, bar["close"], "stop_loss", semantics):
                    return cycle
                return cycle
            if close_ret >= take:
                if _exit_or_defer(cycle, bar, bar["close"], "take_profit", semantics):
                    return cycle
                return cycle

    last = bars[-1]
    if semantics["t_plus_1"]:
        cycle["status"] = "open"
        cycle["bars_held"] = max(cycle.get("bars_held", 0), len(bars) - 1 - entry_index)
        cycle["reason"] = "当日入场，T+1 锁定，顺延至下一交易日"
        return cycle
    _set_exit(cycle, last["time"], last["close"], "end_of_data", semantics)
    return cycle


def _exit_or_defer(cycle: Dict[str, Any], bar: Dict[str, Any], price: float,
                   reason: str, semantics: Dict[str, Any]) -> bool:
    """四条退出路径的唯一出口。

    Returns:
        True  = 已退出（cycle.status 变为 closed）
        False = 因 T+1 被推迟（这些标的不具备当天卖出的资格）

    推迟时标记 deferred_t_plus_1 后继续循环是错的：A 股 T+1 下这个持仓当天
    根本卖不掉，再往后扫到次日的数据也不属于本周期。此处直接结束该周期，
    由 status 表达"未能在当日内退出"。
    """
    if semantics["t_plus_1"]:
        # 当日买、当日不可卖：把持仓标记为 open 带出当日，
        # 由下一交易日的 _carry_forward 处理。这是 T+1 的正确形态，
        # 不是"未定义"状态。
        cycle["status"] = "open"
        cycle["pending_exit_reason"] = reason
        cycle["pending_exit_price"] = round(price, 6)
        cycle["bars_held"] = cycle.get("bars_held", 0) + _bars_since_entry(cycle)
        cycle["reason"] = f"{reason} 触发，但 T+1 禁止当日卖出，顺延至下一交易日"
        return False
    _set_exit(cycle, bar["time"], price, reason, semantics)
    return True


def _bars_since_entry(cycle: Dict[str, Any]) -> int:
    if cycle.get("bars_to_entry") is None:
        return 0
    return max(0, cycle.get("_last_index", 0) - cycle.get("signal_index", 0) - cycle["bars_to_entry"])


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
    """对全部序列执行重放。

    多日模式下按 (symbol, date) 逐日推进，并把当日未平仓位传递给下一交易日，
    使 T+1 能真实跨日结算。单日模式下每个序列独立，行为不变。

    返回两份视图：
      - `symbols`：标的级合并视图（跨日周期合成一条），用于价值评估与摘要；
      - `by_series`：逐序列（symbol@date）视图，用于与同日日志逐项对齐。
    跨日周期的入场记在入场日、退出记在退出日，因此对齐按轴分别取对应序列。
    """
    capital = float(
        initial_capital if initial_capital is not None else semantics["initial_capital"]
    )
    prev_closes = prev_closes or {}

    by_symbol: Dict[str, List[tuple]] = {}
    for series, entry in sorted(bars_by_symbol.items()):
        key = entry.get("symbol") or series.split("@")[0]
        by_symbol.setdefault(key, []).append((entry.get("date") or "", series, entry))

    per_symbol: Dict[str, Any] = {}
    # 逐序列视图：details 按当日 K 线算；signals 属于当日；cycles 按入场/退出分别归日
    by_series: Dict[str, Dict[str, Any]] = {}

    for symbol_key, items in by_symbol.items():
        items.sort(key=lambda it: it[0])
        carry: Optional[Dict[str, Any]] = None
        day_results: List[Dict[str, Any]] = []

        for date_text, series, entry in items:
            result = simulate_symbol(
                series, entry["bars"], semantics, prev_closes.get(series), capital,
                carry=carry,
            )
            result["symbol_key"] = symbol_key
            result["date"] = entry.get("date") or ""
            result["series"] = series
            day_results.append(result)
            carry = result.get("carry_out")

            by_series[series] = {
                "symbol": symbol_key,
                "date": entry.get("date") or "",
                "series": series,
                "bar_count": result["bar_count"],
                "details": result["details"],
                "signals": result["signals"],
                # cycles：本序列作为**入场日**发生的周期（用于 wait/entry 轴）
                "cycles": [],
                # exit_cycles：本序列作为**退出日**发生的周期（含跨日带入的持仓，
                # 用于 exit 轴）。二者分开，避免把昨天的入场配到今天的计划上。
                "exit_cycles": [],
                "closed_count": 0,
                "total_net_pct": 0.0,
            }
            for cycle in result["cycles"]:
                # entry_series 只在第一次出现时记录（跨日对象复用同一个 dict，
                # 不能在后一天把入场日覆盖成今天）
                cycle.setdefault("entry_series", series)
                # exit_series 只在**真正退出**时定格。若周期当天仍是 open
                # （被带出当日），退出日尚未确定，绝不能把今天写成退出日——
                # 否则入场日视图会误以为退出发生在自己这天，比对时对到错误记录。
                if cycle.get("exit_time"):
                    cycle["exit_series"] = series

        if len(day_results) == 1:
            per_symbol[items[0][1]] = day_results[0]
        else:
            merged_cycles = []
            _seen: set[int] = set()
            for r in day_results:
                for c in r["cycles"]:
                    if id(c) in _seen:
                        continue
                    _seen.add(id(c))
                    merged_cycles.append(c)
            merged_signals = [sig for r in day_results for sig in r["signals"]]
            closed = [c for c in merged_cycles if c["status"] == "closed"]
            per_symbol[symbol_key] = {
                "symbol": symbol_key,
                "symbol_key": symbol_key,
                "series": symbol_key,
                "date": items[-1][0],
                "bar_count": sum(r["bar_count"] for r in day_results),
                "details": day_results[-1]["details"],
                "signals": merged_signals,
                "cycles": merged_cycles,
                "closed_count": len(closed),
                "open_count": len([c for c in merged_cycles if c["status"] == "open"]),
                "total_net_pct": round(sum(c["net_return_pct"] for c in closed), 6),
                "carry_out": carry,
                "per_day": [
                    {"date": r["date"], "series": r["series"],
                     "signals": len(r["signals"]), "closed": r["closed_count"],
                     "open": r.get("open_count", 0)}
                    for r in day_results
                ],
            }

    # 把周期按轴分配到所属序列。跨日周期的对象同时出现在两天的
    # day_results 里，必须按对象身份去重，否则同一笔交易会被记两次。
    all_cycles: List[Dict[str, Any]] = []
    seen_cycles: set[int] = set()
    for view in per_symbol.values():
        for cycle in view["cycles"]:
            if id(cycle) in seen_cycles:
                continue
            seen_cycles.add(id(cycle))
            all_cycles.append(cycle)
    for cycle in all_cycles:
        entry_series = cycle.get("entry_series")
        exit_series = cycle.get("exit_series") or entry_series
        if entry_series in by_series:
            by_series[entry_series]["cycles"].append(cycle)
        if exit_series in by_series:
            by_series[exit_series]["exit_cycles"].append(cycle)
    for view in by_series.values():
        closed = [c for c in view["cycles"] if c["status"] == "closed"]
        view["closed_count"] = len(closed)
        view["total_net_pct"] = round(sum(c["net_return_pct"] for c in closed), 6)

    total_closed = sum(v["closed_count"] for v in per_symbol.values())
    return {
        "symbols": per_symbol,
        "by_series": by_series,
        "summary": {
            "symbol_count": len(per_symbol),
            "series_count": len(by_series),
            "signal_count": sum(len(v["signals"]) for v in per_symbol.values()),
            "cycle_count": sum(len(v["cycles"]) for v in per_symbol.values()),
            "closed_count": total_closed,
            "open_count": sum(v.get("open_count", 0) for v in per_symbol.values()),
            "total_net_pct": round(
                sum(v["total_net_pct"] for v in per_symbol.values()), 6
            ),
        },
    }
