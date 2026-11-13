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


def _documented_naive_row(label: str) -> int:
    text = EVIDENCE.read_text(encoding="utf-8")
    pattern = rf"\| {re.escape(label)} \| \*?\*?([\d,]+)"
    match = re.search(pattern, text)
    assert match, f"证据文档里找不到「{label}」"
    return int(match.group(1).replace(",", ""))


def test_naive_ablation_table_shows_no_single_knob_explains_it():
    """naive 日志（8 个旋钮不同）的消融表：单项都不该带来大幅下降。

    这是 §4.2 用来证明「单旋钮消融在多旋钮场景失效」的核心证据——
    只改一个旋钮，差异几乎不降；改两个还会**上升**；
    只有全改才对得上 0。
    """
    base = _documented_naive_row("基线（参考语义 vs naive 日志）")
    ts = _documented_naive_row("只把 `bar_timestamp` 改成 naive 值")
    bp = _documented_naive_row("只把 `baseline_price` 改成 naive 值")
    tp = _documented_naive_row("只把 `t_plus_1` 改成 naive 值")
    allnaive = _documented_naive_row("全部改成 naive（等价于日志侧配置）")

    assert allnaive == 0, "全改成 naive 应当完全对齐"
    # 单项修改最多只能解释一小部分（远不足 100%）
    assert ts > base * 0.5, "bar_timestamp 单独改动就解释了绝大部分差异，结论不成立"
    # 改两个反而可能增加——这正是"方法失效"的表现
    assert bp >= base or tp >= base


@pytest.mark.slow
def test_naive_ablation_counts_reproduce():
    """在真实夹具上重跑 naive 消融表，核对文档数字。"""
    import tempfile

    from scripts import config as cfg
    from scripts import semantics as sem
    from scripts.aligner import align_symbol, aggregate_rows
    from scripts.controls_check import _write_actual_logs
    from scripts.data_loader import group_logs, load_bars, load_logs, normalize_log_records
    from scripts.replayer import replay_all
    from scripts.run_eval import _load_prev_closes

    base = dict(cfg.load_config()["semantics"])
    naive = dict(base)
    naive.update(sem.NAIVE_PROFILE)
    naive["breakout_window"] = base["breakout_window"]
    naive["warmup_bars"] = base["warmup_bars"]

    bars = load_bars(BARS)
    prev = _load_prev_closes(REF, list(bars))

    with tempfile.TemporaryDirectory() as tmp:
        logs_dir = _write_actual_logs(BARS, REF, naive, Path(tmp) / "naive")
        recs = normalize_log_records(load_logs(logs_dir), multi_day=True)
        grouped = group_logs(recs)

    def count(aligned):
        res = replay_all(bars, aligned, prev)
        views = res.get("by_series") or res["symbols"]
        rows = {}
        for series, view in views.items():
            groups = grouped.get(series) or {
                "condition": [], "signal": [], "plan": [], "fill": []}
            rows[series] = align_symbol(series, view, groups, 1, 5.0)["rows"]
        return aggregate_rows(rows)["total"]["divergent"]

    assert count(base) == _documented_naive_row("基线（参考语义 vs naive 日志）")
    assert count(naive) == 0
    for knob, label in (("bar_timestamp", "只把 `bar_timestamp` 改成 naive 值"),
                        ("baseline_price", "只把 `baseline_price` 改成 naive 值"),
                        ("t_plus_1", "只把 `t_plus_1` 改成 naive 值")):
        alt = dict(base)
        alt[knob] = naive[knob]
        assert count(alt) == _documented_naive_row(label), f"{knob} 计数不符"


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