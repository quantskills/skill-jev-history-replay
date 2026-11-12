"""契约校验：检查 K 线与日志是否符合本 skill 的输入契约。

用途：接入真实 JEV 日志之前先跑一遍，把「字段缺失」与「语义不一致」分开——
字段缺失是接入问题，语义不一致才是研究问题。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import data_loader  # noqa: E402

# 各 kind 的必需字段与推荐字段
KIND_FIELDS: Dict[str, Dict[str, List[str]]] = {
    "condition": {
        "required": ["ts", "kind", "symbol", "hit"],
        "recommended": ["reference", "baseline", "gain_pct"],
    },
    "signal": {
        "required": ["ts", "kind", "symbol", "signal"],
        "recommended": ["wait_bars"],
    },
    "plan": {
        "required": ["ts", "kind", "symbol", "plan"],
        "recommended": ["entry_time", "entry_price", "wait_bars", "exit_time", "exit_reason"],
    },
    "fill": {
        "required": ["ts", "kind", "symbol", "side"],
        "recommended": ["price", "qty", "status"],
    },
}


def validate(bars_dir: Path, logs_dir: Path) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []

    try:
        bars = data_loader.load_bars(bars_dir)
    except data_loader.LoadError as exc:
        return {
            "ok": False,
            "stage": "bars",
            "issues": [{"severity": "error", "code": exc.code,
                        "message": exc.message, "hint": exc.hint}],
        }

    lengths = {symbol: len(entry["bars"]) for symbol, entry in bars.items()}
    for symbol, count in lengths.items():
        if count < 30:
            issues.append({
                "severity": "warn",
                "code": "short_history",
                "message": f"{symbol} 只有 {count} 根 K 线",
                "hint": "少于 breakout_window + warmup_bars 时不会产生任何判断",
            })
    if lengths and max(lengths.values()) != min(lengths.values()):
        issues.append({
            "severity": "info",
            "code": "uneven_bars",
            "message": f"各标的根数不一致：{min(lengths.values())}–{max(lengths.values())}",
            "hint": "停牌或数据缺失会这样；对齐会按各自可用根数处理",
        })

    try:
        records = data_loader.load_logs(logs_dir)
    except data_loader.LoadError as exc:
        return {
            "ok": False,
            "stage": "logs",
            "issues": issues + [{"severity": "error", "code": exc.code,
                                 "message": exc.message, "hint": exc.hint}],
        }

    series_keys = set(bars)
    unknown_symbols = sorted({
        data_loader.series_key(r["symbol"], str(r.get("date") or ""))
        for r in records
    } - series_keys)
    if unknown_symbols:
        issues.append({
            "severity": "warn",
            "code": "log_symbol_not_in_bars",
            "message": f"{len(unknown_symbols)} 个序列在日志里但不在 K 线里：{unknown_symbols[:5]}",
            "hint": "这些标的无法对齐，会被忽略",
        })

    field_gaps: Dict[str, Dict[str, int]] = {}
    for rec in records:
        kind = rec["kind"]
        spec = KIND_FIELDS[kind]
        # 退出类计划只携带退出信息，不要求入场字段（wait_bars / entry_price）。
        if kind == "plan" and str(rec.get("plan", "enter")) == "exit":
            spec = {"required": spec["required"],
                    "recommended": [f for f in spec["recommended"]
                                    if f in ("exit_time", "exit_reason")]}
        missing_required = [f for f in spec["required"] if f not in rec]
        if missing_required:
            issues.append({
                "severity": "error",
                "code": "missing_required_field",
                "message": f"{kind} 记录缺必需字段：{missing_required}",
                "hint": "必需字段缺失会使该记录无法参与对齐",
            })
        missing_recommended = [f for f in spec["recommended"] if f not in rec]
        if missing_recommended:
            bucket = field_gaps.setdefault(kind, {})
            for field in missing_recommended:
                bucket[field] = bucket.get(field, 0) + 1

    for kind, gaps in field_gaps.items():
        issues.append({
            "severity": "warn",
            "code": "missing_recommended_field",
            "message": f"{kind} 有记录缺推荐字段：{gaps}",
            "hint": "对应轴会退化为不可比（match_rate=null），不会编造一致",
        })

    counts: Dict[str, int] = {}
    for rec in records:
        counts[rec["kind"]] = counts.get(rec["kind"], 0) + 1
    for kind in data_loader.LOG_KINDS:
        if counts.get(kind, 0) == 0:
            issues.append({
                "severity": "warn",
                "code": "missing_log_kind",
                "message": f"日志中没有任何 {kind} 记录",
                "hint": f"{kind} 轴将全部为单边缺失",
            })

    errors = [i for i in issues if i["severity"] == "error"]
    return {
        "ok": not errors,
        "stage": "complete",
        "bars": {
            "symbol_count": len(bars),
            "bar_count": sum(lengths.values()),
            "min_bars": min(lengths.values()) if lengths else 0,
            "max_bars": max(lengths.values()) if lengths else 0,
        },
        "logs": {"record_count": len(records), "by_kind": counts},
        "issues": issues,
    }


def main(argv: List[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Validate JEV replay input contract")
    parser.add_argument("--bars-dir", default=str(REPO_ROOT / "fixtures" / "bars"))
    parser.add_argument("--logs-dir", default=str(REPO_ROOT / "fixtures" / "logs"))
    args = parser.parse_args(argv)

    result = validate(Path(args.bars_dir), Path(args.logs_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())