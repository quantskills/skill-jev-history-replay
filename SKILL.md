---
name: skill-jev-history-replay
description: 当需要核对 JEV 盯盘条件与历史回放是否语义一致时，使用此 skill。取实际条件/判断日志与已完成 K 线，用显式声明的语义重建盯盘条件与重放器，逐项输出条件判断、信号时点、等待、入场、退出的差异账本，并对差异做单旋钮消融归因。
tags: [quant, build, engineered, 语义对齐, 历史回放, 差异账本]
license: GPL-3.0-only
---

# JEV 盯盘条件与历史回放语义对齐

## 工具定位
- 工具类型：评测 / 对齐工具型
- 工程形态：工程型（通用工具类）
- 解决问题：同一份 K 线、同一条盯盘规则，JEV 侧的判断与一个可复现回放器之间到底差在哪
- 使用对象：研究 agent / 策略复盘 / 人工审计

## 适用场景
- 当需要核对 JEV 记录的信号时点与实际 K 线是否对得上时
- 当需要把"盯盘条件"从自然语言落到可执行代码，并量化每种解释选择的影响时
- 当需要判断一次回放差异是时间戳口径、等待根数，还是成交价口径造成的时
- 当只有只读日志、无法访问 JEV 内部推理或自定义 API 时

## 核心概念：语义旋钮

「语义」指同一份 OHLCV、同一条规则，落到代码里仍必须做出的解释选择。
本 skill 把这些选择全部显式化为**命名档位**（见 `scripts/semantics.py` 的 `KNOB_VALUES`）：

| 旋钮 | 取值 | 影响 |
|---|---|---|
| `bar_timestamp` | `bar_end` / `bar_start` | 判断与成交落在哪一分钟 |
| `baseline_price` | `prev_close` / `day_open` / `window_start` | 涨幅算对谁 |
| `breakout_field` | `high` / `close` / `open` | 突破比什么 |
| `breakout_window` | 整数 | 回看多少根 |
| `breakout_includes_current` | bool | 窗口是否含当前根 |
| `persistence_bars` | 整数 | 连续成立几根才确认 |
| `wait_bars` | 整数 | 信号后空过几根 |
| `entry_price` | `next_open` / `signal_close` | 用什么价成交 |
| `exit_eval` | `bar_close` / `bar_high_low` | 退出按收盘还是按触价 |
| `t_plus_1` | bool | 是否施加 T+1 |
| `cooldown_bars` | 整数 | 同标的再触发间隔 |

任何旋钮改动都会改变 `semantics_hash`，从而禁止与旧结果直接比较。

## 输入

| 字段 | 类型 | 说明 |
|---|---|---|
| `bars_dir` | str | 分钟 K 线目录（`.json` / `.jsonl` / `.json.gz`） |
| `logs_dir` | str | JEV 日志目录；缺失或为空时自动走合成模式 |
| `output_dir` | str | 结果目录，默认 `output/` |
| `semantics` | dict | 语义旋钮覆盖项 |
| `reference_path` | str | 可选，前收价文件 |
| `run_attribution` | bool | 是否跑归因消融，默认 True |

## 输出

| 产物 | 内容 |
|---|---|
| `output/report.json` | 汇总报告，见下 |
| `output/ledger.jsonl` | 逐项差异账本，一行一个对齐项 |

`report.json` 顶层字段：

| 字段 | 说明 |
|---|---|
| `provenance.log_source` | `actual`（真实 JEV 日志）或 `synthetic`（合成） |
| `comparability` | `semantics_hash` / `fixture_fingerprint` / `config_hash` 等 |
| `ledger.aggregate` | 五轴 match / divergent / one_sided 计数与一致率 |
| `ledger.decision_changes` | 交易决策层面的改变（新增/缺失/时点/价格/退出原因） |
| `attribution` | 单旋钮消融：每个旋钮解释了百分之多少差异 |
| `alignment_conclusion` | 对齐结论与置信区间 |
| `value_assessment` | 相对字面直译基线的决策改变、效应量与结论 |
| `applicability` | 覆盖范围、不在范围、结论失效情形 |

## 五轴差异账本

| 轴 | 对齐键 | 差异含义 |
|---|---|---|
| `condition` | 决策时刻 | 同一根 K 线一边判成立、一边判不成立 |
| `signal` | 信号时刻（容差内） | 触发时点错位或单边缺失 |
| `wait` | 配对后的信号 | 从信号到入场的等待根数不同 |
| `entry` | 配对后的周期 | 入场时刻或价格不同 |
| `exit` | 配对后的周期 | 退出时刻、价格或原因不同 |

**口径关键点**：`one_sided`（只有一边有记录）不计入一致率分母。
日志侧若只在状态翻转时落盘，会产生大量 `jev_missing`，那是**记录口径差异**，
不是语义冲突；把它算进差异率会得出完全错误的结论。

## 调用方式

```python
from scripts.build import run

report = run({
    "bars_dir": "fixtures/bars",
    "logs_dir": "fixtures/logs",
    "output_dir": "output",
    "semantics": {"wait_bars": 2, "entry_price": "signal_close"},
})
print(report["alignment_conclusion"])
```

命令行的两条主路径：

```bash
python3 scripts/build.py          # 标准入口，读默认目录
python3 scripts/validate.py       # 先检查日志契约，区分"字段缺失"与"语义不一致"
```

## 结论判定规则（可复现）

对齐结论：

| verdict | 条件 |
|---|---|
| `consistent` | 日志为 `actual` 且可比项一致率 ≥ 0.98 |
| `minor_divergence` | `actual` 且 0.80 ≤ 一致率 < 0.98 |
| `inconsistent` | `actual` 且一致率 < 0.80 |
| `inconclusive` | 无可比项，**或**日志为 `synthetic` |

最后一条是硬约束：合成日志只能证明链路可运行，不能对 JEV 语义下结论。

价值结论（相对字面直译基线）：

| verdict | 条件 |
|---|---|
| `positive` | 配对周期 ≥ `min_cycles` 且符号检验 p<0.05、胜多于负 |
| `negative` | 同上但负多于胜（**可靠负结果**，同样有效） |
| `inconclusive` | 样本不足或胜/负分布不显著 |

均值差只作幅度参考，不单独决定方向——少数大亏可以主导均值而多数周期只小赢。

## 数据来源
- 历史分钟 K 线：`panda_data` 的 `get_stock_min` / `get_stock_daily`，**仅夹具生成阶段调用**
- JEV 日志：调用方提供的只读日志；缺失时由 `scripts/log_synth.py` 合成
- 对齐与回放阶段（`replayer` / `aligner` / `attribution` / `metrics`）纯标准库，不访问任何外部服务
- 详见 `references/data_access.md`

## 依赖
- Python ≥ 3.10
- `panda-data==1.0.6`：仅 `scripts/fetch_data.py` / `scripts/build_fixtures.py` 需要
- `pyyaml>=6.0`：可选，缺失时回退内置默认配置

## 验收要求
- `python3 scripts/build.py` 可独立跑通
- `python3 -m pytest tests/ -v` 全通过
- `python3 scripts/validate.py` 对夹具返回 `ok: true`
- 实测验证记录（`references/validation_evidence.md`）中的数字可用上述命令复现
- 样本外复现：`python3 scripts/oos_check.py`（需凭证，约 5 分钟）
- 报告字段稳定，`ledger.jsonl` 每行可追溯到 `symbol + time + axis`

## 已知局限
- A 股分钟级；支持多日（跨日持仓与 T+1 已实现），但不含除权除息、停牌与涨跌停建模
- 不含撮合排队与部分成交；成交按规则价一次性全额撮合
- 合成日志的结论只能是 `inconclusive`
- 若真实日志缺 `wait_bars` / `entry_price` 等字段，对应轴退化为不可比，不会编造一致
- 跨日持仓的退出在日志侧通常没有独立记录（`plan` 写在入场日），
  因此这类周期的退出轴不可比，报告中标为 `replay_only` 单列，不进一致率分母
- 实测验证记录见 `references/validation_evidence.md`，含 68 处已发现并修复的缺陷

## 可被 Alpha 调用
- 否
- 说明：本 skill 是研究/评测工具，输出供人工或上层 agent 判读；不产生交易信号