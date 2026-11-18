# 语义旋钮全表 / Semantics Matrix

本文件是 `scripts/semantics.py` 中 `KNOB_VALUES` 的人类可读版本。
两者必须同步；`tests/test_semantics.py` 会校验代码侧的取值集合。

---

## 1. 为什么需要这张表

自然语言写下来的一句"突破前 20 根高点且涨幅超过 1% 就买"，在代码里至少隐含
以下判断：

```
用什么价算涨幅？      → baseline_price
"前 20 根" 含不含当前根？ → breakout_includes_current
"高点" 是 high 还是 close？ → breakout_field
09:31 这根代表 09:30–09:31 还是 09:31–09:32？ → bar_timestamp
"就买" 是这根收盘买还是下一根开盘买？ → entry_price / wait_bars
```

每一种选择都不改变规则意图，但都改变结果。把它们做成旋钮，差异才可归因。

---

## 2. 全表

| 旋钮 | 允许取值 | 默认 | 含义 |
|---|---|---|---|
| `bar_timestamp` | `bar_end` | `bar_end` | 时间戳 = 该分钟结束时刻（PandaData 分钟线口径：09:31 覆盖 09:30–09:31） |
| | `bar_start` | | 时间戳 = 该分钟开始时刻（09:31 覆盖 09:31–09:32） |
| `baseline_price` | `prev_close` | `prev_close` | 涨幅基准 = 前收盘价 |
| | `day_open` | | 涨幅基准 = **分钟线首根（09:31）的 open**，不是日线接口的 `open` |
| | `window_start` | | 涨幅基准 = 突破窗口首根开盘价 |
| `breakout_field` | `high` | `high` | 突破参照 = 窗口内最高价 |
| | `close` | | 突破参照 = 窗口内最高收盘价 |
| | `open` | | 突破参照 = 窗口内最高开盘价 |
| `breakout_includes_current` | `true` | `false` | 窗口含当前根（close > max(含自身) 恒假，几乎总是错误配置） |
| | `false` | | 只与历史比 |
| `breakout_window` | 正整数 | `20` | 回看根数 |
| `persistence_bars` | 1 / 2 / 3 | `2` | 条件需连续成立的根数 |
| `warmup_bars` | 正整数 | `20` | 不足这么多根不产生判断 |
| `signal_gain_pct` | 非负数 | `0.01` | 触发所需最小涨幅 |
| `wait_bars` | 0 / 1 / 2 | `1` | 信号后**完全空过**的根数 |
| `entry_price` | `next_open` | `next_open` | 入场价 = 信号后第 `wait+1` 根开盘 |
| | `signal_close` | | 入场价 = 信号后第 `wait` 根收盘 |
| `exit_eval` | `bar_close` | `bar_close` | 退出按收盘价判定 |
| | `bar_high_low` | | 退出按根内触价判定（止损优先，更保守） |
| `stop_loss_pct` | 非负数 | `0.005` | 止损阈值 |
| `take_profit_pct` | 非负数 | `0.01` | 止盈阈值 |
| `max_hold_bars` | 正整数 | `30` | 最长持有根数 |
| `cooldown_bars` | 非负整数 | `10` | 同标的两次触发最小间隔 |
| `no_entry_after` | `HH:MM` | `14:45` | 晚于该时刻不入场 |
| `force_exit_time` | `HH:MM` | `14:45` | 到达该时刻强制退出 |
| `t_plus_1` | bool | `true` | 当日入场不可当日卖出 |
| `fee_bps` | 非负数 | `5` | 单边手续费（基点） |
| `slippage_bps` | 非负数 | `2` | 单边滑点（基点） |
| `initial_capital` | 正数 | `1000000` | 初始资金 |
| `position_pct` | (0,1] | `0.1` | 单次仓位占比 |
| `lot_size` | 正整数 | `100` | 最小交易单位 |

### 一个容易忽略的口径：`day_open` 与集合竞价

`day_open` 取的是**分钟线首根（09:31）的 `open`**，而日线接口的 `open`
可能来自集合竞价，两者在少数标的上会不同。

实测（14 天 × 300 只 = 4,200 序列）：**2 条序列不同（0.05%）**，
最大相对差 1.385%——

| 日期 | 标的 | 日线 open | 分钟线首根 open |
|---|---|---|---|
| 20261029 | 002193.SZ | 3.61 | 3.66 |
| 20261109 | 300462.SZ | 10.46 | 10.40 |

影响范围有限：`day_open` 只用于 `baseline_price=day_open` 的场景，
而参考语义与 `jev_assumed` 都用 `prev_close`，
所以**主对齐结论不受影响**，只在 `naive_literal` 基线（价值评估）里体现。

若你的 JEV 条件用的是日线开盘价，接入时应把基准改成你的口径，
或在上游把首根 `open` 对齐到日线 `open`。

---

## 3. `wait_bars` 的精确定义

这是最容易被两套实现理解成不同东西的一项，因此单独说明。

设信号发生在第 `i` 根（0-based）。

| 配置 | 入场根 | 入场价 |
|---|---|---|
| `wait_bars=0, entry_price=signal_close` | `i` | 第 `i` 根收盘 |
| `wait_bars=0, entry_price=next_open` | `i+1` | 第 `i+1` 根开盘 |
| `wait_bars=1, entry_price=signal_close` | `i+1` | 第 `i+1` 根收盘 |
| `wait_bars=1, entry_price=next_open` | `i+2` | 第 `i+2` 根开盘 |

账本里同时记录两个字段，避免歧义：

- `wait_bars`：配置值本身（信号后空过的根数）
- `bars_to_entry`：信号根到入场根的实际根数差

对齐时若 JEV 日志只给 `wait_bars`，就直接比配置值；
若只给 `entry_time`，则由时间反推 `bars_to_entry`。

---

## 4. 档位（Profiles）

| 档位 | 用途 | 关键取值 |
|---|---|---|
| `naive_literal` | **价值评估的冻结基线**：不做任何领域推断的字面直译 | `day_open` 基准、`close` 参照、不含当前根、单根触发、信号当根收盘入场、无 T+1、无冷却 |
| `jev_assumed` | 无真实日志时生成合成日志的**假设**档位 | `prev_close` 基准、`high` 参照、2 根确认、`next_open` 入场、`bar_high_low` 退出、无 T+1 |

`naive_literal` 里 `breakout_includes_current` 取 `false`：含当前根会让
`close > max(含自身)` 恒假，那不是"字面直译"，而是配置错误。
价值评估要对比的是两种**都成立**的实现，不是一种实现和一种 bug。

---

## 5. 哈希与可比性

`semantics_hash` 由上面全部旋钮（除风控阈值外的 11 个判定旋钮 + 10 个风控参数）
的规范 JSON 计算，取 SHA-256 前 16 位。

- 任何旋钮变化 → 哈希变化 → 禁止与旧 run 直接比较
- 无关字段（如 `_hash` 自身、未来新增的非旋钮键）不进入哈希
- `config_hash` 在此之上再叠加夹具指纹与容差参数

---

## 6. 归因里"替代值"的选取规则

消融实验需要为每个旋钮指定"另一个值"，规则固定以保证可复现：

| 类型 | 规则 |
|---|---|
| 布尔 | 取反 |
| 计数（persistence / wait / cooldown） | 2→1，其余 1↔0 |
| `breakout_window` | 减半，不小于 2 |
| 枚举 | 按本文件表格中的声明顺序取下一个（循环） |

若替代值本身非法（例如缺少某键），该旋钮在报告中标记 `skipped`，
不参与排名，也不贡献解释率。