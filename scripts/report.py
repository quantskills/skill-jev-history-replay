"""报告组装：把对齐账本、归因实验、价值评估与适用边界合成一份可审阅的报告。"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from . import metrics
from .aligner import PRIOR, aggregate_rows, first_divergence


def config_hash(payload: Dict[str, Any]) -> str:
    text = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def build_value_assessment(baseline_replay: Dict[str, Any],
                           current_replay: Dict[str, Any],
                           min_cycles: int) -> Dict[str, Any]:
    """比较「字面直译」基线与「显式语义」当前实现。

    这回答的是"把隐式约定显式化，改变了哪些交易决策"，与日志来源无关，
    因此即使日志是合成的，这一段仍然是基于真实历史 K 线的实测。
    """
    base_cycles = sum(v["closed_count"] for v in baseline_replay["symbols"].values())
    cur_cycles = sum(v["closed_count"] for v in current_replay["symbols"].values())
    base_signals = baseline_replay["summary"]["signal_count"]
    cur_signals = current_replay["summary"]["signal_count"]

    paired_base, paired_cur = metrics.pair_cycles(baseline_replay, current_replay)
    deltas = [b - a for a, b in zip(paired_base, paired_cur)]

    wins = sum(1 for d in deltas if d > 0)
    losses = sum(1 for d in deltas if d < 0)
    p_value = metrics.sign_test_p(wins, losses)
    n = len(deltas)

    comparable = n >= min_cycles and cur_cycles > 0 and base_cycles > 0
    if not comparable:
        verdict = "inconclusive"
        reason = f"配对周期数 {n} < min_cycles={min_cycles}，或某一侧无成交"
    elif n == 0:
        verdict = "inconclusive"
        reason = "两套语义没有共同周期，决策完全分裂，收益不可配对"
    elif wins + losses == 0:
        verdict = "inconclusive"
        reason = "所有配对周期收益相同"
    elif p_value is not None and p_value < 0.05 and wins > losses:
        verdict = "positive"
        reason = (
            f"配对周期中显式语义胜 {wins} 负 {losses}，符号检验 p={round(p_value, 6)}"
            "，方向上显著更优"
        )
    elif p_value is not None and p_value < 0.05 and losses > wins:
        verdict = "negative"
        reason = (
            f"配对周期中显式语义胜 {wins} 负 {losses}，符号检验 p={round(p_value, 6)}"
            "，方向上显著更差，属可靠负结果"
        )
    else:
        verdict = "inconclusive"
        reason = (
            "配对样本下两套语义的胜/负分布不显著"
            f"（胜 {wins} 负 {losses}，p={p_value}），"
            "既不能宣称改善也不能宣称劣化；"
            "但决策层改动幅度见 decision_changes，结论应为「换语义改变交易，收益未可证」"
        )

    delta_stats = metrics.paired_delta_ci(deltas)
    return {
        "baseline": {
            "profile": "naive_literal",
            "description": "未做任何领域推断的字面直译（窗口含当前根、开盘价为基准、信号当根收盘入场、无 T+1）",
            "signal_count": base_signals,
            "closed_cycles": base_cycles,
            "total_net_pct": baseline_replay["summary"]["total_net_pct"],
        },
        "current": {
            "profile": "reference_semantics",
            "signal_count": cur_signals,
            "closed_cycles": cur_cycles,
            "total_net_pct": current_replay["summary"]["total_net_pct"],
        },
        "decision_changes": {
            "signals_added": cur_signals - base_signals,
            "signals_removed": max(0, base_signals - cur_signals),
            "cycles_added": cur_cycles - base_cycles,
            "cycles_removed": max(0, base_cycles - cur_cycles),
            "paired_cycle_count": n,
        },
        "effect_size": {
            "paired_net_pct_delta": delta_stats,
            "win_loss": {"wins": wins, "losses": losses, "ties": n - wins - losses},
            "sign_test_p": None if p_value is None else round(p_value, 6),
            "magnitude_note": "符号检验判断方向（多数周期是否改善），均值差判断幅度；两者可背离——少数大幅亏损能主导均值而多数周期只小赢",
            "relative_change": (
                round(
                    (current_replay["summary"]["total_net_pct"]
                     - baseline_replay["summary"]["total_net_pct"])
                    / abs(baseline_replay["summary"]["total_net_pct"]), 4
                )
                if baseline_replay["summary"]["total_net_pct"] else None
            ),
        },
        "verdict": {
            "verdict": verdict,
            "reason": reason,
            "rule": "配对周期数 >= min_cycles 且符号检验双侧 p<0.05：胜多于负 → positive，负多于胜 → negative；样本不足或胜/负不显著 → inconclusive。均值差只作幅度参考，不单独决定方向（少数大亏可主导均值）",
        },
    }


def build_alignment_conclusion(aggregate: Dict[str, Any],
                               divergence_rows: int,
                               log_source: str) -> Dict[str, Any]:
    total = aggregate["total"]
    rate = total["match_rate"]
    comparable = total["comparable"]
    if comparable == 0:
        verdict = "inconclusive"
        reason = "没有任何可对照的项（日志侧未记录可对齐字段，或重放无输出）"
    elif log_source != "actual":
        verdict = "inconclusive"
        reason = (
            "日志为合成数据，只能证明对齐链路可运行；"
            "对 JEV 实际语义的判定必须等真实日志到位后重跑"
        )
    elif rate is not None and rate >= 0.98:
        verdict = "consistent"
        reason = "在可比项上语义一致"
    elif rate is not None and rate >= 0.8:
        verdict = "minor_divergence"
        reason = "存在可归因的局部差异"
    else:
        verdict = "inconsistent"
        reason = "语义不可互换，需按账本逐项修正"
    return {
        "verdict": verdict,
        "reason": reason,
        "comparable_items": comparable,
        "match_rate": rate,
        "divergence_items": divergence_rows,
        "match_rate_ci95": (
            metrics.wilson_interval(total["match"], comparable) if comparable else None
        ),
    }


def build_applicability(log_source: str, semantics: Dict[str, Any],
                        manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "in_scope": [
            "单一交易日、A 股分钟级盯盘条件的语义还原与回放",
            "condition / signal / wait / entry / exit 五个对齐轴",
            "由语义旋钮差异引起的判断、时点与成交差异归因",
            "只读对齐：不假设可访问 JEV 内部推理或自定义 API",
        ],
        "out_of_scope": [
            "跨日持仓、隔夜跳空、除权除息调整",
            "盘口级撮合、排队与部分成交建模",
            "JEV 内部模型推理路径的复现",
            "收益率、夏普等绩效评价结论",
            "实盘对接：全程不连接任何交易通道",
        ],
        "coverage": {
            "log_source": log_source,
            "axes": ["condition", "signal", "wait", "entry", "exit"],
            "semantics_hash": semantics.get("_hash"),
            "fixture_fingerprint": (manifest or {}).get("fixture_fingerprint"),
            "symbol_count": (manifest or {}).get("symbol_count"),
        },
        "invalid_when": [
            "标的处于停牌、ST 或涨跌停状态（未建模）",
            "当日存在除权除息（K 线未复权对齐）",
            "日志记录口径与 log_contract 不一致（缺 wait_bars / entry_price 等字段）",
            "分钟线时间戳口径与 bar_timestamp 声明不符",
            "样本交易日数不足导致只在单日成立",
        ],
        "requires": [
            "同一份分钟 K 线与同源日志，且两者覆盖同一标的与同一交易日",
            "语义旋钮全部显式声明并计入 semantics_hash",
            "config_hash 一致才可跨 run 比对",
        ],
    }


def build_ledger_block(rows_by_symbol: Dict[str, List[Dict[str, Any]]],
                       max_inline: int) -> Dict[str, Any]:
    all_rows = [row for rows in rows_by_symbol.values() for row in rows]
    all_rows.sort(key=lambda r: (r["symbol"], r["time"] or "", r["axis"]))
    divergent = [r for r in all_rows if r["status"] != "match"]
    aggregate = aggregate_rows(rows_by_symbol)
    return {
        "aggregate": aggregate,
        "by_axis_prior": PRIOR,
        "first_divergence": first_divergence(rows_by_symbol),
        "inline_rows": all_rows[:max_inline],
        "inline_truncated": len(all_rows) > max_inline,
        "total_rows": len(all_rows),
        "divergence_rows": len(divergent),
        "divergence_breakdown": _breakdown(divergent),
    }


def _breakdown(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    for row in rows:
        axis_bucket = out.setdefault(row["axis"], {})
        axis_bucket[row["status"]] = axis_bucket.get(row["status"], 0) + 1
    return out


def assemble(*, run_id: str, generated_at: str, log_source: str, semantics: Dict[str, Any],
             logged_semantics: Optional[Dict[str, Any]], manifest: Optional[Dict[str, Any]],
             ledger: Dict[str, Any], value_assessment: Dict[str, Any],
             attribution: Dict[str, Any], alignment: Dict[str, Any],
             comparability: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "run_id": run_id,
        "generated_at": generated_at,
        "provenance": {
            "log_source": log_source,
            "log_source_meaning": {
                "actual": "用于对齐的日志来自 JEV 实际输出",
                "synthetic": "日志由 log_synth 按显式档位生成，仅验证链路",
            }[log_source],
            "logged_profile": (logged_semantics or {}).get("profile")
            or (manifest or {}).get("logged_profile"),
            "fixture_manifest": manifest,
        },
        "comparability": comparability,
        # 合成模式下把"已记录语义"的旋钮全量回显，使读者能直接核对
        # 日志侧到底按哪套解释生成的，而不是只看一个哈希
        "logged_semantics": logged_semantics,
        "ledger": ledger,
        "attribution": attribution,
        "alignment_conclusion": alignment,
        "value_assessment": value_assessment,
        "applicability": build_applicability(log_source, semantics, manifest),
        "semantics": {k: v for k, v in semantics.items() if not k.startswith("_")},
    }