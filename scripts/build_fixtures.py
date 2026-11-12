"""构建冻结夹具：拉取单日全市场分钟线 + 生成 JEV 模拟日志。

用法：
    python3 scripts/build_fixtures.py --date 20261112 --universe 400
    python3 scripts/build_fixtures.py --date 20261112 --symbols 600519.SH 000001.SZ

产物（均随仓库发布，确定性、可离线回放）：
    fixtures/bars/{date}.json            分钟 K 线
    fixtures/reference/{date}.json       前收 / 当日 OHLC
    fixtures/logs/{date}.jsonl           JEV 模拟日志（logged_profile 语义）
    fixtures/manifest.json               夹具指纹与生成参数

注意：日志是**模拟**的，不是 JEV 真实输出。真实日志到位后直接替换
fixtures/logs/ 即可，回放器与对齐器无需改动。
"""

from __future__ import annotations

import argparse
import gzip
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
from scripts import data_loader, log_synth, semantics as sem  # noqa: E402
from scripts.fetch_data import DEFAULT_SYMBOLS, FetchError, _client, fetch  # noqa: E402


def _pick_universe(client: Any, date: str, limit: int) -> List[str]:
    """单日抽样（保留供只构建一天时使用）。"""
    frame = client.get_trade_list(date=date, exchange="SH")
    if frame is None or len(frame) == 0:
        return list(DEFAULT_SYMBOLS)
    symbols = [str(s) for s in frame["symbol"].tolist()]
    # 确定性抽样：按代码排序后等距取，避免"只挑涨了的"造成选择偏差
    symbols.sort()
    if len(symbols) <= limit:
        return symbols
    step = len(symbols) / limit
    return [symbols[int(i * step)] for i in range(limit)]


def _pick_fixed_universe(client: Any, dates: List[str], limit: int) -> List[str]:
    """构造**全期固定**的标的池。

    为什么必须固定：跨日持仓的前提是同一只股票在相邻两个交易日都有数据。
    若每天各自按当日 trade_list 抽样，池子每天都在变（实测相邻日重合度
    最低只有 18.6%），昨天买的股票今天可能根本不在样本里——跨日逻辑
    形同虚设，T+1 相关结论也就失去基础。

    做法：取所有日期 trade_list 的**交集**（全期都能交易的标的），
    再按代码排序等距抽样。交集本身也保证了没有中途退市/停牌断档。
    """
    common: set[str] | None = None
    for date in dates:
        frame = client.get_trade_list(date=date, exchange="SH")
        if frame is None or len(frame) == 0:
            continue
        symbols = {str(s) for s in frame["symbol"].tolist()}
        common = symbols if common is None else (common & symbols)
    if not common:
        return list(DEFAULT_SYMBOLS)

    ordered = sorted(common)
    if len(ordered) <= limit:
        return ordered
    step = len(ordered) / limit
    return [ordered[int(i * step)] for i in range(limit)]


def _fingerprint(paths: List[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def build(date: str, symbols: List[str] | None, universe: int,
          profile: str) -> Dict[str, Any]:
    bars_dir = REPO_ROOT / "fixtures" / "bars"
    ref_dir = REPO_ROOT / "fixtures" / "reference"
    logs_dir = REPO_ROOT / "fixtures" / "logs"

    if symbols:
        selected = symbols
    else:
        client = _client()
        selected = _pick_universe(client, date, universe)

    info = fetch(date, selected, bars_dir, ref_dir)

    # 大夹具压成 .json.gz（回放器透明解压），避免仓库里放十几 MB 明文
    raw_bars_path = bars_dir / f"{date}.json"
    bars_gz_path = bars_dir / f"{date}.json.gz"
    # mtime=0：gzip 头默认写入当前时间，会让同一份数据每次重建产生不同的
    # 字节流，进而让 fixture_fingerprint 变化、"冻结基线"失去意义、
    # compare_baseline 无故报不可比。固定为 0 后输出才是确定性的。
    with open(raw_bars_path, "rb") as fh_in, \
            gzip.GzipFile(filename="", mode="wb", fileobj=open(bars_gz_path, "wb"), mtime=0) as fh_out:
        fh_out.write(fh_in.read())
    raw_bars_path.unlink()

    records: List[Dict[str, Any]] = []   # 日志由 generate_logs() 统一生成
    logs_path = logs_dir / f"{date}.jsonl"

    manifest = {
        "date": date,
        "prev_date": info.get("prev_date"),
        "symbol_count": info["symbol_count"],
        "bar_count": info["bar_count"],
        "log_record_count": 0,
        "logged_profile": profile,

        # fingerprint 只覆盖本函数产出的文件。日志由 generate_logs() 统一生成，
        # 此时可能还不存在——把它算进来会让单独调用 build() 时崩溃。
        "fixture_fingerprint": _fingerprint(
            [p for p in (bars_gz_path, ref_dir / f"{date}.json", logs_path) if p.exists()]
        ),
        "provenance": {
            "bars": "panda-data==1.0.6 get_stock_min / get_stock_daily，仅生成阶段调用",
            "logs": "synthetic：由 log_synth 按 logged_profile 生成，非 JEV 真实输出",
        },
    }
    (REPO_ROOT / "fixtures" / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def generate_logs(profile: str) -> Dict[str, Any]:
    """**所有交易日一起**跑一次重放，再按日期切分写日志。

    为什么必须全量：跨日持仓的退出发生在下一交易日。若逐日单独生成，
    生成当天时还看不到次日，所有周期都停在 open，退出记录永远是空的
    ——退出轴因此变成 0 可比。这是 v0.3.1 之前的真实缺陷。
    """
    bars_dir = REPO_ROOT / "fixtures" / "bars"
    ref_dir = REPO_ROOT / "fixtures" / "reference"
    logs_dir = REPO_ROOT / "fixtures" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    all_bars = data_loader.load_bars(bars_dir)
    if not all_bars:
        raise FetchError("bars_empty", f"{bars_dir} 没有可用的 K 线")

    from scripts.run_eval import _load_prev_closes

    prev_closes = _load_prev_closes(ref_dir, list(all_bars))
    config = cfg.load_config()
    logged = dict(config["semantics"])
    logged.update(sem.get_profile(profile))

    records = log_synth.synthesize_logs(all_bars, logged, prev_closes)
    per_date: Dict[str, List[Dict[str, Any]]] = {}
    for rec in records:
        per_date.setdefault(str(rec.get("date") or ""), []).append(rec)
    for date_text, rows in per_date.items():
        (logs_dir / f"{date_text}.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8",
        )

    return {
        "dates": sorted(per_date),
        "per_date": [{"date": d, "records": len(per_date[d])}
                     for d in sorted(per_date)],
        "total_records": len(records),
        "logged_profile": profile,
        "logged_semantics_hash": sem.semantics_hash(logged),
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build frozen JEV replay fixtures")
    parser.add_argument("--date", required=True,
                        help="交易日；多日用逗号分隔，如 20261110,20261111,20261112")
    parser.add_argument("--symbols", nargs="*", default=None)
    parser.add_argument("--universe", type=int, default=200)
    parser.add_argument("--logged-profile", default="jev_assumed",
                        choices=sorted(sem.PROFILES))
    args = parser.parse_args(argv)

    dates = [d.strip() for d in args.date.split(",") if d.strip()]
    try:
        # 多日构建必须用全期固定标的池，否则跨日持仓无从谈起
        selected = args.symbols
        if not selected:
            if len(dates) > 1:
                selected = _pick_fixed_universe(_client(), dates, args.universe)
                print(f"固定标的池：{len(selected)} 只（{dates[0]}–{dates[-1]} 全期可交易）")
            else:
                selected = None  # 单日仍走 build() 内部抽样

        manifests = [
            build(date, selected, args.universe, args.logged_profile)
            for date in dates
        ]
        # 数据拉完后统一生成一次日志（跨日持仓需要看到全部交易日）
        log_info = generate_logs(args.logged_profile)
        # 生成夹具时顺带审计未建模状态，写进 manifest 供报告回显。
        # 审计失败不阻断夹具生成。
        try:
            from scripts.data_quality_audit import audit as _audit
            dq = _audit(offline=False)
        except Exception as exc:
            dq = {"error": f"{type(exc).__name__}: {exc}"}

        manifest = manifests[0] if len(manifests) == 1 else {
            "dates": dates,
            "symbol_count": manifests[0]["symbol_count"],
            "bar_count": sum(m["bar_count"] for m in manifests),
            "log_record_count": log_info["total_records"],
            "logged_profile": args.logged_profile,
            "fixture_fingerprint": manifests[0]["fixture_fingerprint"],
            "per_date": log_info["per_date"],
            "logged_semantics_hash": log_info["logged_semantics_hash"],
            "data_quality": dq,
            "provenance": manifests[0]["provenance"],
        }
        # 必须落盘：`build()` 每构建一天都会写一次 manifest.json，
        # 多日时最后留下的是**单日**版本（bar_count 只有一天、log_record_count=0）。
        # 之前这里只 print 不写，导致仓库里的 manifest 长期描述的是最后一天。
        (REPO_ROOT / "fixtures" / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except FetchError as exc:
        print(json.dumps({
            "ok": False,
            "error": {"code": exc.code, "message": exc.message, "hint": exc.hint},
        }, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, **manifest}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())