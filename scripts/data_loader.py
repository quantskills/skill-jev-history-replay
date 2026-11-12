"""只读的行情与日志加载。

两个数据面：
- bars：历史分钟 K 线，一行一根，含 open/high/low/close/volume；
- logs：JEV 侧"条件命中 / 信号 / 计划 / 成交回执"记录。

两者都只读。加载器不做任何语义推断——时间戳代表什么、涨幅对谁算，
全部交给 semantics 层显式声明。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


class LoadError(ValueError):
    """数据加载失败（缺文件 / 空数据 / 字段错误）。"""

    def __init__(self, code: str, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


BAR_REQUIRED = ("symbol", "datetime", "open", "high", "low", "close")
LOG_REQUIRED = ("ts", "kind", "symbol")

LOG_KINDS = ("condition", "signal", "plan", "fill")


def _coerce_float(value: Any, field: str, ctx: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise LoadError("invalid_bar_field", f"{ctx}: 字段 {field} 不是数值：{value!r}") from exc
    return out


def _normalize_time(raw: Any, ctx: str) -> str:
    """把 09:31 / 093100 / 09:31:00 / 2025-11-10 09:31:00 统一成 HH:MM。"""
    text = str(raw).strip()
    if not text:
        raise LoadError("invalid_bar_field", f"{ctx}: datetime 为空")
    if " " in text:
        text = text.split(" ")[-1]
    if "T" in text:
        text = text.split("T")[-1]
    if ":" in text:
        parts = text.split(":")
    elif len(text) == 6 and text.isdigit():
        parts = [text[0:2], text[2:4], text[4:6]]
    elif len(text) == 4 and text.isdigit():
        parts = [text[0:2], text[2:4], "00"]
    else:
        raise LoadError("invalid_bar_field", f"{ctx}: 无法解析时间 {raw!r}")
    if len(parts) < 2:
        raise LoadError("invalid_bar_field", f"{ctx}: 无法解析时间 {raw!r}")
    hour = int(parts[0])
    minute = int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise LoadError("invalid_bar_field", f"{ctx}: 时间越界 {raw!r}")
    return f"{hour:02d}:{minute:02d}"


def minutes_of(time_text: str) -> int:
    """HH:MM → 当日分钟序号，便于窗口比较。"""
    hour, minute = time_text.split(":")
    return int(hour) * 60 + int(minute)


def _read_text(path: Path) -> str:
    """读文本；.gz 透明解压，便于随仓库发布大夹具。"""
    if path.suffix == ".gz":
        import gzip

        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    return path.read_text(encoding="utf-8")


def _list_data_files(base: Path) -> List[Path]:
    """收集 .json / .jsonl / .json.gz / .jsonl.gz，跳过 .DS_Store 之类。"""
    out = []
    for path in sorted(base.iterdir()):
        if not path.is_file():
            continue
        name = path.name
        if name.endswith((".json", ".jsonl", ".json.gz", ".jsonl.gz")):
            out.append(path)
    return out


def _read_json_records(path: Path) -> List[Dict[str, Any]]:
    """支持 .json（单个对象 / 数组 / 含 records 键）与 .jsonl，均可 gzip。"""
    text = _read_text(path)
    if path.name.endswith(".jsonl") or path.name.endswith(".jsonl.gz"):
        records: List[Dict[str, Any]] = []
        for lineno, line in enumerate(text.splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise LoadError(
                    "invalid_json", f"{path.name}:{lineno} 不是合法 JSON：{exc}"
                ) from exc
        return records

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LoadError("invalid_json", f"{path}: 不是合法 JSON：{exc}") from exc
    if isinstance(payload, dict) and "records" in payload:
        payload = payload["records"]
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return payload
    raise LoadError("invalid_json", f"{path}: 顶层必须是对象、数组或含 records 的对象")


def load_bars(bars_dir: str | Path) -> Dict[str, Dict[str, Any]]:
    """按标的分组载入分钟线。

    Returns:
        {symbol: {"date": str, "bars": [bar, ...]}}，bars 已按时间升序。
        每个 bar: {"time": "HH:MM", "minute": int, "open", "high", "low", "close", "volume"}
    """
    base = Path(bars_dir)
    if not base.exists():
        raise LoadError(
            "bars_dir_not_found",
            f"K线目录不存在：{bars_dir}",
            hint="先运行 scripts/fetch_data.py 拉取，或指向已有 fixtures/bars",
        )
    files = _list_data_files(base)
    if not files:
        raise LoadError(
            "bars_empty",
            f"K线目录下没有 .json/.jsonl/.json.gz：{bars_dir}",
            hint="检查目录内容",
        )

    grouped: Dict[str, Dict[str, Any]] = {}
    for path in files:
        for idx, rec in enumerate(_read_json_records(path)):
            ctx = f"{path.name}[{idx}]"
            missing = [f for f in BAR_REQUIRED if f not in rec]
            if missing:
                raise LoadError("missing_bar_field", f"{ctx} 缺字段：{missing}")
            symbol = str(rec["symbol"]).strip()
            if not symbol:
                raise LoadError("invalid_bar_field", f"{ctx}: symbol 为空")
            time_text = _normalize_time(rec["datetime"], ctx)
            bar = {
                "time": time_text,
                "minute": minutes_of(time_text),
                "open": _coerce_float(rec["open"], "open", ctx),
                "high": _coerce_float(rec["high"], "high", ctx),
                "low": _coerce_float(rec["low"], "low", ctx),
                "close": _coerce_float(rec["close"], "close", ctx),
                "volume": float(rec.get("volume") or 0.0),
            }
            if bar["high"] < bar["low"]:
                raise LoadError("invalid_bar_field", f"{ctx}: high < low")
            if bar["close"] <= 0 or bar["open"] <= 0:
                raise LoadError("invalid_bar_field", f"{ctx}: 价格必须为正")
            entry = grouped.setdefault(
                symbol,
                {"date": str(rec.get("date") or ""), "bars": [], "_seen": set()},
            )
            if time_text in entry["_seen"]:
                raise LoadError(
                    "duplicate_bar",
                    f"{symbol} 在 {time_text} 出现重复 K 线（{path.name}）",
                    hint="同一标的同一分钟只应有一根；检查是否混入了多日或多源文件",
                )
            entry["_seen"].add(time_text)
            entry["bars"].append(bar)

    for symbol, entry in grouped.items():
        entry.pop("_seen", None)
        entry["bars"].sort(key=lambda b: b["minute"])
        if not entry["bars"]:
            raise LoadError("bars_empty", f"{symbol} 没有任何 K 线")
    if not grouped:
        raise LoadError("bars_empty", f"没有解析到任何 K 线：{bars_dir}")
    return grouped


def load_logs(logs_dir: str | Path) -> List[Dict[str, Any]]:
    """载入 JEV 日志记录，按 (symbol, 时间, 原始顺序) 返回。

    记录结构（全部字段见 references/log_contract.md）：
        {"ts": "HH:MM", "kind": "condition"|"signal"|"plan"|"fill",
         "symbol": str, "hit": bool, "signal": str, ...}
    """
    base = Path(logs_dir)
    if not base.exists():
        raise LoadError("logs_dir_not_found", f"日志目录不存在：{logs_dir}")
    files = _list_data_files(base)
    if not files:
        raise LoadError("logs_empty", f"日志目录下没有 .json/.jsonl/.json.gz：{logs_dir}")

    records: List[Dict[str, Any]] = []
    for path in files:
        for idx, rec in enumerate(_read_json_records(path)):
            ctx = f"{path.name}[{idx}]"
            missing = [f for f in LOG_REQUIRED if f not in rec]
            if missing:
                raise LoadError("missing_log_field", f"{ctx} 缺字段：{missing}")
            kind = str(rec["kind"])
            if kind not in LOG_KINDS:
                raise LoadError(
                    "invalid_log_kind",
                    f"{ctx}: kind={kind!r}，允许 {list(LOG_KINDS)}",
                )
            norm = dict(rec)
            norm["ts"] = _normalize_time(rec["ts"], ctx)
            norm["minute"] = minutes_of(norm["ts"])
            norm["symbol"] = str(rec["symbol"]).strip()
            norm["_source_file"] = path.name
            norm["_source_index"] = idx
            records.append(norm)

    records.sort(key=lambda r: (r["symbol"], r["minute"], r["_source_index"]))
    return records


def normalize_log_records(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """给日志记录补 minute / 排序键。合成日志与真实日志走同一条规范化路径，
    避免"合成走一条、真实走另一条"造成两套语义。"""
    out: List[Dict[str, Any]] = []
    for idx, rec in enumerate(records):
        missing = [f for f in LOG_REQUIRED if f not in rec]
        if missing:
            raise LoadError("missing_log_field", f"记录 {idx} 缺字段：{missing}")
        kind = str(rec["kind"])
        if kind not in LOG_KINDS:
            raise LoadError(
                "invalid_log_kind", f"记录 {idx}: kind={kind!r}，允许 {list(LOG_KINDS)}"
            )
        norm = dict(rec)
        norm["ts"] = _normalize_time(rec["ts"], f"record[{idx}]")
        norm["minute"] = minutes_of(norm["ts"])
        norm["symbol"] = str(rec["symbol"]).strip()
        norm.setdefault("_source_file", "<synthetic>")
        norm.setdefault("_source_index", idx)
        out.append(norm)
    out.sort(key=lambda r: (r["symbol"], r["minute"], r["_source_index"]))
    return out


def group_logs(records: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """按 symbol → kind 分组，每组按时间排序。"""
    out: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for rec in records:
        per_symbol = out.setdefault(rec["symbol"], {k: [] for k in LOG_KINDS})
        per_symbol[rec["kind"]].append(rec)
    for per_symbol in out.values():
        for kind_list in per_symbol.values():
            kind_list.sort(key=lambda r: (r["minute"], r["_source_index"]))
    return out