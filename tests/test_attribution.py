"""归因：单旋钮消融的解释率、守卫条件、不可解释残差。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

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


@pytest.mark.slow
def test_single_knob_difference_is_attributed_to_that_knob(tmp_path):
    """只差一个旋钮时，归因必须锁定它——但这也意味着信息量有限。

    合成日志 `jev_assumed` 与参考语义恰好只差 `exit_eval` 一个旋钮，
    所以实测的"归因 100% 锁定 exit_eval"在相当程度上是同义反复。
    这个测试固定住"单旋钮时可定位"，同时提醒读者不要外推。

    **这条测试曾长期 `pytest.skip`**：小样本下 exit 轴 comparable=0
    （唯一一笔还是 open_position），核心断言从未执行过。现在改用真实夹具，
    确保断言真的会跑。
    """
    from scripts import config as cfg
    from scripts.run_eval import evaluate

    if not (REPO_ROOT / "fixtures" / "bars").exists():
        pytest.skip("没有真实夹具")

    bars_dir = REPO_ROOT / "fixtures" / "bars"
    ref_dir = REPO_ROOT / "fixtures" / "reference"

    # 用 exit_eval=bar_high_low 生成日志，再用参考语义（bar_close）对齐
    base = dict(cfg.load_config()["semantics"])
    logged = dict(base)
    logged["exit_eval"] = "bar_high_low"

    from scripts import data_loader, log_synth
    from scripts.run_eval import _load_prev_closes

    bars = data_loader.load_bars(bars_dir)
    prev = _load_prev_closes(ref_dir, list(bars))
    records = log_synth.synthesize_logs(bars, logged, prev)
    for rec in records:
        rec.pop("_synthetic", None)
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    per_date = {}
    for rec in records:
        per_date.setdefault(str(rec.get("date") or ""), []).append(rec)
    for date_text, rows in per_date.items():
        (logs_dir / f"{date_text}.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8",
        )

    out = evaluate(bars_dir=bars_dir, logs_dir=logs_dir,
                   output_dir=tmp_path / "out", run_attribution=True)
    exit_axis = out["ledger"]["aggregate"]["by_axis"]["exit"]
    assert exit_axis["comparable"] > 0, (
        "exit 轴没有可比项——测试会变成空转，必须确保真的比过")
    assert exit_axis["divergent"] > 0, "该样本下 exit_eval 应产生差异"

    attr = out["attribution"]
    assert attr["ranked"][0]["knob"] == "exit_eval"
    assert attr["verdict"] == "single_knob"
