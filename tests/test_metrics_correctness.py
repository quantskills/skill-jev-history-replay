"""统计函数的正确性验证。

所有 p 值和置信区间都出自 `scripts/metrics.py` 里手写的实现。
从没验证过这些实现本身对不对——如果符号检验的双尾算错、Wilson 公式
写反、Welch 的分母用错，报告里所有"显著"都会失去意义。

这里用三种独立手段验证：
  1. 已知解析值（二项分布精确值、Wilson 公式手算）
  2. 蒙特卡洛（Type-I 错误率应接近名义水平、覆盖率应接近 95%）
  3. 逐项重算（t / se 与手工公式对比）
"""

from __future__ import annotations

import math
import random
import statistics

import pytest

from scripts import metrics


def _exact_two_sided_sign(min_side: int, n: int) -> float:
    total = sum(math.comb(n, i) for i in range(0, min_side + 1)) / (2 ** n)
    return min(1.0, total * 2)


@pytest.mark.parametrize("wins,losses", [
    (10, 0), (8, 2), (5, 5), (15, 5), (100, 60),
])
def test_sign_test_matches_exact_binomial(wins, losses):
    """符号检验必须等于二项分布的精确双尾 p 值。"""
    mine = metrics.sign_test_p(wins, losses)
    ref = _exact_two_sided_sign(min(wins, losses), wins + losses)
    assert mine == pytest.approx(ref, rel=0, abs=1e-12)


def test_sign_test_symmetric():
    assert metrics.sign_test_p(7, 3) == pytest.approx(metrics.sign_test_p(3, 7))


def test_sign_test_no_data():
    assert metrics.sign_test_p(0, 0) is None


def test_wilson_matches_hand_computation():
    """Wilson 区间必须与手写公式完全一致。"""
    k, n, z = 85, 100, 1.96
    lo, hi = metrics.wilson_interval(k, n)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    assert lo == pytest.approx(center - margin, abs=1e-12)
    assert hi == pytest.approx(center + margin, abs=1e-12)


def test_wilson_monte_carlo_coverage():
    """95% 区间在真实 p 下的覆盖率应接近 95%。"""
    rng = random.Random(2024)
    true_p, n, trials = 0.85, 200, 3000
    covered = 0
    for _ in range(trials):
        k = sum(1 for _ in range(n) if rng.random() < true_p)
        lo, hi = metrics.wilson_interval(k, n)
        if lo <= true_p <= hi:
            covered += 1
    rate = covered / trials
    assert 0.925 <= rate <= 0.972, f"覆盖率 {rate:.4f} 偏离名义 95% 过多"


def test_wilson_degenerate():
    assert metrics.wilson_interval(0, 0) == (0.0, 1.0)
    lo, hi = metrics.wilson_interval(0, 50)
    assert lo == 0.0 and 0 < hi < 0.15


def test_welch_t_and_se_match_manual():
    a = [1.0, 2.0, 3.0, 4.0]
    b = [2.0, 4.0, 6.0]
    r = metrics.welch_test(a, b)
    ma, mb = statistics.mean(a), statistics.mean(b)
    va, vb = statistics.variance(a), statistics.variance(b)
    se = math.sqrt(va / len(a) + vb / len(b))
    t = (mb - ma) / se
    assert r["se"] == pytest.approx(se, abs=1e-8)
    assert r["t"] == pytest.approx(t, abs=1e-4)
    assert r["diff"] == pytest.approx(mb - ma, abs=1e-8)


def test_welch_type_one_error_near_nominal():
    """同分布下，p<0.05 的比例应接近 5%。"""
    rng = random.Random(99)
    trials = 1500
    rejected = 0
    for _ in range(trials):
        a = [rng.gauss(0, 1) for _ in range(80)]
        b = [rng.gauss(0, 1) for _ in range(50)]
        p = metrics.welch_test(a, b)["p"]
        if p is not None and p < 0.05:
            rejected += 1
    rate = rejected / trials
    assert 0.035 <= rate <= 0.068, f"Type-I 错误率 {rate:.4f} 偏离 0.05 过多"


def test_welch_detects_large_effect():
    rng = random.Random(5)
    a = [rng.gauss(0, 1) for _ in range(3000)]
    b = [rng.gauss(0.3, 1) for _ in range(300)]
    r = metrics.welch_test(a, b)
    assert r["p"] is not None and r["p"] < 0.01
    assert r["diff"] > 0


def test_welch_insufficient_samples():
    r = metrics.welch_test([0.1], [0.2])
    assert r["p"] is None


def test_paired_delta_ci_matches_manual():
    deltas = [0.01, -0.02, 0.03, 0.005]
    r = metrics.paired_delta_ci(deltas)
    mu = statistics.mean(deltas)
    var = statistics.variance(deltas)
    se = math.sqrt(var / len(deltas))
    assert r["mean"] == pytest.approx(mu, abs=1e-8)
    assert r["ci95"][0] == pytest.approx(mu - 1.96 * se, abs=1e-8)
    assert r["ci95"][1] == pytest.approx(mu + 1.96 * se, abs=1e-8)
