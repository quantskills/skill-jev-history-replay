# 接口与字段说明 / API Guide

## 1. Python 入口

```python
from scripts.build import run, validate_input

report = run(input_data, config=None)
```

### `input_data`

| 键 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `bars_dir` | str | 否 | 分钟 K 线目录；缺省用 `config.replay_config.yaml` 的 `fixtures/bars` |
| `logs_dir` | str | 否 | JEV 日志目录；缺失或为空 → 合成模式 |
| `output_dir` | str | 否 | 结果目录，默认 `output/` |
| `reference_path` | str | 否 | 前收价 JSON；缺省自动在 `fixtures/reference/` 找 |
| `semantics` | dict | 否 | 语义旋钮覆盖，键见 `references/semantics_matrix.md` |
| `run_attribution` | bool | 否 | 是否跑单旋钮消融，默认 `True` |

也接受 `str`：直接当作 `bars_dir`。

传入未列出的键会抛 `ReplayError(code="unknown_field")`——刻意不做静默忽略。

### `config`

与 `input_data` 同名键的覆盖项，外加：

| 键 | 类型 | 说明 |
|---|---|---|
| `time_tolerance_minutes` | int | 时序对齐容差，默认 1 |
| `price_tolerance_bps` | int/float | 价格比较容差（基点），默认 5 |
| `min_cycles` | int | 价值判定所需最小配对周期，默认 20 |
| `explained_rate_threshold` | float | 归因判定为主要成因的阈值，默认 0.95 |
| `max_inline_rows` | int | 报告内联账本行数上限，默认 50 |
| `logged_profile` | str | 合成日志所用档位，默认 `jev_assumed` |
| `log_source` | str | `auto` / `actual` / `synthetic`，默认 `auto` |

优先级：`run(config=...)` > 环境变量 `JEV_*` > `config/replay_config.yaml` > 内置默认值。

`config` 里的未知键与 `input_data` 口径一致，同样抛 `ConfigError(code="unknown_config")`。
键名拼错（如 `time_tolerence_minutes`）不会被静默忽略——否则评测照跑，
用的却是默认值，结果与预期不符。

---

## 2. 返回值

```python
{
  "run_id": "jev-20261112T153012345678Z",
  "generated_at": "2026-11-12T15:30:12+00:00",
  "provenance": {...},
  "comparability": {...},
  "ledger": {...},
  "attribution": {...},
  "alignment_conclusion": {...},
  "value_assessment": {...},
  "applicability": {...},
  "semantics": {...},
  "logged_semantics": {...},   # 日志侧实际使用的语义档位（合成模式下用于追溯）
  "summary": {...},
  "per_day": {"20261112": {"comparable": 1478, "divergent": 23}, ...},
  "artifacts": {"report": "...", "ledger": "..."},  # 仅 run() 返回，不写进 report.json
}
```

### `summary`

| 字段 | 说明 |
|---|---|
| `symbol_count` | 参与回放的标的数 |
| `signal_count` | 重放产生的信号数 |
| `closed_cycles` | 完整收官的周期数 |
| `total_net_pct` | 全部已收官周期的净收益合计（小数） |
| `ledger_match_rate` | 可比项一致率 |
| `divergence_items` | 真正冲突的账本行数 |
| `one_sided_items` | 单边缺失行数（记录口径差异） |
| `condition_coverage` | 条件轴有日志记录的比例 |
| `alignment_verdict` | 对齐结论 |
| `value_verdict` | 价值结论 |
| `attribution_verdict` | 归因结论 |

### `ledger.aggregate.by_axis`

每个轴：`match` / `divergent` / `one_sided` 细分类（如 `jev_missing`、
`time_shifted`、`replay_only`、`jev_only`）、`comparable`、`match_rate`。

`comparable = match + divergent`；`match_rate = match / comparable`。
单边缺失不进分母。

### `ledger` 里的三个行数，别混用

| 字段 | 含义 | 本样本实测 |
|---|---|---|
| `total_rows` | 账本全部行 | 1,015,406 |
| `non_match_rows` | 全部**非 match** 行（含 `jev_missing`/`open_position`） | 979,639 |
| `divergence_rows` | **真实冲突**行，与 `aggregate.total.divergent` 同口径 | 319 |

`alignment_conclusion.divergence_items`、`summary.divergence_items`、
`ledger.divergence_rows`、`ledger.aggregate.total.divergent` **四处必须相等**。
早期 `divergence_items` 取的是 `non_match_rows`，导致同一份报告里
同一概念同时出现 979,634 和 314 两个数。

### `ledger.by_axis_prior` —— 各轴的先验假设

每个轴一句「差异最可能来自哪里」的**先验判断**，用于读账本时的初始假设，
**不是**从数据推出的结论（结论在 `attribution` 里）。它固定写在代码中，
不随样本变化：

| 轴 | 先验 |
|---|---|
| condition | 日志侧未披露比较基准与窗口口径，差异归因需消融实验确认 |
| signal | 信号时点差异主要由时间戳语义与连续性要求造成 |
| wait | 等待根数差异由 `wait_bars` 与 `bar_timestamp` 共同决定 |
| entry | 入场价差异由 `entry_price` 选择（当根收盘 / 下一根开盘）决定 |
| exit | 退出差异由退出判定字段（收盘 / 高低价）与 T+1 约束决定 |

### `ledger.first_divergence` —— 第一条差异

`{axis, symbol, time, field, jev, replay, delta, status, note}`，
按 `(symbol, time, axis)` 排序后的第一条 `divergent` 行。用于快速定位
「最上游的第一处不一致」——排查时通常从这里开始，而不是直接看聚合数。

### `attribution.ranked[]`

| 字段 | 说明 |
|---|---|
| `knob` / `from` / `to` | 被替换的旋钮及取值 |
| `baseline_divergences` | 当前配置差异总数 |
| `trial_divergences` | 换旋钮后的差异总数（含可比项损失） |
| `lost_comparable` | 因换旋钮而失去的比对数 |
| `comparable_retention` | 试换后可比项占基线的比例（`trial_comparable / baseline_comparable`）。**可大于 1**——换旋钮后可比项变多了，例如 `breakout_field` 会带来 1.002 |
| `alignment_preserved` | 可比项是否未减少 |
| `explained` / `explained_rate` | 解释掉的差异数 / 比例 |
| `skipped` | 替代值非法时跳过 |
| `reason` | **仅 `skipped=true` 时出现**，说明跳过原因（如 `breakout_window` 无法再折半时） |

> `reason` 不是每条都有——正常运行时不出现该键。取值请用 `.get("reason")`。

**守卫规则**：`alignment_preserved=false` 时 `explained` 强制为 0。
否则一个把配对全部打散的旋钮会假装"解释了全部差异"。

### `alignment_conclusion`

| 字段 | 说明 |
|---|---|
| `verdict` | `consistent` / `minor_divergence` / `inconsistent` / `inconclusive` |
| `match_rate` / `match_rate_ci95` | 一致率与 Wilson 95% 区间 |
| `comparable_items` / `divergence_items` | 计数 |

`synthetic` 日志恒为 `inconclusive`。

**判 `consistent` 需要同时满足**：

1. 总体一致率 ≥ 0.98；
2. 真实冲突数 **= 0**（不给"可忽略额度"）；
3. **每一个轴都有可比项**——否则是"没验证"，不是"一致"。

第 3 条来自一个真实反例：日志只写 `condition`、完全不写 `signal`/`plan` 时，
`signal`/`wait`/`entry`/`exit` 四轴 `comparable` 全为 0，而总体因 2 条
`condition` 相符就给出 `consistent`。此时 `reason` 会明确指出哪些轴未验证。

### `value_assessment`

`baseline`（字面直译）与 `current`（当前配置）的对比：

| 字段 | 说明 |
|---|---|
| `decision_changes` | 信号/周期的新增与移除、配对周期数 |
| `effect_size.paired_net_pct_delta` | 配对净收益差均值与 95% 区间 |
| `effect_size.win_loss` | 配对胜/负/平计数 |
| `effect_size.sign_test_p` | 符号检验双侧 p 值 |
| `verdict` | `positive` / `negative` / `inconclusive` + 判定规则 |

### `artifacts`

| 键 | 路径 |
|---|---|
| `report` | `output/report.json` |
| `ledger` | `output/ledger.jsonl` |

---

## 3. 账本行结构

`output/ledger.jsonl` 每行：

```json
{
  "axis": "condition|signal|wait|entry|exit",
  "symbol": "600519.SH",
  "time": "09:41",
  "field": "hit|time|wait_bars|price|reason|null",
  "jev": "JEV 侧值",
  "replay": "重放侧值",
  "delta": "数值差（replay - jev），非数值时为 null",
  "status": "match|divergent|jev_missing|replay_missing|time_shifted|replay_only|jev_only",
  "note": "补充说明"
}
```

`delta` 的符号约定：**replay − jev**。正数表示重放更晚/更高/更多。

### ⚠️ 默认 `ledger_mode: diff` 下不写 `match` 行

`status` 的枚举里虽然有 `match`，但**默认配置下账本里不会出现它**——
`diff` 模式只写需要追溯的行（`divergent` 与 `open_position`），
否则光是 condition 轴的 98 万条 `jev_missing` 就有 185 MB。

**因此不能用 `ledger.jsonl` 统计一致率**：`match` 行不在里面，
算出来的分母会严重偏小。一致率请直接读 `report.json` 的
`ledger.aggregate`（聚合统计用的是内存数据，不受落盘模式影响）。

需要逐行完整账本时设 `ledger_mode: full`（本样本 1,015,406 行 / 185 MB）。

---

## 4. 命令行脚本

| 脚本 | 用途 |
|---|---|
| `scripts/build.py` | 标准入口，跑默认目录 |
| `scripts/validate.py` | 校验 K 线与日志契约 |
| `scripts/env_check.py` | 环境自检，输出结构化 JSON |
| `scripts/compare_baseline.py` | 冻结基线 freeze / compare / list |
| `scripts/fetch_data.py` | 由 MCP 落盘 JSON 生成分钟 K 线夹具 |
| `scripts/build_fixtures.py` | 由 MCP 落盘 JSON 生成发布用夹具 |
| `scripts/mcp_source.py` | 解析 MCP 返回信封（截断 / 缺列 / ok=false） |

```bash
python3 scripts/build.py
python3 scripts/validate.py --bars-dir fixtures/bars --logs-dir fixtures/logs
python3 scripts/compare_baseline.py freeze output/report.json --name v1
python3 scripts/compare_baseline.py compare output/report.json --against baselines/v1.json
```

---

## 5. 异常

`scripts.run_eval.ReplayError`，字段 `code` / `message` / `hint`。

| code | 触发条件 |
|---|---|
| `empty_input` | 传入空字符串 |
| `invalid_type` | 类型不符 |
| `unknown_field` | 传入未声明字段 |
| `bars_dir_not_found` | K 线目录不存在 |
| `bars_empty` | 目录内无数据文件 |
| `missing_bar_field` | K 线缺必需字段 |
| `invalid_bar_field` | 数值非法 / 时间无法解析 / high<low |
| `duplicate_bar` | 同标的同分钟重复 |
| `logs_dir_not_found` | 显式指定的日志目录不存在 |
| `logs_empty` | 日志目录无数据文件 |
| `missing_log_field` / `invalid_log_kind` | 日志字段或 kind 非法 |
| `invalid_semantics` | 语义旋钮取值非法 |
| `unknown_profile` | 引用了未登记档位 |

`scripts.data_loader.LoadError` 是加载层异常，`run_eval` 会转成 `ReplayError`。

---

## 6. 导入方式

```python
import sys
sys.path.insert(0, "path/to/skill-jev-history-replay")
from scripts.build import run
```

包内模块互相使用相对导入（`from .replayer import ...`），
因此必须让 skill 根目录在 `sys.path` 上。`scripts/build.py` 已自行处理。