"""统计量与小样本检验（纯标准库，无三方依赖）。

只实现本 skill 真实用到的三件事：
- Wilson 置信区间（比例）
- 精确二项符号检验（配对样本方向是否偏向一侧）
- 配对均值差及其正态近似区间

刻意不做显著性"包装"：样本不足时报告区间而不是给一个好看的 p 值。
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple


def wilson_interval(successes: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def sign_test_p(wins: int, losses: int) -> Optional[float]:
    """精确二项检验（H0: p=0.5）的双侧 p 值。平局应由调用方剔除。"""
    n = wins + losses
    if n == 0:
        return None
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, tail * 2)


def mean(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def paired_delta_ci(deltas: List[float], z: float = 1.96) -> dict:
    """配对差值的均值与近似 95% 区间。样本 <2 时只给均值。"""
    n = len(deltas)
    if n == 0:
        return {"n": 0, "mean": None, "ci95": None}
    mu = sum(deltas) / n
    if n < 2:
        return {"n": n, "mean": round(mu, 8), "ci95": None}
    var = sum((d - mu) ** 2 for d in deltas) / (n - 1)
    se = math.sqrt(var / n)
    return {
        "n": n,
        "mean": round(mu, 8),
        "ci95": [round(mu - z * se, 8), round(mu + z * se, 8)],
    }


def pair_cycles(naive: dict, reference: dict) -> Tuple[List[float], List[float]]:
    """按 (symbol, signal_index) 配对两个配置的周期净收益。

    只配对两边都收官的周期；单边存在记为决策改变，不进入收益配对。
    """
    def index(rep: dict) -> dict:
        out = {}
        for symbol, result in rep["symbols"].items():
            for cycle in result["cycles"]:
                if cycle["status"] == "closed":
                    out[(symbol, cycle["signal_index"])] = cycle["net_return_pct"]
        return out

    a, b = index(naive), index(reference)
    common = sorted(set(a) & set(b))
    return [a[key] for key in common], [b[key] for key in common]