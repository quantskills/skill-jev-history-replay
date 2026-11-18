"""行情落盘（离线夹具生成阶段）。

取数由**阅读本方 skill 的 AI** 通过 PandaData MCP 工具完成：

    mcp__pandadata__auth_status
    mcp__pandadata__search_methods
    mcp__pandadata__get_method_doc
    mcp__pandadata__call_pandadata   ← 真正取数

脚本本身不联网、不读凭证、不含任何取数客户端。它只消费 agent
按约定落盘的 JSON（目录结构见 `scripts/mcp_source.py` 与
`references/data_access.md`），转换成夹具格式。

对齐与回放执行阶段只读本地 JSON，不访问任何外部服务。

用法：
    # agent 已把 MCP 结果落到 /tmp/mcp-20261112/
    python3 scripts/fetch_data.py --date 20261112 --from-mcp /tmp/mcp-20261112
    python3 scripts/fetch_data.py --date 20261112 --from-mcp /tmp/mcp \\
        --symbols 600519.SH 000001.SZ

输出（结构固定，下游 data_loader / replayer 依赖）：
    fixtures/bars/{date}.json      分钟 K 线，一行一根
    fixtures/reference/{date}.json 每标的的 prev_close / open / high / low / close
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
# 直接 `python3 scripts/fetch_data.py` 时，sys.path[0] 是 scripts/ 而不是仓库根，
# `from scripts.mcp_source import ...` 会 ModuleNotFoundError。只在真正取数时暴露。
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.mcp_source import (  # noqa: E402
    DAILY_COLUMNS,
    MCPDataError,
    MCPSource,
    MIN_COLUMNS,
)

DEFAULT_SYMBOLS = [
    "600519.SH",  # 贵州茅台
    "000001.SZ",  # 平安银行
    "000858.SZ",  # 五粮液
    "002594.SZ",  # 比亚迪
    "300750.SZ",  # 宁德时代
    "600036.SH",  # 招商银行
    "601318.SH",  # 中国平安
    "688981.SH",  # 中芯国际
]

# 向后兼容：旧代码（以及下游调用方）按这个名字捕获结构化错误。
FetchError = MCPDataError


def _float_or_none(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def _group_daily(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """按 symbol → date → OHLC 组织日线行。"""
    reference: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        symbol = str(row["symbol"]).strip()
        date_text = str(row["date"]).strip()
        pre_close = row.get("pre_close")
        reference.setdefault(symbol, {})[date_text] = {
            "open": _float_or_none(row.get("open")),
            "high": _float_or_none(row.get("high")),
            "low": _float_or_none(row.get("low")),
            "close": _float_or_none(row.get("close")),
            "pre_close": _float_or_none(pre_close),
        }
    return reference


def load_from_mcp(date: str, symbols: Optional[List[str]],
                  mcp_dir: Path) -> Dict[str, Any]:
    """从落盘的 MCP 结果读取一天的分钟线与日线/前收，不写文件。"""
    source = MCPSource(mcp_dir)

    bars = source.dataframe("get_stock_min", date=date, required=MIN_COLUMNS)
    wanted = {s.strip() for s in symbols} if symbols else None
    if wanted is not None:
        bars = [r for r in bars if str(r.get("symbol", "")).strip() in wanted]
        if not bars:
            raise MCPDataError(
                "symbols_not_in_data",
                f"{date} 的分钟线里没有任何请求的标的：{sorted(wanted)[:8]}",
                hint="核对 agent 取数时传的 symbol 列表与落盘目录是否一致",
            )

    # 前收：缺 get_prev_trade_date 时仍可继续，reference 里记 null。
    prev_date = source.prev_trade_date(date)

    daily_rows = source.dataframe(
        "get_stock_daily", date=date, required=DAILY_COLUMNS)
    if wanted is not None:
        daily_rows = [r for r in daily_rows
                      if str(r.get("symbol", "")).strip() in wanted]
    reference = _group_daily(daily_rows)

    records: List[Dict[str, Any]] = []
    for row in bars:
        records.append({
            "symbol": str(row["symbol"]).strip(),
            "date": str(row.get("date") or date).strip(),
            "datetime": str(row["datetime"]).strip(),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row.get("volume") or 0.0),
            "amount": float(row.get("amount") or 0.0),
        })
    records.sort(key=lambda r: (r["symbol"], r["datetime"]))

    missing_ref = sorted({r["symbol"] for r in records} - set(reference))
    return {
        "records": records,
        "reference": reference,
        "prev_date": prev_date,
        "missing_reference": missing_ref,
    }


def fetch(date: str, symbols: Optional[List[str]], out_dir: Path,
          ref_dir: Path, mcp_dir: Optional[Path] = None) -> Dict[str, Any]:
    """读取 MCP 落盘数据并写出夹具文件。"""
    if mcp_dir is None:
        raise MCPDataError(
            "missing_mcp_dir",
            "未指定 MCP 取数目录",
            hint=("先用 MCP 工具取数并落盘，再传 --from-mcp <dir>；"
                  "目录约定见 references/data_access.md"),
        )

    payload = load_from_mcp(date, symbols, Path(mcp_dir))
    records = payload["records"]
    reference = payload["reference"]
    prev_date = payload["prev_date"]

    out_dir.mkdir(parents=True, exist_ok=True)
    ref_dir.mkdir(parents=True, exist_ok=True)
    bars_path = out_dir / f"{date}.json"
    ref_path = ref_dir / f"{date}.json"
    bars_path.write_text(json.dumps(records, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    ref_path.write_text(
        json.dumps(
            {"date": date, "prev_date": prev_date, "symbols": reference},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    return {
        "bars_path": str(bars_path),
        "reference_path": str(ref_path),
        "bar_count": len(records),
        "symbol_count": len({r["symbol"] for r in records}),
        "prev_date": prev_date,
        "missing_reference": payload["missing_reference"],
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build JEV replay bar fixtures from MCP-fetched JSON")
    parser.add_argument("--date", required=True, help="交易日 YYYYMMDD")
    parser.add_argument("--from-mcp", required=True, dest="from_mcp",
                        help="agent 落盘 MCP 取数结果的目录")
    parser.add_argument("--symbols", nargs="*", default=None,
                        help="标的列表；省略则使用落盘文件里的全部标的")
    parser.add_argument("--symbols-file", default=None, help="每行一个标的")
    parser.add_argument("--out-dir", default=str(REPO_ROOT / "fixtures" / "bars"))
    parser.add_argument("--ref-dir", default=str(REPO_ROOT / "fixtures" / "reference"))
    args = parser.parse_args(argv)

    symbols = args.symbols
    if args.symbols_file:
        symbols = [
            line.strip()
            for line in Path(args.symbols_file).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]

    try:
        info = fetch(args.date, symbols, Path(args.out_dir), Path(args.ref_dir),
                     Path(args.from_mcp))
    except MCPDataError as exc:
        print(json.dumps(
            {"ok": False, "error": {"code": exc.code, "message": exc.message,
                                    "hint": exc.hint}},
            ensure_ascii=False, indent=2,
        ), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, **info}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())