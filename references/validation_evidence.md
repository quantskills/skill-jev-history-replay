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
| 用例总数 | 92 |
| 通过 | 92 |
| 失败 | 0 |
| 环境 | Python 3.12.12 / 3.11.16 / 3.10 均验证 |

| 文件 | 用例数 | 覆盖 |
|---|---|---|
| `test_semantics.py` | 13 | 旋钮取值校验、哈希敏感性、替代值确定性 |
| `test_data_loader.py` | 17 | 格式容错、gzip、字段校验、重复检测、异常输入 |
| `test_replayer.py` | 20 | 条件判断、连续性、等待/入场、四条退出路径、T+1、时间边界 |
| `test_cross_day.py` | 6 | 跨日持仓传递、未平仓如实上报、单日行为不变 |
| `test_aligner.py` | 12 | 五轴对齐、配对唯一性、单边缺失、差异分类 |
| `test_attribution.py` | 5 | 单旋钮解释率、守卫条件、不可解释残差 |
| `test_report.py` | 16 | verdict 判定、统计量、账本截断 |
| `test_end_to_end.py` | 9 | 输入校验、来源判定、产物落盘、确定性 |

---

## 2. 夹具（真实数据）

```bash
python3 scripts/build_fixtures.py --date 20261110,20261111,20261112 --universe 300
```

| 项 | 值 |
|---|---|
| 数据源 | `panda-data==1.0.6`，`get_stock_min` / `get_stock_daily` |
| 交易日 | 2026-11-10、11-11、11-12（三个连续交易日） |
| 标的数 | 300 / 日（按代码排序后等距抽样，避免选择偏差） |
| 分钟线 | 216,000 根（900 序列 × 240 根） |
| 前收价 | 1,836 条（每标的每日各自的前收，无跨日复用） |
| 日志记录 | 6,219 条（`condition` / `signal` / `plan`） |

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
| condition | 5,985 | 5,985 | 0 | 1.00 |
| signal | 117 | 117 | 0 | 1.00 |
| wait | 117 | 117 | 0 | 1.00 |
| entry | 117 | 117 | 0 | 1.00 |
| exit | 0 | — | — | null |

**总体可比 6,453 项，冲突 0，一致率 1.00。**

### 3.2 退出轴为何是 0 可比（重要边界）

三日夹具、`t_plus_1=true` 下，**所有能收官的交易都必须跨日**：
当日买入当日不可卖，持仓被带到次日才退出。

而日志契约规定 `plan` 记录写在**入场日**，其 `exit_time` 是当日计划退出时刻。
跨日持仓在退出日没有独立记录（那天的 plan 属于当天的新交易）。

因此：

- 退出轴在当前夹具下**不可比**，如实输出 `match_rate=null`，不编造；
- 212 条跨日退出标为 `replay_only`，单列统计，不进一致率分母；
- 要让退出轴可比，需要日志侧提供跨日的独立退出回执，或使用 `t_plus_1=false` 的日内场景。

这是**记录粒度**的差异，不是实现不一致，也不是可以靠调参绕过的。

### 3.3 单边缺失的口径

| 类型 | 数量 | 含义 |
|---|---|---|
| `jev_missing`（condition） | 210,015 | 日志只在状态翻转时写，重放逐根判断 |
| `replay_only`（signal/entry/exit） | 212 | 跨日交易，日志侧无对应记录 |

条件轴覆盖率仅 2.77%（5,985 / 216,000 根）。这是日志记录习惯的直接结果，
**不进入一致率分母**。若混算会得到"一致率 2.8%"这种误导性数字。

---

## 4. 价值评估

对比「显式语义」（当前配置）与「字面直译」（`naive_literal` 基线），
两者共用同一份真实分钟线与前收价，唯一受控变量是语义档位。

```bash
python3 scripts/build.py
python3 -c "import json;print(json.load(open('output/report.json'))['value_assessment'])"
```

| 指标 | 基线（字面直译） | 当前（显式语义） |
|---|---|---|
| 信号数 | 4,797 | 329 |
| 收官周期 | 4,472 | 212 |
| 净收益合计 | −7.654% | +1.892% |

| 效应量 | 值 |
|---|---|
| 配对周期数 | 148 |
| 配对差均值 | +1.176% |
| 95% CI | [+0.734%, +1.619%] |
| 胜 / 负 / 平 | 93 / 53 / 2 |
| 符号检验 p | 0.001173 |
| **verdict** | **positive** |

**解读**：把隐式约定显式化后，交易次数减少了 93%（4,797 → 329），
胜率 93:53，符号检验显著。但这是**同一套规则在两种解释下的差异**，
不是"显式语义更好"的投资结论——它说明的是「语义选择对回放结果的影响有多大」。

### 4.1 方向与幅度必须分开看

报告同时给出符号检验与均值差，并注明二者可背离：

- 符号检验判断**方向**（多数周期是否改善）；
- 均值差判断**幅度**（受少数大幅盈亏主导）。

本案例两者一致（胜多、均值为正）。若二者背离，verdict 只按符号检验定方向，
并在 `magnitude_note` 中说明。

---

## 5. 归因

```bash
python3 -c "import json;print(json.load(open('output/report.json'))['attribution'])"
```

当前夹具下 `divergence_items=0`，因此 `attribution.verdict = no_divergence`——
没有差异可归因，这是正确输出，不是失败。

### 5.1 归因机制的单独验证

在 `tests/test_attribution.py` 中构造了"已知某旋钮不同"的场景：

| 用例 | 验证点 |
|---|---|
| `test_ablation_identifies_changed_knob` | 只改 `exit_eval` 时，归因能锁定它并给出 1.0 解释率 |
| `test_identical_config_has_no_divergence` | 配置完全一致时差异为 0 |
| `test_attribution_does_not_reward_breaking_alignment` | 换旋钮打散配对时 `explained` 强制为 0 |
| `test_ablation_skips_invalid_alternative` | 替代值非法时标记 `skipped`，不参与排名 |

### 5.2 守卫规则的必要性（实测踩到）

早期版本中，把 `bar_timestamp` 从 `bar_end` 改成 `bar_start` 会让可比项从 7,396
掉到 1,556，差异数反而下降——旧逻辑会把这种"配对被打散"算成"解释了差异"，
给出 100% 的假解释率。

现在 `alignment_preserved=false` 时 `explained` 强制为 0。这是本轮验证中
发现并修复的真实缺陷。

---

## 6. 本轮验证中发现并修复的缺陷

以下都不是构造的测试用例，而是在真实多日数据上跑出来的：

| # | 缺陷 | 症状 | 修复 |
|---|---|---|---|
| 1 | 止损/止盈分支绕过 T+1 检查 | 同一天里强平被推迟、止损却能当日成交 | 四条退出路径统一走 `_exit_or_defer` |
| 2 | 单日 + T+1 下无任何周期能收官 | `closed_count=0`（此前能收官全靠缺陷 1） | 新增跨日持仓传递 `_carry_forward` |
| 3 | 跨日持仓每天新建一个周期对象 | 入场日的周期停在 open，退出轴永远配不上 | 复用同一对象，在次日原地补退出信息 |
| 4 | 跨日周期被重复计数两次 | 同一笔交易在 `cycles` 与 `exit_cycles` 各出现一次 | 按对象身份去重 |
| 5 | 多日构建时日志混入其他交易日记录 | `20261110.jsonl` 里出现 20261112 的记录 | 按日期切分生成，`load_bars_files` 精确加载 |
| 6 | 前收价按裸代码取 | 多日下取到别的交易日的前收，涨幅基准错位 | 按 `symbol@date` 取值 |
| 7 | 合并视图导致信号日期错标 | 同一标的各日信号全被标成最后一天 | `log_synth` 遍历 `by_series` 而非 `symbols` |
| 8 | 归因把"配对打散"当成"解释差异" | 假 100% 解释率 | `alignment_preserved` 守卫 |
| 9 | 合成日志写入 `fixtures/logs` 后 provenance 缺档位信息 | 只知道"是合成的"，不知道按哪套语义生成 | 补 `logged_semantics.knobs` 全量回显 |

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

---

## 8. 复现环境

| 项 | 值 |
|---|---|
| Python | 3.12.12（主）、3.11.16、3.10 |
| panda-data | 1.0.6（仅夹具再生） |
| 三方依赖 | 无（对齐与回放为纯标准库） |
| 运行时长 | 全量对齐约 3 秒（900 序列 × 240 根） |
| 单元测试 | 0.15 秒 |

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
- 对齐链路在真实多日行情上可跑通，条件/信号/等待/入场四轴一致率 1.00；
- 重放器在 T+1 下能正确跨日持仓，四条退出路径行为一致；
- 归因机制可用，且有守卫防止假解释；
- 语义选择对回放结果影响巨大（信号数 4,797 → 329），方向显著。

**未验证**：
- **JEV 实际语义**——日志为合成数据，对齐 verdict 恒为 `inconclusive`；
- 退出轴的一致性——当前夹具与日志粒度下不可比（见 §3.2）；
- 跨日持仓的退出时刻差异——日志侧无对应记录。

**结论据此成立的范围**：仅在 `applicability` 声明的单日/多日 A 股分钟级场景，
且日志按 `log_contract.md` 提供记录时。任何超出范围的外推都不受本验证支持。