"""外部日志适配：真实字段名与契约不同时的显式映射。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import adapt_logs


def test_common_aliases_are_applied():
    rec = {"timestamp": "09:41", "type": "condition",
           "code": "600519.SH", "matched": 1}
    r = adapt_logs.adapt_records([rec])
    assert r["ok"]
    out = r["records"][0]
    assert out["ts"] == "09:41"
    assert out["symbol"] == "600519.SH"
    assert out["kind"] == "condition"
    assert out["hit"] is True


@pytest.mark.parametrize("raw,expected", [
    (1, True), (0, False), ("true", True), ("false", False),
    ("1", True), ("0", False), (True, True), (False, False),
])
def test_hit_is_normalized_to_bool(raw, expected):
    """字符串 "false" 必须变成 False——bool("false") == True 是最危险的坑。"""
    r = adapt_logs.adapt_records([
        {"ts": "09:41", "kind": "condition", "symbol": "X", "hit": raw}
    ])
    assert r["ok"]
    assert r["records"][0]["hit"] is expected


def test_explicit_mapping_wins():
    rec = {"ts": "09:41", "kind": "plan", "symbol": "X",
           "plan": "enter", "fill_price": 11.5}
    r = adapt_logs.adapt_records(
        [rec], mapping={"plan": {"fill_price": "entry_price"}}
    )
    assert r["ok"]
    assert r["records"][0]["entry_price"] == 11.5


def test_missing_required_field_is_an_error_not_silent():
    """适配后仍缺必需字段，必须报错——不能带着缺陷进入对齐。"""
    rec = {"ts": "09:41", "kind": "condition", "symbol": "X"}   # 缺 hit
    r = adapt_logs.adapt_records([rec])
    assert not r["ok"]
    assert any(e["code"] == "missing_required_field" for e in r["errors"])


def test_unknown_kind_is_an_error():
    r = adapt_logs.adapt_records([
        {"ts": "09:41", "kind": "vibes", "symbol": "X"}
    ])
    assert not r["ok"]
    assert any(e["code"] == "unknown_kind" for e in r["errors"])


def test_adapt_dir_writes_correct_filenames(tmp_path):
    """文件名转换曾把 a.jsonl 写成 a.jsonll，导致输出为空却报 OK。"""
    src = tmp_path / "raw"
    src.mkdir()
    (src / "a.jsonl").write_text(
        json.dumps({"ts": "09:41", "kind": "condition", "symbol": "X", "hit": True}) + "\n",
        encoding="utf-8",
    )
    dst = tmp_path / "out"
    result = adapt_logs.adapt_dir(src, dst)
    assert result["ok"]
    written = list(dst.glob("*.jsonl"))
    assert len(written) == 1
    assert written[0].name == "a.jsonl"
    assert written[0].read_text(encoding="utf-8").strip(), "输出文件不能为空"


def test_adapt_dir_handles_gz_source(tmp_path):
    import gzip
    src = tmp_path / "raw"
    src.mkdir()
    with gzip.open(src / "b.jsonl.gz", "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"ts": "09:41", "kind": "condition",
                             "symbol": "X", "hit": False}) + "\n")
    dst = tmp_path / "out"
    result = adapt_logs.adapt_dir(src, dst)
    assert result["ok"]
    assert (dst / "b.jsonl").exists()


def test_example_mapping_is_valid_json():
    assert isinstance(adapt_logs.EXAMPLE_MAPPING, dict)
    json.dumps(adapt_logs.EXAMPLE_MAPPING)
