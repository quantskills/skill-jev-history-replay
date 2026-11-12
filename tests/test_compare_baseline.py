"""冻结基线：freeze / compare / list 的行为。

`config_hash` 不一致时必须**拒绝解读 delta**——这是整个机制的意义所在。
若它悄悄给出一个差值，读者会拿两次不可比的运行做比较，还以为在比同一件事。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import compare_baseline


def _report(tmp_path: Path, *, config_hash: str, semantics_hash: str,
            match_rate: float = 0.99, divergent: int = 10,
            log_source: str = "synthetic") -> Path:
    payload = {
        "run_id": "test-run",
        "comparability": {
            "config_hash": config_hash,
            "semantics_hash": semantics_hash,
            "fixture_fingerprint": "abc",
            "log_source": log_source,
        },
        "summary": {
            "ledger_match_rate": match_rate,
            "divergence_items": divergent,
            "one_sided_items": 100,
            "signal_count": 10,
            "closed_cycles": 9,
            "total_net_pct": 0.1,
        },
        "alignment_conclusion": {"verdict": "inconclusive"},
        "value_assessment": {"verdict": {"verdict": "inconclusive"}},
        "attribution": {"verdict": "single_knob"},
    }
    path = tmp_path / f"report-{config_hash}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_freeze_creates_baseline_file(tmp_path):
    report = _report(tmp_path, config_hash="h1", semantics_hash="s1")
    out = compare_baseline.freeze(report, name="v1", baseline_dir=tmp_path / "baselines")
    assert out["ok"]
    saved = Path(out["baseline"])
    assert saved.exists()
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert data["config_hash"] == "h1"
    assert data["name"] == "v1"


def test_compare_same_config_gives_deltas(tmp_path):
    a = _report(tmp_path, config_hash="h1", semantics_hash="s1")
    frozen = compare_baseline.freeze(
        a, name="base", baseline_dir=tmp_path / "baselines")
    b = _report(tmp_path, config_hash="h1", semantics_hash="s1",
                match_rate=0.98, divergent=20)
    out = compare_baseline.compare(b, frozen["baseline"])
    assert out["comparable"] is True
    assert out["deltas"] is not None
    assert out["deltas"]["divergence_items"]["delta"] == 10


def test_compare_different_config_refuses_deltas(tmp_path):
    """config_hash 不同 → 必须拒绝给 delta，并列出变化的字段。"""
    a = _report(tmp_path, config_hash="h1", semantics_hash="s1")
    frozen = compare_baseline.freeze(
        a, name="base", baseline_dir=tmp_path / "baselines")
    b = _report(tmp_path, config_hash="h2", semantics_hash="s2")
    out = compare_baseline.compare(b, frozen["baseline"])
    assert out["comparable"] is False
    assert out["deltas"] is None, "不可比时绝不能给出 delta"
    assert "semantics_hash" in out["changed_fields"]
    assert "不一致" in out["note"]


def test_changed_config_hash_alone_is_reported(tmp_path):
    """只有 config_hash 变化时，它也必须出现在 `changed_fields` 里。

    此前只比较 semantics_hash / fixture_fingerprint / log_source 三个组成项。
    若 config_hash 被外部改动（或组成项之外的成份变了），
    `comparable=false` 却给出**空列表**，而 note 还写着"请确认语义、
    夹具或日志来源是否变化"——读者无从判断到底哪里变了。
    """
    a = _report(tmp_path, config_hash="h1", semantics_hash="s1")
    frozen = compare_baseline.freeze(
        a, name="base", baseline_dir=tmp_path / "baselines")
    b = _report(tmp_path, config_hash="h2", semantics_hash="s1")  # 只改 config_hash
    out = compare_baseline.compare(b, frozen["baseline"])
    assert out["comparable"] is False
    assert out["deltas"] is None
    assert "config_hash" in out["changed_fields"], (
        f"changed_fields 未列出 config_hash：{out['changed_fields']}"
    )


def test_list_empty_dir(tmp_path):
    out = compare_baseline.list_baselines(tmp_path / "nope")
    assert out == {"ok": True, "baselines": []}


def test_list_returns_metadata(tmp_path):
    report = _report(tmp_path, config_hash="h1", semantics_hash="s1")
    d = tmp_path / "baselines"
    compare_baseline.freeze(report, name="v1", baseline_dir=d)
    compare_baseline.freeze(report, name="v2", baseline_dir=d)
    out = compare_baseline.list_baselines(d)
    assert {b["name"] for b in out["baselines"]} == {"v1", "v2"}
    assert all(b["config_hash"] == "h1" for b in out["baselines"])


def test_missing_report_raises_structured_error(tmp_path):
    with pytest.raises(compare_baseline.BaselineError) as exc:
        compare_baseline.freeze(tmp_path / "nope.json")
    assert exc.value.code == "report_not_found"


def test_corrupt_json_raises_structured_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(compare_baseline.BaselineError) as exc:
        compare_baseline.freeze(bad)
    assert exc.value.code == "invalid_json"
