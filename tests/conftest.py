"""单元测试公共夹具。

测试全部使用**内存合成数据**，不读真实夹具、不访问网络，
因此 CI 不装任何取数组件、不联网也能秒级跑完。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "slow: 需要跑多组完整端到端（约 2 分钟），CI 单独调度",
    )


def make_bars(prices: List[float], start_minute: int = 9 * 60 + 31) -> List[Dict[str, Any]]:
    """按给定收盘价序列构造分钟线；开盘价取前一根收盘，高低价包住开收。"""
    bars: List[Dict[str, Any]] = []
    prev = prices[0]
    for idx, close in enumerate(prices):
        minute = start_minute + idx
        hour, rem = divmod(minute, 60)
        bars.append({
            "time": f"{hour:02d}:{rem:02d}",
            "minute": minute,
            "open": prev,
            "high": max(prev, close) + 0.01,
            "low": min(prev, close) - 0.01,
            "close": close,
            "volume": 1000.0,
        })
        prev = close
    return bars


def make_dataset(series: Dict[str, List[float]]) -> Dict[str, Dict[str, Any]]:
    return {
        symbol: {"date": "20260101", "bars": make_bars(prices)}
        for symbol, prices in series.items()
    }


@pytest.fixture
def semantics() -> Dict[str, Any]:
    from scripts import config

    base = dict(config.REFERENCE_SEMANTICS)
    base["breakout_window"] = 5
    base["warmup_bars"] = 5
    base["persistence_bars"] = 1
    base["wait_bars"] = 0
    base["cooldown_bars"] = 0
    base["signal_gain_pct"] = 0.005
    base["take_profit_pct"] = 0.05
    base["stop_loss_pct"] = 0.05
    base["max_hold_bars"] = 10
    base["no_entry_after"] = "14:45"
    base["force_exit_time"] = "14:45"
    return base


@pytest.fixture
def flat_then_breakout() -> List[float]:
    """15 根横盘后突破：保证条件在该点上确实成立。"""
    return [10.0] * 15 + [10.2, 10.4, 10.6, 10.8, 11.0]


@pytest.fixture
def tmp_fixtures(tmp_path: Path):
    """把内存数据写成文件，供走文件路径的测试使用。"""
    def write(bars_by_symbol: Dict[str, Dict[str, Any]],
              logs: List[Dict[str, Any]] | None = None) -> Dict[str, Path]:
        bars_dir = tmp_path / "bars"
        logs_dir = tmp_path / "logs"
        bars_dir.mkdir()
        logs_dir.mkdir()
        records = []
        for symbol, entry in bars_by_symbol.items():
            for bar in entry["bars"]:
                records.append({
                    "symbol": symbol,
                    "date": entry["date"],
                    "datetime": f"{entry['date'][:4]}-{entry['date'][4:6]}-{entry['date'][6:]} {bar['time']}:00",
                    "open": bar["open"],
                    "high": bar["high"],
                    "low": bar["low"],
                    "close": bar["close"],
                    "volume": bar["volume"],
                })
        (bars_dir / "20260101.json").write_text(
            json.dumps(records, ensure_ascii=False), encoding="utf-8"
        )
        if logs:
            (logs_dir / "20260101.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in logs) + "\n",
                encoding="utf-8",
            )
        return {"bars_dir": bars_dir, "logs_dir": logs_dir}
    return write