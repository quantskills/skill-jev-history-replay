"""归因阈值的接线守卫。

两条缺陷都在这里被钉住：

1. `explained_rate_threshold` / `min_comparable_retention` 曾经是**死配置**——
   写在 `config.py` 与 `replay_config.yaml` 顶层，而 `run_ablation` 只从
   `semantics` 字典里 `.get()`。用户改 YAML 完全无效，却谁也发现不了，
   因为默认值恰好和内置值相同。
2. 接线一旦写回，就必须证明阈值**真的参与判定**，而不是又多一个传了没用的参数。
   所以这里用受控的小型场景：解释率固定 0.6，只让阈值变，verdict 必须跟着变。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts import attribution, config as cfg  # noqa: F401
from scripts import aligner, semantics as sem

REPO_ROOT = Path(__file__).resolve().parents[1]


def _scenario(monkeypatch, *, comparable: int, divergent: int):
    """把消融的内层换成受控桩件：不看真实 K 线，只看注入的可比/差异数。"""
    def fake_replay_all(bars, semantics, prev_closes, **kw):
        return {"by_series": {"000001.SZ": {"signals": [], "fills": []}}}

    def fake_align_symbol(symbol, symbol_replay, groups, tol, price_tol):
        return {"rows": []}

    def fake_aggregate(rows_by_symbol):
        return {"total": {"comparable": comparable, "divergent": divergent,
                          "match": comparable - divergent, "one_sided": 0}}

    monkeypatch.setattr(attribution, "replay_all", fake_replay_all)
    monkeypatch.setattr(aligner, "align_symbol", fake_align_symbol)
    monkeypatch.setattr(aligner, "aggregate_rows", fake_aggregate)


def _run(monkeypatch, **kw):
    _scenario(monkeypatch, comparable=100, divergent=40)
    semantics = dict(cfg.REFERENCE_SEMANTICS)
    return attribution.run_ablation(
        bars_by_symbol={"000001.SZ": {"bars": []}},
        semantics=semantics,
        prev_closes={"000001.SZ": 10.0},
        baseline_divergences=100,
        baseline_comparable=100,
        log_groups_by_symbol={},
        tol_minutes=1,
        price_tolerance_bps=5.0,
        knobs=["bar_timestamp"],
        **kw,
    )


def test_explained_rate_of_sixty_is_not_single_knob_at_default_threshold(monkeypatch):
    """解释率 0.6 < 默认 0.95 → 只能判多因素，不能报"主要成因"。"""
    result = _run(monkeypatch)
    assert result["ranked"][0]["explained_rate"] == pytest.approx(0.6)
    assert result["verdict"] == "multi_knob"


def test_lowering_the_threshold_changes_the_verdict(monkeypatch):
    """同一个 0.6，阈值放到 0.5 就必须改口——证明参数真的参与判定。"""
    result = _run(monkeypatch, explained_rate_threshold=0.5)
    assert result["verdict"] == "single_knob"


def test_raising_the_retention_floor_refuses_to_credit_explanation(monkeypatch):
    """retention 门槛高于实测值时，解释一律记 0：不许靠"配对消失"冒充解释。"""
    result = _run(monkeypatch, min_comparable_retention=1.01)
    assert result["ranked"][0]["explained"] == 0
    assert result["verdict"] == "unexplained"


def test_semantics_fallback_keeps_old_callers_working(monkeypatch):
    """没传显式参数时，semantics 里的同名键仍然生效（向后兼容旧调用方）。"""
    _scenario(monkeypatch, comparable=100, divergent=40)
    semantics = dict(cfg.REFERENCE_SEMANTICS)
    semantics["explained_rate_threshold"] = 0.5
    result = attribution.run_ablation(
        {"000001.SZ": {"bars": []}}, semantics, {"000001.SZ": 10.0},
        100, 100, {}, 1, 5.0, knobs=["bar_timestamp"],
    )
    assert result["verdict"] == "single_knob"


def test_explicit_argument_beats_semantics_key(monkeypatch):
    _scenario(monkeypatch, comparable=100, divergent=40)
    semantics = dict(cfg.REFERENCE_SEMANTICS)
    semantics["explained_rate_threshold"] = 0.5
    result = attribution.run_ablation(
        {"000001.SZ": {"bars": []}}, semantics, {"000001.SZ": 10.0},
        100, 100, {}, 1, 5.0, knobs=["bar_timestamp"],
        explained_rate_threshold=0.99,
    )
    assert result["verdict"] == "multi_knob"


def test_main_flow_passes_config_thresholds_into_ablation():
    """接线守卫：run_eval 必须把两个 config 键显式传给 run_ablation。

    只断言"键存在于 load_config 结果里"是不够的——那正是缺陷 #70 蒙混过关的原因：
    键活着，消费者从来没读过它。
    """
    source = (REPO_ROOT / "scripts" / "run_eval.py").read_text(encoding="utf-8")
    call = re.search(r"attribution\.run_ablation\((.*?)\n    \)", source, re.S)
    assert call, "找不到 run_ablation 调用点"
    for key in ("explained_rate_threshold", "min_comparable_retention"):
        assert f'config["{key}"]' in call.group(1), f"{key} 没有从 config 传进消融"
