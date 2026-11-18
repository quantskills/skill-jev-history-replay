"""语义旋钮（semantics knobs）注册表。

「语义」指的是同一份 OHLCV 与同一条自然语言规则，落到代码里时仍必须做出的
解释选择。例如「突破前 20 根高点」——20 根是否含当前根、「前」指的是 high 还是
close、分钟线时间戳代表该分钟开始还是结束。这些选择不改变意图，却会改变逐根
判断结果、信号时点、等待根数与成交价。

本模块把每种解释都做成显式命名档位，使「JEV 条件 vs 回放器」的差异可以被
逐项归因，而不是笼统地说"实现不一致"。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List

# 每个旋钮的可选值及其含义。用于文档、校验与归因实验构造。
KNOB_VALUES: Dict[str, Dict[str, str]] = {
    "bar_timestamp": {
        "bar_end": "分钟线时间戳=该分钟结束时刻（PandaData 分钟线口径，09:31 覆盖 09:30–09:31）",
        "bar_start": "分钟线时间戳=该分钟开始时刻（09:31 覆盖 09:31–09:32）",
    },
    "baseline_price": {
        "prev_close": "涨幅基准=前收盘价",
        "day_open": "涨幅基准=当日开盘价",
        "window_start": "涨幅基准=突破窗口首根的开盘价",
    },
    "breakout_field": {
        "high": "突破参照=窗口内最高价",
        "close": "突破参照=窗口内最高收盘价",
        "open": "突破参照=窗口内最高开盘价",
    },
    "breakout_includes_current": {
        "true": "突破窗口包含当前根（自己与自己比，条件恒偏松）",
        "false": "突破窗口不含当前根（仅与历史比）",
    },
    "persistence_bars": {
        "1": "条件成立 1 根即触发",
        "2": "条件需连续成立 2 根才触发",
        "3": "条件需连续成立 3 根才触发",
    },
    "wait_bars": {
        "0": "信号当根收盘即入场",
        "1": "信号后等待 1 根入场",
        "2": "信号后等待 2 根入场",
    },
    "entry_price": {
        "next_open": "入场价=等待结束那根的开盘价",
        "signal_close": "入场价=信号根的收盘价",
    },
    "exit_eval": {
        "bar_close": "退出按收盘价结算",
        "bar_high_low": "退出按触发根内先到价（止损优先，保守）",
    },
    "t_plus_1": {
        "true": "遵守 T+1：当日入场不得当日卖出",
        "false": "不施加 T+1（日内往返可成交）",
    },
    "cooldown_bars": {
        "0": "无冷却，条件持续成立可连续触发",
        "10": "同一标的上次信号后至少间隔 10 根",
    },
}

# 逻辑型旋钮的 JSON 表示
BOOLEAN_KNOBS = {"breakout_includes_current", "t_plus_1"}

# 「字面直译」基线：未做任何领域推断时最自然的读法。
# 作为 value_assessment 的冻结基线，用来量化"显式化语义"到底改变了多少判断。
NAIVE_PROFILE: Dict[str, Any] = {
    "bar_timestamp": "bar_start",
    "baseline_price": "day_open",
    "breakout_field": "close",
    # 含当前根会让 close > max(close 含当前) 恒假，任何实现都不会这样写；
    # 字面直译取「不含当前根」，但仍用 close 而非 high，且基准为当日开盘。
    "breakout_includes_current": False,
    "persistence_bars": 1,
    "wait_bars": 0,
    "entry_price": "signal_close",
    "exit_eval": "bar_close",
    "t_plus_1": False,
    "cooldown_bars": 0,
}

# JEV 日志侧默认假设档（仅在缺少真实日志、走合成模式时使用）
JEV_ASSUMED_PROFILE: Dict[str, Any] = {
    "bar_timestamp": "bar_end",
    "baseline_price": "prev_close",
    "breakout_field": "high",
    "breakout_includes_current": False,
    "persistence_bars": 2,
    "wait_bars": 1,
    "entry_price": "next_open",
    "exit_eval": "bar_high_low",
    # 多日夹具下 T+1 必须与参考语义一致，否则合成日志里的"执行"根本
    # 无法达成——重放会把当日仓位锁到次日，日志却按当日结算，
    # 两者差异全部来自这一点，等于用错了对照对象。
    "t_plus_1": True,
    "cooldown_bars": 10,
}

# 已登记档位。只有登记过的组合才能被 --logged-profile 引用，避免隐式配置漂移。
PROFILES: Dict[str, Dict[str, Any]] = {
    "naive_literal": NAIVE_PROFILE,
    "jev_assumed": JEV_ASSUMED_PROFILE,
}

# 除档位外，回放侧还有一组来自配置文件的阈值/风控/资金参数，同样计入语义哈希。
#
# `initial_capital` / `lot_size` / `position_pct` 曾被漏掉——它们会改变
# 实际成交股数与资金约束，直接影响回放结果，却不参与哈希，于是资金配置
# 完全不同的两次 run 会被 `compare_baseline` 判为"可比较"。
RISK_KNOBS = (
    "signal_gain_pct",
    "breakout_window",
    "warmup_bars",
    "stop_loss_pct",
    "take_profit_pct",
    "max_hold_bars",
    "no_entry_after",
    "force_exit_time",
    "fee_bps",
    "slippage_bps",
    "initial_capital",
    "lot_size",
    "position_pct",
)


def get_profile(name: str) -> Dict[str, Any]:
    """按名称取档位；未登记则抛 KeyError（由上层转成结构化错误）。"""
    if name not in PROFILES:
        raise KeyError(
            f"未登记的语义档位：{name}；可选：{sorted(PROFILES)}"
        )
    return dict(PROFILES[name])


def extract_knobs(semantics: Dict[str, Any]) -> Dict[str, Any]:
    """抽出参与哈希与归因的键，保持稳定顺序。"""
    keys: List[str] = list(KNOB_VALUES) + list(RISK_KNOBS)
    return {key: semantics[key] for key in keys if key in semantics}


def semantics_hash(semantics: Dict[str, Any]) -> str:
    """语义指纹。任何旋钮变化都会改变哈希，从而禁止跨配置比对。"""
    payload = json.dumps(extract_knobs(semantics), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def validate_semantics(semantics: Dict[str, Any]) -> List[str]:
    """返回问题列表，空列表表示合法。"""
    problems: List[str] = []
    for knob, allowed in KNOB_VALUES.items():
        if knob not in semantics:
            problems.append(f"缺少语义旋钮 {knob}")
            continue
        value = semantics[knob]
        if knob in BOOLEAN_KNOBS:
            if not isinstance(value, bool):
                problems.append(f"{knob} 必须是 bool，收到 {type(value).__name__}")
            continue
        if knob in ("persistence_bars", "wait_bars", "cooldown_bars"):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                problems.append(f"{knob} 必须是非负整数")
            continue
        if str(value) not in allowed:
            problems.append(
                f"{knob}={value!r} 不在允许取值 {sorted(allowed)} 内"
            )
    for key in ("signal_gain_pct", "stop_loss_pct", "take_profit_pct"):
        value = semantics.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            problems.append(f"{key} 必须是数值")
        elif value < 0:
            problems.append(f"{key} 不得为负")
    for key in ("breakout_window", "warmup_bars", "max_hold_bars"):
        value = semantics.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            problems.append(f"{key} 必须是 >=1 的整数")
    return problems


def alternative_value(semantics: Dict[str, Any], knob: str) -> Any:
    """给归因实验用：返回该旋钮的"另一个"取值。

    选择规则是确定性的，保证归因报告可复现：
    - 布尔型 → 取反
    - 计数型 → 在 1/2 与 0/1 之间切换
    - 数值型（breakout_window）→ 减半（不小于 2）
    - 枚举型 → 按 KNOB_VALUES 中登记的声明顺序取下一个
    """
    current = semantics[knob]
    if knob in BOOLEAN_KNOBS:
        return not current
    if knob in ("persistence_bars", "wait_bars", "cooldown_bars"):
        return 1 if current == 2 else (0 if current else 1)
    if knob == "breakout_window":
        return max(2, int(current) // 2)
    options = list(KNOB_VALUES[knob])
    try:
        idx = options.index(str(current))
    except ValueError:
        return options[0]
    return options[(idx + 1) % len(options)]