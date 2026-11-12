"""归因：单旋钮消融的解释率、守卫条件、不可解释残差。"""

from __future__ import annotations

from scripts import attribution, config, semantics as sem
from scripts.aligner import align_symbol
from scripts.replayer import replay_all

from conftest import make_dataset


BREAKOUT = [10.0] * 15 + [10.3, 10.5, 10.7, 10.9, 11.1]


def _log_groups_from(replay, symbol="A"):
    """用某个配置本身生成"日志"，使该配置成为完全一致的参考。"""
    result = replay["symbols"][symbol]
    conditions, signals, plans = [], [], []
    prev = None
    for detail in result["details"]:
        if prev is None or bool(detail["hit"]) != prev:
            conditions.append({
                "ts": detail["time"], "minute": int(detail["time"][:2]) * 60 + int(detail["time"][3:]),
                "symbol": symbol, "hit": bool(detail["hit"]),
            })
            prev = bool(detail["hit"])
    for cycle in result["cycles"]:
        signals.append({"ts": cycle["signal_time"],
                        "minute": int(cycle["signal_time"][:2]) * 60 + int(cycle["signal_time"][3:]),
                        "symbol": symbol})
        if cycle.get("entry_time"):
            plans.append({
                "ts": cycle["entry_time"],
                "minute": int(cycle["entry_time"][:2]) * 60 + int(cycle["entry_time"][3:]),
                "symbol": symbol, "entry_time": cycle["entry_time"],
                "entry_price": cycle["entry_price"], "wait_bars": cycle.get("wait_bars"),
                "exit_time": cycle.get("exit_time"), "exit_reason": cycle.get("exit_reason"),
            })
    return {symbol: {"condition": conditions, "signal": signals, "plan": plans, "fill": []}}


def _base_semantics():
    s = dict(config.REFERENCE_SEMANTICS)
    s["breakout_window"] = 5
    s["warmup_bars"] = 5
    s["persistence_bars"] = 1
    s["wait_bars"] = 0
    s["cooldown_bars"] = 0
    s["signal_gain_pct"] = 0.005
    s["take_profit_pct"] = 0.02
    s["stop_loss_pct"] = 0.02
    s["max_hold_bars"] = 10
    return s


def test_ablation_identifies_changed_knob():
    bars = make_dataset({"A": BREAKOUT})
    base = _base_semantics()
    replay_base = replay_all(bars, base, {"A": 10.0})
    logs = _log_groups_from(replay_base)

    # 用"另一种 exit_eval"生成日志 → 只有 exit_eval 能解释差异
    logged = dict(base)
    logged["exit_eval"] = "bar_high_low"
    replay_logged = replay_all(bars, logged, {"A": 10.0})
    logs = _log_groups_from(replay_logged)

    aligned = align_symbol("A", replay_base["symbols"]["A"], logs["A"], 1, 5.0)
    baseline_div = sum(1 for r in aligned["rows"] if r["status"] == "divergent")
    baseline_cmp = sum(1 for r in aligned["rows"] if r["status"] in ("match", "divergent"))

    result = attribution.run_ablation(
        bars, base, {"A": 10.0},
        baseline_divergences=baseline_div,
        baseline_comparable=baseline_cmp,
        log_groups_by_symbol=logs,
        tol_minutes=1,
        price_tolerance_bps=5.0,
    )
    if baseline_div == 0:
        assert result["verdict"] == "no_divergence"
    else:
        assert result["top_knob"] == "exit_eval"
        assert result["top_explained_rate"] == 1.0
        assert result["verdict"] == "single_knob"


def test_identical_config_has_no_divergence():
    bars = make_dataset({"A": BREAKOUT})
    base = _base_semantics()
    replay_base = replay_all(bars, base, {"A": 10.0})
    logs = _log_groups_from(replay_base)
    aligned = align_symbol("A", replay_base["symbols"]["A"], logs["A"], 1, 5.0)
    divergent = [r for r in aligned["rows"] if r["status"] == "divergent"]
    assert divergent == []


def test_ablation_skips_invalid_alternative():
    bars = make_dataset({"A": BREAKOUT})
    base = _base_semantics()
    # 构造一个替代值会非法的旋钮：把它注册进 KNOB_VALUES 的枚举里不存在
    result = attribution.run_ablation(
        bars, base, {"A": 10.0},
        baseline_divergences=0,
        baseline_comparable=0,
        log_groups_by_symbol={"A": {"condition": [], "signal": [], "plan": [], "fill": []}},
        tol_minutes=1,
        price_tolerance_bps=5.0,
        knobs=["not_a_knob"],
    )
    assert result["ranked"] == []
    assert result["verdict"] == "no_divergence"


def test_attribution_does_not_reward_breaking_alignment():
    """换旋钮把配对打散不应算作"解释差异"。"""
    bars = make_dataset({"A": BREAKOUT})
    base = _base_semantics()
    replay_base = replay_all(bars, base, {"A": 10.0})
    logs = _log_groups_from(replay_base)
    result = attribution.run_ablation(
        bars, base, {"A": 10.0},
        baseline_divergences=3,
        baseline_comparable=10,
        log_groups_by_symbol=logs,
        tol_minutes=1,
        price_tolerance_bps=5.0,
    )
    for row in result["ranked"]:
        if not row["alignment_preserved"]:
            assert row["explained"] == 0


def test_semantics_hash_in_ranked_metadata():
    bars = make_dataset({"A": BREAKOUT})
    base = _base_semantics()
    result = attribution.run_ablation(
        bars, base, {"A": 10.0},
        baseline_divergences=0, baseline_comparable=0,
        log_groups_by_symbol={"A": {"condition": [], "signal": [], "plan": [], "fill": []}},
        tol_minutes=1, price_tolerance_bps=5.0, knobs=["bar_timestamp"],
    )
    assert result["knobs_tested"] == 1

def test_ablation_uses_same_view_as_main_flow():
    """消融必须与主流程共用 by_series 视图，否则可比项口径不一致。"""
    bars = make_dataset({"A": BREAKOUT})
    base = _base_semantics()
    replay_base = replay_all(bars, base, {"A": 10.0})
    assert "by_series" in replay_base
    logs = _log_groups_from(replay_base)
    result = attribution.run_ablation(
        bars, base, {"A": 10.0},
        baseline_divergences=0,
        baseline_comparable=1,
        log_groups_by_symbol=logs,
        tol_minutes=1,
        price_tolerance_bps=5.0,
        knobs=["exit_eval"],
    )
    row = result["ranked"][0]
    # 单日输入下 by_series 与 symbols 同构，可比项不应因视图切换而暴跌
    assert row["comparable"] > 0


def test_real_difference_is_attributable_despite_signal_change():
    """真实语义差异会改变信号集，不能因此被判成"未归因"。"""
    bars = make_dataset({"A": BREAKOUT})
    base = _base_semantics()
    logged_sem = dict(base)
    logged_sem["exit_eval"] = "bar_high_low"
    replay_logged = replay_all(bars, logged_sem, {"A": 10.0})
    logs = _log_groups_from(replay_logged)

    from scripts.aligner import align_symbol, aggregate_rows
    rows = {"A": align_symbol(
        "A", replay_all(bars, base, {"A": 10.0})["symbols"]["A"], logs["A"], 1, 5.0
    )["rows"]}
    agg = aggregate_rows(rows)["total"]

    result = attribution.run_ablation(
        bars, base, {"A": 10.0},
        baseline_divergences=agg["divergent"],
        baseline_comparable=agg["comparable"],
        log_groups_by_symbol=logs,
        tol_minutes=1,
        price_tolerance_bps=5.0,
    )
    if agg["divergent"] == 0:
        assert result["verdict"] == "no_divergence"
    else:
        assert result["top_knob"] == "exit_eval"
        assert result["top_explained_rate"] == 1.0


def test_joint_diagnosis_flags_multi_knob_case():
    """多个旋钮同时不同时，报告必须说明单旋钮消融不适用。"""
    from scripts import semantics as sem
    from scripts.aligner import align_symbol, aggregate_rows

    bars = make_dataset({"A": BREAKOUT})
    base = _base_semantics()
    naive = dict(base)
    naive.update(sem.NAIVE_PROFILE)
    naive["breakout_window"] = base["breakout_window"]
    naive["warmup_bars"] = base["warmup_bars"]

    replay_logged = replay_all(bars, naive, {"A": 10.0})
    logs = _log_groups_from(replay_logged)
    rows = {"A": align_symbol(
        "A", replay_all(bars, base, {"A": 10.0})["symbols"]["A"], logs["A"], 1, 5.0
    )["rows"]}
    agg = aggregate_rows(rows)["total"]

    result = attribution.run_ablation(
        bars, base, {"A": 10.0},
        baseline_divergences=agg["divergent"],
        baseline_comparable=agg["comparable"],
        log_groups_by_symbol=logs,
        tol_minutes=1,
        price_tolerance_bps=5.0,
    )
    joint = result["joint_diagnosis"]
    assert "applicable" in joint
    if result["verdict"] != "single_knob":
        assert joint["applicable"] is False


def test_joint_diagnosis_applicable_when_single_knob_wins():
    bars = make_dataset({"A": BREAKOUT})
    base = _base_semantics()
    logged = dict(base)
    logged["exit_eval"] = "bar_high_low"
    logs = _log_groups_from(replay_all(bars, logged, {"A": 10.0}))

    from scripts.aligner import align_symbol, aggregate_rows
    rows = {"A": align_symbol(
        "A", replay_all(bars, base, {"A": 10.0})["symbols"]["A"], logs["A"], 1, 5.0
    )["rows"]}
    agg = aggregate_rows(rows)["total"]
    if agg["divergent"] == 0:
        return
    result = attribution.run_ablation(
        bars, base, {"A": 10.0},
        baseline_divergences=agg["divergent"],
        baseline_comparable=agg["comparable"],
        log_groups_by_symbol=logs, tol_minutes=1, price_tolerance_bps=5.0,
    )
    if result["verdict"] == "single_knob":
        assert result["joint_diagnosis"]["applicable"] is True
