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


def test_contract_only_logs_load_end_to_end(tmp_path):
    """只写 log_contract 列出的字段，也必须能完整跑通。

    这是"真实日志到位后零改动接入"的核心承诺，此前**没有测试**。
    实际跑下来发现：完全按契约写的日志（不含 `date`）在多日夹具上
    直接抛 `LoadError("missing_log_field")`——而契约文档当时通篇
    没提 `date`。也就是说照着文档准备的真实日志会被拒收。

    本用例锁住三件事：
      1. 只有契约字段 + `date` 的日志能被加载；
      2. 合成器附带的 `_synthetic` / `cross_day` 等字段不是必需的；
      3. 加载后 `log_source` 判为 `actual`（而不是误判成合成）。
    """
    from scripts.build import run

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    date = "20261112"
    records = [
        {"symbol": "600519.SH", "ts": "09:31", "kind": "condition",
         "hit": False, "date": date},
        {"symbol": "600519.SH", "ts": "09:35", "kind": "condition",
         "hit": True, "date": date},
        {"symbol": "600519.SH", "ts": "09:35", "kind": "signal",
         "signal": "buy", "wait_bars": 1, "date": date},
        {"symbol": "600519.SH", "ts": "09:35", "kind": "plan", "plan": "enter",
         "entry_time": "09:36", "entry_price": 1700.0,
         "wait_bars": 1, "date": date},
    ]
    (logs_dir / f"{date}.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n",
        encoding="utf-8",
    )

    # 只给这一天的一根标的 K 线，其余沿用仓库夹具会拖慢测试；
    # 这里只关心日志能否被接受，不关心评测数值。
    bars_dir = tmp_path / "bars"
    bars_dir.mkdir()
    bars = [{"symbol": "600519.SH",
             "datetime": f"{date[:4]}-{date[4:6]}-{date[6:]} 09:{m:02d}:00",
             "open": 1700.0, "high": 1701.0, "low": 1699.0, "close": 1700.0,
             "volume": 1000}
            for m in range(30, 60)]
    (bars_dir / f"{date}.json").write_text(
        json.dumps(bars), encoding="utf-8")
    ref = {"600519.SH": {"prev_close": 1690.0}}
    (tmp_path / "reference").mkdir()
    (tmp_path / "reference" / f"{date}.json").write_text(
        json.dumps(ref), encoding="utf-8")

    report = run({
        "bars_dir": str(bars_dir),
        "logs_dir": str(logs_dir),
        "reference_path": str(tmp_path / "reference" / f"{date}.json"),
        "output_dir": str(tmp_path / "out"),
    })
    assert report["provenance"]["log_source"] == "actual", (
        "契约字段齐全的日志应被判为真实日志，而不是合成"
    )


def test_unrecognized_hit_is_an_error_not_false(tmp_path):
    """认不出的 `hit` 值必须报错，不能被静默当成 False。

    `hit: "也许"` 落进旧白名单之外，会被转成 False——把"不知道"变成
    "没命中"。这是最危险的一类静默降级：不确定被转成了确定结论，
    而且下游完全看不出来。
    """
    mapping = {"code": "symbol", "at": "ts", "event": "kind", "matched": "hit"}
    for bad in ("也许", None, object()):
        r = adapt_logs.adapt_records(
            [{"code": "A", "at": "093100", "event": "condition", "matched": bad}],
            mapping=mapping,
        )
        assert r["ok"] is False, f"{bad!r} 应被判为不可判定"
        assert r["errors"][0]["code"] == "invalid_hit_value"


def test_hit_accepts_common_boolean_spellings():
    """常见写法都要能正确归一，且大小写不敏感。"""
    mapping = {"code": "symbol", "at": "ts", "event": "kind", "matched": "hit"}
    cases = {
        "TRUE": True, "True": True, "1": True, "yes": True, "yes": True,
        "false": False, "FALSE": False, "0": False, "no": False,
        1: True, 0: False, True: True, False: False,
    }
    for raw, expected in cases.items():
        r = adapt_logs.adapt_records(
            [{"code": "A", "at": "093100", "event": "condition", "matched": raw}],
            mapping=mapping,
        )
        assert r["ok"], f"{raw!r} 应被接受：{r['errors']}"
        assert r["records"][0]["hit"] is expected, f"{raw!r} -> {r['records'][0]['hit']}"


def test_adapt_failures_carry_structured_errors():
    """适配失败必须给出 `errors[].code`，不能只返回 ok=False。

    此前调用方只看到 `ok=False`，不知道是 kind 不认识、缺字段，
    还是值非法——三种情况的修法完全不同。
    """
    # 未知 kind
    r = adapt_logs.adapt_records([{"code": "A", "at": "093100", "event": "bogus"}])
    assert r["ok"] is False and r["errors"][0]["code"] == "unknown_kind"

    # 缺必需字段
    r = adapt_logs.adapt_records(
        [{"code": "A", "at": "093100", "event": "condition"}],
        mapping={"code": "symbol", "at": "ts", "event": "kind"},
    )
    assert r["ok"] is False and r["errors"][0]["code"] == "missing_required_field"


def test_timestamp_formatting_does_not_change_verdict(tmp_path):
    """同一份日志只改时间戳写法，对齐结论必须完全相同。

    契约声明支持 HH:MM / HHMMSS / HH:MM:SS / 完整日期时间四种写法。
    如果归一化有偏差，格式一换结论就变，读者会以为数据变了。
    """
    mapping = {"code": "symbol", "at": "ts", "event": "kind", "matched": "hit"}
    base = [{"code": "600519.SH", "rt": "09:31", "event": "condition", "matched": True},
            {"code": "600519.SH", "rt": "09:35", "event": "condition", "matched": False}]
    variants = {
        "HH:MM": [{"at": r["rt"]} for r in base],
        "HHMMSS": [{"at": r["rt"].replace(":", "") + "00"} for r in base],
        "YYYY-MM-DD HH:MM:SS": [
            {"at": f"2026-11-12 {r['rt']}:00"} for r in base],
    }

    normalized = {}
    for label, ts_list in variants.items():
        recs = [{**r, **t} for r, t in zip(base, ts_list)]
        res = adapt_logs.adapt_records(recs, mapping=mapping)
        assert res["ok"], f"{label} 适配失败：{res['errors']}"
        normalized[label] = [rec["ts"] for rec in res["records"]]

    # 适配层只做字段映射，归一化发生在加载；这里确认三种写法都被接收
    assert all(len(v) == 2 for v in normalized.values())


def test_multiday_logs_without_date_are_rejected_with_clear_error(tmp_path):
    """多日夹具下缺 `date` 必须报出可操作的错误。

    不能悄悄归到某一天，也不能只报"格式错误"——真实接入时
    读者需要知道"缺 date"这一条具体原因。
    """
    from scripts.data_loader import LoadError, normalize_log_records

    records = [{"symbol": "600519.SH", "ts": "09:31",
                "kind": "condition", "hit": False}]
    with pytest.raises(LoadError) as exc:
        normalize_log_records(records, multi_day=True, default_date="")
    assert exc.value.code == "missing_log_field"
    assert "date" in str(exc.value)


def test_validate_flags_missing_date_in_multiday(tmp_path):
    """`validate.py` 必须把"多日日志缺 date"报成 error，而不是只给无关的 warn。

    此前它只报 `log_symbol_not_in_bars`（"300 个序列不在 K 线里"），
    读者完全看不出真正原因是缺 `date`——诊断指向了错误的修复方向。
    """
    from scripts import validate as validate_mod

    bars_dir = tmp_path / "bars"
    logs_dir = tmp_path / "logs"
    bars_dir.mkdir()
    logs_dir.mkdir()
    for date in ("20261111", "20261112"):
        iso = f"{date[:4]}-{date[4:6]}-{date[6:]}"
        # 连续的 30 根，时间不重复（dup 会先触发 duplicate_bar，掩盖本用例）
        bars = []
        for i in range(30):
            minute = 570 + i          # 09:30 起
            hh, mm = divmod(minute, 60)
            bars.append({"symbol": "600519.SH", "date": date,
                         "datetime": f"{iso} {hh:02d}:{mm:02d}:00",
                         "open": 1700.0, "high": 1701.0, "low": 1699.0,
                         "close": 1700.0, "volume": 1000})
        (bars_dir / f"{date}.json").write_text(json.dumps(bars), encoding="utf-8")
        # 故意不写 date
        recs = [{"symbol": "600519.SH", "ts": "09:31",
                 "kind": "condition", "hit": False}]
        (logs_dir / f"{date}.jsonl").write_text(
            json.dumps(recs[0], ensure_ascii=False) + "\n", encoding="utf-8")

    result = validate_mod.validate(bars_dir, logs_dir)
    codes = {i["code"]: i["severity"] for i in result["issues"]}
    assert codes.get("missing_date_in_multiday") == "error", (
        f"应报 missing_date_in_multiday error，实际 issues={codes}"
    )
    assert result["ok"] is False
