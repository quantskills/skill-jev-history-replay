"""样本外复现脚本的自洽性。

`oos_check.py` 里有一份**硬编码**的样本内基准（`IN_SAMPLE`），用于判断
样本外结果是否复现。这份基准必须与当前主样本的实际结果一致——
否则"复现判定"是拿旧基准比新结果，结论无效。

这个风险是真实发生过的：修好容差判定后，主样本总一致率从 0.9895 变成
0.9913、退出轴从 0.8667 变成 0.8896，而 `IN_SAMPLE` 没有同步，
导致判定仍在用旧基准。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT = REPO_ROOT / "output" / "report.json"


@pytest.fixture(scope="module")
def report():
    if not REPORT.exists():
        pytest.skip("需要先运行 scripts/build.py 生成 output/report.json")
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_in_sample_baseline_matches_current_report(report):
    """`IN_SAMPLE` 必须反映当前主样本的真实结果。

    只要主样本数字变了（换样本、修判定逻辑、改容差），这条就会红，
    提醒同步基准——而不是让复现判定悄悄用旧数字。
    """
    from scripts import oos_check

    base = oos_check.IN_SAMPLE
    summary = report["summary"]
    by_axis = report["ledger"]["aggregate"]["by_axis"]

    assert base["total_match_rate"] == summary["ledger_match_rate"], (
        f"IN_SAMPLE.total_match_rate={base['total_match_rate']} "
        f"与报告 {summary['ledger_match_rate']} 不一致"
    )
    assert base["exit_match_rate"] == by_axis["exit"]["match_rate"], (
        f"IN_SAMPLE.exit_match_rate={base['exit_match_rate']} "
        f"与报告 {by_axis['exit']['match_rate']} 不一致"
    )
    assert base["attribution_top_knob"] == report["attribution"]["ranked"][0]["knob"]
    assert base["value_verdict"] == summary["value_verdict"]


def test_in_sample_total_comparable_matches_report(report):
    total = report["ledger"]["aggregate"]["total"]
    from scripts import oos_check

    assert oos_check.IN_SAMPLE["total_comparable"] == total["comparable"]


def test_judge_flags_weakened_significance():
    """显著性明显减弱时必须单列为未复现，不能算"完全复现"。"""
    from scripts import oos_check

    summary = {
        "total": {"match_rate": 0.9921},
        "axes": {"exit": {"match_rate": 0.8879}},
        "attribution": {"top_knob": "exit_eval", "top_explained_rate": 1.0},
        "value": {"verdict": "negative", "welch_p": 0.0488},
    }
    verdict = oos_check.judge(summary, oos_check.IN_SAMPLE)
    assert verdict["ok"] is False, "显著性减弱时不应判为完全复现"

    checks = {c["check"]: c for c in verdict["checks"]}
    assert checks["welch_significance_strength"]["replicated"] is False
    # 其余项仍应通过——减弱的是强度，不是方向或结构
    assert checks["value_verdict"]["replicated"] is True
    assert checks["attribution_knob"]["replicated"] is True
    assert checks["total_match_rate_band"]["replicated"] is True


def test_judge_passes_when_everything_replicates():
    """全部项都达标时应判为复现。"""
    from scripts import oos_check

    summary = {
        "total": {"match_rate": 0.9921},
        "axes": {"exit": {"match_rate": 0.8879}},
        "attribution": {"top_knob": "exit_eval", "top_explained_rate": 1.0},
        "value": {"verdict": "negative", "welch_p": 7e-06},
    }
    verdict = oos_check.judge(summary, oos_check.IN_SAMPLE)
    assert verdict["ok"] is True
    assert verdict["failed"] == []