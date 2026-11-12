"""逐笔核对：价格与收益算术必须能从原始 K 线独立重算出来。"""

from __future__ import annotations

import pytest

from scripts import trade_audit


def test_audit_runs_and_reports_shape():
    result = trade_audit.run_audit(sample=50)
    assert result["total_closed_cycles"] > 0
    assert result["sampled"] <= 50
    assert result["checked"] > 0
    assert "failures" in result


def test_all_sampled_trades_pass():
    """抽样 120 笔，任意一笔的价格或算术有误都必须报出来。"""
    result = trade_audit.run_audit(sample=120)
    assert result["ok"], (
        "逐笔核对失败：\n"
        + "\n".join(
            f"  {f['entry_series']} → {f['exit_series']}: {f['problems']}"
            for f in result["failures"]
        )
    )


def test_audit_covers_cross_day_trades():
    """样本里应包含跨日交易——那是 T+1 逻辑的主战场。"""
    result = trade_audit.run_audit(sample=200)
    assert result["cross_day_checked"] > 0, "抽样中没有任何跨日交易"


def test_audit_detects_wrong_entry_price():
    """构造一笔入场价造假的周期，核对器必须抓到。"""
    from scripts import config as cfg
    from scripts import data_loader
    from scripts.replayer import replay_all
    from scripts.run_eval import _load_prev_closes
    from pathlib import Path

    root = Path(cfg.REPO_ROOT)
    bars = data_loader.load_bars(root / "fixtures" / "bars")
    prev = _load_prev_closes(root / "fixtures" / "reference", list(bars))
    sem = dict(cfg.load_config()["semantics"])
    replay = replay_all(bars, sem, prev)

    cycle = None
    for result in replay["symbols"].values():
        for c in result["cycles"]:
            if c["status"] == "closed":
                cycle = dict(c)
                break
        if cycle:
            break
    assert cycle is not None

    # 故意把入场价改掉 1%
    cycle["entry_price"] = cycle["entry_price"] * 1.01
    audit = trade_audit.audit_trade(cycle, bars, sem)
    assert not audit["ok"]
    assert any("入场价不符" in p or "gross" in p or "net" in p for p in audit["problems"])
