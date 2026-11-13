"""报告内部各处的计数必须同口径。

来源：`alignment_conclusion.divergence_items` 曾报 **979,634**，
而 `summary.divergence_items` 与 `ledger.aggregate.total.divergent` 都是
**314**——同一份报告里同一个概念出现三个差三个数量级的数字，
读者会误以为有近百万条真实冲突。

根因：`build_alignment_conclusion` 收到的 `divergence_rows` 是
"全部非 match 行"（含近 98 万条 `jev_missing`），而不是真实冲突数。
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
        pytest.skip("需要先运行 scripts/build.py")
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_divergence_items_agree_everywhere(report):
    """`divergence_items` 在所有出现位置必须是同一个数。"""
    values = {
        "summary": report["summary"]["divergence_items"],
        "alignment_conclusion": report["alignment_conclusion"]["divergence_items"],
        "ledger.divergence_rows": report["ledger"]["divergence_rows"],
        "ledger.aggregate.total.divergent": report["ledger"]["aggregate"]["total"]["divergent"],
    }
    assert len(set(values.values())) == 1, f"同一概念出现多个值：{values}"


def test_divergence_items_equals_sum_of_axis_divergents(report):
    """总冲突数必须等于各轴 divergent 之和。"""
    total = report["ledger"]["aggregate"]["total"]["divergent"]
    by_axis = report["ledger"]["aggregate"]["by_axis"]
    axis_sum = sum(row.get("divergent", 0) for row in by_axis.values())
    assert total == axis_sum, f"total={total} 但各轴合计={axis_sum}"


def test_non_match_rows_is_reported_separately(report):
    """非 match 行（含 one_sided）必须有独立字段，不能混进 divergence。"""
    ledger = report["ledger"]
    assert "non_match_rows" in ledger, "缺少 non_match_rows 字段"
    assert ledger["non_match_rows"] >= ledger["divergence_rows"]
    # 差值应等于 one_sided + open_position 等非冲突行
    total = report["ledger"]["aggregate"]["total"]
    expected = total["one_sided"] + total["divergent"]
    assert ledger["non_match_rows"] == expected, (
        f"non_match_rows={ledger['non_match_rows']} 期望 {expected}")


def test_per_day_sums_to_total(report):
    """`per_day` 加总必须等于 total——读者会用它交叉验证。"""
    per_day = report.get("per_day") or {}
    total = report["ledger"]["aggregate"]["total"]
    assert sum(v["comparable"] for v in per_day.values()) == total["comparable"]
    assert sum(v["divergent"] for v in per_day.values()) == total["divergent"]


def test_inline_truncation_flag_matches_max_rows(report):
    """`inline_truncated` 必须与 `max_inline_rows` 一致。"""
    ledger = report["ledger"]
    cap = report["comparability"]["max_inline_rows"]
    rows = ledger["inline_rows"]
    assert len(rows) <= cap
    assert ledger["inline_truncated"] == (ledger["total_rows"] > cap)