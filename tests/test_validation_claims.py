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


def test_welch_p_drift_is_caught_by_relative_tolerance(report):
    """p 值必须用**相对**容差比。

    绝对容差 5e-3 配 1e-5 量级的 p 值，等于声称 7e-06、实测 1.1e-05 也判通过——
    偏差近 700 倍无人报（缺陷 #71）。把声称值翻一倍必须失败。
    """
    claims = json.loads(CLAIMS.read_text(encoding="utf-8"))
    actual = (report["value_assessment"]["effect_size"]["full_sample_welch"]["p"])
    tampered = json.loads(json.dumps(claims))
    tampered["value_assessment"]["welch_p"] = actual * 2
    result = verify_claims.verify(report, tampered)
    assert not result["ok"]
    assert any(r["check"] == "value_assessment.welch_p" for r in result["failed"])


def test_welch_p_claim_matches_the_shipped_report(report):
    """声称值与实际值必须在 25% 相对误差内一致（防止改了报告不改 claims）。"""
    claims = json.loads(CLAIMS.read_text(encoding="utf-8"))
    actual = (report["value_assessment"]["effect_size"]["full_sample_welch"]["p"])
    claimed = claims["value_assessment"]["welch_p"]
    assert abs(actual - claimed) <= 0.25 * abs(claimed), (actual, claimed)


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

@pytest.mark.slow
def test_verdict_discriminates_semantic_difference(tmp_path):
    """阳性/阴性对照：判定器必须随语义差异变化，而不是永远 inconclusive。

    用 5 天 / 300 标的的子集，控制测试时长的同时保证每个旋钮都能产生差异；
    完整版见 `python3 scripts/controls_check.py`。

    子集不能太小：2 天 / 60 标的时 exit_eval 与 signal_gain_pct 产生 0 条差异，
    对照变成空转（vacuous），测不出任何东西。
    
    """
    from scripts.controls_check import _subset, run_controls

    bars_dir = REPO_ROOT / "fixtures" / "bars"
    ref_dir = REPO_ROOT / "fixtures" / "reference"
    sub_bars, sub_ref = _subset(bars_dir, ref_dir, days=5, max_symbols=300)
    result = run_controls(sub_bars, sub_ref)

    assert result["failed"] == [], (
        "判定器未能区分语义差异：\n"
        + "\n".join(f"  {r['case']}: {r['verdict']} (div={r['divergent']}) "
                    f"— {r['why']}" for r in result["failed"])
    )
    # 每个阴性对照都必须真的产生差异，否则是空转
    for r in result["results"]:
        if r["knob"] is not None:
            assert r["divergent"] > 0, (
                f"{r['knob']} 对照产生 0 条差异——样本不足，对照未生效"
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


def test_no_stale_numbers_in_evidence_doc():
    """验证文档里不得残留历史样本的具体数字。

    claims 只覆盖关键指标；文档表格里还有大量数字不受它保护。
    v0.6.1 换了样本后，一度有 5 处旧数字（7,000 序列、0.9913、46,642 等）
    没被任何检查发现。
    """
    text = EVIDENCE.read_text(encoding="utf-8")
    hits = verify_claims.scan_stale_tokens(text)
    assert hits == [], (
        "验证文档残留历史样本数字：\n"
        + "\n".join(f"  行 {h['line']}: {h['token']} — {h['text']}"
                    for h in hits)
    )


def test_stale_scanner_ignores_historical_lines():
    """标注了版本号的历史叙述允许保留旧数字。"""
    text = "当前是 4,200 序列。\n上表中 v0.5.0 的 7,000 序列样本已作废。\n"
    hits = verify_claims.scan_stale_tokens(text)
    # 第二行含 "v0.5"，应被豁免；该行也不含 STALE_TOKENS 中的 token
    assert all("v0.5" not in h["text"] for h in hits)


def test_stale_scanner_detects_current_description():
    text = "样本共 1,680,000 根分钟线。"
    hits = verify_claims.scan_stale_tokens(text)
    assert hits and hits[0]["token"] == "1,680,000"


def test_per_day_numbers_are_verified(report):
    """分日表也必须被校验——它曾停留在旧样本上（7,000 vs 4,200 序列）。"""
    claims = json.loads(CLAIMS.read_text(encoding="utf-8"))
    assert "per_day" in claims, "claims 缺 per_day 段"
    assert len(claims["per_day"]) >= 10, "per_day 覆盖天数过少"
    result = verify_claims.verify(report, claims)
    per_day_failures = [f for f in result["failed"]
                        if f["check"].startswith("per_day.")]
    assert per_day_failures == [], (
        "分日数字与实现对不上：\n"
        + "\n".join(f"  {f['check']}: actual={f['actual']} claimed={f['claimed']}"
                    for f in per_day_failures)
    )


def test_report_internals_are_consistent(report):
    """报告内部各字段必须互相自洽。

    summary / aggregate / per_day 由不同代码路径算出，任一处口径不一致
    都会让读者拿到互相矛盾的数，而单看每个字段都"像是对的"。
    """
    result = verify_claims.verify(report, {})   # 空 claims：只跑自洽检查
    failed = [f for f in result["failed"] if f["check"].startswith("consistency.")]
    assert failed == [], (
        "报告内部不一致：\n"
        + "\n".join(f"  {f['check']}: actual={f['actual']} expected={f['claimed']}"
                    for f in failed)
    )


def test_consistency_check_catches_tampering(report):
    """篡改 summary 的一个数字，自洽检查必须报错。"""
    import copy

    tampered = copy.deepcopy(report)
    tampered["summary"]["divergence_items"] = (
        tampered["summary"]["divergence_items"] + 1
    )
    result = verify_claims.verify(tampered, {})
    assert not result["ok"]
    assert any(f["check"].startswith("consistency.") for f in result["failed"])


def test_by_axis_one_sided_rollup_exists(report):
    """每个轴都要有 one_sided 汇总，否则无法从 by_axis 加总校验 total。"""
    by_axis = report["ledger"]["aggregate"]["by_axis"]
    for axis, info in by_axis.items():
        assert "one_sided" in info, f"{axis} 缺 one_sided 汇总"
