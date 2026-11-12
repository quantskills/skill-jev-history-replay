# 实测验证记录 / Validation Evidence

本文件记录在真实环境下跑出的结果，供审核方核对。
除「夹具再生」外，下列命令**均可由 clone 后直接复现，无需任何凭证**。

---

## 1. 单元测试

```bash
python3 -m pytest tests/ -q
```

| 项 | 结果 |
|---|---|
| 用例总数 | 94 |
| 通过 | 94 |
| 失败 | 0 |
| 环境 | Python 3.12.12 / 3.11.16 |

| 文件 | 用例数 | 覆盖 |
|---|---|---|
| `test_semantics.py` | 13 | 旋钮取值校验、哈希敏感性、替代值确定性 |
| `test_data_loader.py` | 17 | 格式容错、gzip、字段校验、重复检测、异常输入 |
| `test_replayer.py` | 20 | 条件判断、连续性、等待/入场、四条退出路径、T+1、时间边界 |
| `test_cross_day.py` | 6 | 跨日持仓传递、未平仓如实上报、单日行为不变 |
| `test_aligner.py` | 12 | 五轴对齐、配对唯一性、单边缺失、差异分类 |
| `test_attribution.py` | 7 | 单旋钮解释率、视图一致性、真实差异可归因 |
| `test_report.py` | 16 | verdict 判定、统计量、账本截断 |
| `test_end_to_end.py` | 9 | 输入校验、来源判定、产物落盘、确定性 |

---

## 2. 夹具（真实数据）

```bash
python3 scripts/build_fixtures.py --date 20261104,20261105,20261106,20261109,20261110,20261111,20261112 --universe 200
```

| 项 | 值 |
|---|---|
| 数据源 | `panda-data==1.0.6`，`get_stock_min` / `get_stock_daily` |
| 交易日 | 7 个（2026-11-04 至 11-12，含周末跳过） |
| 标的数 | 200 / 日 |
| 序列数 | 1,400（`symbol@date`） |
| 分钟线 | 336,000 根 |
| 前收价 | 每标的每日各自的前收，无跨日复用 |
| 日志记录 | 11,188 条（`condition` 9,406 + `plan` 891 + `signal` 501 + `fill` 390） |

**抽样方法**：`get_trade_list(exchange='SH')` 取全市场，按代码排序后等距抽样。
不按当日涨跌筛选——那会让结论只对"涨了的股票"成立。

---

## 3. 端到端对齐

```bash
python3 scripts/env_check.py    # ok=true, blocked=0
python3 scripts/validate.py     # ok=true
python3 scripts/build.py
```

### 3.1 五轴结果

| 轴 | 可比项 | 一致 | 冲突 | 一致率 |
|---|---|---|---|---|
| condition | 9,406 | 9,406 | 0 | **1.00** |
| signal | 501 | 501 | 0 | **1.00** |
| wait | 501 | 501 | 0 | **1.00** |
| entry | 501 | 501 | 0 | **1.00** |
| exit | 716 | 657 | 59 | **0.9176** |
| **合计** | **11,625** | **11,566** | **59** | **0.9949** |

### 3.2 退出轴如何变成可比的（v0.2.1 的关键修复）

v0.2.0 时退出轴 `comparable=0`，原因是合成日志对跨日退出**从不写退出记录**：
`plan` 只写在入场日，`exit_time` 为 `None`。这既不是语义分歧，也不是可接受的口径，
而是**日志生成器的缺陷**——真实交易系统必然会有次日卖出回执。

修复后日志按「一笔交易两端分属两个记录日」生成：

| 记录日 | 写入内容 |
|---|---|
| 入场日 | `signal` + `plan(enter)`，`cross_day_pending=true` |
| 退出日 | `plan(exit)` + `fill(side=sell)`，`cross_day=true` |

退出轴相应改为按**退出时刻**在本序列的退出记录里配对，而不是复用入场配对。

退出轴剩余分类：

| 状态 | 数量 | 含义 |
|---|---|---|
| `match` | 657 | 重放与日志退出时刻/原因一致 |
| `divergent` | 59 | 见 §5，已被 `exit_eval` 完整解释 |
| `replay_only` | 32 | 重放退出、日志无对应记录 |
| `open_position` | 111 | 数据末尾仍未退出（最后一日的持仓），无退出可比 |

### 3.3 单边缺失的口径

| 类型 | 数量 | 含义 |
|---|---|---|
| `jev_missing`（condition） | 326,594 | 日志只在状态翻转时写，重放逐根判断 |
| `jev_only`（entry） | 390 | 日志的退出日 `plan` 在入场轴无对应项 |

条件轴覆盖率 2.80%（9,406 / 336,000 根）。这**不进入一致率分母**。
混算会得到"一致率 2.8%"这种误导性数字。

---

## 4. 归因

```bash
python3 -c "import json;print(json.load(open('output/report.json'))['attribution'])"
```

| 排名 | 旋钮 | 从 → 到 | 解释差异 | 解释率 |
|---|---|---|---|---|
| 1 | `exit_eval` | `bar_close` → `bar_high_low` | 59 | **100%** |
| 2 | `baseline_price` | `prev_close` → `day_open` | 0 | 0% |
| 3 | `bar_timestamp` | `bar_end` → `bar_start` | 0 | 0% |

`verdict = single_knob`。

**解读**：59 条退出差异**全部**由「退出按收盘价还是按触价判定」造成。
其余旋钮一个都解释不了——这说明两侧的条件/信号/入场语义确实一致，
唯一分歧就是退出判定的价格口径。这是一个干净的、可复现的归因结论。

### 4.1 归因机制的两个守卫

本轮修复了两处会让归因给出错误结论的缺陷：

| 缺陷 | 症状 | 修复 |
|---|---|---|
| 消融用 `symbols` 视图，主流程用 `by_series` | 两侧可比项口径不一致，真实成因归不出来（0%） | 统一用 `by_series` |
| 一律拒绝"可比项减少"的旋钮 | 真实差异必然改变信号集，被误判为"未归因"（假阴性） | 区分"配对消失"与"冲突消失"：`raw_explained > lost_comparable` 且可比项保有率 ≥ 5% 才认 |

两条都保留在测试中：

- `test_ablation_uses_same_view_as_main_flow`
- `test_real_difference_is_attributable_despite_signal_change`
- `test_attribution_does_not_reward_breaking_alignment`（防假阳性）

---

## 5. 价值评估

对比「显式语义」（当前配置）与「字面直译」（`naive_literal` 基线），
两者共用同一份真实分钟线与前收价，唯一受控变量是语义档位。

| 指标 | 基线（字面直译） | 当前（显式语义） |
|---|---|---|
| 信号数 | 9,979 | 501 |
| 净收益合计 | 见报告 | +0.980% |

| 效应量 | 值 |
|---|---|
| 配对周期数 | 314 |
| 配对差均值 | +0.0966% |
| 95% CI | [−0.267%, +0.460%] |
| 胜 / 负 / 平 | 151 / 160 / 3 |
| 符号检验 p | 0.650 |
| **verdict** | **inconclusive** |

**解读**：显式语义把交易次数砍掉 95%（9,979 → 501），但配对周期的
收益方向不显著（151 胜 : 160 负，p=0.65）。

这是**可靠负结果**：语义选择巨大地改变了交易行为，但在这 7 个交易日的样本上，
无法证明它改善了收益。报告如实给出 `inconclusive`，不因均值微正而判 positive。

---

## 6. 本轮验证中发现并修复的缺陷

以下都不是构造的测试用例，而是在真实多日数据上跑出来的：

| # | 缺陷 | 症状 | 修复 |
|---|---|---|---|
| 1 | 止损/止盈分支绕过 T+1 检查 | 同一天里强平被推迟、止损却能当日成交 | 四条退出路径统一走 `_exit_or_defer` |
| 2 | 单日 + T+1 下无任何周期能收官 | `closed_count=0`（此前能收官全靠缺陷 1） | 新增跨日持仓传递 `_carry_forward` |
| 3 | 跨日持仓每天新建一个周期对象 | 入场日的周期停在 open，退出轴永远配不上 | 复用同一对象，次日原地补退出信息 |
| 4 | 跨日周期被重复计数两次 | 同一笔交易在 `cycles` 与 `exit_cycles` 各出现一次 | 按对象身份去重 |
| 5 | 多日构建时日志混入其他交易日记录 | `20261110.jsonl` 里出现 20261112 的记录 | 按日期切分生成，`load_bars_files` 精确加载 |
| 6 | 前收价按裸代码取 | 多日下取到别的交易日的前收，涨幅基准错位 | 按 `symbol@date` 取值 |
| 7 | 合并视图导致信号日期错标 | 同一标的各日信号全被标成最后一天 | `log_synth` 遍历 `by_series` |
| 8 | 归因把"配对打散"当成"解释差异" | 假 100% 解释率 | `alignment_preserved` 守卫 |
| 9 | 合成日志缺档位信息 | 只知道"是合成的"，不知道按哪套语义生成 | 回显 `logged_semantics.knobs` |
| 10 | **合成日志从不写跨日退出记录** | 退出轴 `comparable=0`，等于自证无差异 | 入场日/退出日分别写 `plan`，退出轴按退出时刻配对 |
| 11 | **`exit_series` 在未退出时被写成当天** | 入场日视图误以为退出发生在自己这天，比对错记录 | 仅当 `exit_time` 存在时定格 `exit_series` |
| 12 | **消融与主流程使用不同视图** | 真实成因归不出来（解释率 0%） | 统一用 `by_series` |

---

## 7. 错误路径

| 场景 | 结果 |
|---|---|
| 空字符串输入 | `ReplayError: empty_input` |
| 未知字段 | `ReplayError: unknown_field`，列出允许字段 |
| `bars_dir` 不存在 | `ReplayError: bars_dir_not_found` |
| K 线缺字段 / high<low / 价格非正 | `ReplayError: missing_bar_field` / `invalid_bar_field` |
| 同标的同分钟重复 | `ReplayError: duplicate_bar`，提示检查多日混入 |
| 语义旋钮取值非法 | `ReplayError: invalid_semantics` |
| 日志 `kind` 非法 | `LoadError: invalid_log_kind` |
| 多日模式日志缺 `date` | `LoadError: missing_log_field`，提示必须带日期 |
| 缺 panda_data | `env_check` 报 `warn` 而非 `blocked`（评测不需要它） |
| `config_hash` 不一致时比对基线 | `comparable=false`，不给 delta 并列出 `changed_fields` |
| 非交易日拉数据 | `FetchError: no_data`，退出码 2 |

---

## 8. 复现环境

| 项 | 值 |
|---|---|
| Python | 3.12.12（主）、3.11.16 |
| panda-data | 1.0.6（仅夹具再生） |
| 三方依赖 | 无（对齐与回放为纯标准库） |
| 全量对齐耗时 | 约 5 秒（1,400 序列 × 240 根） |
| 单元测试 | 0.23 秒 |

```bash
git clone https://github.com/quantskills/skill-jev-history-replay
cd skill-jev-history-replay
pip install -r requirements-dev.txt
python3 scripts/env_check.py
python3 scripts/validate.py
python3 -m pytest tests/ -v
python3 scripts/build.py
```

---

## 9. 结论与边界

**已验证**：
- 五轴全部可比：条件/信号/等待/入场一致率 1.00，退出轴 0.9176，总体 0.9949；
- 59 条退出差异被 `exit_eval` 单一旋钮完整解释（100%）；
- 重放器在 T+1 下能正确跨日持仓，四条退出路径行为一致；
- 语义选择对回放结果影响巨大（信号 9,979 → 501），但收益改善未可证（p=0.65）。

**未验证**：
- **JEV 实际语义**——日志为合成数据，对齐 verdict 恒为 `inconclusive`；
- 跨日之外的持仓形态（如 T+0 市场、多空双向）；
- 除权除息、停牌、涨跌停场景。

**结论据此成立的范围**：仅在 `applicability` 声明的 A 股分钟级单/多日场景，
且日志按 `log_contract.md` 提供记录时。任何超出范围的外推都不受本验证支持。

**要让对齐 verdict 变成 `consistent` / `inconsistent`**：把真实 JEV 日志按
`log_contract.md` 放进 `fixtures/logs/`，重跑 `build.py`。代码无需改动。