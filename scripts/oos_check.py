"""样本外复现：用与主夹具完全不重叠的日期重跑，看结论是否复现。

为什么需要：主结论来自固定的一段日期（2026-10-26 至 11-12）。只在一段
样本上成立的结论，很可能只是那段行情的产物。换成另一段时间，如果
结构结论（各轴一致率量级、归因锁定 `exit_eval`）能复现，可信度才成立；
如果 p 值从 7×10⁻⁶ 掉到 0.05 边缘，也必须如实说出来。

用法：
    python3 scripts/oos_check.py                 # 默认 2026-09 全月
    python3 scripts/oos_check.py --dates 20260901,20260902,...
    python3 scripts/oos_check.py --json

需要 panda_data 凭证（要拉新数据）。结果写到临时目录，不污染 fixtures/。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# 与主夹具（20261026–20261112）完全不重叠
DEFAULT_DATES = [
    "20260901", "20260902", "20260903", "20260904",
    "20260907", "20260908", "20260909", "20260910",
    "20260911", "20260914", "20260915",
]

# 主样本（in-sample）的实测值，作为复现的对照基准
IN_SAMPLE = {
    "total_comparable": 36086,
    "total_match_rate": 0.9895,
    "exit_match_rate": 0.8667,
    "attribution_top_knob": "exit_eval",
    "attribution_top_rate": 1.0,
    "value_verdict": "negative",
    "welch_p": 7e-06,
}


def _load_credentials() -> bool:
    """凭证是否齐备。解析细节交给 scripts/credentials.py 统一处理。"""
    from scripts.credentials import is_available

    return is_available()


def build_and_evaluate(dates: List[str], universe: int = 300,
                       workdir: Path | None = None) -> Dict[str, Any]:
    """在临时目录构建 OOS 夹具并评测。"""
    from scripts import build_fixtures as bf
    from scripts.run_eval import evaluate

    root = workdir or Path(tempfile.mkdtemp(prefix="jev-oos-"))
    for sub in ("bars", "reference", "logs"):
        (root / "fixtures" / sub).mkdir(parents=True, exist_ok=True)

    original_root = bf.REPO_ROOT
    bf.REPO_ROOT = root
    try:
        client = bf._client()
        selected = bf._pick_fixed_universe(client, dates, universe)
        for date in dates:
            try:
                bf.build(date, selected, universe, "jev_assumed")
            except FileNotFoundError:
                # build() 的 fingerprint 曾依赖当日日志文件；日志稍后统一生成
                pass
        log_info = bf.generate_logs("jev_assumed")
    finally:
        bf.REPO_ROOT = original_root

    report = evaluate(
        bars_dir=str(root / "fixtures" / "bars"),
        logs_dir=str(root / "fixtures" / "logs"),
        output_dir=str(root / "out"),
    )
    return {"root": str(root), "log_info": log_info, "report": report}


def summarize(result: Dict[str, Any]) -> Dict[str, Any]:
    r = result["report"]
    a = r["ledger"]["aggregate"]
    va = r["value_assessment"]
    welch = va["effect_size"]["full_sample_welch"]
    return {
        "dates": result["log_info"]["dates"],
        "symbols": result["log_info"].get("symbol_count"),
        "log_records": result["log_info"]["total_records"],
        "axes": {
            axis: {"comparable": v.get("comparable"), "match_rate": v.get("match_rate")}
            for axis, v in a["by_axis"].items()
        },
        "total": {
            "comparable": a["total"]["comparable"],
            "match_rate": a["total"]["match_rate"],
            "divergent": a["total"]["divergent"],
        },
        "attribution": {
            "verdict": r["attribution"]["verdict"],
            "top_knob": r["attribution"]["top_knob"],
            "top_explained_rate": r["attribution"]["top_explained_rate"],
        },
        "value": {
            "verdict": va["verdict"]["verdict"],
            "paired_coverage": va["decision_changes"]["paired_coverage"],
            "welch_p": welch.get("p"),
            "welch_diff": welch.get("diff"),
            "n_a": welch.get("n_a"),
            "n_b": welch.get("n_b"),
        },
        "alignment_verdict": r["alignment_conclusion"]["verdict"],
    }


def judge(oos: Dict[str, Any], in_sample: Dict[str, Any]) -> Dict[str, Any]:
    """判断样本外是否复现了样本内的结构结论。"""
    checks = []

    def add(name, ok, detail):
        checks.append({"check": name, "replicated": bool(ok), "detail": detail})

    oos_total = oos["total"]["match_rate"]
    add("total_match_rate_band",
        0.97 <= oos_total <= 1.0,
        f"样本外 {oos_total:.4f}（样本内 {in_sample['total_match_rate']:.4f}）")

    oos_exit = oos["axes"]["exit"]["match_rate"]
    add("exit_match_rate_band",
        oos_exit is not None and 0.80 <= oos_exit <= 0.95,
        f"样本外 {oos_exit}（样本内 {in_sample['exit_match_rate']:.4f}）")

    add("attribution_knob",
        oos["attribution"]["top_knob"] == in_sample["attribution_top_knob"],
        f"样本外 {oos['attribution']['top_knob']}（样本内 {in_sample['attribution_top_knob']}）")

    add("attribution_rate",
        oos["attribution"]["top_explained_rate"] == in_sample["attribution_top_rate"],
        f"样本外 {oos['attribution']['top_explained_rate']}")

    add("value_verdict",
        oos["value"]["verdict"] == in_sample["value_verdict"],
        f"样本外 {oos['value']['verdict']}（样本内 {in_sample['value_verdict']}）")

    # 显著性强度是否复现——这一项允许不成立，但必须报出来
    p = oos["value"]["welch_p"]
    strong = p is not None and p < 0.01
    add("welch_significance_strength",
        strong,
        f"样本外 p={p}（样本内 {in_sample['welch_p']:.1e}）；"
        + ("强度复现" if strong else "方向一致但**显著性明显减弱**，属边缘证据"))

    failed = [c for c in checks if not c["replicated"]]
    return {
        "ok": not failed,
        "checks": checks,
        "failed": failed,
        "caveat": (
            "结构结论（一致率量级、归因锁定、价值方向）复现，才说明结论"
            "不是某段行情的产物；显著性强度不必然复现，减弱时必须如实标注。"
        ),
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Out-of-sample replication check")
    parser.add_argument("--dates", default=None,
                        help="逗号分隔的交易日；默认 2026-09 的 11 天")
    parser.add_argument("--universe", type=int, default=300)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not _load_credentials():
        print(json.dumps({
            "ok": False,
            "error": {"code": "missing_credentials",
                      "message": "样本外复现需要拉新数据，必须提供 panda_data 凭证"},
            "hint": "写入 ~/.pandadata/pandadata.env 或 export PANDA_DATA_*",
        }, ensure_ascii=False, indent=2))
        return 2

    dates = ([d.strip() for d in args.dates.split(",") if d.strip()]
             if args.dates else DEFAULT_DATES)
    try:
        result = build_and_evaluate(dates, args.universe)
    except Exception as exc:   # 网络/凭证/数据问题一律结构化报错，不抛堆栈
        code = getattr(exc, "code", type(exc).__name__)
        hint = getattr(exc, "hint", "")
        print(json.dumps({
            "ok": False,
            "error": {"code": code, "message": str(exc), "hint": hint},
        }, ensure_ascii=False, indent=2))
        return 2
    summary = summarize(result)
    verdict = judge(summary, IN_SAMPLE)
    payload = {"ok": verdict["ok"], "out_of_sample": summary,
               "in_sample": IN_SAMPLE, "replication": verdict}

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"样本外日期 {summary['dates'][0]}–{summary['dates'][-1]}"
              f"（{len(summary['dates'])} 天）")
        for axis, info in summary["axes"].items():
            print(f"  {axis:10s} comparable={info['comparable']:>6} rate={info['match_rate']}")
        print(f"  合计 comparable={summary['total']['comparable']:,} "
              f"rate={summary['total']['match_rate']}")
        print(f"  归因 {summary['attribution']['top_knob']} "
              f"{summary['attribution']['top_explained_rate']}")
        print(f"  价值 {summary['value']['verdict']} welch_p={summary['value']['welch_p']}")
        print("\n复现判定：")
        for c in verdict["checks"]:
            print(f"  {'OK  ' if c['replicated'] else 'DIFF'} {c['check']}: {c['detail']}")
        print("OK" if verdict["ok"] else "NOT FULLY REPLICATED")
    return 0 if verdict["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())