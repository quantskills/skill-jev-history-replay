"""旋钮功效审计：每个语义旋钮是否真的影响输出。

"语义对齐"的前提是每个旋钮都真实生效。若某个旋钮接进了配置、却对
重放结果毫无影响，那它就是一个**装饰性参数**——对齐它没有意义，
而报告仍会显示"该旋钮一致"。这类沉默失效比报错难发现得多。

做法：把每个旋钮单独换成备选值，比较整份交易的指纹
（入场时点/价、退出时点/原因、信号索引）。指纹不变即为"无效果"。

用法：
    python3 scripts/knob_efficacy.py
    python3 scripts/knob_efficacy.py --days 5 --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import config as cfg  # noqa: E402
from scripts import data_loader, semantics as sem  # noqa: E402
from scripts.replayer import replay_all  # noqa: E402
from scripts.run_eval import _load_prev_closes  # noqa: E402

# 预期必然改变输出的旋钮（用于判定"无效果"是否真的异常）
_EXPECTED_EFFECT = {k: True for k in sem.KNOB_VALUES}


def _fingerprint(replay: Dict[str, Any]) -> str:
    """整份交易的指纹：入场/退出的时点、价格、原因、信号索引。"""
    rows = []
    for symbol, result in sorted(replay["symbols"].items()):
        for cycle in result["cycles"]:
            rows.append((
                symbol,
                cycle.get("signal_index"),
                cycle.get("entry_time"),
                cycle.get("entry_price"),
                cycle.get("exit_time"),
                cycle.get("exit_price"),
                cycle.get("exit_reason"),
                cycle.get("status"),
            ))
    payload = json.dumps(rows, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def audit(days: int = 3) -> Dict[str, Any]:
    bars = data_loader.load_bars(REPO_ROOT / "fixtures" / "bars")
    dates = sorted({v["date"] for v in bars.values()})[:days]
    subset = {k: v for k, v in bars.items() if v["date"] in dates}
    prev = _load_prev_closes(REPO_ROOT / "fixtures" / "reference", list(subset))

    base = dict(cfg.load_config()["semantics"])
    base_replay = replay_all(subset, base, prev)
    base_fp = _fingerprint(base_replay)
    base_signals = base_replay["summary"]["signal_count"]

    results: List[Dict[str, Any]] = []
    for knob in sem.KNOB_VALUES:
        alt = dict(base)
        alt[knob] = sem.alternative_value(base, knob)
        problems = sem.validate_semantics(alt)
        if problems:
            results.append({
                "knob": knob,
                "value": alt[knob],
                "effective": None,
                "skipped": "; ".join(problems),
            })
            continue
        replay = replay_all(subset, alt, prev)
        fp = _fingerprint(replay)
        effective = fp != base_fp
        results.append({
            "knob": knob,
            "from": base[knob],
            "value": alt[knob],
            "effective": effective,
            "signal_count": replay["summary"]["signal_count"],
            "delta_signals": replay["summary"]["signal_count"] - base_signals,
        })

    ineffective = [
        r for r in results
        if r["effective"] is False and _EXPECTED_EFFECT.get(r["knob"], True)
    ]
    return {
        "ok": not ineffective,
        "days_used": dates,
        "series_count": len(subset),
        "base_fingerprint": base_fp,
        "base_signals": base_signals,
        "knobs_checked": len([r for r in results if r["effective"] is not None]),
        "ineffective": ineffective,
        "results": results,
        "note": (
            "指纹 = 全部周期的 信号索引/入场时点与价/退出时点与价/原因/状态。"
            "指纹不变说明该旋钮对重放完全没有影响，是装饰性参数。"
        ),
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit whether every semantics knob matters")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = audit(args.days)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"子集 {result['series_count']} 序列（{len(result['days_used'])} 天），"
              f"基准信号 {result['base_signals']}，指纹 {result['base_fingerprint']}")
        for r in result["results"]:
            if r["effective"] is None:
                print(f"  SKIP {r['knob']:26s} {r['skipped']}")
            else:
                mark = "OK  " if r["effective"] else "NO-EFFECT"
                print(f"  {mark} {r['knob']:26s} {r['from']} → {r['value']}"
                      f"  signals={r['signal_count']} ({r['delta_signals']:+d})")
        if result["ineffective"]:
            print(f"\n无效果旋钮：{[r['knob'] for r in result['ineffective']]}")
        print("OK" if result["ok"] else "FAILED")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())