"""判定器区分度自检：证明对齐结论不是常数，而是随语义差异变化。

为什么需要这个：一个总是返回 `inconclusive` 的判定器也能"通过"所有测试——
因为合成日志下本来就应该 inconclusive。那样的话，等真实日志到位，
判定器能不能正确区分 `consistent` / `minor_divergence` / `inconsistent`，
根本没被验证过。

做法：用参考语义生成日志，**抹掉 `_synthetic` 标记**使其被当作真实日志，
然后分别用「完全一致」和「只差一个旋钮」的语义去对齐，看结论是否随之变化。

这是受控的阳性/阴性对照：
- 阳性：完全一致 → 必须 `consistent` 且 0 冲突
- 阴性：单旋钮差异 → 必须显著偏离 `consistent`

用法：
    python3 scripts/controls_check.py
    python3 scripts/controls_check.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(REPO_ROOT),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts import config as cfg  # noqa: E402
from scripts import data_loader, log_synth  # noqa: E402
from scripts.run_eval import _load_prev_closes, evaluate  # noqa: E402

# 每个旋钮改一次，看判定器是否把它识别为"不一致"。
# 期望不是"必须 inconsistent"——小幅度的旋钮本来就可能只是 minor_divergence。
CONTROLS = [
    {"knob": "exit_eval", "value": "bar_high_low",
     "expect_not": ["consistent"], "why": "退出判定口径不同，必然产生真实冲突"},
    {"knob": "bar_timestamp", "value": "bar_start",
     "expect_not": ["consistent", "minor_divergence"], "why": "时间戳整体错位一根"},
    {"knob": "baseline_price", "value": "day_open",
     "expect_not": ["consistent"], "why": "涨幅基准不同"},
    {"knob": "breakout_field", "value": "close",
     "expect_not": ["consistent"], "why": "突破参照字段不同"},
    {"knob": "persistence_bars", "value": 1,
     "expect_not": ["consistent"], "why": "确认根数不同"},
    {"knob": "wait_bars", "value": 0,
     "expect_not": ["consistent"], "why": "等待根数不同"},
    {"knob": "entry_price", "value": "signal_close",
     "expect_not": ["consistent"], "why": "入场价口径不同"},
    {"knob": "signal_gain_pct", "value": 0.05,
     "expect_not": ["consistent"], "why": "触发阈值差 5 倍"},
]


def _write_actual_logs(bars_dir: Path, ref_dir: Path, semantics: Dict[str, Any],
                       out_dir: Path) -> Path:
    """生成日志并去掉 `_synthetic` 标记，使其被当作真实日志。"""
    bars = data_loader.load_bars(bars_dir)
    prev = _load_prev_closes(ref_dir, list(bars))
    records = log_synth.synthesize_logs(bars, semantics, prev)
    for rec in records:
        rec.pop("_synthetic", None)
    per_date: Dict[str, List[Dict[str, Any]]] = {}
    for rec in records:
        per_date.setdefault(str(rec.get("date") or ""), []).append(rec)
    logs_dir = out_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    for date_text, rows in per_date.items():
        (logs_dir / f"{date_text}.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
            encoding="utf-8",
        )
    return logs_dir


def run_controls(bars_dir: Path, ref_dir: Path) -> Dict[str, Any]:
    base = dict(cfg.load_config()["semantics"])
    results: List[Dict[str, Any]] = []

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # 阳性对照：日志与对齐都用参考语义
        logs = _write_actual_logs(bars_dir, ref_dir, base, root / "same")
        out = evaluate(logs_dir=str(logs), output_dir=root / "same" / "out",
                       run_attribution=False)
        ac = out["alignment_conclusion"]
        results.append({
            "case": "positive_control",
            "knob": None,
            "value": None,
            "verdict": ac["verdict"],
            "match_rate": ac["match_rate"],
            "divergent": out["ledger"]["aggregate"]["total"]["divergent"],
            "log_source": out["provenance"]["log_source"],
            "ok": ac["verdict"] == "consistent"
                  and out["ledger"]["aggregate"]["total"]["divergent"] == 0,
            "why": "完全一致的语义必须判 consistent 且零冲突",
        })

        # 阴性对照：日志按改动后的语义生成，对齐仍用参考语义
        for ctrl in CONTROLS:
            altered = dict(base)
            altered[ctrl["knob"]] = ctrl["value"]
            logs = _write_actual_logs(bars_dir, ref_dir, altered, root / ctrl["knob"])
            out = evaluate(logs_dir=str(logs),
                           output_dir=root / ctrl["knob"] / "out",
                           run_attribution=False)
            ac = out["alignment_conclusion"]
            verdict = ac["verdict"]
            results.append({
                "case": ctrl["knob"],
                "knob": ctrl["knob"],
                "value": ctrl["value"],
                "verdict": verdict,
                "match_rate": ac["match_rate"],
                "divergent": out["ledger"]["aggregate"]["total"]["divergent"],
                "log_source": out["provenance"]["log_source"],
                "ok": verdict not in ctrl["expect_not"],
                "why": ctrl["why"],
            })

    failed = [r for r in results if not r["ok"]]
    return {
        "ok": not failed,
        "total": len(results),
        "passed": len(results) - len(failed),
        "failed": failed,
        "results": results,
    }


def _subset(bars_dir: Path, ref_dir: Path, days: int,
            max_symbols: int = 120) -> tuple[Path, Path]:
    """取前 N 个交易日、前 M 个标的构造临时子集，供 CI 快速跑。

    只截日期不够——500 标的 × 3 天仍要跑两分钟。
    同时截标的数，把 9 个对照组的总耗时压到 CI 可接受范围。
    """
    import gzip
    import json
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="jev-controls-"))
    (root / "bars").mkdir()
    (root / "reference").mkdir()

    keep: set[str] | None = None
    for path in sorted(bars_dir.glob("*.json.gz"))[:days]:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            records = json.load(fh)
        if keep is None:
            symbols = sorted({r["symbol"] for r in records})
            keep = set(symbols[:max_symbols])
        subset = [r for r in records if r["symbol"] in keep]
        with gzip.open(root / "bars" / path.name, "wt", encoding="utf-8") as fh:
            json.dump(subset, fh, ensure_ascii=False)

    for path in sorted(ref_dir.glob("*.json"))[:days]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if keep is not None:
            payload["symbols"] = {
                k: v for k, v in payload.get("symbols", {}).items() if k in keep
            }
        (root / "reference" / path.name).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    return root / "bars", root / "reference"


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the alignment verdict discriminates semantic differences")
    parser.add_argument("--bars-dir", default=str(REPO_ROOT / "fixtures" / "bars"))
    parser.add_argument("--ref-dir", default=str(REPO_ROOT / "fixtures" / "reference"))
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--quick", action="store_true",
        help="只用前 3 个交易日的标的做一次快速验证（CI 用，约 30 秒）",
    )
    args = parser.parse_args(argv)

    bars_dir = Path(args.bars_dir)
    ref_dir = Path(args.ref_dir)
    if args.quick:
        bars_dir, ref_dir = _subset(bars_dir, ref_dir, days=3, max_symbols=120)

    result = run_controls(bars_dir, ref_dir)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"controls: {result['passed']}/{result['total']} passed")
        for r in result["results"]:
            mark = "OK  " if r["ok"] else "FAIL"
            knob = r["knob"] or "(identical)"
            print(f"  {mark} {knob:18s} verdict={r['verdict']:18s} "
                  f"rate={r['match_rate']} divergent={r['divergent']}")
        if result["failed"]:
            print("\nfailures:")
            for r in result["failed"]:
                print(f"  {r['case']}: {r['verdict']} — {r['why']}")
        print("OK" if result["ok"] else "FAILED")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())