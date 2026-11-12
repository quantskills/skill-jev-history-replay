"""数据质量审计：量化「未建模」的市场状态在样本中占多大比重。

本 skill 的 `applicability.out_of_scope` 里写了「不含停牌/ST/涨跌停建模」。
但"不含"不等于"无关"——如果样本里有 4% 的序列是 ST、4% 触及涨停，
那结论的适用范围就比看上去窄。这个脚本把缺口量化出来，
让读者在相信结论前先看到边界。

两种数据来源：
  1. 有凭证时：调用 panda_data 取真实 ST / 停牌名单（最准）
  2. 无凭证时：只做 OHLC 层面推断（涨跌停可达性），ST/停牌标注为未核验

用法：
    python3 scripts/data_quality_audit.py
    python3 scripts/data_quality_audit.py --offline
    python3 scripts/data_quality_audit.py --json
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import data_loader  # noqa: E402

# 各板块涨跌幅上限。判断"是否触及"用略低的阈值，避免浮点边界漏判。
LIMIT_PCT = {
    "default": 0.10,
    "chinext": 0.20,   # 300xxx / 301xxx
    "star": 0.20,      # 688xxx
    "bj": 0.30,        # 8xxxxx / 4xxxxx
    "st": 0.05,
}


def _board_of(symbol: str) -> str:
    code = symbol.split(".")[0]
    if code.startswith(("300", "301")):
        return "chinext"
    if code.startswith("688"):
        return "star"
    if code.startswith(("8", "4")):
        return "bj"
    return "default"


def _load_reference(ref_dir: Path) -> Dict[tuple, Dict[str, Any]]:
    out: Dict[tuple, Dict[str, Any]] = {}
    for path in sorted(ref_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for symbol, by_date in payload.get("symbols", {}).items():
            for date_text, row in by_date.items():
                if row.get("pre_close"):
                    out[(symbol, date_text)] = row
    return out


def _fetch_exchange_lists(start: str, end: str) -> Optional[Dict[str, Any]]:
    """取 ST / 停牌名单。无凭证或调用失败时返回 None（不静默当成空集）。"""
    import os

    try:
        import panda_data  # type: ignore[import-not-found]
    except ImportError:
        return None

    username = os.environ.get("PANDA_DATA_USERNAME") or os.environ.get("DEFAULT_USERNAME")
    zinfoid = os.environ.get("PANDA_DATA_PASSWORD") or os.environ.get("DEFAULT_PASSWORD")
    base_url = os.environ.get("PANDA_DATA_BASE_URL") or os.environ.get("JAVA_SERVICE_BASE_URL")
    if not all([username, zinfoid, base_url]):
        env_file = Path.home() / ".pandadata" / "pandadata.env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("export "):
                    line = line[len("export "):]
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
            username = os.environ.get("PANDA_DATA_USERNAME") or os.environ.get("DEFAULT_USERNAME")
            zinfoid = os.environ.get("PANDA_DATA_PASSWORD") or os.environ.get("DEFAULT_PASSWORD")
            base_url = os.environ.get("PANDA_DATA_BASE_URL") or os.environ.get("JAVA_SERVICE_BASE_URL")
    if not all([username, zinfoid, base_url]):
        return None

    try:
        panda_data.init_token(username=username, password=zinfoid, base_url=base_url)
        st = panda_data.get_st_list(start_date=start, end_date=end, is_st=True)
        susp = panda_data.get_suspended_list(
            start_date=start, end_date=end, is_suspended=True
        )
    except Exception:
        return None

    st_set = set()
    if st is not None and hasattr(st, "itertuples"):
        st_set = {(str(row.symbol), str(row.date))
                  for row in st.itertuples() if getattr(row, "is_st", False)}
    susp_set = set()
    if susp is not None and hasattr(susp, "itertuples"):
        susp_set = {(str(row.symbol), str(row.date))
                    for row in susp.itertuples()
                    if getattr(row, "is_suspended", False)}
    return {"st": st_set, "suspended": susp_set}


def audit(offline: bool = False) -> Dict[str, Any]:
    bars_dir = REPO_ROOT / "fixtures" / "bars"
    ref_dir = REPO_ROOT / "fixtures" / "reference"
    bars = data_loader.load_bars(bars_dir)
    reference = _load_reference(ref_dir)

    series = [(entry["symbol"], entry.get("date") or "") for entry in bars.values()]
    total = len(series)
    dates = sorted({d for _, d in series if d})

    result: Dict[str, Any] = {
        "series_count": total,
        "date_range": [dates[0], dates[-1]] if dates else [],
        "trading_days": len(dates),
        "checks": {},
        "unmodeled_share": {},
        "caveat": (
            "本 skill 不对这些状态做特殊处理：ST/停牌/涨跌停标的照常产生信号与成交。"
            "下面的占比就是结论的适用范围折扣——占比越高，结论越不能直接外推到实盘。"
        ),
    }

    # 涨跌停可达性（离线可算）
    limit_up = limit_dn = st_band_touch = 0
    considered = 0
    for symbol, date_text in series:
        row = reference.get((symbol, date_text))
        if not row:
            continue
        considered += 1
        pc = float(row["pre_close"])
        hi, lo = float(row["high"]), float(row["low"])
        board = _board_of(symbol)
        pct = LIMIT_PCT[board]
        # 用 0.5 个百分点的余量吸收四舍五入
        if hi >= pc * (1 + pct - 0.005):
            limit_up += 1
        if lo <= pc * (1 - pct + 0.005):
            limit_dn += 1
        if hi >= pc * (1 + LIMIT_PCT["st"] - 0.005):
            st_band_touch += 1

    result["checks"]["limit_up_touch"] = {
        "count": limit_up,
        "share": round(limit_up / considered, 4) if considered else None,
        "note": "当日最高价触及所在板块涨停价；重放仍会在该价位照常成交",
    }
    result["checks"]["limit_down_touch"] = {
        "count": limit_dn,
        "share": round(limit_dn / considered, 4) if considered else None,
        "note": "当日最低价触及跌停价；跌停时卖出可能实际无法成交",
    }

    # 板块分布（影响涨跌幅口径）
    boards: Dict[str, int] = {}
    for symbol, _ in series:
        boards[_board_of(symbol)] = boards.get(_board_of(symbol), 0) + 1
    result["checks"]["board_mix"] = {
        k: {"count": v, "share": round(v / total, 4)} for k, v in sorted(boards.items())
    }

    # 交易所名单（需凭证）
    lists = None if offline else (len(dates) >= 2 and _fetch_exchange_lists(dates[0], dates[-1]))
    if lists:
        series_set = set(series)
        st_hit = series_set & lists["st"]
        susp_hit = series_set & lists["suspended"]
        result["checks"]["st"] = {
            "count": len(st_hit),
            "share": round(len(st_hit) / total, 4),
            "symbols": len({s for s, _ in st_hit}),
            "note": "ST 标的有 5% 涨跌幅限制与特殊交易规则，本 skill 未做区分",
            "source": "panda_data.get_st_list",
        }
        result["checks"]["suspended"] = {
            "count": len(susp_hit),
            "share": round(len(susp_hit) / total, 4),
            "symbols": len({s for s, _ in susp_hit}),
            "note": "停牌日不应产生任何成交，本 skill 未做过滤",
            "source": "panda_data.get_suspended_list",
        }
        unmodeled = st_hit | susp_hit
        result["unmodeled_share"]["st_or_suspended"] = (
            round(len(unmodeled) / total, 4) if total else None
        )
    else:
        result["checks"]["st"] = {
            "count": None, "share": None,
            "note": "未核验（无凭证或 --offline）；ST 状态需交易所名单才能判定",
        }
        result["checks"]["suspended"] = {
            "count": None, "share": None,
            "note": "未核验（无凭证或 --offline）",
        }
        result["unmodeled_share"]["st_or_suspended"] = None

    result["unmodeled_share"]["limit_touch"] = (
        round((limit_up + limit_dn) / considered, 4) if considered else None
    )
    worst = [v for v in result["unmodeled_share"].values() if v is not None]
    result["overall_unmodeled_upper_bound"] = round(max(worst), 4) if worst else None
    result["verdict"] = _verdict(result)
    return result


def _verdict(result: Dict[str, Any]) -> Dict[str, Any]:
    share = result.get("overall_unmodeled_upper_bound")
    if share is None:
        return {"level": "unknown",
                "reason": "既无交易所名单也无法计算涨跌停可达性"}
    if share >= 0.10:
        return {"level": "material",
                "reason": f"未建模状态占比 {share:.2%}，结论外推需显著打折"}
    if share >= 0.02:
        return {"level": "moderate",
                "reason": f"未建模状态占比 {share:.2%}，属可接受但需声明的范围"}
    return {"level": "minor",
            "reason": f"未建模状态占比 {share:.2%}，对结论影响有限"}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit unmodeled market states")
    parser.add_argument("--offline", action="store_true",
                        help="不调用 panda_data，只做 OHLC 层面推断")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    result = audit(offline=args.offline)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"序列数 {result['series_count']:,}，交易日 {result['trading_days']}")
        for name, info in result["checks"].items():
            if isinstance(info, dict) and "share" in info:
                share = info["share"]
                shown = f"{share:.2%}" if share is not None else "未核验"
                print(f"  {name:20s} {shown:>10}  {info.get('note','')}")
        print(f"\n未建模占比上界：{result['overall_unmodeled_upper_bound']}")
        print(f"判定：{result['verdict']['level']} — {result['verdict']['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())