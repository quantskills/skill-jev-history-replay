"""端到端：输入校验、日志来源判定、产物落盘、可复现性。"""

from __future__ import annotations

import json

import pytest

from scripts import build, run_eval
from scripts.run_eval import ReplayError


def test_validate_input_rejects_empty_string():
    with pytest.raises(ReplayError) as exc:
        build.validate_input("")
    assert exc.value.code == "empty_input"


def test_validate_input_rejects_unknown_field():
    with pytest.raises(ReplayError) as exc:
        build.validate_input({"bars_dir": ".", "typo": 1})
    assert exc.value.code == "unknown_field"


def test_validate_input_rejects_wrong_type():
    with pytest.raises(ReplayError) as exc:
        build.validate_input(123)
    assert exc.value.code == "invalid_type"


def test_validate_input_rejects_bad_semantics():
    with pytest.raises(ReplayError) as exc:
        build.validate_input({"semantics": {"bar_timestamp": "nope"}})
    assert exc.value.code == "invalid_semantics"


def test_run_end_to_end_with_actual_logs(tmp_fixtures, flat_then_breakout, tmp_path):
    from scripts import config, log_synth, semantics as sem

    bars = {"S": {"date": "20260101", "bars": __import__("conftest").make_bars(flat_then_breakout)}}
    s = dict(config.REFERENCE_SEMANTICS)
    s.update({"breakout_window": 5, "warmup_bars": 5, "persistence_bars": 1,
              "wait_bars": 0, "cooldown_bars": 0, "signal_gain_pct": 0.005,
              "take_profit_pct": 0.02, "stop_loss_pct": 0.02, "max_hold_bars": 10})
    logs = [
        {k: v for k, v in rec.items() if k != "_synthetic"}
        for rec in log_synth.synthesize_logs(bars, s, {"S": 10.0})
    ]
    dirs = tmp_fixtures(bars, logs)

    result = run_eval.evaluate(
        bars_dir=dirs["bars_dir"], logs_dir=dirs["logs_dir"],
        output_dir=tmp_path / "out",
        semantics_override={"breakout_window": 5, "warmup_bars": 5,
                            "persistence_bars": 1, "wait_bars": 0,
                            "cooldown_bars": 0, "signal_gain_pct": 0.005,
                            "take_profit_pct": 0.02, "stop_loss_pct": 0.02,
                            "max_hold_bars": 10},
        run_attribution=False,
    )
    assert result["provenance"]["log_source"] == "actual"
    assert result["comparability"]["log_source"] == "actual"
    assert (tmp_path / "out" / "report.json").exists()
    assert (tmp_path / "out" / "ledger.jsonl").exists()


def test_run_falls_back_to_synthetic_when_logs_missing(tmp_fixtures, flat_then_breakout, tmp_path):
    from conftest import make_bars

    bars = {"S": {"date": "20260101", "bars": make_bars(flat_then_breakout)}}
    dirs = tmp_fixtures(bars, logs=None)
    result = run_eval.evaluate(
        bars_dir=dirs["bars_dir"], logs_dir=dirs["logs_dir"],
        output_dir=tmp_path / "out", run_attribution=False,
    )
    assert result["provenance"]["log_source"] == "synthetic"
    assert result["alignment_conclusion"]["verdict"] == "inconclusive"


def test_run_rejects_bad_semantics(tmp_fixtures, flat_then_breakout, tmp_path):
    from conftest import make_bars

    bars = {"S": {"date": "20260101", "bars": make_bars(flat_then_breakout)}}
    dirs = tmp_fixtures(bars)
    with pytest.raises(ReplayError) as exc:
        run_eval.evaluate(
            bars_dir=dirs["bars_dir"], output_dir=tmp_path / "out",
            semantics_override={"breakout_field": "vwap"},
        )
    assert exc.value.code == "invalid_semantics"


def test_run_rejects_missing_bars_dir(tmp_path):
    with pytest.raises(ReplayError) as exc:
        run_eval.evaluate(bars_dir=tmp_path / "nope", output_dir=tmp_path / "out")
    assert exc.value.code == "bars_dir_not_found"


def test_report_json_is_serializable(tmp_fixtures, flat_then_breakout, tmp_path):
    from conftest import make_bars

    bars = {"S": {"date": "20260101", "bars": make_bars(flat_then_breakout)}}
    dirs = tmp_fixtures(bars)
    result = run_eval.evaluate(bars_dir=dirs["bars_dir"],
                               output_dir=tmp_path / "out",
                               run_attribution=False)
    dumped = json.dumps(result, ensure_ascii=False)
    loaded = json.loads(dumped)
    assert loaded["summary"]["symbol_count"] == 1


def test_run_is_deterministic_except_timestamps(tmp_fixtures, flat_then_breakout, tmp_path):
    from conftest import make_bars

    bars = {"S": {"date": "20260101", "bars": make_bars(flat_then_breakout)}}
    dirs = tmp_fixtures(bars)
    a = run_eval.evaluate(bars_dir=dirs["bars_dir"], output_dir=tmp_path / "a",
                          run_attribution=False)
    b = run_eval.evaluate(bars_dir=dirs["bars_dir"], output_dir=tmp_path / "b",
                          run_attribution=False)
    for key in ("run_id", "generated_at", "artifacts"):
        a.pop(key)
        b.pop(key)
    assert a == b


def test_status_axes_always_present(tmp_fixtures, flat_then_breakout, tmp_path):
    from conftest import make_bars

    bars = {"S": {"date": "20260101", "bars": make_bars(flat_then_breakout)}}
    dirs = tmp_fixtures(bars)
    result = run_eval.evaluate(bars_dir=dirs["bars_dir"], output_dir=tmp_path / "out",
                               run_attribution=False)
    assert set(result["ledger"]["aggregate"]["by_axis"]) == {
        "condition", "signal", "wait", "entry", "exit"
    }