"""冻结基线：持久化一次运行结果，供跨 run 比对。

用法：
    python3 scripts/compare_baseline.py freeze output/report.json --name v1
    python3 scripts/compare_baseline.py compare output/report.json --against baselines/v1.json
    python3 scripts/compare_baseline.py list

可比性由 config_hash 保证：哈希不一致时比对明确标记 incompatible，
而不是给出一个看似合理但无意义的差值。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_DIR = REPO_ROOT / "baselines"

COMPARED = [
    "ledger_match_rate",
    "divergence_items",
    "one_sided_items",
    "signal_count",
    "closed_cycles",
    "total_net_pct",
]


class BaselineError(ValueError):
    def __init__(self, code: str, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


def _load(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise BaselineError("report_not_found", f"报告不存在：{path}",
                            hint="先运行 scripts/build.py")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise BaselineError("invalid_json", f"不是合法 JSON：{exc}") from exc


def freeze(report_path: str | Path, name: str | None = None,
           baseline_dir: Path | None = None) -> Dict[str, Any]:
    report = _load(report_path)
    out_dir = baseline_dir or BASELINE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    cmp_block = report.get("comparability", {})
    frozen = {
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "name": name or datetime.now(timezone.utc).strftime("jev_%Y%m%dT%H%M%SZ"),
        "run_id": report.get("run_id"),
        "config_hash": cmp_block.get("config_hash"),
        "semantics_hash": cmp_block.get("semantics_hash"),
        "log_source": cmp_block.get("log_source"),
        "fixture_fingerprint": cmp_block.get("fixture_fingerprint"),
        "summary": report.get("summary", {}),
        "alignment_verdict": report.get("alignment_conclusion", {}).get("verdict"),
        "value_verdict": report.get("value_assessment", {}).get("verdict", {}).get("verdict"),
        "attribution_verdict": report.get("attribution", {}).get("verdict"),
    }
    path = out_dir / f"{frozen['name']}.json"
    path.write_text(json.dumps(frozen, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "baseline": str(path), "name": frozen["name"]}


def compare(report_path: str | Path, baseline_path: str | Path) -> Dict[str, Any]:
    current = _load(report_path)
    baseline = _load(baseline_path)
    cur_hash = current.get("comparability", {}).get("config_hash")
    base_hash = baseline.get("config_hash")
    comparable = bool(cur_hash) and cur_hash == base_hash

    cur_summary = current.get("summary", {})
    base_summary = baseline.get("summary", {})
    deltas = {}
    for metric in COMPARED:
        a, b = base_summary.get(metric), cur_summary.get(metric)
        deltas[metric] = {
            "baseline": a,
            "current": b,
            "delta": round(b - a, 6) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None,
        }

    cur_cmp = current.get("comparability", {})
    base_fp = baseline.get("fixture_fingerprint")
    changed = []
    # config_hash 本身必须能出现在 changed_fields 里。此前只比较三个组成项，
    # 若报告有人手工改过 config_hash（或组成项之外的因素变了），
    # comparable=false 却给出空列表，读者无从判断到底哪里变了。
    if cur_hash != base_hash:
        changed.append("config_hash")
    if cur_cmp.get("semantics_hash") != baseline.get("semantics_hash"):
        changed.append("semantics_hash")
    if cur_cmp.get("fixture_fingerprint") != base_fp:
        changed.append("fixture_fingerprint")
    if cur_cmp.get("log_source") != baseline.get("log_source"):
        changed.append("log_source")
    # 日志内容变了必须让读者看到，即使 config_hash 没变（条数与来源相同）。
    # 不参与 comparable 判定，只把「看不见的输入变化」变成看得见的字段。
    # 但**旧锚点根本没有这个键**：那时它还没被记录。把"缺席"当成"漂移"会让每个
    # 历史锚点都谎报一次变化，所以只在两侧都有值且不等时点名，缺席单独说明。
    cur_logs_fp = cur_cmp.get("logs_fingerprint")
    base_logs_fp = baseline.get("logs_fingerprint")
    if cur_logs_fp and base_logs_fp and cur_logs_fp != base_logs_fp:
        changed.append("logs_fingerprint")

    return {
        "ok": True,
        "comparable": comparable,
        "config_hash": {"baseline": base_hash, "current": cur_hash},
        "changed_fields": changed,
        "deltas": deltas if comparable else None,
        "note": (
            "delta 可解读" if comparable else
            "config_hash 不一致，差异不可解读；请确认语义、夹具或日志来源是否变化"
        ),
    }


def list_baselines(baseline_dir: Path | None = None) -> Dict[str, Any]:
    out_dir = baseline_dir or BASELINE_DIR
    if not out_dir.exists():
        return {"ok": True, "baselines": []}
    items = []
    for path in sorted(out_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        items.append({
            "name": data.get("name", path.stem),
            "frozen_at": data.get("frozen_at"),
            "config_hash": data.get("config_hash"),
            "log_source": data.get("log_source"),
        })
    return {"ok": True, "baselines": items}


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Freeze/compare JEV replay baselines")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_freeze = sub.add_parser("freeze")
    p_freeze.add_argument("report")
    p_freeze.add_argument("--name", default=None)
    p_compare = sub.add_parser("compare")
    p_compare.add_argument("report")
    p_compare.add_argument("--against", required=True)
    sub.add_parser("list")
    args = parser.parse_args(argv)

    try:
        if args.cmd == "freeze":
            result = freeze(args.report, args.name)
        elif args.cmd == "compare":
            result = compare(args.report, args.against)
        else:
            result = list_baselines()
    except BaselineError as exc:
        print(json.dumps({"ok": False, "error": {
            "code": exc.code, "message": exc.message, "hint": exc.hint}},
            ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())