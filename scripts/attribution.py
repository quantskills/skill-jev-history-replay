"""差异归因：单旋钮消融实验。

思路：对齐差异可能由多个语义旋钮共同造成。逐个把旋钮换成"另一个值"，
看能否解释已经观测到的差异。若单独换一个旋钮就几乎解释了全部差异，
报告给出该旋钮为主要成因；若单一旋钮都解释不了，如实说"多因素/未归因"。

这是可证伪的：任何人都可以按报告里的旋钮名与另一值复跑同一实验。
"""

from __future__ import annotations

from typing import Any, Dict, List

from . import semantics as sem
from .replayer import replay_all


def run_ablation(bars_by_symbol: Dict[str, Dict[str, Any]],
                 semantics: Dict[str, Any],
                 prev_closes: Dict[str, float],
                 baseline_divergences: int,
                 baseline_comparable: int,
                 log_groups_by_symbol: Dict[str, Dict[str, List[Dict[str, Any]]]],
                 tol_minutes: int,
                 price_tolerance_bps: float,
                 knobs: List[str] | None = None) -> Dict[str, Any]:
    """对每个旋钮做单点替换，返回可解释率与不可解释残差。

    Args:
        baseline_divergences: 当前配置下的差异总数（来自账本汇总）
        log_groups_by_symbol: JEV 侧记录，两次比对完全相同，只变回放侧
    """
    from .aligner import aggregate_rows, align_symbol

    knobs = knobs or (list(sem.KNOB_VALUES) + ["breakout_window"])
    baseline_div = baseline_divergences
    results: List[Dict[str, Any]] = []

    for knob in knobs:
        if knob not in semantics:
            continue
        trial = dict(semantics)
        trial[knob] = sem.alternative_value(semantics, knob)
        problems = sem.validate_semantics(trial)
        if problems:
            results.append({
                "knob": knob,
                "from": semantics[knob],
                "to": trial[knob],
                "skipped": True,
                "reason": "; ".join(problems),
                "explained": 0,
                "explained_rate": None,
            })
            continue

        replay = replay_all(bars_by_symbol, trial, prev_closes)
        rows_by_symbol: Dict[str, List[Dict[str, Any]]] = {}
        for symbol, symbol_replay in replay["symbols"].items():
            groups = log_groups_by_symbol.get(symbol) or {
                "condition": [], "signal": [], "plan": [], "fill": []
            }
            rows_by_symbol[symbol] = align_symbol(
                symbol, symbol_replay, groups, tol_minutes, price_tolerance_bps
            )["rows"]
        total = aggregate_rows(rows_by_symbol)["total"]
        # 待解释差异 = 真实冲突 + 因换旋钮而"丢失的可比项"。
        # 后者必须计入，否则"把配对全打断"会被误判成"解释掉了差异"。
        lost_comparable = max(0, baseline_comparable - total["comparable"])
        trial_div = total["divergent"] + lost_comparable
        # 只有在"可比项没有减少"的前提下减少的差异才算被解释。
        # 否则一个把配对全部打断的旋钮会假装解释了所有差异（假阳性）。
        alignment_preserved = total["comparable"] >= baseline_comparable
        explained = max(0, baseline_div - trial_div) if alignment_preserved else 0
        results.append({
            "knob": knob,
            "from": semantics[knob],
            "to": trial[knob],
            "skipped": False,
            "baseline_divergences": baseline_div,
            "baseline_comparable": baseline_comparable,
            "trial_divergences": trial_div,
            "lost_comparable": lost_comparable,
            "comparable": total["comparable"],
            "alignment_preserved": alignment_preserved,
            "explained": explained,
            "explained_rate": (
                round(explained / baseline_div, 4) if baseline_div else None
            ),
        })

    ranked = sorted(
        [r for r in results if not r.get("skipped")],
        key=lambda r: (-(r["explained"] or 0), r["knob"]),
    )
    top = ranked[0] if ranked else None
    threshold = semantics.get("explained_rate_threshold", 0.95)
    if not ranked or baseline_div == 0:
        verdict = "no_divergence"
    elif top and (top["explained_rate"] or 0) >= threshold:
        verdict = "single_knob"
    elif top and (top["explained_rate"] or 0) > 0:
        verdict = "multi_knob"
    else:
        verdict = "unexplained"
    return {
        "baseline_divergences": baseline_div,
        "knobs_tested": len(ranked),
        "ranked": ranked,
        "top_knob": top["knob"] if top else None,
        "top_explained_rate": top["explained_rate"] if top else None,
        "verdict": verdict,
        "note": (
            "explained_rate = (基线差异 - 换一个旋钮后的差异) / 基线差异；"
            "单旋钮达到阈值即认定该旋钮为主要成因，否则属多因素或未归因。"
        ),
    }
