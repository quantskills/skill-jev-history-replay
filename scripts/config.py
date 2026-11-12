"""配置加载与语义参数定义。

优先级：run() 参数 > config 覆盖 > config/*.yaml > 代码内置默认值。

本模块只做配置合并与默认值，不解释语义；语义参数的含义见
`scripts/semantics.py` 与 `references/semantics_matrix.md`。
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]

# 参考语义（aligned）：文档化的 JEV 条件与回放语义约定。
# 所有字段都是"可被另一种解释替换"的旋钮，替换后由账本给出差异归因。
REFERENCE_SEMANTICS: Dict[str, Any] = {
    # 分钟线时间戳所指的时点：bar_end = 该分钟的收盘时刻（panda_data 口径）
    "bar_timestamp": "bar_end",
    # 涨幅基准价
    "baseline_price": "prev_close",
    # 突破比较所用的历史价格字段
    "breakout_field": "high",
    # 突破回看窗口（根）
    "breakout_window": 20,
    # 突破窗口是否把当前 bar 计入（计入即"自己和自己比"，必然偏松）
    "breakout_includes_current": False,
    # 条件需要连续成立的根数
    "persistence_bars": 2,
    # 最少预热根数，不足时不产生信号
    "warmup_bars": 20,
    # 触发所需的最小涨幅（相对 baseline_price）
    "signal_gain_pct": 0.01,
    # 信号后等待多少根再入场（0 = 信号当根收盘入场）
    "wait_bars": 1,
    # 入场价与退出价取哪个字段
    "entry_price": "next_open",
    "exit_eval": "bar_close",
    # 风控
    "stop_loss_pct": 0.005,
    "take_profit_pct": 0.01,
    "max_hold_bars": 30,
    # 同标的再次触发所需的最小间隔（根）
    "cooldown_bars": 10,
    # 时间边界（HH:MM）
    "no_entry_after": "14:45",
    "force_exit_time": "14:45",
    # 是否遵守 A 股 T+1（当日买入不可当日卖出）
    "t_plus_1": True,
    # 成本
    "fee_bps": 5.0,
    "slippage_bps": 2.0,
    # 仓位与资金
    "initial_capital": 1_000_000.0,
    "position_pct": 0.1,
    "lot_size": 100,
}

_DEFAULTS: Dict[str, Any] = {
    "bars_dir": "fixtures/bars",
    "logs_dir": None,
    "output_dir": "output",
    # 日志来源标记：actual = 真实 JEV 日志；synthetic = 由 log_synth 生成
    "log_source": "auto",
    # 合成日志使用的"已记录语义"配置（仅在无真实日志时生效）
    "logged_profile": "jev_assumed",
    # 账本比对容差
    "time_tolerance_minutes": 1,
    "price_tolerance_bps": 5.0,
    # 归因：单旋钮消融后可解释的周期占比阈值
    "explained_rate_threshold": 0.95,
    # 最小周期数（不足则 verdict 只能 inconclusive）
    "min_cycles": 20,
    # 报告里最多内联多少条账本行（完整账本写 JSONL）
    "max_inline_rows": 50,
    "semantics": copy.deepcopy(REFERENCE_SEMANTICS),
}


def _load_yaml_config(config_path: Path) -> Dict[str, Any]:
    if not config_path.exists():
        return {}
    try:
        import yaml  # type: ignore[import-untyped]

        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except ImportError:
        return {}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_config(
    config_path: str | Path | None = None,
    overrides: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """合并配置：overrides > 环境变量 > YAML > 默认值。"""
    config = copy.deepcopy(_DEFAULTS)

    if config_path is None:
        config_path = REPO_ROOT / "config" / "replay_config.yaml"
    config = _deep_merge(config, _load_yaml_config(Path(config_path)))

    # 环境变量（JEV_ 前缀），仅覆盖标量顶层键
    for key in _DEFAULTS:
        env_val = os.environ.get(f"JEV_{key.upper()}")
        if env_val is None:
            continue
        default_val = _DEFAULTS[key]
        if isinstance(default_val, bool):
            config[key] = env_val.lower() in ("true", "1", "yes")
        elif isinstance(default_val, int):
            config[key] = int(env_val)
        elif isinstance(default_val, float):
            config[key] = float(env_val)
        else:
            config[key] = env_val

    if overrides:
        config = _deep_merge(config, overrides)

    return config