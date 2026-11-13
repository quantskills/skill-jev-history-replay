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
    coverage = (len(deltas) / base_cycles) if base_cycles else 0.0

    wins = sum(1 for d in deltas if d > 0)
    losses = sum(1 for d in deltas if d < 0)
    p_value = metrics.sign_test_p(wins, losses)
    n = len(deltas)

    # 配对覆盖率：配对周期占基线周期的比例。
    # 两套语义的交易集合可能差异极大（本案例 45,507 vs 2,014），
    # 配对检验只测重叠部分。覆盖率过低时，结论不能代表全样本，
    # 必须降级为 inconclusive 并在报告里显式说明，而不是照给 positive/negative。
    min_coverage = 0.10
    low_coverage = coverage < min_coverage

    # 全样本 Welch 检验**不依赖配对**，因此不受覆盖率影响。
    # 覆盖率闸门只约束配对检验；若配对样本不足以代表全样本，
    # 但全样本检验本身显著，就用全样本结论——否则会把一个
    # 有效证据错误地否掉。
    full_sample = metrics.welch_test(
        metrics.all_closed_returns(baseline_replay),
        metrics.all_closed_returns(current_replay),
    )
    full_p = full_sample.get("p")
    full_diff = full_sample.get("diff")
    full_significant = (
        full_p is not None and full_p < 0.05
        and full_diff is not None and full_diff != 0
        and full_sample.get("n_a", 0) >= min_cycles
        and full_sample.get("n_b", 0) >= min_cycles
    )

    comparable = (n >= min_cycles and cur_cycles > 0 and base_cycles > 0
                  and not low_coverage)
    if not comparable and low_coverage and n >= min_cycles:
        if full_significant:
            # 配对覆盖不足，但全样本检验显著：采用全样本结论
            if full_diff < 0:
                verdict = "negative"
                reason = (
                    f"配对覆盖率仅 {coverage:.2%}，配对检验不可外推；"
                    f"改用不依赖配对的全样本 Welch 检验（{full_sample['n_a']:,} vs "
                    f"{full_sample['n_b']:,}），均值差 {full_diff:.4%}，"
                    f"p={full_p} — 显著更差"
                )
            else:
                verdict = "positive"
                reason = (
                    f"配对覆盖率仅 {coverage:.2%}，配对检验不可外推；"
                    f"改用不依赖配对的全样本 Welch 检验（{full_sample['n_a']:,} vs "
                    f"{full_sample['n_b']:,}），均值差 {full_diff:.4%}，"
                    f"p={full_p} — 显著更优"
                )
        else:
            verdict = "inconclusive"
            reason = (
                f"配对覆盖率仅 {coverage:.2%}（{n}/{base_cycles}），"
                f"低于 {min_coverage:.0%} 门槛：两套语义的交易集合差异过大，"
                "配对检验只覆盖重叠部分的少数周期，不能代表全样本；"
                f"全样本 Welch 检验也不显著（p={full_p}）"
            )
    elif not comparable:
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
            "paired_coverage": round(coverage, 4),
            "coverage_threshold": min_coverage,
            "coverage_sufficient": not low_coverage,
            "note": (
                "配对覆盖率 = 配对周期 / 基线周期。覆盖率低说明两套语义选出的交易"
                "集合差异很大，配对检验只测重叠部分，结论不可外推到全样本。"
            ),
        },
        "effect_size": {
            "paired_net_pct_delta": delta_stats,
            "full_sample_welch": full_sample,
            "win_loss": {"wins": wins, "losses": losses, "ties": n - wins - losses},
            # 不能 round(p, 6)：精确二项检验在 n≈1200 时 p 可到 1e-12，
            # 四舍五入会变成 0.0，读者会当成"p 恰为 0"（统计上不可能）。
            # 保留有效数字，小值走科学计数法。
            "sign_test_p": None if p_value is None else float(f"{p_value:.4g}"),
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
            "rule": "优先用配对检验：配对周期数 >= min_cycles、覆盖率 >= 10% 且符号检验 p<0.05。若覆盖率不足但全样本 Welch 检验显著（p<0.05 且两侧样本 >= min_cycles），采用全样本结论——它不依赖配对，不受覆盖率影响。两者都不满足 → inconclusive",
        },
    }


# `consistent` 的双重门槛。
#
# 只看一致率会有盲区：样本极大时，几百条真实冲突会被"稀释"成高比率。
# 实测中只差 `exit_eval` 一个旋钮就产生 503 条冲突，一致率却仍有 0.9913，
# 按纯比率会误判为 consistent。所以必须同时约束冲突的绝对数量。
CONSISTENT_MIN_RATE = 0.98
# 真实冲突的绝对上限：**0**。
# 曾经设成 5，结果 60 标的子集里 exit_eval 只产生 3 条冲突，
# 就落进"可忽略"区间被判 consistent——而它确实是语义不一致。
# "一致"的含义就是没有冲突，不能给真实冲突留默认容忍额度。
# 若某类冲突确属噪声，应由上游过滤，而不是在这里放宽。
CONSISTENT_MAX_DIVERGENT_ABS = 0
CONSISTENT_MAX_DIVERGENT_RATIO = 0.0
# 判 `consistent` 时，**每一个轴都必须有可比项**。
#
# 只看总体会让"没验证"冒充"一致"：日志若只写了 condition 而没有任何
# plan/signal，exit/entry/wait 三轴 comparable 全是 0，总体却可能因为
# 少量 condition 相符而给出 consistent。那个"一致"覆盖不到最关键的执行轴。
#
# 这条门槛不要求每轴有很多项——只要求"确实比过"，把未验证明确暴露出来。
CONSISTENT_REQUIRE_ALL_AXES_COMPARABLE = True


def build_alignment_conclusion(aggregate: Dict[str, Any],
                               divergence_rows: int,
                               log_source: str) -> Dict[str, Any]:
    total = aggregate["total"]
    rate = total["match_rate"]
    comparable = total["comparable"]
    divergent = total.get("divergent", divergence_rows)
    divergent_ratio = (divergent / comparable) if comparable else 0.0

    # consistent 的绝对门槛：真实冲突必须少到可以忽略
    negligible_conflicts = (
        divergent <= CONSISTENT_MAX_DIVERGENT_ABS
        or divergent_ratio <= CONSISTENT_MAX_DIVERGENT_RATIO
    )

    if comparable == 0:
        verdict = "inconclusive"
        reason = "没有任何可对照的项（日志侧未记录可对齐字段，或重放无输出）"
    elif log_source != "actual":
        verdict = "inconclusive"
        reason = (
            "日志为合成数据，只能证明对齐链路可运行；"
            "对 JEV 实际语义的判定必须等真实日志到位后重跑"
        )
    elif CONSISTENT_REQUIRE_ALL_AXES_COMPARABLE and (
            unverified_axes := [a for a, row in aggregate.get("by_axis", {}).items()
                                if not row.get("comparable")]
    ):
        # 有轴完全没比过，不能判 consistent——那是"没验证"，不是"一致"。
        # 归为 inconclusive，并指出是哪几个轴。
        verdict = "inconclusive"
        reason = (
            f"以下轴线完全没有可比项：{unverified_axes}。"
            f"虽然其余轴一致率 {rate:.4f}，但未覆盖的轴可能藏着差异，"
            "不能据此判定语义一致。请在日志中补齐对应记录"
            "（signal / plan 的 entry_time、exit_time 等）后重跑。"
        )
    elif rate is not None and rate >= CONSISTENT_MIN_RATE and negligible_conflicts:
        verdict = "consistent"
        reason = (
            f"在 {comparable:,} 个可比项上一致率 {rate:.4f}，"
            f"且仅有 {divergent} 条真实冲突"
        )
    elif rate is not None and rate >= CONSISTENT_MIN_RATE:
        # 高比率但冲突数不可忽略 —— 这是纯比率阈值的盲区，必须降级
        verdict = "minor_divergence"
        reason = (
            f"一致率虽达 {rate:.4f}，但存在 {divergent} 条真实冲突"
            f"（占可比项 {divergent_ratio:.2%}），不可判为一致；"
            "高比率是被样本量稀释的结果"
        )
    elif rate is not None and rate >= 0.8:
        verdict = "minor_divergence"
        reason = f"一致率 {rate:.4f}，存在 {divergent} 条可归因的局部差异"
    else:
        verdict = "inconsistent"
        reason = f"一致率 {rate:.4f}，语义不可互换，需按账本逐项修正"
    return {
        "verdict": verdict,
        "reason": reason,
        "comparable_items": comparable,
        "match_rate": rate,
        # 必须是**真实冲突数**，与 summary.divergence_items 和
        # ledger.aggregate.total.divergent 同口径。
        # 此前这里传的是 divergence_rows（= 全部非 match 行，含近 98 万条
        # jev_missing），于是同一份报告里同一概念出现 979,634 / 314 两个数，
        # 读者会误以为有上百万条冲突。
        "divergence_items": divergent,
        "match_rate_ci95": (
            metrics.wilson_interval(total["match"], comparable) if comparable else None
        ),
        "divergent_abs": divergent,
        "divergent_ratio": round(divergent_ratio, 6),
        "consistent_gate": {
            "min_rate": CONSISTENT_MIN_RATE,
            "max_divergent_abs": CONSISTENT_MAX_DIVERGENT_ABS,
            "max_divergent_ratio": CONSISTENT_MAX_DIVERGENT_RATIO,
            "note": "consistent 需同时满足：一致率达门槛 且 真实冲突数可忽略（绝对值或占比任一达标）。"
                    "只看比率会在样本量大时把真差异稀释成假一致。",
        },
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
        # 未建模状态的实际占比必须随报告提供，而不是只在文档里说"不含"。
        # None 表示未核验（离线或无凭证），与"占比为 0"严格区分。
        "unmodeled_market_states": (manifest or {}).get("data_quality"),
        "unmodeled_market_states_note": (
            "本 skill 不对 ST / 停牌 / 涨跌停做特殊处理。上面的占比是结论适用范围的折扣："
            "占比越高，越不能把回放结果直接外推到实盘。未核验时为 null，不等于 0。"
        ),
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
    # 注意区分：这条列表装的是**所有非 match 行**（含海量 one_sided），
    # 不是"真实冲突"。真实冲突数是 aggregate.total.divergent。
    non_match = [r for r in all_rows if r["status"] != "match"]
    aggregate = aggregate_rows(rows_by_symbol)
    return {
        "aggregate": aggregate,
        "by_axis_prior": PRIOR,
        "first_divergence": first_divergence(rows_by_symbol),
        "inline_rows": all_rows[:max_inline],
        "inline_truncated": len(all_rows) > max_inline,
        "total_rows": len(all_rows),
        # 与 aggregate.total.divergent 同口径（真实冲突数）
        "divergence_rows": aggregate["total"].get("divergent", 0),
        "non_match_rows": len(non_match),
        "divergence_breakdown": _breakdown(non_match),
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
            # 配置降级（如缺 pyyaml）必须出现在报告里，不能静默
            "config_warnings": comparability.get("config_warnings", []),
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