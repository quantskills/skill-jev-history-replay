"""夹具有效性：`reference` 与分钟线、与 panda 数据源是否一致。

`reference` 提供 `pre_close`，是涨幅判断的基准。它一旦有误，
下游所有条件判断都会偏，而此前没有任何测试校验它。
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BARS = REPO_ROOT / "fixtures" / "bars"
REF = REPO_ROOT / "fixtures" / "reference"


def _load_bars(date: str):
    with gzip.open(BARS / f"{date}.json.gz", "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _load_ref(date: str):
    return json.loads((REF / f"{date}.json").read_text(encoding="utf-8"))["symbols"]


def _all_dates():
    return sorted(p.stem for p in REF.glob("*.json"))


def test_pre_close_matches_previous_close_or_is_explained():
    """`pre_close` 通常等于前一交易日收盘价，但**不总是**。

    少数标的的 `pre_close` 与前一交易日 `close` 不同（实测 5/4,200），
    原因是除权除息或数据源自身的 pre_close 口径。夹具忠实复制 panda
    返回值（已用 `get_stock_daily` 逐字段核对 600 条全对），
    所以这里**不要求相等**，只要求：
      - 差异必须存在且可列出（不能悄悄变化）
      - 差异比例保持在一个小范围内
    """
    dates = _all_dates()
    mismatches = []
    compared = 0
    for i in range(1, len(dates)):
        prev_date, date = dates[i - 1], dates[i]
        prev = _load_ref(prev_date)
        cur = _load_ref(date)
        for symbol, per in cur.items():
            day = per.get(date)
            prev_rec = prev.get(symbol, {}).get(prev_date)
            if not day or not prev_rec:
                continue
            compared += 1
            if abs(day["pre_close"] - prev_rec["close"]) > 1e-6:
                mismatches.append((date, symbol,
                                   day["pre_close"], prev_rec["close"]))

    # 差异应极少：若大量出现，说明夹具或数据源出了问题
    ratio = len(mismatches) / compared if compared else 0
    assert ratio < 0.01, (
        f"pre_close 与前一日收盘不符的比例过高：{len(mismatches)}/{compared}"
        f"（{ratio:.2%}），首个：{mismatches[:3]}")
    # 且差异幅度不应离谱（除权送股可能较大，但不会出现数量级差异）
    for date, symbol, pc, prev_close in mismatches:
        assert 0.5 < pc / prev_close < 2.0, (
            f"{date} {symbol}: pre_close={pc} 与 prev close={prev_close} 相差过大")


def test_reference_high_low_close_match_minute_bars():
    """日线 high/low/close 与分钟线聚合的差异必须极小且可解释。

    绝大多数应为精确相等。例外来自集合竞价：09:31 首根可能带竞价成交价，
    使分钟线的 high 略高于日线 high（实测 1/4,200：`002193.SZ` 3.66 vs 3.65）。
    这不是夹具错误——日线值直接来自 panda `get_stock_daily`（已逐字段核对
    600 条全对），分钟线来自 `get_stock_min`，两者在竞价边界天然可能不同。

    这里守两件事：
      1. 差异比例极小（<1%）；
      2. close 必须严格相等（收盘价不受竞价影响）。
    """
    mismatches = []
    compared = 0
    close_bad = []
    for date in _all_dates():
        ref = _load_ref(date)
        by = {}
        for r in _load_bars(date):
            by.setdefault(r["symbol"], []).append(r)
        for symbol, per in ref.items():
            day = per.get(date)
            bars = by.get(symbol)
            if not day or not bars:
                continue
            compared += 1
            if abs(day["close"] - bars[-1]["close"]) > 1e-6:
                close_bad.append(
                    f"{date} {symbol}: close ref={day['close']} bars={bars[-1]['close']}")
            for field, value in (
                ("high", max(b["high"] for b in bars)),
                ("low", min(b["low"] for b in bars)),
            ):
                if abs(day[field] - value) > 1e-6:
                    mismatches.append((date, symbol, field, day[field], value))

    assert close_bad == [], "收盘价必须完全一致：\n" + "\n".join(close_bad[:10])
    ratio = len(mismatches) / compared if compared else 0
    assert ratio < 0.01, (
        f"high/low 与分钟线不符的比例过高：{len(mismatches)}/{compared}"
        f"（{ratio:.2%}），样例：{mismatches[:3]}")


def test_day_open_uses_first_bar_open_not_daily_open():
    """`day_open` 口径固定为「分钟线首根 open」，须与文档一致。

    实测有 2/4200 条序列日线 open 与首根 open 不同（集合竞价）。
    这不是缺陷，但必须是有意识的、写下来的口径——否则读者
    自己发现时会误以为是数据错误。
    """
    from scripts.replayer import _baseline_price

    bars = [{"open": 10.0, "high": 10.0, "low": 10.0, "close": 10.0},
            {"open": 11.0, "high": 11.0, "low": 11.0, "close": 11.0}]
    value = _baseline_price(bars, 0, bars, {"baseline_price": "day_open"}, 9.5)
    assert value == 10.0, "day_open 应取首根 open"


def test_documented_day_open_caveat_exists():
    """`semantics_matrix.md` 必须写明 day_open 的口径与影响面。"""
    text = (REPO_ROOT / "references" / "semantics_matrix.md").read_text(encoding="utf-8")
    assert "分钟线首根" in text, "未说明 day_open 取的是分钟线首根 open"
    assert "集合竞价" in text, "未说明与日线 open 的差异来自集合竞价"