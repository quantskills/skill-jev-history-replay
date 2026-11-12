"""数据质量审计：未建模状态的占比必须可算、可查，且不被静默当成 0。"""

from __future__ import annotations

import pytest

from scripts import data_quality_audit as dqa


def test_board_classification():
    assert dqa._board_of("600519.SH") == "default"
    assert dqa._board_of("300750.SZ") == "chinext"
    assert dqa._board_of("301276.SZ") == "chinext"
    assert dqa._board_of("688981.SH") == "star"
    assert dqa._board_of("830799.BJ") == "bj"


def test_limit_pct_by_board():
    assert dqa.LIMIT_PCT["default"] == 0.10
    assert dqa.LIMIT_PCT["chinext"] == 0.20
    assert dqa.LIMIT_PCT["star"] == 0.20
    assert dqa.LIMIT_PCT["st"] == 0.05


def test_offline_audit_runs_without_credentials():
    """离线模式必须能跑，且把 ST/停牌标为「未核验」而不是 0。"""
    result = dqa.audit(offline=True)
    assert result["series_count"] > 0
    assert result["checks"]["st"]["count"] is None, \
        "离线时 ST 未核验，不能报成 0"
    assert result["checks"]["st"]["share"] is None
    assert "未核验" in result["checks"]["st"]["note"]
    # 涨跌停在离线模式仍可算
    assert result["checks"]["limit_up_touch"]["share"] is not None


def test_audit_exposes_unmodeled_share():
    result = dqa.audit(offline=True)
    assert "unmodeled_share" in result
    assert "limit_touch" in result["unmodeled_share"]
    assert result["overall_unmodeled_upper_bound"] is not None
    assert result["verdict"]["level"] in ("minor", "moderate", "material", "unknown")


def test_verdict_thresholds():
    assert dqa._verdict({"overall_unmodeled_upper_bound": 0.005})["level"] == "minor"
    assert dqa._verdict({"overall_unmodeled_upper_bound": 0.05})["level"] == "moderate"
    assert dqa._verdict({"overall_unmodeled_upper_bound": 0.20})["level"] == "material"
    assert dqa._verdict({})["level"] == "unknown"


def test_report_surfaces_data_quality():
    """报告必须带上数据质量的审计结果，而不能只在文档里写 "不含"。"""
    from scripts import config as cfg
    from scripts.run_eval import evaluate
    import tempfile

    cfg._LOAD_YAML_WARNINGS.clear()
    r = evaluate(output_dir=tempfile.mkdtemp(), run_attribution=False)
    dq = r["applicability"]["unmodeled_market_states"]
    assert dq is not None, "applicability 里缺未建模状态审计"
    assert "checks" in dq
    note = r["applicability"]["unmodeled_market_states_note"]
    assert "未建模" in note or "未核验" in note
