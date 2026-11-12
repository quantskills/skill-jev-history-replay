"""夹具标的池必须全期固定。

跨日持仓的前提是同一只股票在相邻交易日都有数据。若每天各自抽样，
池子天天变（实测相邻日重合度最低 18.6%），昨天买的今天不在样本里，
跨日逻辑形同虚设，T+1 相关结论也失去基础。
"""

from __future__ import annotations

import gzip
import json
import re
from collections import Counter
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BARS_DIR = REPO_ROOT / "fixtures" / "bars"


def _symbols_by_date():
    out = {}
    for path in sorted(BARS_DIR.glob("*.json*")):
        match = re.match(r"(\d{8})\.json", path.name)
        if not match:
            continue
        date = match.group(1)
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as fh:
            records = json.load(fh)
        out[date] = {r["symbol"] for r in records}
    return out


def test_fixture_universe_is_constant_across_dates():
    by_date = _symbols_by_date()
    if len(by_date) < 2:
        pytest.skip("单日夹具不涉及跨日持仓")

    dates = sorted(by_date)
    reference = by_date[dates[0]]
    for date in dates[1:]:
        diff = reference.symmetric_difference(by_date[date])
        assert not diff, (
            f"{date} 的标的池与 {dates[0]} 不一致，差异 {len(diff)} 只："
            f"{sorted(diff)[:5]}。多日夹具必须使用全期固定标的池，"
            "否则跨日持仓会无故中断。"
        )


def test_every_series_has_full_bars():
    """每只股票每天都应有完整的 240 根，不能有天缺数据。"""
    for path in sorted(BARS_DIR.glob("*.json*")):
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as fh:
            records = json.load(fh)
        counts = Counter(r["symbol"] for r in records)
        bad = {s: c for s, c in counts.items() if c != 240}
        assert not bad, f"{path.name} 有标的分时根数异常：{list(bad.items())[:5]}"
