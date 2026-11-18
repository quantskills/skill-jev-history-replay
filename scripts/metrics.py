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


def all_closed_returns(rep: dict) -> List[float]:
    """取出全部收官周期的净收益，不做配对。

    配对检验只覆盖两套语义重叠的周期；当交易集合差异很大时覆盖率极低。
    全样本检验不依赖配对，可作为独立佐证。
    """
    out: List[float] = []
    for _symbol, result in rep["symbols"].items():
        for cycle in result["cycles"]:
            if cycle["status"] == "closed" and cycle["net_return_pct"] is not None:
                out.append(cycle["net_return_pct"])
    return out


def welch_test(a: List[float], b: List[float]) -> dict:
    """Welch 两样本 t 检验（不假设方差相等），返回均值差、标准误、t 与近似 p。"""
    if len(a) < 2 or len(b) < 2:
        return {"n_a": len(a), "n_b": len(b), "mean_a": None, "mean_b": None,
                "diff": None, "se": None, "t": None, "p": None}
    ma, mb = mean(a), mean(b)
    va = sum((x - ma) ** 2 for x in a) / (len(a) - 1)
    vb = sum((x - mb) ** 2 for x in b) / (len(b) - 1)
    se = math.sqrt(va / len(a) + vb / len(b))
    # 零方差判定必须用容差，不能与 0 精确比较。
    # 常数序列的方差理论上为 0，浮点误差会算出 1e-35 之类的残值，
    # 使 se ≈ 1e-19 而非 0；此时 t = diff/se 会放大到 1e16 量级，
    # 正态近似给出 p=0.0，把「无法判定」误报成「极显著」。
    # 用相对容差：se 小于均值量级的极小比例即视为退化。
    scale = max(abs(ma), abs(mb), 1e-12)
    if se <= scale * 1e-9:
        return {"n_a": len(a), "n_b": len(b), "mean_a": round(ma, 8),
                "mean_b": round(mb, 8), "diff": round(mb - ma, 8), "se": 0.0,
                "t": None, "p": None,
                "note": "两组样本方差为 0（常数序列），Welch 检验无法判定显著性"}
    t = (mb - ma) / se
    # 正态近似（样本量远大于 30，t 分布与正态几乎一致）
    p = math.erfc(abs(t) / math.sqrt(2))
    return {
        "n_a": len(a), "n_b": len(b),
        "mean_a": round(ma, 8), "mean_b": round(mb, 8),
        "diff": round(mb - ma, 8),
        "se": round(se, 8), "t": round(t, 4), "p": round(p, 6),
        "note": "Welch 检验，正态近似；不依赖配对，不受配对覆盖率影响",
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