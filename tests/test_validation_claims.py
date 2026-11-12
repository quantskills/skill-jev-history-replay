"""验收自检：验证文档声明的数字必须与当前实现一致。

这个测试的意义在于防止「文档写了数字、代码改了、没人复核」的静默漂移。
若真实改动导致指标变化，是**测试失败**提醒你更新
`references/validation_claims.json` 与 `validation_evidence.md`；
而不是让文档继续声称一个已经不成立的数字。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import verify_claims

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAIMS = REPO_ROOT / "references" / "validation_claims.json"
EVIDENCE = REPO_ROOT / "references" / "validation_evidence.md"


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    """真实跑一遍端到端，而不是读上一次的 output（可能过期）。"""
    from scripts.run_eval import evaluate

    out = tmp_path_factory.mktemp("claims")
    return evaluate(output_dir=out, run_attribution=True)


def test_claims_file_exists():
    assert CLAIMS.exists(), "缺少 validation_claims.json"
    assert EVIDENCE.exists(), "缺少 validation_evidence.md"


def test_report_matches_documented_claims(report):
    claims = json.loads(CLAIMS.read_text(encoding="utf-8"))
    result = verify_claims.verify(report, claims)
    assert result["ok"], (
        "验证文档与实现不符：\n"
        + "\n".join(
            f"  {row['check']}: actual={row['actual']!r} "
            f"claimed={row['claimed']!r}"
            for row in result["failed"]
        )
    )


def test_claim_checker_catches_drift(report):
    """证明这个校验器不是摆设：篡改一项必须失败。"""
    claims = json.loads(CLAIMS.read_text(encoding="utf-8"))
    tampered = json.loads(json.dumps(claims))
    tampered["total"]["comparable"] = claims["total"]["comparable"] + 1
    result = verify_claims.verify(report, tampered)
    assert not result["ok"]
    assert any(r["check"] == "total.comparable" for r in result["failed"])


def test_documented_evidence_quotes_match_claims():
    """证据文档里写的一致率数字，必须与 claims 文件一致。"""
    claims = json.loads(CLAIMS.read_text(encoding="utf-8"))
    text = EVIDENCE.read_text(encoding="utf-8")
    total_rate = claims["total"]["match_rate"]
    assert f"{total_rate:.4f}" in text, (
        f"validation_evidence.md 未出现当前总一致率 {total_rate:.4f}"
    )
    for axis, spec in claims["axes"].items():
        rate = spec.get("match_rate")
        if rate is None:
            continue
        rendered = f"{rate:.4f}" if rate < 1 else "1.00"
        assert rendered in text, (
            f"validation_evidence.md 未出现 {axis} 的一致率 {rendered}"
        )


def test_claims_are_internally_consistent(report):
    """claims 内部的加总关系必须自洽。"""
    a = report["ledger"]["aggregate"]["total"]
    assert a["comparable"] == a["match"] + a["divergent"]
    assert a["rows"] == a["match"] + a["divergent"] + a["one_sided"]
    assert a["divergence_items"] == a["divergent"]

def test_verdict_discriminates_semantic_difference(tmp_path):
    """阳性/阴性对照：判定器必须随语义差异变化，而不是永远 inconclusive。

    只跑 2 天 / 60 标的的微缩版，控制测试时长；完整版见
    `python3 scripts/controls_check.py`。
    """
    from scripts.controls_check import _subset, run_controls

    bars_dir = REPO_ROOT / "fixtures" / "bars"
    ref_dir = REPO_ROOT / "fixtures" / "reference"
    sub_bars, sub_ref = _subset(bars_dir, ref_dir, days=2, max_symbols=60)
    result = run_controls(sub_bars, sub_ref)

    assert result["failed"] == [], (
        "判定器未能区分语义差异：\n"
        + "\n".join(f"  {r['case']}: {r['verdict']} — {r['why']}"
                    for r in result["failed"])
    )

    by_case = {r["case"]: r for r in result["results"]}
    # 阳性对照：完全一致必须 consistent 且零冲突
    pos = by_case["positive_control"]
    assert pos["verdict"] == "consistent"
    assert pos["divergent"] == 0
    assert pos["log_source"] == "actual"

    # 关键回归：单旋钮差异不能被判成 consistent
    for case in ("exit_eval", "bar_timestamp", "baseline_price"):
        assert by_case[case]["verdict"] != "consistent"
