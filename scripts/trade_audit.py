"""逐笔核对：从 replayer 的输出反查原始 K 线，验证价格与收益算术。

前面的验证都是统计层面的（一致率、显著性、覆盖率）。但统计对，
不代表每一笔的算术都对——比如入场价取错行、成本算反、收益公式写错，
在小样本下可能被整体一致率掩盖。

这个脚本独立重算：给定一个周期，从原始 K 线里找出入场/退出那两根，
用它们重算 gross/net，与 replayer 记录的值比对。全程不复用 replayer 的
内部函数，避免"用同一个错误验证自己"。

用法：
    python3 scripts/trade_audit.py                 # 抽样 200 笔
    python3 scripts/trade_audit.py --sample 1000
    python3 scripts/trade_audit.py --json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import config as cfg  # noqa: E402
from scripts import data_loader  # noqa: E402
from scripts.replayer import replay_all  # noqa: E402
from scripts.run_eval import _load_prev_closes  # noqa: E402

PRICE_TOL = 1e-6
RETURN_TOL = 1e-7


def _bar_at(bars: List[Dict[str, Any]], time_text: str) -> Dict[str, Any] | None:
    for bar in bars:
        if bar["time"] == time_text:
            return bar
    return None


def audit_trade(cycle: Dict[str, Any], bars_by_series: Dict[str, Dict[str, Any]],
                semantics: Dict[str, Any]) -> Dict[str, Any]:
    """完全独立地重算一笔交易。"""
    problems: List[str] = []

    entry_series = cycle.get("entry_series")
    exit_series = cycle.get("exit_series") or entry_series
    if entry_series not in bars_by_series:
        return {"ok": True, "skipped": "entry_series 不在数据里"}
    if exit_series not in bars_by_series:
        return {"ok": True, "skipped": "exit_series 不在数据里"}

    entry_bars = bars_by_series[entry_series]["bars"]
    exit_bars = bars_by_series[exit_series]["bars"]

    # 1) 入场价：next_open 取 entry_time 那根的 open
    entry_bar = _bar_at(entry_bars, cycle["entry_time"])
    if entry_bar is None:
        problems.append(f"入场时刻 {cycle['entry_time']} 在 {entry_series} 中不存在")
    else:
        expected_entry = (entry_bar["open"]
                          if semantics["entry_price"] == "next_open"
                          else entry_bar["close"])
        if abs(expected_entry - cycle["entry_price"]) > PRICE_TOL:
            problems.append(
                f"入场价不符：记录 {cycle['entry_price']}，"
                f"K线 {cycle['entry_time']} 的 open/close 为 {expected_entry}"
            )

    # 2) 退出价：按 exit_reason 判断应取哪一列
    exit_bar = _bar_at(exit_bars, cycle["exit_time"])
    reason = cycle.get("exit_reason")
    if exit_bar is None:
        problems.append(f"退出时刻 {cycle['exit_time']} 在 {exit_series} 中不存在")
    elif reason in ("stop_loss", "take_profit") and semantics["exit_eval"] == "bar_high_low":
        # 按触价退出，价格由止损/止盈比例决定，应落在该根 [low, high] 内
        p = cycle["exit_price"]
        if not (exit_bar["low"] - PRICE_TOL <= p <= exit_bar["high"] + PRICE_TOL):
            problems.append(
                f"{reason} 的退出价 {p} 不在该根 [low={exit_bar['low']}, "
                f"high={exit_bar['high']}] 区间内"
            )
    elif reason == "max_hold":
        if abs(exit_bar["open"] - cycle["exit_price"]) > PRICE_TOL:
            problems.append(
                f"max_hold 退出价不符：记录 {cycle['exit_price']}，"
                f"该根 open={exit_bar['open']}"
            )
    elif reason == "force_exit_time":
        if abs(exit_bar["close"] - cycle["exit_price"]) > PRICE_TOL:
            problems.append(
                f"强平退出价不符：记录 {cycle['exit_price']}，"
                f"该根 close={exit_bar['close']}"
            )
    else:
        if abs(exit_bar["close"] - cycle["exit_price"]) > PRICE_TOL:
            problems.append(
                f"{reason} 退出价不符：记录 {cycle['exit_price']}，"
                f"该根 close={exit_bar['close']}"
            )

    # 3) 收益算术
    entry_price = cycle["entry_price"]
    exit_price = cycle["exit_price"]
    gross = (exit_price - entry_price) / entry_price
    cost = (semantics["fee_bps"] + semantics["slippage_bps"]) * 2 / 10_000
    net = gross - cost

    if abs(gross - cycle["gross_return_pct"]) > RETURN_TOL:
        problems.append(
            f"gross 不符：重算 {gross:.8f}，记录 {cycle['gross_return_pct']}"
        )
    if abs(net - cycle["net_return_pct"]) > RETURN_TOL:
        problems.append(
            f"net 不符：重算 {net:.8f}，记录 {cycle['net_return_pct']}"
        )

    # 4) 股数：必须是最小交易单位的整数倍
    lot = int(semantics["lot_size"])
    if cycle["qty"] % lot != 0:
        problems.append(f"股数 {cycle['qty']} 不是 {lot} 的整数倍")

    # 5) 持仓根数必须为正（跨日持仓应明显大于 0）
    if cycle.get("bars_held") is not None and cycle["bars_held"] <= 0:
        problems.append(f"bars_held 非正：{cycle['bars_held']}")

    return {
        "ok": not problems,
        "symbol": cycle.get("symbol"),
        "entry_series": entry_series,
        "exit_series": exit_series,
        "entry_time": cycle["entry_time"],
        "exit_time": cycle["exit_time"],
        "exit_reason": reason,
        "gross": round(gross, 8),
        "net": round(net, 8),
        "problems": problems,
    }


def run_audit(sample: int = 200, seed: int = 12345) -> Dict[str, Any]:
    bars = data_loader.load_bars(REPO_ROOT / "fixtures" / "bars")
    prev = _load_prev_closes(REPO_ROOT / "fixtures" / "reference", list(bars))
    semantics = dict(cfg.load_config()["semantics"])
    replay = replay_all(bars, semantics, prev)

    closed = []
    for _symbol, result in replay["symbols"].items():
        for cycle in result["cycles"]:
            if cycle["status"] == "closed":
                closed.append(cycle)

    rng = random.Random(seed)
    picked = closed if len(closed) <= sample else rng.sample(closed, sample)
    results = [audit_trade(c, bars, semantics) for c in picked]
    checked = [r for r in results if "skipped" not in r]
    failed = [r for r in checked if not r["ok"]]

    cross_day = sum(1 for r in checked if r["entry_series"] != r["exit_series"])
    return {
        "ok": not failed,
        "total_closed_cycles": len(closed),
        "sampled": len(picked),
        "checked": len(checked),
        "cross_day_checked": cross_day,
        "failed": len(failed),
        "failures": failed[:20],
        "note": (
            "逐笔从原始 K 线反查入场/退出价并重算 gross/net，"
            "不复用 replayer 内部函数。"
        ),
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Per-trade price and return audit")
    parser.add_argument("--sample", type=int, default=200)
    parser.add_argument("--seed", type=int, default=12345)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = run_audit(args.sample, args.seed)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"收官周期 {result['total_closed_cycles']:,}，抽样 {result['sampled']}，"
              f"已核对 {result['checked']}（其中跨日 {result['cross_day_checked']}）")
        if result["failed"]:
            print(f"\n失败 {result['failed']} 笔：")
            for f in result["failures"]:
                print(f"  {f['entry_series']} → {f['exit_series']}")
                for p in f["problems"]:
                    print(f"    - {p}")
        print("OK" if result["ok"] else "FAILED")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())