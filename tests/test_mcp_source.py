"""MCP 取数结果解析：两种信封形态、截断、缺列、ok=false。

取数路径是「agent 通过 `mcp__pandadata__call_pandadata` 取回 → 落盘 JSON →
脚本消费」。解析器是这个契约唯一的守门人：它若把截断数据当完整、
把缺列当成有数据，下游全部结论都会建立在错误输入上。

全部测试只用内存/临时文件，不联网。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import mcp_source as m
from scripts.mcp_source import MCPDataError, MCPSource


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _dataframe(columns, rows, *, truncated=False, total_rows=None,
               reasons=None):
    return {
        "type": "dataframe",
        "columns": list(columns),
        "rows": [list(r) for r in rows],
        "row_count": len(rows),
        "total_rows": total_rows if total_rows is not None else len(rows),
        "truncated": truncated,
        "truncation_reasons": reasons or [],
    }


def _envelope(result, method="get_stock_min", ok=True):
    return {"ok": ok, "method": method, "params": {}, "result": result,
            "request_id": "req-test"}


# ---------------------------------------------------------------- 信封形态

def test_dataframe_envelope_parses_to_records():
    result = _dataframe(
        ["symbol", "datetime", "minute"],
        [["000001.SZ", "2026-11-12 09:31:00", 571],
         ["000001.SZ", "2026-11-12 09:32:00", 572]],
    )
    records = m.to_records(result, method="get_stock_min",
                           required=("symbol", "datetime"))
    assert [r["minute"] for r in records] == [571, 572]
    assert records[0]["symbol"] == "000001.SZ"


def test_list_envelope_parses_to_records():
    """`get_trade_list` 返回对象数组，不是 dataframe 信封。"""
    result = [{"date": "20251110", "symbol": "000001.SZ"},
              {"date": "20251110", "symbol": "600519.SH"}]
    records = m.to_records(result, method="get_trade_list",
                           required=m.TRADE_LIST_COLUMNS)
    assert [r["symbol"] for r in records] == ["000001.SZ", "600519.SH"]


def test_dict_date_result_parses():
    assert m.scalar_date({"date": "20251107"}) == "20251107"
    assert m.scalar_date("2025-11-07") == "20251107"


def test_date_normalisation_rejects_garbage():
    with pytest.raises(MCPDataError) as exc:
        m.norm_date("上周五")
    assert exc.value.code == "invalid_date"


# ------------------------------------------------------------------- 截断

def test_truncated_dataframe_is_rejected_not_silently_used():
    """实测：240 行分钟线只回 180 行。必须报错。"""
    result = _dataframe(["symbol"], [["000001.SZ"]] * 180,
                        truncated=True, total_rows=240,
                        reasons=["byte_limit"])
    with pytest.raises(MCPDataError) as exc:
        m.to_records(result, method="get_stock_min", required=("symbol",))
    assert exc.value.code == "truncated_result"
    assert "240" in exc.value.message
    assert "byte_limit" in exc.value.message
    assert exc.value.hint, "截断错误必须提示按窄日期区间分批"


def test_row_count_below_total_rows_without_flag_is_still_rejected():
    """即使没有 truncated 标记，row_count < total_rows 也不能当完整。"""
    result = _dataframe(["symbol"], [["000001.SZ"]] * 3, total_rows=10)
    with pytest.raises(MCPDataError) as exc:
        m.to_records(result, required=("symbol",))
    assert exc.value.code == "truncated_result"


# ------------------------------------------------------------------- 缺列

def test_missing_required_column_is_rejected():
    result = _dataframe(["symbol", "datetime"], [["000001.SZ", "2026-11-12 09:31:00"]])
    with pytest.raises(MCPDataError) as exc:
        m.to_records(result, method="get_stock_min",
                     required=("symbol", "close"))
    assert exc.value.code == "missing_columns"
    assert "close" in exc.value.message


def test_ragged_rows_are_rejected():
    result = _dataframe(["symbol", "close"], [["000001.SZ"]])
    with pytest.raises(MCPDataError) as exc:
        m.to_records(result, required=("symbol",))
    assert exc.value.code == "ragged_rows"


def test_empty_dataframe_rejected_unless_allowed():
    result = _dataframe(["symbol"], [])
    with pytest.raises(MCPDataError) as exc:
        m.to_records(result, method="get_stock_min", required=("symbol",))
    assert exc.value.code == "no_data"
    assert m.to_records(result, required=("symbol",), allow_empty=True) == []


# ----------------------------------------------------------------- ok=false

def test_ok_false_envelope_raises_structured_error():
    envelope = {
        "ok": False,
        "method": "get_stock_min",
        "params": {},
        "result": {"code": "auth_required",
                   "message": "OAuth 登录已失效",
                   "hint": "重新登录"},
        "request_id": "req-1",
    }
    with pytest.raises(MCPDataError) as exc:
        m.unwrap(envelope, method="get_stock_min")
    assert exc.value.code == "auth_required"
    assert "OAuth" in exc.value.message
    assert exc.value.hint == "重新登录"


def test_envelope_without_result_is_rejected():
    with pytest.raises(MCPDataError) as exc:
        m.unwrap({"ok": True})
    assert exc.value.code == "invalid_envelope"


# ------------------------------------------------------------------- 落盘

def test_mcpsource_finds_day_scoped_and_shared_files(tmp_path):
    _write(tmp_path / "20261112" / "get_stock_min.json",
           _envelope(_dataframe(["symbol", "close"], [["000001.SZ", 11.5]])))
    _write(tmp_path / "get_st_list.json",
           _envelope(_dataframe(["symbol", "date", "is_st"],
                                [["000001.SZ", "20261112", True]]),
                     method="get_st_list"))
    _write(tmp_path / "20261112" / "get_prev_trade_date.json",
           _envelope({"date": "20261111"}, method="get_prev_trade_date"))

    source = MCPSource(tmp_path)
    rows = source.dataframe("get_stock_min", date="20261112",
                            required=("symbol", "close"))
    assert rows == [{"symbol": "000001.SZ", "close": 11.5}]
    assert source.prev_trade_date("20261112") == "20261111"
    assert source.has("get_st_list") is True

    st = source.dataframe("get_st_list", required=m.ST_COLUMNS)
    assert st[0]["is_st"] is True


def test_mcpsource_missing_file_is_structured(tmp_path):
    source = MCPSource(tmp_path)
    with pytest.raises(MCPDataError) as exc:
        source.dataframe("get_stock_min", date="20261112")
    assert exc.value.code == "missing_mcp_file"
    assert "mcp__pandadata__call_pandadata" in exc.value.hint


def test_mcpsource_accepts_bare_result_without_envelope(tmp_path):
    """手工准备的落盘文件可以直接是 result 内容。"""
    path = tmp_path / "20261112" / "get_prev_trade_date.json"
    _write(path, {"date": "2026-11-11"})
    assert MCPSource(tmp_path).prev_trade_date("20261112") == "20261111"


def test_mcpsource_rejects_invalid_json(tmp_path):
    path = tmp_path / "20261112" / "get_stock_min.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(MCPDataError) as exc:
        MCPSource(tmp_path).dataframe("get_stock_min", date="20261112")
    assert exc.value.code == "invalid_mcp_json"


def test_unknown_method_is_rejected(tmp_path):
    with pytest.raises(MCPDataError) as exc:
        MCPSource(tmp_path).path_for("get_not_a_real_method")
    assert exc.value.code == "unknown_method"