"""价值结论的旋钮拆解：`negative` 到底是谁造成的。

`value_assessment` 把「显式语义」与「字面直译」当成两个整体比较。
但两者之间有 8 个旋钮不同——结论可能只由其中一两个驱动。
不做拆解就宣称"显式语义更差"，会把一个具体机制（如隔夜风险）
误归因为"语义对齐"本身。

用法：
    python3 scripts/value_decomposition.py
    python3 scripts/value_decomposition.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import config as cfg  # noqa: E402
from scripts import data_loader, metrics, report, semantics as sem  # noqa: E402
from scripts.replayer import replay_all  # noqa: E402
from scripts.run_eval import _load_prev_closes  # noqa: E402


def _summary(replay: Dict[str, Any]) -> Dict[str, Any]:
    rets = metrics.all_closed_returns(replay)
    return {
        "signals": replay["summary"]["signal_count"],
        "closed": len(rets),
        "mean_net_pct": metrics.mean(rets) if rets else None,
        "total_net_pct": replay["summary"]["total_net_pct"],
    }


def _carry_breakdown(replay: Dict[str, Any]) -> Dict[str, Any]:
    same, cross = [], []
    for result in replay["symbols"].values():
        for cycle in result["cycles"]:
            if cycle["status"] != "closed" or cycle["net_return_pct"] is None:
                continue
            (cross if cycle.get("carried_from_previous_day") else same).append(
                cycle["net_return_pct"]
            )
    return {
        "same_day": {"n": len(same), "mean": metrics.mean(same) if same else None},
        "cross_day": {"n": len(cross), "mean": metrics.mean(cross) if cross else None},
    }


def decompose() -> Dict[str, Any]:
    bars = data_loader.load_bars(REPO_ROOT / "fixtures" / "bars")
    prev = _load_prev_closes(REPO_ROOT / "fixtures" / "reference", list(bars))
    base_cfg = dict(cfg.load_config()["semantics"])

    naive = dict(base_cfg)
    naive.update(sem.NAIVE_PROFILE)
    reference = dict(base_cfg)

    naive_replay = replay_all(bars, naive, prev)
    ref_replay = replay_all(bars, reference, prev)
    naive_stats = _summary(naive_replay)
    ref_stats = _summary(ref_replay)

    differing = [k for k in list(sem.KNOB_VALUES) + list(sem.RISK_KNOBS)
                 if naive.get(k) != reference.get(k)]

    # 单旋钮：从 naive 出发只把该旋钮拨到参考值
    single: List[Dict[str, Any]] = []
    for knob in differing:
        trial = dict(naive)
        trial[knob] = reference[knob]
        stats = _summary(replay_all(bars, trial, prev))
        delta = None
        if stats["mean_net_pct"] is not None and naive_stats["mean_net_pct"] is not None:
            delta = stats["mean_net_pct"] - naive_stats["mean_net_pct"]
        single.append({"knob": knob, "stats": stats, "delta_mean_vs_naive": delta})

    total_delta = None
    if ref_stats["mean_net_pct"] is not None and naive_stats["mean_net_pct"] is not None:
        total_delta = ref_stats["mean_net_pct"] - naive_stats["mean_net_pct"]

    dominant = None
    if total_delta and single:
        ranked = sorted(
            [s for s in single if s["delta_mean_vs_naive"] is not None],
            key=lambda s: s["delta_mean_vs_naive"],
        )
        if ranked:
            worst = ranked[0]
            dominant = {
                "knob": worst["knob"],
                "delta": worst["delta_mean_vs_naive"],
                "share_of_total_delta": round(
                    worst["delta_mean_vs_naive"] / total_delta, 4
                ) if total_delta else None,
            }

    # T+1 隔离：参考语义关掉 T+1，与 naive 比
    ref_no_t1 = dict(reference)
    ref_no_t1["t_plus_1"] = False
    ref_no_t1_stats = _summary(replay_all(bars, ref_no_t1, prev))
    no_t1_verdict = report.build_value_assessment(
        naive_replay, replay_all(bars, ref_no_t1, prev),
        int(cfg.load_config()["min_cycles"]),
    )["verdict"]

    return {
        "naive": naive_stats,
        "reference": ref_stats,
        "total_delta_mean": total_delta,
        "differing_knobs": differing,
        "single_knob": single,
        "dominant": dominant,
        "t_plus_1_isolation": {
            "reference_without_t_plus_1": ref_no_t1_stats,
            "carry_breakdown_reference": _carry_breakdown(ref_replay),
            "carry_breakdown_reference_without_t_plus_1":
                _carry_breakdown(replay_all(bars, ref_no_t1, prev)),
            "verdict_vs_naive": no_t1_verdict,
        },
        "note": (
            "delta_mean = 该配置的周期平均净收益 − naive 的周期平均净收益。"
            "若单一旋钮的 |delta| 接近 total_delta，说明整份结论由它驱动，"
            "不应归因为『语义显式化』这个笼统的说法。"
        ),
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Decompose the value verdict by knob")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = decompose()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    n, r = result["naive"], result["reference"]
    print(f"{'配置':24s} {'信号':>7} {'收官':>7} {'均值净收益':>12}")
    print(f"{'naive（字面直译）':24s} {n['signals']:>7} {n['closed']:>7} "
          f"{n['mean_net_pct']:>+12.6f}")
    print(f"{'reference（显式语义）':24s} {r['signals']:>7} {r['closed']:>7} "
          f"{r['mean_net_pct']:>+12.6f}")
    print(f"\n总差值 {result['total_delta_mean']:+.6f}\n")

    print(f"{'单旋钮拨到参考值':26s} {'信号':>7} {'收官':>7} {'Δ均值':>12}")
    for row in sorted(result["single_knob"],
                      key=lambda x: (x["delta_mean_vs_naive"] or 0)):
        d = row["delta_mean_vs_naive"]
        print(f"{row['knob']:26s} {row['stats']['signals']:>7} "
              f"{row['stats']['closed']:>7} {(d if d is not None else 0):>+12.6f}")

    dom = result["dominant"]
    if dom:
        print(f"\n主导旋钮：{dom['knob']}，占总差值 {dom['share_of_total_delta']:.1%}")

    iso = result["t_plus_1_isolation"]
    print(f"\n参考语义关掉 T+1：均值 "
          f"{iso['reference_without_t_plus_1']['mean_net_pct']:+.6f}，"
          f"与 naive 比 = {iso['verdict_vs_naive']['verdict']}")
    cb = iso["carry_breakdown_reference"]
    print(f"  含 T+1：当日平仓 n={cb['same_day']['n']}，跨日 n={cb['cross_day']['n']} "
          f"（均值 {cb['cross_day']['mean']:+.6f}）"
          if cb["cross_day"]["mean"] is not None else "")
    return 0


if __name__ == "__main__":
    sys.exit(main())