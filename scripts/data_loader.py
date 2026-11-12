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

# A 股午休：11:30 收市，13:00/13:01 复市。缺口检测必须排除这段，
# 否则每条序列都会报一个假缺口。
LUNCH_BREAK = (11 * 60 + 30, 13 * 60 + 1)


def find_gaps(bars: List[Dict[str, Any]],
              lunch_break: tuple[int, int] = LUNCH_BREAK) -> List[Dict[str, Any]]:
    """找出序列中的分钟缺口（排除午休）。

    为什么重要：重放器按「根数」计算 breakout_window / max_hold_bars /
    bars_to_entry。若序列有缺口，10 分钟的空档会被当成 0 根，
    窗口和持有期语义都会失真——而且**不会报错**，只是静默算错。
    """
    gaps: List[Dict[str, Any]] = []
    for prev, cur in zip(bars, bars[1:]):
        step = cur["minute"] - prev["minute"]
        if step == 1:
            continue
        if prev["minute"] == lunch_break[0] and cur["minute"] == lunch_break[1]:
            continue
        gaps.append({
            "after": prev["time"],
            "before": cur["time"],
            "missing_minutes": step - 1,
            "missing_bars": step - 1,
        })
    return gaps
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


def series_key(symbol: str, date: str) -> str:
    """多日夹具的序列键。

    单日夹具沿用裸代码（`600519.SH`），多日夹具用 `600519.SH@20261112`。
    这样下游（重放/对齐/归因）无需感知日期，又能保证不同交易日的
    同一分钟不会被误判成重复 K 线。
    """
    return f"{symbol}@{date}" if date else symbol


def load_bars(bars_dir: str | Path) -> Dict[str, Dict[str, Any]]:
    """按 (标的, 交易日) 分组载入分钟线。

    Returns:
        {series_key: {"symbol": str, "date": str, "bars": [bar, ...]}}，bars 按时间升序。
        每个 bar: {"time": "HH:MM", "minute": int, "open", "high", "low", "close", "volume"}

    单日夹具只有一个日期时，key 等于裸标的代码；存在多个交易日时
    key 为 `symbol@date`，避免跨日同分钟被误判为重复。
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
    return load_bars_files(files)


def load_bars_files(files: List[Path]) -> Dict[str, Dict[str, Any]]:
    """从显式文件列表载入分钟线（供单日构建等精确场景使用）。"""
    grouped: Dict[str, Dict[str, Any]] = {}
    for path in files:
        for idx, rec in enumerate(_read_json_records(path)):
            ctx = f"{path.name}[{idx}]"
            missing = [f for f in BAR_REQUIRED if f not in rec]
            if missing:
                raise LoadError("missing_bar_field", f"{ctx} 缺字段：{missing}")
            symbol = str(rec["symbol"]).strip().upper()
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
            date_text = str(rec.get("date") or "")
            entry = grouped.setdefault(
                (symbol, date_text),
                {"symbol": symbol, "date": date_text, "bars": [], "_seen": set()},
            )
            if time_text in entry["_seen"]:
                raise LoadError(
                    "duplicate_bar",
                    f"{symbol} 在 {date_text or '当日'} {time_text} 出现重复 K 线（{path.name}）",
                    hint="同一标的、同一交易日、同一分钟只应有一根",
                )
            entry["_seen"].add(time_text)
            entry["bars"].append(bar)

    dates = {key[1] for key in grouped if key[1]}
    multi_day = len(dates) > 1
    out: Dict[str, Dict[str, Any]] = {}
    for (symbol, date_text), entry in grouped.items():
        entry.pop("_seen", None)
        entry["bars"].sort(key=lambda b: b["minute"])
        if not entry["bars"]:
            raise LoadError("bars_empty", f"{series_key(symbol, date_text)} 没有任何 K 线")
        out[series_key(symbol, date_text) if multi_day else symbol] = entry
    if not out:
        raise LoadError("bars_empty", f"没有解析到任何 K 线：{bars_dir}")
    return out


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
            # 代码统一大写：真实日志里 `000001.sz` 与 K 线的 `000001.SZ` 必须能对上。
            # 不归一的话，日志会全部变成 jev_missing、一致率显示 null，
            # 而报告看不出真正原因是大小写——一个非常隐蔽的"完全对不上"。
            norm["symbol"] = str(rec["symbol"]).strip().upper()
            norm["_source_file"] = path.name
            norm["_source_index"] = idx
            records.append(norm)

    records.sort(key=lambda r: (r["symbol"], r["minute"], r["_source_index"]))
    return records


def normalize_log_records(records: List[Dict[str, Any]],
                         multi_day: bool = False,
                         default_date: str = "") -> List[Dict[str, Any]]:
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
        symbol = str(rec["symbol"]).strip().upper()
        date_text = str(rec.get("date") or default_date or "")
        if multi_day:
            if not date_text:
                raise LoadError(
                    "missing_log_field",
                    f"记录 {idx} 在多日模式下缺 date 字段，无法归属到具体交易日",
                    hint="多日夹具的日志记录必须带 date（YYYYMMDD）",
                )
            norm["series"] = series_key(symbol, date_text)
        else:
            norm["series"] = symbol
        norm["symbol"] = symbol
        norm["date"] = date_text
        norm.setdefault("_source_file", "<synthetic>")
        norm.setdefault("_source_index", idx)
        out.append(norm)
    out.sort(key=lambda r: (r["series"], r["minute"], r["_source_index"]))
    return out


def group_logs(records: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
    """按 symbol → kind 分组，每组按时间排序。"""
    out: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for rec in records:
        per_symbol = out.setdefault(rec.get("series") or rec["symbol"],
                                    {k: [] for k in LOG_KINDS})
        per_symbol[rec["kind"]].append(rec)
    for per_symbol in out.values():
        for kind_list in per_symbol.values():
            kind_list.sort(key=lambda r: (r["minute"], r["_source_index"]))
    return out