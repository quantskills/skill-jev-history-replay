"""外部日志适配：把真实 JEV 日志的字段映射到本 skill 的日志契约。

真实系统的字段名几乎不会和 `log_contract.md` 完全一致——成交价可能叫
`price`、方向可能叫 `side`、标的可能叫 `code`。本模块把这些差异
**显式声明**，而不是靠猜或靠静默丢弃。

设计原则：
  1. 映射必须写在配置里，不接受隐式猜测；
  2. 映射后仍缺必需字段 → 直接报错，不让它带着缺陷进入对齐；
  3. 未映射的字段原样保留，不丢弃（便于追溯）。

用法：
    python3 scripts/adapt_logs.py --src raw/ --dst adapted/ \\
        --map-example

    # 或在 Python 里：
    from scripts.adapt_logs import adapt_records
    adapted = adapt_records(records, mapping={...})
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import data_loader  # noqa: E402

# 每个 kind 需要的字段（与 log_contract.md 一致）
REQUIRED = {
    "condition": ["ts", "kind", "symbol", "hit"],
    "signal": ["ts", "kind", "symbol", "signal"],
    "plan": ["ts", "kind", "symbol", "plan"],
    "fill": ["ts", "kind", "symbol", "side"],
}

# 常见的外部字段名 → 契约字段名。只映射语义明确的同义词。
COMMON_ALIASES: Dict[str, str] = {
    "time": "ts",
    "timestamp": "ts",
    "datetime": "ts",
    "at": "ts",
    "code": "symbol",
    "ticker": "symbol",
    "instrument": "symbol",
    "type": "kind",
    "event": "kind",
    "record_type": "kind",
    "matched": "hit",
    "triggered": "hit",
    "is_hit": "hit",
    "condition_hit": "hit",
    "direction": "signal",
    "action": "signal",
    "side": "signal",
    "order_side": "side",
    "fill_price": "price",
    "deal_price": "price",
}

EXAMPLE_MAPPING = {
    "_comment": "按实际日志调整：左边是对方字段名，右边是本 skill 契约字段名",
    "condition": {
        "timestamp": "ts",
        "code": "symbol",
        "matched": "hit",
    },
    "signal": {
        "time": "ts",
        "ticker": "symbol",
        "action": "signal",
    },
    "plan": {
        "time": "ts",
        "code": "symbol",
        "fill_price": "entry_price",
    },
    "fill": {
        "time": "ts",
        "code": "symbol",
        "direction": "side",
    },
}


class AdaptError(ValueError):
    def __init__(self, code: str, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


def _apply_mapping(rec: Dict[str, Any], mapping: Dict[str, str]) -> Dict[str, Any]:
    """按映射重命名字段。已存在目标字段时不覆盖（原字段优先）。"""
    out = dict(rec)
    for src, dst in mapping.items():
        if src in out and dst not in out:
            out[dst] = out[src]
    return out


def adapt_records(records: List[Dict[str, Any]],
                  mapping: Dict[str, Dict[str, str]] | None = None,
                  use_common_aliases: bool = True) -> Dict[str, Any]:
    """把外部记录适配成契约格式。

    Args:
        records: 原始记录
        mapping: {"condition": {对方字段: 契约字段}, ...}（按 kind 细化）
        use_common_aliases: 是否附加通用同义词映射（在按 kind 的映射之后应用，
                            优先级更低）

    Returns:
        {"ok": bool, "records": [...], "errors": [...], "renamed": {...}}
    """
    mapping = mapping or {}
    out: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    renamed: Dict[str, int] = {}

    for idx, rec in enumerate(records):
        kind = str(rec.get("kind") or rec.get("type") or rec.get("event") or "").strip()
        # 先按 kind 映射（需要知道 kind，所以先粗取一次）
        per_kind = mapping.get(kind, {}) if kind else {}
        adapted = _apply_mapping(rec, per_kind)
        if use_common_aliases:
            adapted = _apply_mapping(adapted, COMMON_ALIASES)

        for src, dst in {**COMMON_ALIASES, **per_kind}.items():
            if src in rec and dst in adapted and rec.get(src) == adapted.get(dst):
                renamed[f"{src}→{dst}"] = renamed.get(f"{src}→{dst}", 0) + 1

        # 布尔字段规范化：1/0、"true"/"false" 都要变成真正的 bool。
        # 否则下游 bool("false") == True，会把"没命中"读成"命中"。
        if "hit" in adapted:
            raw_hit = adapted["hit"]
            if isinstance(raw_hit, str):
                adapted["hit"] = raw_hit.strip().lower() in ("1", "true", "yes", "y")
            else:
                adapted["hit"] = bool(raw_hit)

        k = str(adapted.get("kind") or "").strip()
        if k not in REQUIRED:
            errors.append({
                "index": idx,
                "code": "unknown_kind",
                "message": f"kind={k!r} 不在 {list(REQUIRED)} 内",
                "record": rec,
            })
            continue
        missing = [f for f in REQUIRED[k] if f not in adapted]
        if missing:
            errors.append({
                "index": idx,
                "code": "missing_required_field",
                "message": f"{k} 记录适配后仍缺必需字段：{missing}",
                "hint": "在 mapping 里补充该字段的映射",
                "record": rec,
            })
            continue
        out.append(adapted)

    return {
        "ok": not errors,
        "records": out,
        "errors": errors,
        "renamed": renamed,
        "input_count": len(records),
        "output_count": len(out),
    }


def adapt_dir(src: Path, dst: Path,
              mapping: Dict[str, Dict[str, str]] | None = None) -> Dict[str, Any]:
    """适配整个目录，逐文件写出。任何一条记录失败即整体失败。"""
    files = data_loader._list_data_files(src)
    if not files:
        raise AdaptError("logs_empty", f"{src} 下没有日志文件")

    dst.mkdir(parents=True, exist_ok=True)
    total_in = total_out = 0
    all_errors: List[Dict[str, Any]] = []

    for path in files:
        raw = data_loader._read_json_records(path)
        result = adapt_records(raw, mapping)
        total_in += result["input_count"]
        total_out += result["output_count"]
        all_errors.extend(result["errors"])
        if result["ok"]:
            stem = path.name
            for suffix in (".jsonl.gz", ".json.gz", ".jsonl", ".json"):
                if stem.endswith(suffix):
                    stem = stem[: -len(suffix)]
                    break
            out_path = dst / f"{stem}.jsonl"
            out_path.write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in result["records"]) + "\n",
                encoding="utf-8",
            )

    return {
        "ok": not all_errors,
        "input_count": total_in,
        "output_count": total_out,
        "error_count": len(all_errors),
        "errors": all_errors[:20],
        "output_dir": str(dst),
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Adapt external JEV logs to the contract")
    parser.add_argument("--src", help="原始日志目录")
    parser.add_argument("--dst", help="适配后输出目录")
    parser.add_argument("--mapping", help="映射 JSON 文件路径")
    parser.add_argument("--map-example", action="store_true",
                        help="打印映射模板后退出")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.map_example:
        print(json.dumps(EXAMPLE_MAPPING, ensure_ascii=False, indent=2))
        return 0

    if not args.src or not args.dst:
        print(json.dumps({
            "ok": False,
            "error": {"code": "missing_args",
                      "message": "需要 --src 与 --dst",
                      "hint": "先用 --map-example 看映射模板"},
        }, ensure_ascii=False, indent=2))
        return 2

    mapping = None
    if args.mapping:
        mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8"))

    try:
        result = adapt_dir(Path(args.src), Path(args.dst), mapping)
    except AdaptError as exc:
        print(json.dumps({"ok": False, "error": {
            "code": exc.code, "message": exc.message, "hint": exc.hint}},
            ensure_ascii=False, indent=2))
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"输入 {result['input_count']} 条 → 输出 {result['output_count']} 条")
        if result["errors"]:
            print(f"失败 {result['error_count']} 条：")
            for e in result["errors"][:5]:
                print(f"  [{e['code']}] {e['message']}")
        print("OK" if result["ok"] else "FAILED")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())