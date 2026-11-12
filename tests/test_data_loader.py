"""数据加载：格式容错、字段校验、重复检测、异常输入。"""

from __future__ import annotations

import gzip
import json

import pytest

from scripts import data_loader


def _write(path, records):
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_bars_normal(tmp_path):
    path = _write(tmp_path / "a.json", [{
        "symbol": "600519.SH", "datetime": "2026-11-12 09:31:00",
        "open": 10.0, "high": 10.2, "low": 9.9, "close": 10.1, "volume": 100,
    }])
    bars = data_loader.load_bars(tmp_path)
    assert list(bars) == ["600519.SH"]
    bar = bars["600519.SH"]["bars"][0]
    assert bar["time"] == "09:31"
    assert bar["minute"] == 9 * 60 + 31


def test_load_bars_accepts_compact_time(tmp_path):
    _write(tmp_path / "a.json", [{
        "symbol": "X", "datetime": "093100",
        "open": 1, "high": 1, "low": 1, "close": 1,
    }])
    assert data_loader.load_bars(tmp_path)["X"]["bars"][0]["time"] == "09:31"


def test_load_bars_gzip(tmp_path):
    payload = json.dumps([{
        "symbol": "X", "datetime": "09:31",
        "open": 1, "high": 1, "low": 1, "close": 1,
    }])
    with gzip.open(tmp_path / "a.json.gz", "wt", encoding="utf-8") as fh:
        fh.write(payload)
    assert data_loader.load_bars(tmp_path)["X"]["bars"][0]["time"] == "09:31"


def test_missing_field_raises(tmp_path):
    _write(tmp_path / "a.json", [{"symbol": "X", "datetime": "09:31"}])
    with pytest.raises(data_loader.LoadError) as exc:
        data_loader.load_bars(tmp_path)
    assert exc.value.code == "missing_bar_field"


def test_high_below_low_raises(tmp_path):
    _write(tmp_path / "a.json", [{
        "symbol": "X", "datetime": "09:31",
        "open": 10, "high": 9, "low": 11, "close": 10,
    }])
    with pytest.raises(data_loader.LoadError) as exc:
        data_loader.load_bars(tmp_path)
    assert exc.value.code == "invalid_bar_field"


def test_non_positive_price_raises(tmp_path):
    _write(tmp_path / "a.json", [{
        "symbol": "X", "datetime": "09:31",
        "open": 0, "high": 1, "low": 1, "close": 1,
    }])
    with pytest.raises(data_loader.LoadError):
        data_loader.load_bars(tmp_path)


def test_duplicate_bar_raises(tmp_path):
    rec = {"symbol": "X", "datetime": "09:31",
           "open": 1, "high": 1, "low": 1, "close": 1}
    _write(tmp_path / "a.json", [rec, dict(rec)])
    with pytest.raises(data_loader.LoadError) as exc:
        data_loader.load_bars(tmp_path)
    assert exc.value.code == "duplicate_bar"


def test_empty_dir_raises(tmp_path):
    with pytest.raises(data_loader.LoadError) as exc:
        data_loader.load_bars(tmp_path)
    assert exc.value.code == "bars_empty"


def test_missing_dir_raises(tmp_path):
    with pytest.raises(data_loader.LoadError) as exc:
        data_loader.load_bars(tmp_path / "nope")
    assert exc.value.code == "bars_dir_not_found"


def test_load_logs_sorts_and_normalizes(tmp_path):
    path = tmp_path / "l.jsonl"
    path.write_text("\n".join([
        json.dumps({"ts": "10:00", "kind": "signal", "symbol": "S"}),
        json.dumps({"ts": "09:31", "kind": "condition", "symbol": "S", "hit": True}),
    ]) + "\n", encoding="utf-8")
    recs = data_loader.load_logs(tmp_path)
    assert [r["ts"] for r in recs] == ["09:31", "10:00"]
    assert all("minute" in r for r in recs)


def test_invalid_log_kind_raises(tmp_path):
    (tmp_path / "l.jsonl").write_text(
        json.dumps({"ts": "10:00", "kind": "vibes", "symbol": "S"}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(data_loader.LoadError) as exc:
        data_loader.load_logs(tmp_path)
    assert exc.value.code == "invalid_log_kind"


def test_normalize_accepts_synthetic_records():
    recs = data_loader.normalize_log_records([
        {"ts": "09:31", "kind": "condition", "symbol": "S", "hit": False},
    ])
    assert recs[0]["minute"] == 9 * 60 + 31
    assert recs[0]["_source_file"] == "<synthetic>"


def test_group_logs_fills_all_kinds():
    recs = data_loader.normalize_log_records([
        {"ts": "09:31", "kind": "signal", "symbol": "S"},
    ])
    grouped = data_loader.group_logs(recs)
    assert set(grouped["S"]) == set(data_loader.LOG_KINDS)
    assert grouped["S"]["plan"] == []