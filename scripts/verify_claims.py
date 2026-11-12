"""验收自检：把验证文档里的数字与当前产物逐项核对。

用途：验证文档最怕"写了数字、代码改了、没人复核"。这个脚本把
`references/validation_evidence.md` 中声明的关键指标与 `output/report.json`
的实际值逐条比对，任一项不符即返回非零退出码。

用法：
    python3 scripts/verify_claims.py
    python3 scripts/verify_claims.py --report output/report.json

CI 中在 `build.py` 之后运行，防止文档与实现悄悄漂移。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _check(results: List[Dict[str, Any]], name: str, actual: Any, claimed: Any,
           tol: float = 1e-6) -> None:
    """数值按容差比，非数值按完全相等比。"""
    a, c = _num(actual), _num(claimed)
    if a is not None and c is not None:
        ok = abs(a - c) <= tol
    else:
        ok = actual == claimed
    results.append({
        "check": name,
        "actual": actual,
        "claimed": claimed,
        "ok": ok,
    })


def verify(report: Dict[str, Any], claims: Dict[str, Any]) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    agg = report.get("ledger", {}).get("aggregate", {})
    by_axis = agg.get("by_axis", {})
    total = agg.get("total", {})

    for axis, spec in claims.get("axes", {}).items():
        entry = by_axis.get(axis, {})
        if "comparable" in spec:
            _check(results, f"axes.{axis}.comparable",
                   entry.get("comparable"), spec["comparable"])
        if "match_rate" in spec:
            _check(results, f"axes.{axis}.match_rate",
                   entry.get("match_rate"), spec["match_rate"], tol=5e-4)
        if "statuses" in spec:
            for status, expected in spec["statuses"].items():
                _check(results, f"axes.{axis}.{status}",
                       entry.get(status, 0), expected)

    if "total" in claims:
        spec = claims["total"]
        for key in ("comparable", "divergent", "one_sided", "match"):
            if key in spec:
                _check(results, f"total.{key}", total.get(key), spec[key])
        if "match_rate" in spec:
            _check(results, "total.match_rate", total.get("match_rate"),
                   spec["match_rate"], tol=5e-4)

    attr = report.get("attribution", {})
    for key in ("verdict", "top_knob", "top_explained_rate"):
        if key in claims.get("attribution", {}):
            _check(results, f"attribution.{key}", attr.get(key),
                   claims["attribution"][key])

    jd = attr.get("joint_diagnosis", {})
    if "joint_diagnosis_applicable" in claims.get("attribution", {}):
        _check(results, "attribution.joint_diagnosis.applicable",
               jd.get("applicable"),
               claims["attribution"]["joint_diagnosis_applicable"])

    ac = report.get("alignment_conclusion", {})
    if "verdict" in claims.get("alignment_conclusion", {}):
        _check(results, "alignment_conclusion.verdict", ac.get("verdict"),
               claims["alignment_conclusion"]["verdict"])

    va_block = report.get("value_assessment", {})
    va = va_block.get("verdict", {})
    claims_va = claims.get("value_assessment", {})
    if "verdict" in claims_va:
        _check(results, "value_assessment.verdict", va.get("verdict"),
               claims_va["verdict"])
    if "paired_coverage" in claims_va:
        _check(results, "value_assessment.paired_coverage",
               va_block.get("decision_changes", {}).get("paired_coverage"),
               claims_va["paired_coverage"], tol=5e-4)
    if "welch_p" in claims_va:
        _check(results, "value_assessment.welch_p",
               va_block.get("effect_size", {}).get("full_sample_welch", {}).get("p"),
               claims_va["welch_p"], tol=5e-3)

    dq_claims = claims.get("data_quality")
    if dq_claims:
        dq = report.get("applicability", {}).get("unmodeled_market_states") or {}
        checks = dq.get("checks", {})
        mapping = {
            "st_share": checks.get("st", {}).get("share"),
            "suspended_share": checks.get("suspended", {}).get("share"),
            "limit_up_touch_share": checks.get("limit_up_touch", {}).get("share"),
            "limit_down_touch_share": checks.get("limit_down_touch", {}).get("share"),
            "overall_unmodeled_upper_bound": dq.get("overall_unmodeled_upper_bound"),
            "verdict_level": (dq.get("verdict") or {}).get("level"),
        }
        for key, expected in dq_claims.items():
            if expected is None:
                continue
            _check(results, f"data_quality.{key}", mapping.get(key), expected,
                   tol=5e-4)

    prov = report.get("provenance", {})
    if "log_source" in claims.get("provenance", {}):
        _check(results, "provenance.log_source", prov.get("log_source"),
               claims["provenance"]["log_source"])

    summ = report.get("summary", {})
    for key, expected in claims.get("summary", {}).items():
        _check(results, f"summary.{key}", summ.get(key), expected)

    failed = [r for r in results if not r["ok"]]
    return {
        "ok": not failed,
        "total_checks": len(results),
        "passed": len(results) - len(failed),
        "failed": failed,
        "results": results,
    }


def _claims_file() -> Path:
    return REPO_ROOT / "references" / "validation_claims.json"


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify validation-doc numbers against the actual report")
    parser.add_argument("--report", default=str(REPO_ROOT / "output" / "report.json"))
    parser.add_argument("--claims", default=str(_claims_file()))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report_path = Path(args.report)
    if not report_path.exists():
        print(json.dumps({
            "ok": False,
            "error": {"code": "report_not_found",
                      "message": f"报告不存在：{report_path}",
                      "hint": "先运行 python3 scripts/build.py"},
        }, ensure_ascii=False, indent=2))
        return 2

    report = json.loads(report_path.read_text(encoding="utf-8"))
    claims = json.loads(Path(args.claims).read_text(encoding="utf-8"))
    result = verify(report, claims)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"checks: {result['passed']}/{result['total_checks']} passed")
        for row in result["failed"]:
            print(f"  MISMATCH {row['check']}: actual={row['actual']!r} "
                  f"claimed={row['claimed']!r}")
        print("OK" if result["ok"] else "FAILED")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())