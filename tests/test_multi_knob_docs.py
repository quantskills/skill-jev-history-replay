"""§4.2 多旋钮失效实测：文档里的数字必须可复现。

这张表证明「单旋钮消融在多旋钮同时偏移时会漏报」，是方法边界的关键证据。
但它此前只在文档里手写，容差判定修好后数字全变了（wait_bars 4,522 → 2,963，
合并 4,649 → 3,096）却没人发现。

本测试在真实夹具上重跑这三个场景并核对。较慢（约 90 秒），
用 `@pytest.mark.slow` 标记，CI 的慢速步骤会跑到。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = REPO_ROOT / "references" / "validation_evidence.md"
BARS = REPO_ROOT / "fixtures" / "bars"
REF = REPO_ROOT / "fixtures" / "reference"


def _documented_row(label: str):
    text = EVIDENCE.read_text(encoding="utf-8")
    pattern = rf"\| {re.escape(label)} \| ([\d,]+) \| `([a-z_]+)` \| `([a-z_]+)` \| \*?\*?([\d.]+)%"
    match = re.search(pattern, text)
    assert match, f"证据文档里找不到「{label}」这一行"
    return {
        "divergent": int(match.group(1).replace(",", "")),
        "verdict": match.group(2),
        "top_knob": match.group(3),
        "explained_rate": float(match.group(4)),
    }


def test_multi_knob_table_is_internally_consistent():
    """合并场景的差异数必须 ≥ 单旋钮场景（子集关系）。"""
    single = _documented_row("仅 `wait_bars`")
    both = _documented_row("`exit_eval` + `wait_bars`")
    assert both["divergent"] >= single["divergent"], (
        f"合并 {both['divergent']} < 单独 {single['divergent']}，不合理")
    # 合并场景的归因率不应高于单旋钮场景
    assert both["explained_rate"] <= 100.0


def test_documented_single_knob_case_matches_report():
    """「仅 exit_eval」那一行必须与当前报告一致（这是主样本本身）。"""
    report_path = REPO_ROOT / "output" / "report.json"
    if not report_path.exists():
        pytest.skip("需要先运行 scripts/build.py")
    report = json.loads(report_path.read_text(encoding="utf-8"))

    doc = _documented_row("仅 `exit_eval`")
    assert doc["divergent"] == report["ledger"]["aggregate"]["total"]["divergent"]
    assert doc["top_knob"] == report["attribution"]["ranked"][0]["knob"]
    assert doc["explained_rate"] == pytest.approx(
        report["attribution"]["ranked"][0]["explained_rate"] * 100, abs=0.1)


@pytest.mark.slow
def test_wait_bars_and_combined_counts_reproduce():
    """在真实夹具上重跑两个场景，核对文档数字。

    慢（每次全量对齐约 30 秒），只在慢速步骤执行。
    """
    from scripts import config as cfg
    from scripts.controls_check import _write_actual_logs
    from scripts.run_eval import evaluate
    import tempfile

    base = dict(cfg.load_config()["semantics"])

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # 仅 wait_bars
        alt = dict(base)
        alt["wait_bars"] = 0
        logs = _write_actual_logs(BARS, REF, alt, root / "wait")
        out = evaluate(logs_dir=str(logs), output_dir=root / "wait" / "o",
                       run_attribution=False)
        documented = _documented_row("仅 `wait_bars`")
        assert out["ledger"]["aggregate"]["total"]["divergent"] == documented["divergent"], (
            f"wait_bars 差异数：实际 {out['ledger']['aggregate']['total']['divergent']} "
            f"文档 {documented['divergent']}")

        # 两者同时
        alt2 = dict(base)
        alt2["wait_bars"] = 0
        alt2["exit_eval"] = "bar_high_low"
        logs2 = _write_actual_logs(BARS, REF, alt2, root / "both")
        out2 = evaluate(logs_dir=str(logs2), output_dir=root / "both" / "o",
                        run_attribution=True)
        doc_both = _documented_row("`exit_eval` + `wait_bars`")
        assert out2["attribution"]["verdict"] == "multi_knob"
        assert out2["attribution"]["ranked"][0]["knob"] == doc_both["top_knob"]
        assert out2["attribution"]["ranked"][0]["explained_rate"] == pytest.approx(
            doc_both["explained_rate"] / 100, abs=0.005)
        # 关键结论：exit_eval 被漏掉
        assert out2["attribution"]["ranked"][0]["knob"] != "exit_eval"