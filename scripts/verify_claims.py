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


def _internal_consistency(report: Dict[str, Any],
                          results: List[Dict[str, Any]]) -> None:
    """报告内部各字段必须互相自洽。

    这些数字由不同代码路径算出：summary 来自 run_eval，aggregate 来自
    aligner，per_day 又一次聚合。任何一处口径不一致都会让读者拿到
    互相矛盾的数，而单看每个字段都"像是对的"。
    """
    agg = report.get("ledger", {}).get("aggregate", {})
    total = agg.get("total", {})
    by_axis = agg.get("by_axis", {})
    summary = report.get("summary", {})
    per_day = report.get("per_day", {})

    def same(name: str, a: Any, b: Any) -> None:
        _check(results, f"consistency.{name}", a, b)

    # 1) summary 与 aggregate.total 必须一致
    same("summary.match_rate", summary.get("ledger_match_rate"),
         total.get("match_rate"))
    same("summary.divergent", summary.get("divergence_items"),
         total.get("divergent"))

    # 2) 各轴加总 = total
    for key in ("match", "divergent", "one_sided"):
        same(f"by_axis_sum.{key}",
             sum(v.get(key, 0) for v in by_axis.values()), total.get(key))

    # 3) per_day 加总 = total
    if per_day:
        for key in ("match", "divergent", "one_sided"):
            same(f"per_day_sum.{key}",
                 sum(b.get(key, 0) for b in per_day.values()), total.get(key))

    # 4) total 内部恒等式
    comparable = total.get("comparable", 0)
    same("total.comparable_eq_match_plus_divergent", comparable,
         total.get("match", 0) + total.get("divergent", 0))
    same("total.rows_eq_parts", total.get("rows", 0),
         total.get("match", 0) + total.get("divergent", 0) + total.get("one_sided", 0))

    # 5) "冲突数"这个概念在报告里有四处，必须同口径。
    #    此前 alignment_conclusion.divergence_items 报的是"全部非 match 行"
    #    （含近 98 万条 jev_missing），与 summary/total 差三个数量级。
    ledger = report.get("ledger", {})
    alignment = report.get("alignment_conclusion", {})
    same("divergence_items.alignment_conclusion_eq_total",
         alignment.get("divergence_items"), total.get("divergent"))
    same("divergence_items.ledger_eq_total",
         ledger.get("divergence_rows"), total.get("divergent"))

    # 6) ledger 的 non_match_rows 必须等于 one_sided + divergent
    if "non_match_rows" in ledger:
        same("ledger.non_match_rows_eq_parts",
             ledger.get("non_match_rows"),
             total.get("one_sided", 0) + total.get("divergent", 0))

    # 7) 归因各行的 explained 不得超过 baseline_divergences
    attr = report.get("attribution", {})
    baseline_div = attr.get("baseline_divergences")
    if baseline_div is not None:
        over = [r.get("knob") for r in attr.get("ranked", [])
                if (r.get("explained") or 0) > baseline_div]
        _check(results, "consistency.attribution.explained_le_baseline",
               over, [])

    # 9) 单边缺失不可能超过该轴总根数——这是"逻辑上不可能"的边界。
    #    曾出现 `jev_missing = 1,633,358` 而总根数只有 1,008,000 的记录，
    #    这种数字只要做一次量级检查就能发现。
    rows_total = total.get("rows", 0)
    non_match = ledger.get("non_match_rows")
    if non_match is not None:
        _check(results, "consistency.ledger.non_match_le_total_rows",
               non_match <= rows_total, True)

    # 10) 条件轴覆盖率 = comparable / (comparable + jev_missing)
    cond = by_axis.get("condition", {})
    cond_comparable = cond.get("comparable", 0)
    cond_missing = cond.get("jev_missing", 0)
    denom = cond_comparable + cond_missing
    if denom:
        summary_cov = summary.get("condition_coverage")
        if summary_cov is not None:
            _check(results, "consistency.condition_coverage_matches_axes",
                   summary_cov, round(cond_comparable / denom, 4), tol=5e-4)

    # 8) inline_rows 不得超过 max_inline_rows，且截断标记要正确
    max_inline = report.get("comparability", {}).get("max_inline_rows")
    inline = ledger.get("inline_rows") or []
    if max_inline is not None:
        _check(results, "consistency.ledger.inline_within_cap",
               len(inline) <= max_inline, True)
        _check(results, "consistency.ledger.inline_truncated_flag",
               ledger.get("inline_truncated"),
               (ledger.get("total_rows", 0) > max_inline))


def verify(report: Dict[str, Any], claims: Dict[str, Any]) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    _internal_consistency(report, results)
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

    per_day_claims = claims.get("per_day")
    if per_day_claims:
        import collections as _c

        counts = _c.defaultdict(_c.Counter)
        ledger_path = REPO_ROOT / "output" / "ledger.jsonl"

        # 优先用报告里的 per_day（内存聚合，不依赖落盘账本的完整模式）
        per_day_block = report.get("per_day")
        if per_day_block:
            for day, b in per_day_block.items():
                counts[day]["match"] = b.get("match", 0)
                counts[day]["divergent"] = b.get("divergent", 0)
                counts[day]["_one_sided"] = b.get("one_sided", 0)
            ledger_path = None   # 已有内存数据，无需读文件

        if ledger_path is None:
            pass
        elif not ledger_path.exists():
            results.append({
                "check": "per_day.ledger_available",
                "actual": "missing",
                "claimed": "output/ledger.jsonl 必须存在",
                "ok": False,
            })
        else:
            for line in ledger_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                sym = row.get("symbol", "")
                day = sym.split("@")[-1] if "@" in sym else "single"
                counts[day][row.get("status")] += 1
        for day, expected in per_day_claims.items():
            c = counts.get(day, _c.Counter())
            comparable = c.get("match", 0) + c.get("divergent", 0)
            _check(results, f"per_day.{day}.comparable", comparable,
                   expected.get("comparable"))
            _check(results, f"per_day.{day}.divergent", c.get("divergent", 0),
                   expected.get("divergent"))

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

    # 陈旧数字扫描：claims 只覆盖关键指标，文档表格里还有大量数字
    # 不受它保护。这里额外扫一遍已知的历史样本 token。
    evidence_path = REPO_ROOT / "references" / "validation_evidence.md"
    stale_hits: List[Dict[str, Any]] = []
    if evidence_path.exists():
        stale_hits = scan_stale_tokens(evidence_path.read_text(encoding="utf-8"))
    for hit in stale_hits:
        results.append({
            "check": f"evidence.stale_token.line{hit['line']}",
            "actual": hit["token"],
            "claimed": "（不应出现）",
            "ok": False,
        })

    failed = [r for r in results if not r["ok"]]
    return {
        "ok": not failed,
        "total_checks": len(results),
        "passed": len(results) - len(failed),
        "failed": failed,
        "results": results,
    }


# 文档中出现即为"陈旧值"的具体数字 token。
# 这些是历史样本的产物，出现在当前描述里就说明文档没跟上代码。
# 例外：显式标注了版本/日期的历史叙述行不计入（见 _is_historical）。
STALE_TOKENS = [
    # v0.6.0 及更早（7,000 序列 / 500 标的/日）
    "1,680,000", "46,642", "58,110", "57,607",
    # v0.6.1 曾用的清单式写法
    "28,754 / 1,680,000",
]


def _is_historical(line: str) -> bool:
    """判断一行是否属于"历史叙述"（允许保留旧数字）。"""
    markers = ("v0.4", "v0.5", "v0.6.0", "当时", "历史", "上一版", "旧样本")
    return any(m in line for m in markers)


def scan_stale_tokens(evidence_text: str) -> List[Dict[str, Any]]:
    hits: List[Dict[str, Any]] = []
    for lineno, line in enumerate(evidence_text.splitlines(), 1):
        if _is_historical(line):
            continue
        for token in STALE_TOKENS:
            if token in line:
                hits.append({"line": lineno, "token": token, "text": line.strip()[:100]})
    return hits


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