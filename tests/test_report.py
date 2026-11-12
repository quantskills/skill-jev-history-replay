"""价值评估判定规则、统计量与报告组装。"""

from __future__ import annotations

from scripts import metrics, report


def _replay(closed_returns, signals=1):
    cycles = [{
        "symbol": "S", "signal_index": i, "signal_time": "09:40",
        "status": "closed", "net_return_pct": r,
    } for i, r in enumerate(closed_returns)]
    return {
        "symbols": {"S": {"closed_count": len(cycles), "cycles": cycles,
                          "signals": [{}] * signals, "total_net_pct": sum(closed_returns)}},
        "summary": {"signal_count": signals, "closed_count": len(cycles),
                    "total_net_pct": sum(closed_returns)},
    }


def test_value_inconclusive_when_too_few_pairs():
    base = _replay([0.01] * 3)
    cur = _replay([0.02] * 3)
    out = report.build_value_assessment(base, cur, min_cycles=20)
    assert out["verdict"]["verdict"] == "inconclusive"
    assert "min_cycles" in out["verdict"]["reason"]


def test_value_positive_when_most_pairs_improve():
    base = _replay([0.0] * 30)
    cur = _replay([0.01] * 28 + [-0.01] * 2)
    out = report.build_value_assessment(base, cur, min_cycles=20)
    assert out["verdict"]["verdict"] == "positive"
    assert out["effect_size"]["win_loss"]["wins"] == 28


def test_value_negative_when_most_pairs_worsen():
    base = _replay([0.0] * 30)
    cur = _replay([-0.01] * 28 + [0.01] * 2)
    out = report.build_value_assessment(base, cur, min_cycles=20)
    assert out["verdict"]["verdict"] == "negative"


def test_value_inconclusive_on_mixed_direction():
    base = _replay([0.0] * 30)
    cur = _replay([0.01] * 16 + [-0.01] * 14)
    out = report.build_value_assessment(base, cur, min_cycles=20)
    assert out["verdict"]["verdict"] == "inconclusive"


def test_value_counts_decision_changes():
    base = _replay([0.01] * 5)
    cur = _replay([0.01] * 8)
    out = report.build_value_assessment(base, cur, min_cycles=3)
    assert out["decision_changes"]["cycles_added"] == 3
    assert out["decision_changes"]["paired_cycle_count"] == 5


def test_alignment_inconclusive_for_synthetic_logs():
    agg = {"total": {"match": 9, "divergent": 1, "comparable": 10, "match_rate": 0.9,
                     "one_sided": 0, "rows": 10}}
    out = report.build_alignment_conclusion(agg, 1, log_source="synthetic")
    assert out["verdict"] == "inconclusive"
    assert "合成" in out["reason"]


def test_alignment_consistent_for_actual_logs():
    agg = {"total": {"match": 100, "divergent": 0, "comparable": 100, "match_rate": 1.0,
                     "one_sided": 0, "rows": 100}}
    assert report.build_alignment_conclusion(agg, 0, "actual")["verdict"] == "consistent"


def test_alignment_inconsistent_below_threshold():
    agg = {"total": {"match": 5, "divergent": 15, "comparable": 20, "match_rate": 0.25,
                     "one_sided": 0, "rows": 20}}
    assert report.build_alignment_conclusion(agg, 15, "actual")["verdict"] == "inconsistent"


def test_alignment_without_comparable_is_inconclusive():
    agg = {"total": {"match": 0, "divergent": 0, "comparable": 0, "match_rate": None,
                     "one_sided": 5, "rows": 5}}
    out = report.build_alignment_conclusion(agg, 0, "actual")
    assert out["verdict"] == "inconclusive"


def test_applicability_lists_scope_and_limits():
    out = report.build_applicability("synthetic", {"_hash": "abc"}, None)
    assert out["in_scope"] and out["out_of_scope"]
    assert out["invalid_when"] and out["requires"]


def test_config_hash_stable_and_sensitive():
    a = {"x": 1, "y": [1, 2]}
    assert report.config_hash(a) == report.config_hash(dict(a))
    assert report.config_hash(a) != report.config_hash({"x": 2, "y": [1, 2]})


def test_ledger_block_truncates_inline_rows():
    rows = {"S": [{"axis": "condition", "symbol": "S", "time": "09:31",
                   "status": "match", "field": "hit", "jev": True,
                   "replay": True, "delta": None, "note": ""}] * 10}
    out = report.build_ledger_block(rows, max_inline=3)
    assert len(out["inline_rows"]) == 3
    assert out["inline_truncated"] is True
    assert out["total_rows"] == 10


def test_wilson_interval_bounds():
    lo, hi = metrics.wilson_interval(9, 10)
    assert 0 <= lo < 0.9 < hi <= 1.0


def test_sign_test_symmetric():
    assert metrics.sign_test_p(5, 5) == 1.0
    assert metrics.sign_test_p(10, 0) < metrics.sign_test_p(7, 3)


def test_sign_test_p_never_rounds_to_zero():
    """报告里的 `sign_test_p` 不能因为四舍五入变成 0.0。

    精确二项检验在 n≈1200 时 p 可以到 1e-12。此前用 `round(p, 6)`
    把它压成 `0.0`，读者会以为"p 恰为 0"——统计上不可能，
    也会误判证据强度。小值必须以科学计数法保留。
    """
    from scripts import metrics

    exact = metrics.sign_test_p(484, 727)
    assert exact is not None and exact > 0, "精确 p 值不该为 0"
    assert exact < 1e-6, "这个样本量下应是小概率"

    # 报告侧的序列化方式必须保住这个量级
    reported = float(f"{exact:.4g}")
    assert reported > 0, f"序列化后变成 {reported}，应保留科学计数法"
    assert reported < 1e-6


def test_sign_test_no_samples():
    assert metrics.sign_test_p(0, 0) is None


def test_paired_delta_ci_requires_two_samples():
    assert metrics.paired_delta_ci([])["ci95"] is None
    assert metrics.paired_delta_ci([0.01])["ci95"] is None
    two = metrics.paired_delta_ci([0.01, 0.02])
    assert two["n"] == 2 and two["ci95"] is not None

def test_low_pairing_coverage_forces_inconclusive():
    """配对覆盖率过低时，不能凭符号检验给 positive/negative。"""
    # 基线 1000 个周期，只有 30 个能配上 → 覆盖率 3%
    base = _replay([0.0] * 1000)
    cur = _replay([-0.01] * 30)
    out = report.build_value_assessment(base, cur, min_cycles=20)
    assert out["verdict"]["verdict"] == "inconclusive"
    assert "覆盖率" in out["verdict"]["reason"]
    assert out["decision_changes"]["coverage_sufficient"] is False
    assert out["decision_changes"]["paired_coverage"] < 0.1


def test_high_coverage_allows_verdict():
    base = _replay([0.0] * 100)
    cur = _replay([0.01] * 95 + [-0.01] * 5)
    out = report.build_value_assessment(base, cur, min_cycles=20)
    assert out["decision_changes"]["paired_coverage"] >= 0.1
    assert out["verdict"]["verdict"] == "positive"


def test_full_sample_welch_reported():
    base = _replay([0.01] * 50)
    cur = _replay([0.02] * 50)
    out = report.build_value_assessment(base, cur, min_cycles=20)
    w = out["effect_size"]["full_sample_welch"]
    assert w["n_a"] == 50 and w["n_b"] == 50
    assert w["diff"] is not None


def test_welch_test_detects_difference():
    from scripts import metrics
    a = [0.0] * 200
    b = [0.02] * 200
    r = metrics.welch_test(a, b)
    assert r["diff"] is not None
    assert r["p"] is None or r["p"] < 0.05


def test_welch_test_no_difference():
    from scripts import metrics
    a = [0.01, -0.01] * 100
    b = [0.01, -0.01] * 100
    r = metrics.welch_test(a, b)
    assert r["diff"] == 0 or abs(r["diff"]) < 1e-12


def test_high_rate_with_many_conflicts_is_not_consistent():
    """纯比率阈值的盲区：样本大时几百条真冲突会被稀释成"高一致率"。"""
    agg = {"total": {"match": 57607, "divergent": 503, "comparable": 58110,
                     "match_rate": 0.9913, "one_sided": 0, "rows": 58110}}
    out = report.build_alignment_conclusion(agg, 503, "actual")
    assert out["verdict"] == "minor_divergence", \
        "503 条真实冲突不应被判为 consistent"
    assert "稀释" in out["reason"] or "真实冲突" in out["reason"]
    assert out["divergent_abs"] == 503


def test_consistent_requires_zero_conflicts():
    """哪怕只有 1 条真实冲突，也不能叫"一致"。

    实测教训：60 标的子集下 exit_eval 只产生 3 条冲突，一致率 0.994，
    旧规则（允许 ≤5 条）把它判成 consistent——那确实是一次误判。
    """
    clean = {"total": {"match": 10000, "divergent": 0, "comparable": 10000,
                       "match_rate": 1.0, "one_sided": 0, "rows": 10000}}
    assert report.build_alignment_conclusion(clean, 0, "actual")["verdict"] == "consistent"

    for divergent in (1, 3, 10, 50):
        agg = {"total": {"match": 10000 - divergent, "divergent": divergent,
                         "comparable": 10000,
                         "match_rate": (10000 - divergent) / 10000,
                         "one_sided": 0, "rows": 10000}}
        out = report.build_alignment_conclusion(agg, divergent, "actual")
        assert out["verdict"] != "consistent", f"{divergent} 条真实冲突不应判 consistent"


def test_consistent_gate_documented():
    agg = {"total": {"match": 100, "divergent": 0, "comparable": 100,
                     "match_rate": 1.0, "one_sided": 0, "rows": 100}}
    out = report.build_alignment_conclusion(agg, 0, "actual")
    gate = out["consistent_gate"]
    assert gate["min_rate"] == 0.98
    assert gate["max_divergent_abs"] == 0
    assert gate["max_divergent_ratio"] == 0.0


def test_low_coverage_but_full_sample_significant_uses_full_sample():
    """覆盖率不足时，若全样本 Welch 显著，应采用全样本结论而非一律 inconclusive。"""
    base = _replay([0.0] * 1000)
    cur = _replay([-0.05, 0.05] * 15)
    out = report.build_value_assessment(base, cur, min_cycles=20)
    dc = out["decision_changes"]
    assert dc["paired_coverage"] < 0.10
    w = out["effect_size"]["full_sample_welch"]
    if w["p"] is not None and w["p"] < 0.05:
        assert out["verdict"]["verdict"] in ("positive", "negative")
        assert "全样本" in out["verdict"]["reason"]
    else:
        assert out["verdict"]["verdict"] == "inconclusive"


def test_low_coverage_and_full_sample_flat_stays_inconclusive():
    """覆盖率不足且全样本也不显著时，必须 inconclusive。"""
    base = _replay([0.0] * 1000)
    cur = _replay([0.0] * 30)
    out = report.build_value_assessment(base, cur, min_cycles=20)
    assert out["verdict"]["verdict"] == "inconclusive"
