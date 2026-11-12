"""§9 结论与边界里的数字必须与当前报告一致。

这一节是读者决定"能不能信这个工具"的依据，却长期没有任何自动校验：
上界曾写 4.20%（实际 4.67%）、ST 交易占比曾写 2.04%（实际 3.31%）、
「容差 0–5 分钟结果不变」在 v0.12.8 修好容差后已经不成立。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = REPO_ROOT / "references" / "validation_evidence.md"
REPORT = REPO_ROOT / "output" / "report.json"


@pytest.fixture(scope="module")
def report():
    if not REPORT.exists():
        pytest.skip("需要先运行 scripts/build.py")
    return json.loads(REPORT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def conclusions():
    text = EVIDENCE.read_text(encoding="utf-8")
    start = text.index("## 9. 结论与边界")
    return text[start:]


def test_conclusion_match_rate_matches_report(report, conclusions):
    rate = report["summary"]["ledger_match_rate"]
    assert f"{rate:.4f}" in conclusions, (
        f"§9 未出现当前总体一致率 {rate:.4f}"
    )


def test_conclusion_exit_match_rate_matches_report(report, conclusions):
    exit_rate = report["ledger"]["aggregate"]["by_axis"]["exit"]["match_rate"]
    assert f"{exit_rate:.4f}" in conclusions, (
        f"§9 未出现当前退出轴一致率 {exit_rate:.4f}"
    )


def test_conclusion_unmodeled_upper_bound_matches_report(report, conclusions):
    """上界曾是 4.20%，实际 4.67%——这种手写数字必须对账。"""
    upper = report["applicability"]["unmodeled_market_states"][
        "overall_unmodeled_upper_bound"]
    shown = f"{upper * 100:.2f}%"
    assert shown in conclusions, f"§9 未出现当前未建模上界 {shown}"


def test_conclusion_tolerance_not_claimed_constant(conclusions):
    """§9 不得再声称"容差 0–5 分钟结果不变"。

    v0.12.8 修好容差判定后四档分别为 0.9895/0.9913/0.9920/0.9931，
    单调上升；这句旧结论与事实相反。
    """
    assert "容差 0–5 分钟结果不变" not in conclusions
    assert "容差 0/1/2/5 分钟" in conclusions


def test_st_trade_share_is_documented_consistently():
    """§3.4 与 §9 的 ST 交易占比必须是同一个数。"""
    text = EVIDENCE.read_text(encoding="utf-8")
    # 形如 "占全部交易的 **3.31%**" 与 "ST 标的实际产生 3.31% 的交易"
    shares = set(re.findall(r"占全部交易的 \*\*([\d.]+)%\*\*", text))
    shares |= set(re.findall(r"ST 标的实际产生 ([\d.]+)% 的交易", text))
    assert len(shares) == 1, f"ST 交易占比出现多个不同值：{shares}"