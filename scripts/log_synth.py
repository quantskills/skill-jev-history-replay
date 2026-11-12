"""JEV 侧日志生成器（合成模式）。

真实 JEV 日志不可得时，用同一份历史 K 线 + 一份**显式声明**的「已记录语义」
档位生成等价形态的日志，用途是：

1. 验证对齐链路本身可跑通（信号时点 / 等待 / 入场 / 退出四段都有记录）；
2. 让「语义差异 → 账本差异」这条因果链可被复现与验收。

合成日志**不是** JEV 的真实行为，因此任何基于它的结论都只能记为
`verdict=inconclusive`。报告会在 `provenance` 段显式标注 `log_source=synthetic`。
"""

from __future__ import annotations

from typing import Any, Dict, List

from .replayer import replay_all


def synthesize_logs(bars_by_symbol: Dict[str, Dict[str, Any]],
                    logged_semantics: Dict[str, Any],
                    prev_closes: Dict[str, float]) -> List[Dict[str, Any]]:
    """按「已记录语义」生成 condition/signal/plan/fill 四类记录。

    额外模拟两处真实日志系统常见的记录习惯（不改变交易结果，只改变可观测性）：
    - `condition` 记录只在条件成立或状态翻转时写，避免逐根刷屏；
    - `fill` 记录的成交价带有 1 个最小价位的滑点，与计划价不完全相等。
    """
    replay = replay_all(bars_by_symbol, logged_semantics, prev_closes)
    records: List[Dict[str, Any]] = []

    # 必须遍历逐序列视图。合并视图（symbols）里一个标的所有交易日的信号
    # 会被压成一条并共用最后一天的日期，导致日志日期错标。
    views = replay.get("by_series") or replay["symbols"]
    for series, result in views.items():
        symbol = result.get("symbol") or result.get("symbol_key") or series
        date_text = result.get("date") or ""
        base = {"symbol": symbol}
        if date_text:
            base["date"] = date_text
        details = result["details"]
        prev_state = None
        for detail in details:
            state = bool(detail["hit"])
            if prev_state is None or state != prev_state:
                records.append({
                    **base,
                    "ts": detail["time"],
                    "kind": "condition",
                    "symbol": symbol,
                    "hit": state,
                    "reference": detail["reference"],
                    "baseline": detail["baseline"],
                    "gain_pct": (
                        round(detail["gain_pct"], 8)
                        if detail["gain_pct"] is not None else None
                    ),
                })
                prev_state = state

        for cycle in result["cycles"]:
            # 只输出在本序列入场的信号；跨日带入的持仓属于前一日的信号
            if cycle.get("carried_from_previous_day"):
                continue
            records.append({
                **base,
                "ts": cycle["signal_time"],
                "kind": "signal",
                "symbol": symbol,
                "signal": "buy",
                "wait_bars": cycle.get("wait_bars"),
            })
            if cycle.get("entry_time"):
                records.append({
                    **base,
                    "ts": cycle["entry_time"],
                    "kind": "plan",
                    "symbol": symbol,
                    "plan": "enter",
                    "entry_time": cycle["entry_time"],
                    "entry_price": cycle.get("entry_price"),
                    "wait_bars": cycle.get("wait_bars"),
                    "qty": cycle.get("qty"),
                    "exit_time": cycle.get("exit_time"),
                    "exit_reason": cycle.get("exit_reason"),
                    "net_return_pct": cycle.get("net_return_pct"),
                })
            if cycle.get("entry_time") and cycle.get("exit_time"):
                tick = round(cycle["entry_price"] * 0.001, 2) or 0.01
                records.append({
                    **base,
                    "ts": cycle["entry_time"],
                    "kind": "fill",
                    "symbol": symbol,
                    "side": "buy",
                    "price": round(cycle["entry_price"] + tick, 6),
                    "qty": cycle.get("qty"),
                    "status": "filled",
                })
                records.append({
                    **base,
                    "ts": cycle["exit_time"],
                    "kind": "fill",
                    "symbol": symbol,
                    "side": "sell",
                    "price": cycle["exit_price"],
                    "qty": cycle.get("qty"),
                    "status": "filled",
                })

    # 记录级来源标记：随文件走，替换成真实日志后该字段自然消失，
    # 报告据此判定 log_source，不依赖目录名或人工声明。
    for rec in records:
        rec["_synthetic"] = True
    records.sort(key=lambda r: (r.get("date", ""), r["symbol"], r["ts"]))
    return records