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

# 配置降级时记录的原因，供报告回显
_LOAD_YAML_WARNINGS: list[str] = []


class ConfigError(ValueError):
    """配置错误。与 `run_eval.ReplayError` 分开定义以避免循环导入。"""

    def __init__(self, code: str, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


def load_warnings() -> list[str]:
    """返回本次进程内配置加载过程中的降级原因。"""
    return list(_LOAD_YAML_WARNINGS)


_DEFAULTS: Dict[str, Any] = {
    "bars_dir": "fixtures/bars",
    # 必须与 config/replay_config.yaml 保持一致。
    # 曾设成 None，导致缺 pyyaml 时静默走合成模式——评测仍能跑，
    # 但用的是合成日志而不是 fixtures/logs 里的真实日志，属于静默降级。
    "logs_dir": "fixtures/logs",
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
    # 归因时消融配置必须保留的最小可比项比例（防止"配对消失"冒充"冲突消失"）
    "min_comparable_retention": 0.05,
    # 最小周期数（不足则 verdict 只能 inconclusive）
    "min_cycles": 20,
    # 报告里最多内联多少条账本行（完整账本写 JSONL）
    "max_inline_rows": 50,
    # 账本落盘模式：diff = 只写非 match 记录（默认，1M 行里 96% 是无信息量的
    # jev_missing）；full = 全量逐行。
    "ledger_mode": "diff",
    "semantics": copy.deepcopy(REFERENCE_SEMANTICS),
}


def _load_yaml_config(config_path: Path) -> Dict[str, Any]:
    if not config_path.exists():
        return {}
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        # 缺 pyyaml 时回退内置默认值。这是**有意的降级**，不是错误，
        # 但必须可见：调用方应知道本次运行没读到 config/replay_config.yaml。
        _LOAD_YAML_WARNINGS.append(
            f"缺少 pyyaml，未加载 {config_path}，使用内置默认值"
        )
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


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
    """合并配置：overrides > 环境变量 > YAML > 默认值。

    `overrides` 里的未知键会抛 `ConfigError`。`input_data` 对未知字段
    坚持报 `unknown_field`（"刻意不做静默忽略"），`config` 却曾静默接受
    拼错的键——写 `time_tolerence_minutes: 5` 会悄悄用回默认值 1，
    评测结果看似正常却与预期不符。两边口径必须一致。
    """
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
        unknown = set(overrides) - set(_DEFAULTS)
        if unknown:
            raise ConfigError(
                "unknown_config",
                f"未知配置键：{sorted(unknown)}",
                hint=f"允许的键：{sorted(_DEFAULTS)}",
            )
        config = _deep_merge(config, overrides)

    return config