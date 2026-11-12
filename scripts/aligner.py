"""逐项差异账本：把「JEV 侧记录」与「重放器输出」按同一时间轴对齐。

对齐分五个轴，每个轴单独一行，互不吞并：

| 轴 | 对齐键 | 差异含义 |
|---|---|---|
| condition | 决策时刻 | 同一根 K 线，一边判成立、一边判不成立 |
| signal | 信号时刻（带容差） | 触发时点错位或单边缺失 |
| wait | 配对后的信号 | 从信号到入场的等待根数不同 |
| entry | 配对后的周期 | 入场时刻/价格不同 |
| exit | 配对后的周期 | 退出时刻/价格/原因不同 |

账本不判断哪边"对"，只记录差异。哪边更接近规则意图，由 `PRIOR` 明示，
并计入报告的 caveat。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .data_loader import minutes_of

AXES = ("condition", "signal", "wait", "entry", "exit")

# 预设先验：用于给差异标注"更可能由哪一侧的解释造成"。
# 这是显式假设，不是事实；报告中原样输出。
PRIOR = {
    "condition": "日志侧未披露比较基准与窗口口径，差异归因需消融实验确认",
    "signal": "信号时点差异主要由时间戳语义与连续性要求造成",
    "wait": "等待根数差异由 wait_bars 与 bar_timestamp 共同决定",
    "entry": "入场价差异由 entry_price 选择（当根收盘/下一根开盘）决定",
    "exit": "退出差异由退出判定字段（收盘/高低价）与 T+1 约束决定",
}


def _fmt_delta(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return round(b - a, 6)


def _row(axis: str, symbol: str, time: str, status: str, jev: Any, replay: Any,
         field: str = "", delta: Any = None, note: str = "") -> Dict[str, Any]:
    return {
        "axis": axis,
        "symbol": symbol,
        "time": time,
        "field": field,
        "jev": jev,
        "replay": replay,
        "delta": delta,
        "status": status,
        "note": note,
    }


def compare_conditions(symbol: str, details: List[Dict[str, Any]],
                       log_conditions: List[Dict[str, Any]],
                       tol_minutes: int) -> List[Dict[str, Any]]:
    """按决策时刻对齐条件判断。同一时刻两边都有记录才可能判 match。

    日志里没记录的时刻说明 JEV 未输出该根判断，单独标 `jev_missing`，
    不与"判不成立"混同——这两者语义完全不同。
    """
    rows: List[Dict[str, Any]] = []
    log_by_minute: Dict[int, Dict[str, Any]] = {}
    for rec in log_conditions:
        log_by_minute[rec["minute"]] = rec

    replay_by_minute = {minutes_of(d["time"]): d for d in details}

    # 第一轮：同一决策时刻精确对齐。只有这一轮的结果算"可比"。
    matched_log_minutes: set[int] = set()
    for minute, detail in sorted(replay_by_minute.items()):
        rec = log_by_minute.get(minute)
        if rec is None:
            continue
        matched_log_minutes.add(minute)
        jev_hit = bool(rec.get("hit"))
        status = "match" if jev_hit == bool(detail["hit"]) else "divergent"
        rows.append(_row("condition", symbol, detail["time"], status,
                         jev_hit, bool(detail["hit"]), "hit",
                         note="" if status == "match" else detail.get("reason", "")))

    # 第二轮：对未对齐的时刻，在容差内找"同样未被精确匹配"的日志记录。
    # 命中即说明同一次判断落在相邻分钟 —— 时间戳口径差异的直接证据。
    # 绝不复用已精确匹配的记录，否则会把一次判断重复计成两行。
    used_log_minutes: set[int] = set()
    unmatched_log = [
        m for m in log_by_minute if m not in matched_log_minutes
    ]
    for minute, detail in sorted(replay_by_minute.items()):
        if minute in log_by_minute:
            continue
        best = None
        best_gap = tol_minutes + 1
        for log_minute in unmatched_log:
            if log_minute in used_log_minutes:
                continue
            gap = abs(log_minute - minute)
            if gap <= tol_minutes and gap < best_gap:
                best, best_gap = log_minute, gap
        if best is not None:
            used_log_minutes.add(best)
            rows.append(_row("condition", symbol, detail["time"], "time_shifted",
                             log_by_minute[best]["ts"], detail["time"], "time", best_gap,
                             note="同一判断落在相邻分钟，指向时间戳口径差异"))
        else:
            rows.append(_row("condition", symbol, detail["time"], "jev_missing",
                             None, bool(detail["hit"]), "hit",
                             note=detail.get("reason", "")))

    # 日志有、重放完全没有对应时刻
    for minute, rec in sorted(log_by_minute.items()):
        if minute in matched_log_minutes or minute in used_log_minutes:
            continue
        rows.append(_row("condition", symbol, rec["ts"], "replay_missing",
                         bool(rec.get("hit")), None, "hit"))
    return rows


def _pair_signals(replay_signals: List[Dict[str, Any]],
                  log_signals: List[Dict[str, Any]],
                  tol_minutes: int) -> List[Dict[str, Any]]:
    """贪心最近时刻配对，一对一，不重复使用。"""
    used: set[int] = set()
    pairs: List[Dict[str, Any]] = []
    for rs in replay_signals:
        best_idx = None
        best_gap = tol_minutes + 1
        for idx, ls in enumerate(log_signals):
            if idx in used:
                continue
            gap = abs(minutes_of(rs["time"]) - ls["minute"])
            if gap <= tol_minutes and gap < best_gap:
                best_idx, best_gap = idx, gap
        if best_idx is None:
            pairs.append({"replay": rs, "log": None})
        else:
            used.add(best_idx)
            pairs.append({"replay": rs, "log": log_signals[best_idx]})
    for idx, ls in enumerate(log_signals):
        if idx not in used:
            pairs.append({"replay": None, "log": ls})
    return pairs


def _pair_cycles(replay_cycles: List[Dict[str, Any]],
                 log_plans: List[Dict[str, Any]],
                 tol_minutes: int) -> List[Dict[str, Any]]:
    """用入场时刻配对周期与计划；无计划记录时按顺序回退配对。"""
    if not log_plans:
        return [{"replay": c, "log": None} for c in replay_cycles]

    used: set[int] = set()
    pairs: List[Dict[str, Any]] = []
    for cycle in replay_cycles:
        entry_time = cycle.get("entry_time") or cycle["signal_time"]
        best_idx = None
        best_gap = tol_minutes + 1
        for idx, plan in enumerate(log_plans):
            if idx in used:
                continue
            gap = abs(minutes_of(entry_time) - plan["minute"])
            if gap <= tol_minutes and gap < best_gap:
                best_idx, best_gap = idx, gap
        if best_idx is None:
            pairs.append({"replay": cycle, "log": None})
        else:
            used.add(best_idx)
            pairs.append({"replay": cycle, "log": log_plans[best_idx]})
    for idx, plan in enumerate(log_plans):
        if idx not in used:
            pairs.append({"replay": None, "log": plan})
    return pairs


def align_symbol(symbol: str, replay: Dict[str, Any], log_groups: Dict[str, List[Dict[str, Any]]],
                 tol_minutes: int, price_tolerance_bps: float) -> Dict[str, Any]:
    """对一个标的生成完整账本与交易改变分类。"""
    rows: List[Dict[str, Any]] = []
    rows.extend(compare_conditions(symbol, replay["details"], log_groups["condition"],
                                   tol_minutes))

    pairs = _pair_signals(replay["signals"], log_groups["signal"], tol_minutes)
    for pair in pairs:
        rs, ls = pair["replay"], pair["log"]
        if rs and ls:
            gap = minutes_of(rs["time"]) - ls["minute"]
            rows.append(_row("signal", symbol, rs["time"], "match" if gap == 0 else "divergent",
                             ls["ts"], rs["time"], "time", gap,
                             note="时点错位" if gap else ""))
        elif rs:
            rows.append(_row("signal", symbol, rs["time"], "replay_only",
                             None, rs["time"], "time",
                             note="重放触发、日志无信号"))
        else:
            rows.append(_row("signal", symbol, ls["ts"], "jev_only",
                             ls["ts"], None, "time", note="日志有信号、重放未触发"))

    cycle_pairs = _pair_cycles(replay["cycles"], log_groups["plan"], tol_minutes)
    decision_changes: List[Dict[str, Any]] = []
    for pair in cycle_pairs:
        rc, lp = pair["replay"], pair["log"]
        if rc and not lp:
            rows.append(_row("entry", symbol, rc.get("entry_time") or rc["signal_time"],
                             "replay_only", None, rc.get("entry_time"), "time"))
            rows.append(_row("exit", symbol, rc.get("exit_time") or "", "replay_only",
                             None, rc.get("exit_reason")))
            decision_changes.append({
                "changes": ["trade_added"],
                "symbol": symbol,
                "signal_time": rc["signal_time"],
                "replay": {"entry": rc.get("entry_time"), "exit": rc.get("exit_time"),
                           "net_return_pct": rc.get("net_return_pct")},
                "jev": None,
            })
            continue
        if lp and not rc:
            rows.append(_row("entry", symbol, lp["ts"], "jev_only", lp["ts"], None, "time"))
            decision_changes.append({
                "changes": ["trade_missing"],
                "symbol": symbol,
                "signal_time": lp["ts"],
                "replay": None,
                "jev": {"entry": lp.get("entry_time"), "exit": lp.get("exit_time")},
            })
            continue

        changes: List[str] = []
        replay_wait = rc.get("wait_bars")
        jev_wait = lp.get("wait_bars")
        if replay_wait is not None and jev_wait is not None:
            status = "match" if replay_wait == jev_wait else "divergent"
            rows.append(_row("wait", symbol, rc["signal_time"], status,
                             jev_wait, replay_wait, "wait_bars",
                             replay_wait - jev_wait))
            if status == "divergent":
                changes.append("wait_changed")

        jev_entry_time = lp.get("entry_time") or lp["ts"]
        replay_entry_time = rc.get("entry_time")
        if replay_entry_time and jev_entry_time:
            gap = minutes_of(replay_entry_time) - minutes_of(jev_entry_time)
            status = "match" if gap == 0 else "divergent"
            rows.append(_row("entry", symbol, replay_entry_time, status,
                             jev_entry_time, replay_entry_time, "time", gap))
            if gap:
                changes.append("entry_shifted")

        jev_entry_price = lp.get("entry_price")
        replay_entry_price = rc.get("entry_price")
        if jev_entry_price and replay_entry_price:
            bps = (replay_entry_price - jev_entry_price) / jev_entry_price * 10_000
            if abs(bps) > price_tolerance_bps:
                rows.append(_row("entry", symbol, replay_entry_time or "", "divergent",
                                 jev_entry_price, replay_entry_price, "price", round(bps, 2),
                                 note="bps"))
                changes.append("entry_price_changed")

        jev_exit_time = lp.get("exit_time")
        replay_exit_time = rc.get("exit_time")
        if replay_exit_time and jev_exit_time:
            gap = minutes_of(replay_exit_time) - minutes_of(jev_exit_time)
            status = "match" if gap == 0 else "divergent"
            rows.append(_row("exit", symbol, replay_exit_time, status,
                             jev_exit_time, replay_exit_time, "time", gap))
            if gap:
                changes.append("exit_shifted")
        if rc.get("exit_reason") and lp.get("exit_reason"):
            status = "match" if rc["exit_reason"] == lp["exit_reason"] else "divergent"
            rows.append(_row("exit", symbol, replay_exit_time or rc["signal_time"], status,
                             lp["exit_reason"], rc["exit_reason"], "reason"))
            if status == "divergent":
                changes.append("exit_reason_changed")

        if changes:
            decision_changes.append({
                "changes": changes,
                "symbol": symbol,
                "signal_time": rc["signal_time"],
                "replay": {"entry": replay_entry_time, "exit": replay_exit_time,
                           "net_return_pct": rc.get("net_return_pct")},
                "jev": {"entry": jev_entry_time, "exit": jev_exit_time,
                        "net_return_pct": lp.get("net_return_pct")},
            })

    return {"rows": rows, "decision_changes": decision_changes}


def aggregate_rows(rows_by_symbol: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """按轴、按状态汇总。

    口径说明（重要）：
    - `comparable` = 两边都有记录、可以判一致或不一致的项；
    - `divergent`  = 真正冲突的项，这才是"差异账本"的计数来源；
    - `one_sided`  = 只有一边有记录。日志侧稀疏记录（只在状态翻转时落盘）
      会产生大量 `jev_missing`，这是**记录口径差异**而非语义冲突，
      因此不计入 divergent，单独作为覆盖率指标报告。
    """
    by_axis: Dict[str, Dict[str, int]] = {axis: {} for axis in AXES}
    total = {"rows": 0, "match": 0, "divergent": 0, "one_sided": 0}
    for rows in rows_by_symbol.values():
        for row in rows:
            axis = row["axis"]
            status = row["status"]
            by_axis[axis][status] = by_axis[axis].get(status, 0) + 1
            total["rows"] += 1
            if status == "match":
                total["match"] += 1
            elif status == "divergent":
                total["divergent"] += 1
            else:
                total["one_sided"] += 1

    per_axis = {}
    for axis, counts in by_axis.items():
        comparable = counts.get("match", 0) + counts.get("divergent", 0)
        per_axis[axis] = {
            **counts,
            "comparable": comparable,
            "match_rate": (
                round(counts.get("match", 0) / comparable, 4) if comparable else None
            ),
        }
    comparable_total = total["match"] + total["divergent"]
    total["condition_coverage"] = (
        round(
            (by_axis["condition"].get("match", 0) + by_axis["condition"].get("divergent", 0))
            / (by_axis["condition"].get("match", 0)
               + by_axis["condition"].get("divergent", 0)
               + by_axis["condition"].get("jev_missing", 0)),
            4,
        )
        if (by_axis["condition"].get("match", 0)
            + by_axis["condition"].get("divergent", 0)
            + by_axis["condition"].get("jev_missing", 0)) else None
    )
    return {
        "by_axis": per_axis,
        "total": {
            **total,
            "comparable": comparable_total,
            "match_rate": (
                round(total["match"] / comparable_total, 4) if comparable_total else None
            ),
            "divergence_items": total["divergent"],
        },
    }


def first_divergence(rows_by_symbol: Dict[str, List[Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """按时间顺序给出最早一处可解释差异，供报告摘要引用。"""
    candidates = [
        row
        for rows in rows_by_symbol.values()
        for row in rows
        if row["status"] != "match"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (minutes_of(r["time"]) if r["time"] else 10**9,
                                   r["symbol"], r["axis"]))
    return candidates[0]