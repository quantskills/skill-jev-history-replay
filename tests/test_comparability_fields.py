"""`logs_fingerprint` 的守卫。

这条字段最容易坏成的样子是"算了但没人看"，所以三件事一起钉住：
同一份日志换顺序/换缩进不变；任何内容变化必变；`compare_baseline` 必须点名它。
不挑字段是刻意的——`_synthetic` 标记、`baseline`/`reference` 口径一旦漏掉，
换一批日志就换不出指纹，这条守卫就成了假绿。
"""
from __future__ import annotations

import copy
import json

from scripts import compare_baseline, report


def _records():
    return [
        {"symbol": "600000.SH", "date": "20261026", "ts": "09:31", "kind": "condition",
         "hit": True, "gain_pct": 1.2, "baseline": 10.0, "reference": 10.12,
         "_synthetic": True},
        {"symbol": "000001.SZ", "date": "20261026", "ts": "09:32", "kind": "condition",
         "hit": False, "gain_pct": 0.0, "baseline": 11.0, "reference": 10.9,
         "_synthetic": True},
        {"symbol": "600000.SH", "date": "20261027", "ts": "10:15", "kind": "signal",
         "hit": True, "gain_pct": 2.0, "baseline": 10.0, "reference": 10.2,
         "_synthetic": True},
    ]


def test_fingerprint_is_order_independent():
    assert (report.logs_fingerprint(_records())
            == report.logs_fingerprint(list(reversed(_records()))))


def test_fingerprint_is_indent_independent(tmp_path):
    """同一份内容换个键序/缩进落盘再读回来，指纹必须不动。"""
    rekeyed = [dict(reversed(list(rec.items()))) for rec in _records()]
    assert report.logs_fingerprint(rekeyed) == report.logs_fingerprint(_records())


def test_flipping_one_hit_changes_fingerprint():
    base = report.logs_fingerprint(_records())
    flipped = copy.deepcopy(_records())
    flipped[0]["hit"] = False
    assert report.logs_fingerprint(flipped) != base


def test_dropping_the_synthetic_marker_changes_fingerprint():
    """`_synthetic` 参与哈希：把合成日志伪装成真实日志，指纹必须变。"""
    base = report.logs_fingerprint(_records())
    laundered = [{k: v for k, v in rec.items() if k != "_synthetic"} for rec in _records()]
    assert report.logs_fingerprint(laundered) != base


def test_empty_logs_fingerprint_is_stable():
    assert report.logs_fingerprint([]) == report.logs_fingerprint([])


def test_compare_baseline_names_log_content_drift(tmp_path):
    """config_hash 相同、日志内容不同 → comparable 仍可为真，但必须点名 logs_fingerprint。"""
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "report.json"
    baseline.write_text(json.dumps({
        "config_hash": "deadbeefdeadbeef",
        "semantics_hash": "s", "fixture_fingerprint": "f",
        "log_source": "synthetic", "logs_fingerprint": "OLDOLDOLDOLD0000",
        "summary": {},
    }), encoding="utf-8")
    current.write_text(json.dumps({
        "comparability": {
            "config_hash": "deadbeefdeadbeef",
            "semantics_hash": "s", "fixture_fingerprint": "f",
            "log_source": "synthetic", "logs_fingerprint": "NEWNEWNEWNEW1111",
        },
        "summary": {},
    }), encoding="utf-8")

    result = compare_baseline.compare(current, baseline)
    assert result["ok"] is True
    assert result["comparable"] is True
    assert "logs_fingerprint" in result["changed_fields"]


def test_legacy_anchor_without_the_field_is_not_reported_as_drift(tmp_path):
    """旧锚点压根没记 `logs_fingerprint`。

    把"键缺席"当成"内容漂移"，会让每个历史锚点在升级后都谎报一次变化，
    读者就再也分不清这是真漂移还是字段新增——这条专门钉住那个假阳性。
    """
    baseline = tmp_path / "baseline.json"
    current = tmp_path / "report.json"
    baseline.write_text(json.dumps({
        "config_hash": "deadbeefdeadbeef", "semantics_hash": "s",
        "fixture_fingerprint": "f", "log_source": "synthetic", "summary": {},
    }), encoding="utf-8")
    current.write_text(json.dumps({
        "comparability": {
            "config_hash": "deadbeefdeadbeef", "semantics_hash": "s",
            "fixture_fingerprint": "f", "log_source": "synthetic",
            "logs_fingerprint": "ANYVALUE",
        },
        "summary": {},
    }), encoding="utf-8")

    result = compare_baseline.compare(current, baseline)
    assert result["comparable"] is True
    assert "logs_fingerprint" not in result["changed_fields"]


def test_compare_baseline_silent_when_logs_identical(tmp_path):
    payload = {
        "config_hash": "deadbeefdeadbeef", "semantics_hash": "s",
        "fixture_fingerprint": "f", "log_source": "synthetic",
        "logs_fingerprint": "SAME", "summary": {},
    }
    baseline = tmp_path / "b.json"
    current = tmp_path / "c.json"
    baseline.write_text(json.dumps(payload), encoding="utf-8")
    current.write_text(json.dumps({"comparability": payload, "summary": {}}),
                       encoding="utf-8")
    result = compare_baseline.compare(current, baseline)
    assert "logs_fingerprint" not in result["changed_fields"]
