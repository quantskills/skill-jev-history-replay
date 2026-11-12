"""账本落盘模式：默认瘦身，full 可回溯全量。"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from scripts.run_eval import evaluate


def test_default_ledger_omits_quiet_rows():
    """默认 diff 模式必须略过 match 与 jev_missing。

    1M 行里 99.9% 是这两类，全量落盘会让账本到 185MB，
    而真正需要逐行追溯的只有几百条。
    """
    out = Path(tempfile.mkdtemp())
    result = evaluate(output_dir=out, run_attribution=False)
    art = result["artifacts"]
    assert art["ledger_mode"] == "diff"
    assert art["ledger_quiet_rows_omitted"] > 0
    assert art["ledger_rows_written"] < art["ledger_quiet_rows_omitted"]

    statuses = set()
    for line in Path(art["ledger"]).read_text(encoding="utf-8").splitlines():
        if line.strip():
            statuses.add(json.loads(line)["status"])
    assert "match" not in statuses
    assert "jev_missing" not in statuses


def test_full_mode_keeps_everything():
    out = Path(tempfile.mkdtemp())
    result = evaluate(output_dir=out, run_attribution=False,
                      config_overrides={"ledger_mode": "full"})
    art = result["artifacts"]
    assert art["ledger_mode"] == "full"
    assert art["ledger_quiet_rows_omitted"] == 0
    assert art["ledger_rows_written"] > 0


def test_report_has_per_day_block():
    """per_day 必须写进报告——否则校验要读 185MB 账本。"""
    out = Path(tempfile.mkdtemp())
    result = evaluate(output_dir=out, run_attribution=False)
    per_day = result.get("per_day")
    assert per_day, "报告缺 per_day"
    for day, bucket in per_day.items():
        assert "match" in bucket and "divergent" in bucket
        assert bucket["comparable"] == bucket["match"] + bucket["divergent"]
