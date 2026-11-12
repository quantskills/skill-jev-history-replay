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
        # 必须与主流程使用同一套视图（by_series，逐序列），
        # 否则消融时的可比项口径与基线不一致，归因结果不可比。
        views = replay.get("by_series") or replay["symbols"]
        for symbol, symbol_replay in views.items():
            groups = log_groups_by_symbol.get(symbol) or {
                "condition": [], "signal": [], "plan": [], "fill": []
            }
            rows_by_symbol[symbol] = align_symbol(
                symbol, symbol_replay, groups, tol_minutes, price_tolerance_bps
            )["rows"]
        total = aggregate_rows(rows_by_symbol)["total"]
        trial_comparable = total["comparable"]
        trial_div = total["divergent"]
        lost_comparable = max(0, baseline_comparable - trial_comparable)

        # 归因要防两种错，方向相反：
        #
        #  A. 假阳性：旋钮把配对打散，什么也没解释，却因为分母变小而显得"差异少了"。
        #  B. 假阴性：旋钮确实解释了差异，但它同时改变了信号集，
        #     可比项必然减少——若一律拒绝，真实成因永远归不出来。
        #
        # 区分办法是看"剩余可比项是否仍足以支撑结论"。定义一个保守的可解释率：
        #   explained_rate = 1 - trial_div / baseline_div
        # 只有当 trial_div 明显下降（不是靠可比项消失），且剩余可比项
        # 仍达到基线的 min_comparable_retention 时，才承认这次解释。
        retention = (trial_comparable / baseline_comparable
                     if baseline_comparable else 0.0)
        min_retention = float(semantics.get("min_comparable_retention", 0.05))
        raw_explained = baseline_div - trial_div
        # 若 lost_comparable 本身就大于被"解释"掉的数量，说明下降主要来自
        # 配对消失而非冲突消失——不认。
        genuinely_explained = (
            raw_explained > 0
            and raw_explained > lost_comparable
            and retention >= min_retention
        )
        explained = int(raw_explained) if genuinely_explained else 0
        alignment_preserved = retention >= min_retention
        results.append({
            "knob": knob,
            "from": semantics[knob],
            "to": trial[knob],
            "skipped": False,
            "baseline_divergences": baseline_div,
            "baseline_comparable": baseline_comparable,
            "trial_divergences": trial_div,
            "lost_comparable": lost_comparable,
            "comparable": trial_comparable,
            "comparable_retention": round(retention, 4),
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
    # 单旋钮消融的适用边界：它假定"只有少数旋钮不同"。
    # 若每个旋钮单独改动都解释不了多少，且方向并不一致（有的增加、有的减少），
    # 说明多个旋钮同时不同——这已超出单旋钮可解范围，结论只能是
    # "无法定位"，而不是"某个旋钮只解释 24%"这种半吊子结论。
    other = [r for r in ranked if r is not top]
    opposite_moves = 0
    for r in other:
        trial = r.get("trial_divergences")
        if trial is not None and trial > baseline_div:
            opposite_moves += 1
    joint = {
        "applicable": verdict in ("single_knob",),
        "explanation": (
            "单旋钮消融在多个语义旋钮同时不同时不可解。"
            "若把最可能的那一个旋钮调到正确值，差异也不见明显下降，"
            "说明差异由多因素叠加，需要联合搜索而非逐个消融。"
        ),
        "knobs_moving_opposite": opposite_moves,
        "knobs_ranked": len(ranked),
        "diagnosis": (
            "multiple_knobs_shifted"
            if verdict in ("multi_knob", "unexplained") and opposite_moves >= max(1, len(ranked)//3)
            else "inconclusive_attribution"
        ),
    }

    return {
        "baseline_divergences": baseline_div,
        "knobs_tested": len(ranked),
        "ranked": ranked,
        "top_knob": top["knob"] if top else None,
        "top_explained_rate": top["explained_rate"] if top else None,
        "verdict": verdict,
        "joint_diagnosis": joint,
        "note": (
            "explained_rate = (基线差异 - 换一个旋钮后的差异) / 基线差异；"
            "单旋钮达到阈值即认定该旋钮为主要成因。"
            "若多个旋钮同时不同，单旋钮消融不适用——见 joint_diagnosis。"
        ),
    }
