"""报告里 `ledger` 的辅助字段必须被文档覆盖且行为正确。

`by_axis_prior` 与 `first_divergence` 长期没有出现在 `api_guide.md` 里，
读者拿到报告能看到字段却不知道含义。而 `api_guide` 里已有的
`total_rows` / `non_match_rows` / `divergence_rows` 三个数又整体过期。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORT = REPO_ROOT / "output" / "report.json"
API_GUIDE = REPO_ROOT / "references" / "api_guide.md"
LEDGER = REPO_ROOT / "output" / "ledger.jsonl"


@pytest.fixture(scope="module")
def report():
    if not REPORT.exists():
        pytest.skip("需要先运行 scripts/build.py")
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_ledger_aux_fields_are_documented():
    """`by_axis_prior` 与 `first_divergence` 必须写进 api_guide。"""
    text = API_GUIDE.read_text(encoding="utf-8")
    for field in ("by_axis_prior", "first_divergence"):
        assert field in text, f"api_guide 未说明 `{field}`"


def test_by_axis_prior_matches_code():
    """报告里的先验必须与 `aligner.PRIOR` 完全一致（各处一份会漂）。"""
    from scripts.aligner import PRIOR

    report_prior = json.loads(REPORT.read_text(encoding="utf-8"))["ledger"]["by_axis_prior"]
    assert set(report_prior) == set(PRIOR)
    for axis, sentence in PRIOR.items():
        assert report_prior[axis] == sentence, f"{axis} 的先验与代码不符"


def test_first_divergence_exists_in_ledger(report):
    """`first_divergence` 必须真实存在于账本里，不能是编出来的。

    若它指向一条账本中不存在的行，读者按它排查会找不到任何东西。
    """
    fd = report["ledger"].get("first_divergence")
    if not fd:
        pytest.skip("本次运行没有差异")
    if not LEDGER.exists():
        pytest.skip("需要 output/ledger.jsonl")

    rows = [json.loads(line) for line in LEDGER.open(encoding="utf-8") if line.strip()]
    matched = [
        r for r in rows
        if r.get("symbol") == fd["symbol"]
        and r.get("axis") == fd["axis"]
        and r.get("field") == fd.get("field")
        and r.get("status") == "divergent"
    ]
    assert matched, f"first_divergence 在账本中找不到对应行：{fd}"


def test_api_guide_ledger_counts_match_report(report):
    """api_guide 里列出的三个行数必须与当前报告一致。"""
    text = API_GUIDE.read_text(encoding="utf-8")
    ledger = report["ledger"]
    for field in ("total_rows", "non_match_rows", "divergence_rows"):
        actual = ledger.get(field)
        assert actual is not None
        # 表格里形如 `| `total_rows` | 说明 | 1,015,406 |`
        pattern = rf"\| `{field}` \|[^|]*\| ([\d,]+) \|"
        match = re.search(pattern, text)
        assert match, f"api_guide 的表格里没有 `{field}` 这一行"
        documented = int(match.group(1).replace(",", ""))
        assert documented == actual, (
            f"`{field}` 文档写 {documented}，实际 {actual}")

def test_diff_mode_ledger_cannot_compute_match_rate(report):
    """默认 diff 模式下落盘的账本**不含 match 行**，不能用它算一致率。

    读者很容易拿 `output/ledger.jsonl` 去统计"匹配多少条"，
    结果分母严重偏小（本样本 match=35,767 一条都没写）。
    api_guide 此前只列了 status 枚举（含 match），没说默认不会出现，
    属于会直接导致错误分析的文档缺口。
    """
    if not LEDGER.exists():
        pytest.skip("需要 output/ledger.jsonl")

    rows = [json.loads(line) for line in LEDGER.open(encoding="utf-8") if line.strip()]
    statuses = {r["status"] for r in rows}

    assert "match" not in statuses, (
        "diff 模式下账本不应包含 match 行；若出现说明模式或实现变了，"
        "需要同步更新文档说明")
    # 只有需要追溯的行才落盘
    assert statuses <= {"divergent", "open_position", "time_shifted",
                        "replay_only", "jev_only"}

    # 报告里的 match 数远大于账本行数——正是"不能用来算一致率"的证据
    total_match = report["ledger"]["aggregate"]["total"]["match"]
    assert total_match > len(rows), (
        "match 数应远超落盘行数；若不然，本条说明的前提需重新审视")


def test_api_guide_warns_about_diff_mode():
    """api_guide 必须明确警告「不能用 ledger 算一致率」。"""
    text = API_GUIDE.read_text(encoding="utf-8")
    assert "不会出现它" in text or "不写 `match` 行" in text, (
        "api_guide 未说明 diff 模式下没有 match 行")
    assert "不能用 `ledger.jsonl` 统计一致率" in text, (
        "api_guide 未明确警告不能用账本算一致率")
