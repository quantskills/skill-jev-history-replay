"""行情拉取（离线夹具生成阶段）。

只在**生成夹具**时调用 `panda_data`；对齐与回放执行阶段只读本地 JSON，
不访问任何外部服务，也不需要凭证。这与本库评测类 skill 的范围边界一致。

用法：
    python3 scripts/fetch_data.py --date 20261112 --symbols 600519.SH 000001.SZ
    python3 scripts/fetch_data.py --date 20261112 --symbols-file symbols.txt

输出：
    fixtures/bars/{date}.json      分钟 K 线，一行一根
    fixtures/reference/{date}.json 每标的的 prev_close / open / high / low / close
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
# 直接 `python3 scripts/fetch_data.py` 时，sys.path[0] 是 scripts/ 而不是仓库根，
# `from scripts.credentials import ...` 会 ModuleNotFoundError。
# 其他脚本都有这行，本文件曾漏掉——只有真正调用凭证时才暴露。
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

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


class FetchError(RuntimeError):
    def __init__(self, code: str, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


def _env(primary: str, fallback: str) -> str:
    """从环境变量或 ~/.pandadata/pandadata.env 取值（去除包裹引号）。"""
    import os

    from scripts.credentials import FIELDS, load

    values = load()
    for name, names in FIELDS.items():
        if primary in names or fallback in names:
            return values.get(name, "")
    return os.environ.get(primary) or os.environ.get(fallback) or ""


def _client() -> Any:
    try:
        import panda_data  # type: ignore[import-not-found]
    except ImportError as exc:
        raise FetchError(
            "missing_dependency",
            "缺少 panda_data 依赖",
            hint="pip install -r requirements.txt（仅夹具生成需要）",
        ) from exc

    username = _env("PANDA_DATA_USERNAME", "DEFAULT_USERNAME")
    zinfoid = _env("PANDA_DATA_PASSWORD", "DEFAULT_PASSWORD")
    base_url = _env("PANDA_DATA_BASE_URL", "JAVA_SERVICE_BASE_URL")
    if not all([username, zinfoid, base_url]):
        raise FetchError(
            "missing_credentials",
            "缺少 PandaData 凭证（PANDA_DATA_USERNAME / PANDA_DATA_PASSWORD / PANDA_DATA_BASE_URL）",
            hint="写入 ~/.pandadata/pandadata.env 或 export 环境变量",
        )
    # SDK 的网络/认证异常必须转成结构化 FetchError，否则 CLI 会直接吐
    # 几十行 traceback，读者拿不到可操作的提示。实测：base_url 指到不存在的
    # 主机时，init_token 抛原始 ServiceError("Network error: ...")。
    try:
        panda_data.init_token(username=username, password=zinfoid,
                              base_url=base_url)
    except Exception as exc:  # noqa: BLE001 - SDK 异常类型不稳定，统一兜住
        raise FetchError(
            "auth_request_failed",
            f"PandaData 登录请求失败：{exc}",
            hint=("检查 PANDA_DATA_BASE_URL 是否可达、网络是否正常；"
                  "凭证过期也会表现为登录失败"),
        ) from exc
    try:
        authenticated = panda_data.is_authenticated()
    except Exception as exc:  # noqa: BLE001
        raise FetchError("auth_check_failed", f"PandaData 登录状态检查失败：{exc}") from exc
    if not authenticated:
        raise FetchError("auth_failed", "PandaData 登录失败",
                         hint="凭证可能已过期，请重新获取")
    return panda_data


def fetch(date: str, symbols: List[str], out_dir: Path, ref_dir: Path) -> Dict[str, Any]:
    client = _client()

    try:
        bars = client.get_stock_min(
            symbol=symbols,
            start_date=date,
            end_date=date,
            fields=["symbol", "datetime", "open", "high", "low", "close",
                    "volume", "amount"],
        )
    except Exception as exc:  # noqa: BLE001 - SDK 网络异常统一兜住
        raise FetchError(
            "fetch_failed",
            f"拉取 {date} 分钟线失败：{exc}",
            hint="检查网络与服务地址；已有夹具不受影响，重试即可",
        ) from exc
    if bars is None or len(bars) == 0:
        raise FetchError(
            "no_data",
            f"{date} 没有分时数据",
            hint="确认是否交易日；非交易日返回空表属于正常",
        )

    prev_date = None
    try:
        probe = client.get_prev_trade_date(date=date, exchange="SH", n=1)
        if probe:
            prev_date = str(probe).strip() or None
    except Exception:  # 交易日历不可用不阻断主流程
        prev_date = None

    try:
        daily = client.get_stock_daily(
            symbol=symbols,
            start_date=prev_date or date,
            end_date=date,
            fields=["symbol", "date", "open", "high", "low", "close", "pre_close"],
        )
    except Exception as exc:  # noqa: BLE001
        raise FetchError(
            "fetch_failed",
            f"拉取 {date} 日线/前收失败：{exc}",
            hint="分钟线可能已写入；重试会覆盖，无需手动清理",
        ) from exc
    reference: Dict[str, Any] = {}
    if daily is not None and len(daily) > 0:
        for _, row in daily.iterrows():
            symbol = str(row["symbol"])
            ref = reference.setdefault(symbol, {})
            ref[str(row["date"])] = {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "pre_close": float(row["pre_close"]) if row.get("pre_close") == row.get("pre_close") else None,
            }

    records = []
    for _, row in bars.iterrows():
        records.append({
            "symbol": str(row["symbol"]),
            "date": str(row["date"]),
            "datetime": str(row["datetime"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]),
            "amount": float(row["amount"]),
        })
    records.sort(key=lambda r: (r["symbol"], r["datetime"]))

    out_dir.mkdir(parents=True, exist_ok=True)
    ref_dir.mkdir(parents=True, exist_ok=True)
    bars_path = out_dir / f"{date}.json"
    ref_path = ref_dir / f"{date}.json"
    bars_path.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
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
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch minute bars for JEV replay fixtures")
    parser.add_argument("--date", required=True, help="交易日 YYYYMMDD")
    parser.add_argument("--symbols", nargs="*", default=None, help="标的列表，默认内置 8 只")
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
    symbols = symbols or DEFAULT_SYMBOLS

    try:
        info = fetch(args.date, symbols, Path(args.out_dir), Path(args.ref_dir))
    except FetchError as exc:
        print(json.dumps(
            {"ok": False, "error": {"code": exc.code, "message": exc.message, "hint": exc.hint}},
            ensure_ascii=False, indent=2,
        ), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, **info}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())