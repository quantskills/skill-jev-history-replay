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
                 tol_minutes: int,
                 time_field: str = "entry_time",
                 pair_tolerance_minutes: int | None = None) -> List[Dict[str, Any]]:
    """用指定时刻配对周期与计划。

    time_field="entry_time" → 入场/等待轴
    time_field="exit_time"  → 退出轴（跨日周期的入场在昨天、退出在今天，
                               只有按退出时刻配才配对得对）

    **配对容差**与**判定容差**必须分开：
      - 判定容差（tol_minutes）：配上了之后，差几分钟才算"一致"；
      - 配对容差（pair_tolerance_minutes）：多大范围内还愿意认为是同一条记录。
    若两者共用，两个本该"时点差 2 分钟的差异"会先配对失败，
    再被误记成"单边缺失"，把真实差异藏起来。
    """
    if not log_plans:
        return [{"replay": c, "log": None} for c in replay_cycles]

    search = (pair_tolerance_minutes if pair_tolerance_minutes is not None
              else max(tol_minutes, 10))
    used: set[int] = set()
    pairs: List[Dict[str, Any]] = []
    for cycle in replay_cycles:
        cycle_time = cycle.get(time_field) or cycle.get("signal_time")
        best_idx = None
        best_gap = search + 1
        for idx, plan in enumerate(log_plans):
            if idx in used:
                continue
            # 日志侧的配对时刻：退出轴用记录里的 exit_time，没有则退回 ts。
            # 计划记录通常只写一条、ts 挂在入场时刻，但退出时刻另存于 exit_time，
            # 因此不能一律用 ts 配对，否则跨日周期永远配不上。
            if time_field == "exit_time" and plan.get("exit_time"):
                plan_time = minutes_of(plan["exit_time"])
            else:
                plan_time = plan["minute"]
            gap = abs(minutes_of(cycle_time) - plan_time)
            if gap <= search and gap < best_gap:
                best_idx, best_gap = idx, gap
        if best_idx is None:
            # 容差内没有候选：退回"时间上最近的未用记录"，并标记为低置信配对。
            # 直接把这种情况记成"单边缺失"会把真实的时点差异藏起来——
            # 两侧明明都有这笔交易，只是相差得远。
            nearest_idx = None
            nearest_gap = None
            for idx, plan in enumerate(log_plans):
                if idx in used:
                    continue
                plan_time = (minutes_of(plan["exit_time"])
                             if time_field == "exit_time" and plan.get("exit_time")
                             else plan["minute"])
                gap = abs(minutes_of(cycle_time) - plan_time)
                if nearest_gap is None or gap < nearest_gap:
                    nearest_idx, nearest_gap = idx, gap
            if nearest_idx is not None:
                used.add(nearest_idx)
                pairs.append({"replay": cycle, "log": log_plans[nearest_idx],
                              "low_confidence_pairing": True,
                              "pairing_gap_minutes": nearest_gap})
            else:
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

    # 入场/等待轴只看"本序列作为入场日"的周期；
    # 退出轴额外要覆盖"昨天入场、今天退出"的跨日周期。
    entry_cycles = replay.get("cycles") or []
    # 退出轴仍以"一笔周期 = 一次入场 + 一次退出"为配对单位，按**入场**配对。
    # 若重放因 T+1 把退出推到次日、而日志当日退出，这本身就是真实的决策差异
    # （退出时点相差一个交易日），必须记成 divergent 而不是排除掉。
    # 只有当日入场、窗口结束时仍未收官的周期（exit_time 为空）不参与退出比对。
    exit_cycles = [c for c in (replay.get("exit_cycles") or entry_cycles)
                   if c.get("exit_time")]
    cross_day_exits: List[Dict[str, Any]] = []
    # 入场轴只能用**入场类**计划记录。退出日的 plan(exit) 也带 entry_time，
    # 若混进候选池，会把 390 条退出记录误判成"日志有入场、重放没有"。
    entry_log_plans = [pl for pl in log_groups["plan"]
                       if str(pl.get("plan", "enter")) == "enter"]
    cycle_pairs = _pair_cycles(entry_cycles, entry_log_plans, tol_minutes,
                                time_field="entry_time")
    # 退出轴按**退出时刻**在本序列的退出记录里配对：
    #   - 当日入当日出：日志 plan 的 exit_time 就在这条上；
    #   - 跨日持仓：日志在退出日另写了一条 plan(exit)，Ts 即次日退出时刻。
    # 只拿"入场配对"复用会把跨日退出永远判成无记录，等于自证无差异。
    exit_log_plans = [pl for pl in log_groups["plan"]
                      if str(pl.get("plan", "enter")) != "enter"]
    exit_pair_list = _pair_cycles(exit_cycles, exit_log_plans, tol_minutes,
                                  time_field="exit_time")
    exit_pair_of = {id(pr["replay"]): pr for pr in exit_pair_list
                    if pr["replay"] is not None}
    # 当日入当日出的周期没有独立 plan(exit)，退出信息挂在入场那条 plan 上
    entry_pair_of = {id(pr["replay"]): pr for pr in cycle_pairs
                     if pr["replay"] is not None and pr["log"] is not None}

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

        # 退出轴在**入场日视图**里比对：日志的 plan 记录就写在这一天，
        # 它的 exit_time 是当日计划退出时刻。若重放因 T+1 把退出推到次日，
        # 时点自然对不上——这是真实的决策差异，如实记为 divergent。
        #
        # 在**退出日视图**里，同一条跨日周期没有对应的 plan 记录（那天的 plan
        # 属于当天的新交易），因此标 cross_day_no_log，不参与一致率。
        exit_pair = exit_pair_of.get(id(rc))
        exit_log = exit_pair["log"] if exit_pair else None
        if exit_log is None:
            # 回退到入场配对的那条 plan（当日入当日出的情况）
            fallback = entry_pair_of.get(id(rc))
            if fallback and fallback["log"].get("exit_time"):
                exit_log = fallback["log"]
        if exit_log is None:
            # 入场日视图里看到跨日周期时，它的退出记录在退出日，
            # 这里跳过即可，不产生一条"缺失"——退出日视图会独立比对。
            if rc.get("exit_series") and rc.get("exit_series") != symbol:
                continue
            # 到数据末尾仍未退出：这是"仓位仍持有"，不是差异，也不是日志缺失
            rows.append(_row("exit", symbol, "", "open_position", None,
                             rc.get("exit_reason"), "reason",
                             note="数据末尾仍未退出，无退出可比"))
            continue
        jev_exit_time = exit_log.get("exit_time") if exit_log else None
        replay_exit_time = rc.get("exit_time")
        if replay_exit_time and jev_exit_time:
            gap = minutes_of(replay_exit_time) - minutes_of(jev_exit_time)
            status = "match" if gap == 0 else "divergent"
            rows.append(_row("exit", symbol, replay_exit_time, status,
                             jev_exit_time, replay_exit_time, "time", gap))
            if gap:
                changes.append("exit_shifted")
        if rc.get("exit_reason") and exit_log and exit_log.get("exit_reason"):
            status = ("match" if rc["exit_reason"] == exit_log["exit_reason"]
                      else "divergent")
            rows.append(_row("exit", symbol, replay_exit_time or rc["signal_time"], status,
                             exit_log["exit_reason"], rc["exit_reason"], "reason"))
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

    # 退出日视图：本序列没有"当日入场"的周期，退出都在 exit_cycles 里。
    # 这部分必须单独比对，否则跨日退出的退出轴永远是空集。
    entry_ids = {id(p["replay"]) for p in cycle_pairs if p["replay"] is not None}
    for pr in exit_pair_list:
        rc2, lp2 = pr["replay"], pr["log"]
        if rc2 is None or id(rc2) in entry_ids:
            continue
        if lp2 is None:
            rows.append(_row("exit", symbol, rc2.get("exit_time") or "", "replay_only",
                             None, rc2.get("exit_time"), "time",
                             note="重放退出、日志无退出记录"))
            continue
        jev_exit_time = lp2.get("exit_time") or lp2.get("ts")
        replay_exit_time = rc2.get("exit_time")
        gap = minutes_of(replay_exit_time) - minutes_of(jev_exit_time)
        status = "match" if gap == 0 else "divergent"
        rows.append(_row("exit", symbol, replay_exit_time, status,
                         jev_exit_time, replay_exit_time, "time", gap))
        if rc2.get("exit_reason") and lp2.get("exit_reason"):
            rstatus = ("match" if rc2["exit_reason"] == lp2["exit_reason"]
                       else "divergent")
            rows.append(_row("exit", symbol, replay_exit_time, rstatus,
                             lp2["exit_reason"], rc2["exit_reason"], "reason"))
            if rstatus == "divergent":
                decision_changes.append({
                    "changes": ["exit_reason_changed"], "symbol": symbol,
                    "signal_time": lp2.get("entry_time") or lp2["ts"],
                    "replay": {"exit": replay_exit_time,
                               "net_return_pct": rc2.get("net_return_pct")},
                    "jev": {"exit": jev_exit_time,
                            "net_return_pct": lp2.get("net_return_pct")},
                })

    if cross_day_exits:
        # 汇总成一行，避免每个跨日周期刷一条单边缺失
        rows.append(_row(
            "exit", symbol, "", "cross_day_unpaired",
            None, len(cross_day_exits), "count",
            note="跨日退出（T+1 带入次日）在日志侧无独立记录，不参与退出轴比对",
        ))

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
        # 每轴都要给出 one_sided 汇总，与 total 的命名一致。
        # 否则读者无法从 by_axis 各轴加总校验 total——
        # 曾出现"各轴 one_sided 加起来是 0，total 却是 97 万"的困惑，
        # 原因是各轴只存了具体状态名（jev_missing 等）。
        one_sided = sum(
            v for k, v in counts.items()
            if k not in ("match", "divergent")
        )
        per_axis[axis] = {
            **counts,
            # `match` / `divergent` 必须始终存在（零也写），否则某轴恰好
            # 没有冲突时这个键会整个消失。文档写的是"每个轴：match /
            # divergent / one_sided"，读者按 `row["divergent"]` 取值会
            # 在四个轴上直接 KeyError。
            "match": counts.get("match", 0),
            "divergent": counts.get("divergent", 0),
            "one_sided": one_sided,
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