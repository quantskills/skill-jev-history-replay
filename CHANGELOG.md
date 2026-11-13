# CHANGELOG

## 0.15.9 — 2026-11-13

这一轮核对「`validation_claims.json` 里声明的每一条是否真的被检查」。

### 缺陷 64：`claims.fixture` 整段从未被 `verify_claims` 检查

`validation_claims.json` 的 `fixture` 段有 5 个字段
（`dates` / `symbol_count` / `series_count` / `bar_count` / `universe_policy`），
但 `verify_claims.py` 里**没有任何代码读它**——一整块失效的对账数据。

现在补上检查（79 → **84** 项）。实测：把 `symbol_count` 改成 999、
`bar_count` 改成 1，立刻报出两处 MISMATCH。

> `series_count` 不在 manifest 里，由 `symbol_count × 交易日数` 推导后核对。

### 缺陷 65：`universe_policy` 声称存在，产物里根本没有

claims 声明「全期固定（14 日 trade_list 交集，按代码排序等距抽样）」，
但 `build_fixtures.py` **从不写这个字段**，manifest 里也没有。
读者无法核实"全期固定"是否属实——而这是跨日持仓成立的前提。

修复：`build_fixtures` 把该策略落盘到 manifest（含实际天数），
claims 的声明终于有据可查。

### 交付物
- `verify_claims` 检查数 **79 → 84**
- 新增 `test_manifest_records_universe_policy`

### 缺陷台账 63 → 65 项

---

## 0.15.8 — 2026-11-13

这一轮用**真实 panda 接口**核对 `data_access.md`——这是读者重新生成夹具的
唯一依据，此前只有签名是抄来的，行为描述没实测过。

### 缺陷 63：接口耗时与返回列未经实测

| 项 | 文档 | 实测 |
|---|---|---|
| `get_stock_min` 300 标的 / 72,000 根 | 约 3 秒 | **0.6 秒**（快 5 倍） |

同时缺失的关键信息：
- 各接口的**返回列**（`get_st_list` 是 `symbol,date,is_st` 等）
- `get_prev_trade_date` 返回 **`str`** 而非 DataFrame
- `get_trade_list('20261112','SH')` 实测 **5,218 行**（含深市）

### 6 个接口逐个实测，全部正常

| 接口 | 实测结果 |
|---|---|
| `get_stock_min` | 时间戳 `15:00` = 分钟**结束**时刻 ✓ |
| `get_stock_daily` | 按 `fields` 裁剪，返回 `pre_close` ✓ |
| `get_prev_trade_date` | 返回 `'20261111'`（str）✓ |
| `get_trade_list` | 5,218 行，含深市 ✓ |
| `get_st_list` | 2,732 行 ✓ |
| `get_suspended_list` | 92 行 ✓ |

### 新增测试（2 例，纯静态，CI 不装 panda_data 也能跑）
- `test_documented_pandata_apis_match_code_calls`：文档列的接口 == 代码调用的接口
- `test_data_access_signature_notes_match_code`：签名坑说明与代码一致

### 缺陷台账 62 → 63 项

---

## 0.15.7 — 2026-11-13

这一轮核对报告里几个尚未验证过的辅助字段：`by_axis_prior`、`first_divergence`、
以及 `api_guide` 中账本三行数的准确性。

### 缺陷 61：`by_axis_prior` / `first_divergence` 完全没有文档

报告里有这两个字段，`api_guide.md` 里一个字都没提。读者拿到报告能看到它们，
却不知道是什么、能用来做什么。

- `by_axis_prior`：每个轴一句「差异最可能来自哪里」的**先验判断**，
  固定写在代码中，**不是**从数据推出的结论（结论在 `attribution`）
- `first_divergence`：按 `(symbol, time, axis)` 排序的第一条冲突，
  排查通常从这里开始

### 缺陷 62：`api_guide` 的账本三行数全部过期

| 字段 | 文档 | 实际 |
|---|---|---|
| `non_match_rows` | 979,634 | **979,639** |
| `divergence_rows` | 314 | **319** |

### 核对中确认正确的项
- `first_divergence` 指向的那一行**真实存在于 `ledger.jsonl`**（不是编的）
- `by_axis_prior` 与 `aligner.PRIOR` 完全一致
- `decision_change_count=177` 与内联 50 条（受 `max_inline_rows` 截断）自洽

### 新增测试 `tests/test_ledger_fields.py`（4 例）
实测有效：把 `non_match_rows` 改回 979,634，测试立刻报错。

### 缺陷台账 60 → 62 项

---

## 0.15.6 — 2026-11-13

这一轮核对报告里的 `semantics` / `logged_semantics` 是否如实回显配置——
读者要靠它重建实验。

### 缺陷 59：资金参数未计入 `semantics_hash`

`initial_capital` / `lot_size` / `position_pct` 会改变成交股数与资金约束、
直接影响回放结果，却**不参与 hash**。实测：

```
资金 100 万 vs 50 万          → hash 完全相同
手数 100 vs 200、仓位 0.1 vs 0.5 → hash 完全相同
```

后果：`compare_baseline` 会把这两次 run 判为「可比较」，给出一个
**不可解读的 delta**——而这正是 `config_hash` 机制存在的意义。

### 缺陷 60：`logged_semantics.knobs` 只有 20/23，且与 hash 自相矛盾

按 `knobs` 重算的 hash（`7a6da8e3`）**≠** 记录的 hash（`91fecace`）。
读者按 `knobs` 重建配置，会得到一个不同的指纹。

修复后 23 个键齐全，重算与记录一致。

### 修复
- 三项加入 `RISK_KNOBS`
- 新增测试：
  - `test_capital_params_are_part_of_semantics_hash`
  - `test_extract_knobs_covers_all_configurable_semantics`
  （实测回滚后两条同时变红）

### 影响
`semantics_hash` 值变化（`43c97eb4` → `50f2f5c1`），但对齐数字不受影响
（仍是 0.9912 / 0.8878）。已有冻结基线需要重新 freeze。

### 缺陷台账 58 → 60 项

---

## 0.15.5 — 2026-11-13

这一轮核对 `applicability`（报告里的适用范围声明）与实际能力是否一致。

### 缺陷 57：`applicability` 把已实现的能力列为「不在范围内」

| 位置 | 原文 | 实际 |
|---|---|---|
| `in_scope` | 「**单一交易日**、A 股分钟级…」 | 完整支持多日 |
| `out_of_scope` | 「**跨日持仓**、隔夜跳空、除权除息调整」 | 跨日持仓 + T+1 **已实现** |

证据：`tests/test_cross_day.py` 有 6 条专门测试、本样本 **1,422 笔全部
跨日结算**、`open_position` 74 笔如实上报。

**这是方向相反的误导**——比"漏写功能"更严重：读者会以为跨日持仓不可用，
从而放弃一个本来能用的能力。而且 `SKILL.md` 的表述（「支持多日（跨日持仓与
T+1 已实现）」）一直是对的，**只有报告里的 `applicability` 错**。

修复后 `in_scope` 明确列出跨日与 T+1；`out_of_scope` 改为真正没做的项
（隔夜跳空不单列损益、不复权、不建模撮合等）。

### 缺陷 58：`SKILL.md` 的缺陷数停在 9，台账已 58

读者会严重低估这个 skill 已历的验证强度。

### 修复
- 重写 `applicability` 的 in/out_of_scope
- `SKILL.md` 缺陷数 9 → 58
- 新增测试：
  - `test_applicability_scope_matches_actual_capability`（实测回滚后立刻失败）
  - `test_skill_md_defect_count_matches_ledger`（双向对账）

### 缺陷台账 56 → 58 项

---

## 0.15.4 — 2026-11-13

这一轮验证 `log_contract.md` 里一条从未实测过的声明：
「若日志侧每根都写 condition，一致率会覆盖全部 K 线」。

### 实测结果：声明成立

| 记录习惯 | condition 可比 | `one_sided` | 覆盖率 | 总一致率 |
|---|---|---|---|---|
| 仅翻转时写（现状） | 28,754 | 979,246 | 2.85% | 0.9912 |
| **每根都写** | **1,008,000** | **0** | **100%** | **0.9997** |

每根都写时 `comparable` **恰好等于总根数 1,008,000**，`one_sided` 归零。
这验证了 `one_sided` 口径的设计用意：记录稀疏时不算差异、记录完整时全部纳入。

**这是一个正面结果**——两种记录习惯都能正确工作，不需要用户先改日志格式。

### 补充
- `log_contract.md` 补上这张实测对照表（此前只有一句定性描述）
- 新增两条测试：
  - `test_every_bar_condition_logging_covers_all_bars`
  - `test_flip_only_condition_logging_yields_one_sided`

### 缺陷台账仍为 56 项（本轮未发现缺陷）

---

## 0.15.3 — 2026-11-13

这一轮核对价值结论的**稳健性**。查出一个此前完全没记录的边界。

### 缺陷 56：价值结论对样本长度高度敏感，方向会翻转

把同一套语义在**连续缩短的窗口**上重跑（取最近 N 个交易日）：

| 交易日 | ref 均值 | 差值 | 方向 |
|---|---|---|---|
| 14（全部） | −0.5527% | **−0.3678%** | ref **更差** |
| 7 | −0.1187% | **+0.1866%** | 反转（p=0.101，不显著） |
| 5 | — | **+0.9862%** | ref 更好（p<0.001） |
| 3 | **+0.8118%** | **+0.9948%** | ref 更好（p<0.001） |
| 2 | — | **+1.2516%** | ref 更好（p<0.001） |

**方向在 7 天附近翻转。** 14 天的 `negative` 不能外推到更短窗口，
短窗口的 `positive` 也不能外推到这里。

已用官方 `evaluate_naive()` 交叉验证（不是手工构造），14 天与 3 天两档一致。

**此前文档把 `negative` 作为该样本的可靠结论交付，未说明它不可外推。**
这正是"可靠负结果"与"普适判断"的分界——不写清楚，读者会误把
"这 14 天显式语义更差"当成"显式语义普遍更差"。

### 修复
- §5.3 新增「对样本长度高度敏感」子节，列出 2/3/5/7/14 天实测
- §9「未验证」列表补上**价值结论的跨样本稳定性**
- 新增测试：
  - `test_value_conclusion_sensitivity_is_documented`
  - `@pytest.mark.slow` `test_value_direction_reverses_on_short_window`
    （在真实夹具上断言 14 天 ref 更差、3 天 ref 更好）

### 缺陷台账 55 → 56 项

---

## 0.15.2 — 2026-11-13

上一轮修复 `bars_held` 并重新生成夹具后，§4.5（样本外复现）与 §5.25
（价值拆解）的数字都是修复前测的。这一轮全部重跑。

### 样本外复现（2026-09，11 天）

| 项 | 修复前记录 | 重跑 |
|---|---|---|
| exit 一致率 | 0.8879 | **0.8830** |
| 合计一致率 | 0.9921 | **0.9917** |
| Welch p | 0.0488 | **0.0461** |

**结构结论仍然全部复现**（四轴 1.00、exit 0.883、归因 `exit_eval` 100%、
价值 `negative`），显著性依旧明显减弱——仍未完全复现，这一点不变。

### 价值拆解

| 项 | 修复前 | 重跑 |
|---|---|---|
| reference 均值 | −0.5599% | **−0.5527%** |
| 总差值 | −0.3749% | **−0.3678%** |
| `t_plus_1` 占差值 | 82.6% | **84.0%** |
| 全样本 Welch p | 7×10⁻⁶ | **1.1×10⁻⁵** |

**结论方向不变**：`t_plus_1` 仍是唯一主导旋钮（占比反而更高），
关掉 T+1 后显式语义仍优于字面直译（p=0.036，此值未变）。

### 也核对过、确认未受影响
- §3.4 ST 交易占比仍为 47 笔 / 3.31%、52 个信号——`bars_held` 修复改变
  的是退出原因，不影响哪些交易存在
- §4.2 两张消融表：slow 测试逐格复现通过

### 同步
`oos_check.IN_SAMPLE` 的 `welch_p` 从 7e-06 改为 1.1e-05。

---

## 0.15.1 — 2026-11-13

上一轮修复后归因从 `single_knob` 降级为 `multi_knob`（30 条差异无法解释）。
按文档 §4.2 的要求，`multi_knob` 必须人工逐项核对——这一轮就做了这件事。

### 缺陷 55：夹具日志没跟着重放修复一起更新

逐条检查那 30 条"无法归因"的差异，模式非常一致：

| 类型 | 条数 | 形态 |
|---|---|---|
| `exit.reason` 不符 | 27 | 日志判 `max_hold`，重放判 `stop_loss`/`take_profit` |
| `exit.time` 不符 | 3 | 时点相差 3–18 分钟 |

全部发生在**次日开盘首根附近**，且入场时间都在 14:16–14:32（接近收盘）。

继续追查发现：用当前代码重新生成日志，同样的记录会得到 `stop_loss`——
**`fixtures/logs/` 里存的是修复 `bars_held` 之前的旧产物**。
上一轮改了重放器，却忘了重新生成夹具日志。

这不是语义分歧，是**夹具过期**。重新生成后：

| 项 | 过期日志 | 重新生成后 |
|---|---|---|
| 退出轴冲突 | 344 | **319** |
| 退出轴一致率 | 0.8790 | **0.8878** |
| 总一致率 | 0.9905 | **0.9912** |
| 归因 | `multi_knob` 91.3% | **`single_knob` 100%** |

`exit_eval` 重新完整解释了全部差异——这才是正确的形态。

### 修复
- 用当前代码重新生成 14 个日志文件（34,590 条）
- 新增 `test_fixture_logs_match_current_replayer`：**逐条比对**落盘日志与
  当前重放产出的 `exit_reason`，不一致即失败
  （实测有效：手改一条变回 `max_hold`，测试立刻报出该条）

### 一个方法论收获

`multi_knob` 这个结论本身就是**线索**：合成日志只与参考语义差 1 个旋钮，
理应能被完全归因。出现 `multi_knob` 说明有东西不对——这次是夹具过期。
若当时接受"无法归因"就漏掉了真正的根因。

### 缺陷台账 54 → 55 项

---

## 0.15.0 — 2026-11-13

这一轮验证 CLAUDE.md 要求的 **A 股交易约束**（100 股整数倍、14:45 强平、T+1）。
前两条正常，第三条挖出一个**影响主结论**的重放缺陷。

### 逐条实证（全量 1,496 周期）

| 约束 | 结果 |
|---|---|
| 100 股整数倍 | ✅ 0 笔违反 |
| 入场不晚于 14:45 | ✅ 15 笔晚于 14:45 的全部为 `rejected_late_entry`、无 qty |
| T+1 禁止当日平仓 | ✅ 1,422 笔收官**全部跨日**，0 笔当日 |

### 缺陷 53：强平推迟分支重复累加 `bars_held`

`force_exit_time` 分支在 `_exit_or_defer` 返回 False（T+1 推迟）后
**没有 `return`**，循环继续。下一根仍满足 `bar_minute >= force_time`，
再次进入该分支、`bars_held` 被重复累加。

实测影响：14:45→15:00 的 15 根让 `bars_held` 从 30 涨到 **360**
（另有 34 笔 328–344）。

后果不是显示问题：次日 `held = bars_held + j + 1` 立刻超过 `max_hold=30`，
这些仓位**在次日第一根就被当作"持有超时"平仓**。止损/止盈分支本来
就有 `return cycle`，只有强平这一条漏了。

### 缺陷 54：这个缺陷掩盖了 30 条真实差异

修复后主结论数字变化：

| 项 | 修复前 | 修复后 |
|---|---|---|
| 退出轴冲突 | 314 | **344** |
| 退出轴一致率 | 0.8896 | **0.8790** |
| 总一致率 | 0.9913 | **0.9905** |
| `exit_eval` 解释率 | 100% | **91.3%** |
| 归因判定 | `single_knob` | **`multi_knob`** |

**此前那 30 条差异被错误的"次日开盘平仓"逻辑抹掉了，于是归因看起来
100% 干净。** 修复后才暴露出它们无法由单一旋钮解释。

`verify_claims` 一次拦下 16 处偏差（含 9 个分日数字），已全部按实测更新。

### 新增测试
`test_force_exit_defer_does_not_accumulate_bars_held`——实测能抓住原缺陷
（回滚修复后该测试立刻失败）。

### 缺陷台账 52 → 54 项

---

## 0.14.3 — 2026-11-13

这一轮验证**代码能否在 CI 声明的环境里跑**（CI 矩阵 3.10/3.11/3.12，
而我一直在 3.12 上测）。

### 环境验证结果（全部通过）

| 验证 | 结果 |
|---|---|
| Python 3.9.6 全量 `build.py` | ✅ 数字完全相同（0.9913 / 0.8896） |
| Python 3.9.6 `verify_claims.py` | ✅ 79/79 |
| **屏蔽 `panda_data` 后跑测试** | ✅ **255 passed, 13 skipped, 0 failed** |
| 所有脚本在 3.9 下语法编译 | ✅ 通过 |
| `match` 语句 / 无 `__future__` 的 PEP 604 注解 | ✅ 无 |

屏蔽 `panda_data` 这一项很关键：CI 只装 `requirements-dev.txt`（不装
`panda-data`），若任何测试间接依赖它，CI 会在 `pip install` 后直接 ImportError。
实测确认不依赖。

### 缺陷 52：离线审计把「上界」报成「已知项的最大值」

`data_quality_audit --offline` 输出：

```
未建模占比上界：2.40%
判定：moderate — 未建模状态占比 2.40%，属可接受但需声明的范围
```

但 ST / 停牌此时是 `null`（**未核验**）。在线实测上界是 **4.67%**——
等于把「一半没查」说成「风险可接受」。

这恰恰是文档反复强调的原则（"不能把未核验当 0"），却在聚合层漏了：
上界取的是「已核验项的最大值」，把 `None` 直接过滤掉了。

而且**原测试 `assert result["overall_unmodeled_upper_bound"] is not None`
固化了这个错误行为**。

### 修复
- 有任一未核验项时：上界 `null`、级别 `unknown`，并给出
  `unverified_components` 与 `known_components_max`
- 修复后：`unknown — 有未核验的组成项：['st_or_suspended']（已核验部分最高 2.40%）`
- 在线路径不变（4.67% / `moderate`）
- 测试改为断言「离线时必须为 None」

### 缺陷台账 51 → 52 项

---

## 0.14.2 — 2026-11-13

这一轮核对 §3.3（单边缺失口径）与 §4.5（样本外复现）的数字。

### 缺陷 51：`jev_missing` 写成 1,633,358，超过总根数 1,008,000

这是一个**逻辑上不可能**的数字——单边缺失行数不可能多于该轴总根数。
实际值是 979,246。

这类错误只要做一次量级检查就能发现，但此前没有任何校验覆盖它。

### 修复
- 按实测更正为 979,246
- `verify_claims` 新增两条检查（77 → **79**）：
  - `non_match_rows <= total_rows`
  - 条件轴覆盖率与 `summary.condition_coverage` 一致
- 实测有效：把值改回 1,633,358，两条检查都立刻报错

### 核对中确认正确的项（我一度怀疑过）

| 项 | 结果 |
|---|---|
| 条件轴覆盖率 2.85%（28,754 / 1,008,000） | ✅ 与 `summary` 一致 |
| 样本外样本量 12,050 vs 611 | ✅ 实测确认 |
| 样本内样本量 27,987 vs 1,422 | ✅ 与报告一致 |

**我最初以为「12,050 vs 611」与 exit 轴可比 1,222 冲突**，查下来是三个不同口径：
Welch 全样本收官条数（27,987 vs 1,422）、账本可比项（36,086 / 17,264）、
配对后周期数（2,844 / 1,222）。已在文档里补一段说明，避免读者踩同一个坑。

### 缺陷台账 50 → 51 项

---

## 0.14.1 — 2026-11-13

上一轮发现判定逻辑漏洞后，这一轮系统性审计**其余判定路径**是否有同类问题。

### 审计结果

| 判定路径 | 结论 |
|---|---|
| `alignment_conclusion` | ✅ 上轮已加"每轴须有可比项" |
| `value_assessment` | ✅ 有覆盖率门槛 + 最小周期数 + 全样本检验兜底 |
| `attribution` | ✅ `no_divergence` 有明确条件，`single_knob` 需达阈值 |
| `data_quality` | ✅ 离线时把"未核验"标为 null 而非 0 |

判定分支本身**没有**新的"未验证冒充结论"问题。

### 缺陷 50：`reason` 文字里的 p 值仍在舍入

但查出一个外围问题：`value_assessment.verdict.reason` 里写着
`round(p_value, 6)`。字段层面的 `sign_test_p` 在 v0.12.6 已修成
`3.013e-12`，**文字描述里却还是 `p=0.0`**——同一份报告，字段对、文字错。

实测：胜 60 负 0 时精确二项 p = 1.7e-18，旧写法显示 `p=0.0`。

### 修复
- 新增 `report._fmt_p()`，统一 `{p:.4g}` 格式化
- 两处 `reason` 改用该函数
- 新增 `test_value_reason_never_shows_p_as_zero` 与 `test_fmt_p_preserves_small_values`

### 缺陷台账 49 → 50 项

---

## 0.14.0 — 2026-11-13

这一轮逐条实测 `applicability.invalid_when` 声明的 5 个"结论失效"场景，
看它们是否真的会暴露，而不是只写在文档里。查出一个"没验证冒充一致"的缺陷。

### 缺陷 49：有轴零可比时仍判 `consistent`

构造一份只写 `condition`、完全不含 `signal`/`plan` 的日志：

```
condition: comparable=2
signal/wait/entry/exit: comparable=0     ← 四个轴一条都没比过
verdict: consistent                       ← 仍然判"一致"
```

`exit` 恰恰是最关键的一轴（退出判定口径正是本项目的主要分歧来源），
完全没比过却报告"一致"。这等于把**没验证**说成**一致**。

修复：判 `consistent` 增加第三个条件——**每个轴都必须有可比项**。
未满足时判 `inconclusive`，并在 `reason` 里点名：

> 以下轴线完全没有可比项：['signal','wait','entry','exit']。虽然其余轴
> 一致率 1.0000，但未覆盖的轴可能藏着差异，不能据此判定语义一致。

### 其余 4 条的实测结果

| invalid_when 条目 | 实测 |
|---|---|
| 停牌/ST/涨跌停未建模 | ✅ 已量化并在 `applicability` 声明（上界 4.67%） |
| 除权除息 | ✅ 已在 `data_access.md` 说明（pre_close 口径） |
| **日志缺 wait_bars/entry_price** | ❌ **判 consistent**（本缺陷） |
| 时间戳口径与 bar_timestamp 不符 | ✅ 能被抓出（condition 一致率 → 0） |
| 样本天数不足 | ✅ 已由 `min_cycles` 与覆盖率门槛约束 |

### 新增测试
`test_report.py` 27 → 29：
- `test_alignment_inconclusive_when_any_axis_unverified`
- `test_alignment_consistent_when_all_axes_have_comparable`（防止门槛过死）

阳性对照组仍判 `consistent`，区分度完好。

### 缺陷台账 48 → 49 项

---

## 0.13.9 — 2026-11-13

前几轮反复出现同一类问题：「改一处逻辑，别处数字悄悄过期」。这一轮不再
逐处打补丁，而是**系统性地找 `verify_claims` 的覆盖缺口**。

### 缺陷 48：`verify_claims` 覆盖不全，是反复出错的根因

`verify_claims` 只核对了 40 个路径，报告里大量字段没被检查。补了 6 条
内部一致性检查（总数 71 → **77**）：

| 新增检查 | 抓的是 |
|---|---|
| `divergence_items` 四处同口径 | 上轮那个 979,634 vs 314 的错 |
| `ledger.non_match_rows == one_sided + divergent` | 新增字段的分解关系 |
| 归因各行 `explained <= baseline_divergences` | 消融不可能解释超过基线 |
| `inline_rows <= max_inline_rows` | 截断上限 |
| `inline_truncated` 标记正确 | 截断标记与行数一致 |

实测有效：把 `divergence_items` 改成 979,634、把 `inline_truncated` 取反，
两项都立刻报错。

### 缺陷 47：§4.2 的 naive 消融表也整体过期

| 操作 | 文档 | 实际 |
|---|---|---|
| 基线 | 7,206 | **20,774** |
| 只改 `bar_timestamp` | 5,489 | **15,581** |
| 只改 `baseline_price` | 7,261 | **20,848** |
| 只改 `t_plus_1` | 8,742 | **23,063** |
| 全部改成 naive | 0 | 0 ✓ |

**趋势完全一致**（单项解释不了、改两个反而增加、全改才归零），
结论不变，只是数值全错。`bar_timestamp` 的解释率也从 23.8% 改为 25.0%。

### 新增测试
`tests/test_multi_knob_docs.py` 从 3 例扩到 5 例，新增：
- naive 消融表的**内部逻辑**断言（单项不解释、改两个反增）
- `@pytest.mark.slow` 在真实夹具上**逐格复现**该表（64 秒）

### 缺陷台账 46 → 48 项

---

## 0.13.8 — 2026-11-13

这一轮核对**受容差修复影响、但当时没跟着更新**的章节。§4.2 的多旋钮表
在 v0.12.8 之后已经全错。

### 缺陷 46：§4.2 多旋钮表的数字整体过期

| 场景 | 文档 | 实际 |
|---|---|---|
| 仅 `exit_eval` | 314 / 100% | 314 / 100% ✓ |
| 仅 `wait_bars` | **4,522** | **2,963** |
| `exit_eval` + `wait_bars` | **4,649 / 92.0%** | **3,096 / 90.3%** |

数字变化方向符合预期：放宽容差后，部分时点抖动不再算冲突，
所以 `wait_bars` 造成的差异数下降。

**结论本身仍然成立**——归因判定仍是 `multi_knob`，首位仍是 `wait_bars`，
`exit_eval` 依然被完全漏掉。这一节要证明的方法边界没有变，
错的只是具体计数。

### 修复
- 三处数字按实测重算，`原因` 段落里的 4,522 同步改为 2,963
- 新增 `tests/test_multi_knob_docs.py`（3 例）：
  - 多旋钮表内部一致（合并 ≥ 单独）
  - 「仅 exit_eval」行与当前报告一致
  - **`@pytest.mark.slow`：在真实夹具上重跑两个场景核对数字**（46 秒，
    CI 的慢速步骤会跑）

### 也确认了正确的项
`185 MB → 68 KB（69,454 字节）` 的账本缩减比例仍然准确。

### 缺陷台账 45 → 46 项

---

## 0.13.7 — 2026-11-13

这一轮核对**报告内部各处的计数是否同口径**。查出一个差三个数量级的缺陷。

### 缺陷 45：`divergence_items` 报的是"非 match 行"而非"冲突数"

同一份 `report.json` 里，同一个概念出现了不同数字：

| 位置 | 值 |
|---|---|
| `alignment_conclusion.divergence_items` | **979,634** |
| `summary.divergence_items` | 314 |
| `ledger.aggregate.total.divergent` | 314 |
| `ledger.divergence_rows` | **979,634** |

**差三个数量级**。读者看到 979,634 会以为有近百万条真实冲突，
实际那 98 万条几乎全是 `jev_missing`（日志只在状态翻转时记录）。

根因：`build_alignment_conclusion` 收到的 `divergence_rows` 是
「全部非 match 行」，而不是真实冲突数。`verify_claims` 恰好没覆盖这个字段，
所以从很早以前就错了却一直没被发现。

### 修复
- `divergence_items` 改用真实冲突数，四处口径统一
- `ledger.divergence_rows` 同步；另设 `non_match_rows` 保留原含义（979,634）
- `api_guide.md` 新增「三个行数，别混用」对照表
- 新增 `tests/test_report_consistency.py`（5 例）：
  - 四处 `divergence_items` 必须相等
  - 总冲突数 == 各轴 `divergent` 之和
  - `non_match_rows` 单列且 == `one_sided + divergent`
  - `per_day` 加总 == `total`
  - `inline_truncated` 与 `max_inline_rows` 一致

### 顺带验证（无问题）
- `per_day` 加总：comparable 36,086、divergent 314，与 total 完全一致
- `ledger_mode: full`：1,015,406 行 / 185 MB / 32 秒，行数 == `total_rows`
- `inline_truncated` 在 50 行上限时正确置 true

### 缺陷台账 44 → 45 项

---

## 0.13.6 — 2026-11-13

这一轮核对 **`fixtures/reference` 是否真的来自 panda 数据源**——它提供
`pre_close`，是涨幅判断的基准，此前没有任何测试校验。

### 与 panda 数据源逐字段核对（真实数据）

| 核对 | 结果 |
|---|---|
| 300 只 × 2 天日线 OHLC + `pre_close` vs `get_stock_daily` | **600 条全对** |
| 2 只标的全天分钟线 vs `get_stock_min` | **480 行 × 5 字段全对** |

夹具忠实复制了数据源，没有二次加工。

### 缺陷 44：两条数据源口径从未写明

核对时发现两类"看起来像错误、实际是口径"的差异：

**① `pre_close` 不总等于前一交易日 `close`**（实测 5/4,200）
源于除权除息或数据源自身的 pre_close 口径。已用 panda 官方接口确认
（`601298.SH` 20261028：panda 的 `pre_close=9.43`，前一日 `close=9.57`）。

**② `day_open` 取的是分钟线首根 open，不是日线 open**（实测 2/4,200，最大差 1.385%）
集合竞价使 09:31 首根与日线 `open` 不同。

两者此前都没写进文档。读者自己核对时会以为是夹具错误，
**实际是必须写下来的口径假设**。

### 影响面
`day_open` 只用于 `baseline_price=day_open` 的场景；参考语义与 `jev_assumed`
都用 `prev_close`，**主对齐结论不受影响**，只在 `naive_literal` 基线里体现。

### 修复
- `semantics_matrix.md` 标明 `day_open` = 分钟线首根 open，并列出那 2 个案例
- `data_access.md` 补两条数据源口径与实测比例
- 新增 `tests/test_fixture_integrity.py`（4 例）：pre_close 差异比例 <1%、
  日线 close 必须严格相等、day_open 取首根、文档必须写明口径

### 缺陷台账 43 → 44 项

---

## 0.13.5 — 2026-11-13

这一轮核对 **§9「结论与边界」**——读者据此判断能不能信这个工具。
这一节长期没有任何自动校验，查出 3 处错误。

### 缺陷 43：§9 的数字无人校验

| 项 | 文档写的 | 实际 |
|---|---|---|
| 未建模状态上界 | 4.20% | **4.67%** |
| ST 交易占比 | 2.04%（41 笔） | **3.31%（47 笔）** |
| ST 信号数 | 47 | **52** |
| 容差敏感性 | 「0–5 分钟结果不变」 | **0.9895 / 0.9913 / 0.9920 / 0.9931，单调上升** |

最后一条最严重：v0.12.8 修好容差判定后，「结果不变」已经不成立，
但这句话作为结论留在了 §9 里，与 §3.6 的更正说明**自相矛盾**。

### 修复
- 三处数字按实测更正
- 「容差结果不变」改为列出四档实际值并标注单调上升
- 新增 `tests/test_conclusion_consistency.py`（5 例）：
  - 总体一致率 / 退出轴一致率与报告对账
  - 未建模上界与 `applicability` 对账
  - **禁止**出现「容差 0–5 分钟结果不变」
  - ST 交易占比在 §3.4 与 §9 两处必须一致

### 顺带核对（无问题）
- `t_plus_1` 占总差值 82.6%、关 T+1 后 p=0.036 —— 与 §5.25 完整拆解表一致
- ST 序列占比 4.67%、触涨停 1.76%、触跌停 0.64% —— 与 `applicability` 一致

### 缺陷台账 42 → 43 项

---

## 0.13.4 — 2026-11-13

这一轮针对真实日志导入时最常见的三类坑做压力验证：代码写法、同分钟多条、
时间边界。

### 缺陷 42：标的代码大小写不归一，导致全部对不上

日志写 `000001.sz`（或 `" 000001.sz "`）而 K 线是 `000001.SZ` 时：

```
condition 轴: jev_missing=72000, comparable=0, match_rate=null
```

**一条也配不上**。报告只显示"一致率 null"，看不出真正原因是大小写，
表现上就像"这份日志和行情毫无关系"。真实日志若用小写代码，
会静默得到彻底错误的结论。

修复：加载时统一 `strip().upper()`，K 线与日志两处都改。

### 已确认无问题的边界
| 场景 | 结果 |
|---|---|
| 同一标的同一分钟多条 condition | ✅ 保留全部，按出现顺序 |
| `symbol` 首尾空格 | ✅ 已 strip（现在也统一大写） |
| 跨午休 `11:30` / `13:01` | ✅ 正常保留，不被缺口检测误判 |
| 三种时间戳写法 | ✅ 结论完全相同 |

### 新增测试
- `test_symbol_case_and_whitespace_are_normalized`
- `test_bar_symbol_case_is_normalized`

### 文档同步
`log_contract.md` 的 `symbol` 说明改为「去首尾空格并统一大写」，
不再是容易误解的"完全一致"。

### 缺陷台账 41 → 42 项

---

## 0.13.3 — 2026-11-13

这一轮用**「外部厂商格式」日志跑端到端**：字段名不同（`code`/`at`/`event`/`matched`）、
时间戳是 `HHMMSS`、condition 只在状态翻转时落盘——这是真实 JEV 日志的实际形态。

### 实测通过的部分
- 字段映射 → 适配 → 对齐全链路跑通，`log_source` 正确判 `actual`
- 状态翻转式记录产生 71,918 条 `jev_missing`，**正确归入 `one_sided`**
  而不进一致率分母——文档口径成立
- 单日夹具下日志**不要求** `date`（与契约一致）
- 三种时间戳写法（`HH:MM` / `HHMMSS` / `YYYY-MM-DD HH:MM:SS`）
  得到**完全相同**的结论

### 缺陷 41：无法判定的 `hit` 被静默当成 `False`

```python
adapt_records([{"hit": "也许", ...}])   # ok=True, hit=False
```

`"也许"` 落在旧白名单之外，被转成 `False`——把「不知道」变成「没命中」。
下游完全看不出来。这是最危险的一类静默降级：**不确定被转成了确定结论**。

已改为白名单外报 `invalid_hit_value`，并明确接受的写法：
`bool` / `1` `0` / `true` `false` `yes` `no`（大小写不敏感）。

### 新增测试（`test_adapt_logs.py` 18 → 22）
- `test_unrecognized_hit_is_an_error_not_false`
- `test_hit_accepts_common_boolean_spellings`
- `test_adapt_failures_carry_structured_errors`（失败必须带 `errors[].code`）
- `test_timestamp_formatting_does_not_change_verdict`

### 文档同步
`log_contract.md` 补上「认不出的值会报错，不会默认成 False」。

### 缺陷台账 40 → 41 项

---

## 0.13.2 — 2026-11-13

这一轮核对**社区审核会看的合规内容**。

### 缺陷 40：CI 的 release hygiene 只查文件存在、不查内容

原步骤只有 `test -f README.en.md` 之类。但社区审核真正看的是：

- README 免责声明是否覆盖**四个要点**（研究用途 / 不保证收益 / 风险边界 / 非官方背书）
- INSTALL.md 是否覆盖**五个平台**（Claude Code / Codex / Cursor / Hermes / OpenClaw）
- 许可证是否用 SPDX 的 `GPL-3.0-only`
- 有没有残留占位符（TODO / 待补充 / `<your-...>`）
- 有没有泄露凭证值、内网地址、私人邮箱

这些**内容全错也照样能让 CI 变绿**。

### 修复
- CI `Release hygiene` 步骤扩充为真实内容断言
- 新增 `tests/test_release_compliance.py`（7 例），本地即可跑：
  - 免责声明四点（中/英各一遍）
  - INSTALL 五平台覆盖
  - SPDX 许可证（skill.json / SKILL.md frontmatter / LICENSE 首行）
  - 三处 `name` 一致（仓库名 / skill.json / SKILL.md）
  - 无占位符
  - **无凭证 / 内网地址 / 私人邮箱**（`git@github.com` 这类 SSH clone 地址已排除）
  - `entrypoint` 与 `entry_script` 真实存在

### 核对结果（本轮未发现内容问题）
免责声明四点齐全（中英都有）、INSTALL 覆盖五平台、无占位符、无敏感信息。
**唯一缺陷是检查本身不到位**——这轮补的就是这层防线。

### 缺陷台账 39 → 40 项

---

## 0.13.1 — 2026-11-13

这一轮核对**面向用户的文档**（README 中/英）与 **`agents/` 运行时适配器**
——后者是社区审核的硬性要求。查出 3 个缺陷。

### 缺陷 37：README 的「实例」数字严重过时

README.md 与 README.en.md 的实例表都写着：

| 轴 | 旧值 |
|---|---|
| condition | 1,576 项 |
| signal/wait/entry | 各 168 项 |
| exit | **0.80（282 项）** |

这是很早的单日小样本。而仓库夹具是 **14 天**，读者照 README 跑
`python3 scripts/build.py` 得到的是 28,754 项 / 0.8896，**完全对不上**。
`build.py` 也没有 CLI 参数可以只跑一天，旧数字根本无从复现。

已按实际输出重写，并注明退出轴随 `time_tolerance_minutes` 变化的三个值。

### 缺陷 38：`openai.yaml` 的旋钮清单与代码三处不一致

`x-semantics-knobs` 声明 **18** 个旋钮，而代码里：

| 集合 | 数量 |
|---|---|
| `REFERENCE_SEMANTICS` 可配置语义键 | **23** |
| `KNOB_VALUES` 可做单旋钮消融的旋钮 | **10** |

18 既不是前者也不是后者，是手抄残留。现在拆成两个字段：

- `x-semantics-knobs` = 23，可配置全集
- `x-attribution-knobs` = 10，可消融子集（阈值/资金类参数不构成"解释选择"，
  不适合做归因）

### 缺陷 39：`openai.yaml` 版本长期未跟

`version: 0.1.0` 而 `skill.json` 已是 `0.13.0`。

### 新增测试（`tests/test_runtime_adapters.py`，9 例）
适配器文件齐备、声明的脚本与 entry 真实存在、两组旋钮清单与代码双向对账
（含子集关系）、版本与 `skill.json` 一致、**README 实例数字与报告一致**。

### 顺带核实
`openai.yaml` 里声明的各条命令（`validate.py --bars-dir ... --logs-dir ...`、
`env_check.py --json`、`build_fixtures.py --date ... --universe ...`）
逐个实跑，参数名全部正确。

### 缺陷台账 36 → 39 项

---

## 0.13.0 — 2026-11-13

这一轮逐条实跑 **§7 错误路径**那 11 行声明。大部分正确，查出 2 个真实缺陷
（外加一个在验证过程中撞见的）。

### 缺陷 35：`fetch_data.py` 直接运行必崩

按 §8 的复现命令跑 `python3 scripts/fetch_data.py --date 20260101 --symbols 600519.SH`：

```
ModuleNotFoundError: No module named 'scripts'
```

该文件漏了 `sys.path.insert(0, REPO_ROOT)`，而其它脚本都有。
问题只在**真正调用凭证**时才触发（`_client()` → `from scripts.credentials import ...`），
所以 `--help`、单元测试都发现不了。这直接影响"重新生成夹具"这条主路径。

### 缺陷 36：`changed_fields` 不报告 `config_hash` 本身

`compare_baseline.compare()` 在 `comparable=false` 时给出：

```json
{"comparable": false, "changed_fields": [], 
 "note": "config_hash 不一致，差异不可解读；请确认语义、夹具或日志来源是否变化"}
```

`changed_fields` 空着，note 却让读者去查三个组成项。只改 `config_hash` 的情形下
读者完全无从判断哪里变了。已加入 `config_hash` 自身的变化检测。

### §7 逐条实跑结果

| 场景 | 文档 | 实测 |
|---|---|---|
| 空字符串 / 未知字段 / bars_dir 不存在 / 语义非法 | ReplayError | ✅ 4/4 |
| K 线缺字段 / high<low / 价格非正 / 重复 | ReplayError | ✅ 4/4 |
| 日志 kind 非法 | LoadError | ✅ |
| 多日缺 `date` | LoadError | ✅（v0.12.7 已验） |
| 缺 panda_data | `env_check` 报 warn 不报 blocked | ✅ warn / blocked=0 |
| config_hash 不一致 | comparable=false，不给 delta | ✅（`changed_fields` 已修） |
| 非交易日拉数据 | **退出码 2** | ✅（我一开始误读成 0，那是 `tail` 的退出码） |

### 新增测试
- `test_fetch_data_can_run_as_script`（以脚本方式加载并调用 `_env`）
- `test_changed_config_hash_alone_is_reported`
- 缺陷台账 34 → 36 项

---

## 0.12.9 — 2026-11-13

这一轮做**真实冷克隆验收**（§1.1）并核对 §8 复现环境。流程本身全过，
但发现文档里的验收数字长期过期。

### 缺陷 34：§1.1 / §8 的验收数字都是旧值

从 `origin/main` 全新 clone 到 /tmp 逐项实跑，对照文档：

| 项 | 文档写的 | 实际 |
|---|---|---|
| `verify_claims.py` | 27/27（§1.1）、61/61（§1.0a） | **71/71** |
| `pytest tests/ -q` | 113 passed | **275 passed, 1 skipped** |
| `build.py` | 54 秒 | **31 秒** |
| Python | 3.12.12 / 3.11.16 | 3.12.12 / **3.9.6**（实测） |

冷克隆验收是最容易被读者照着跑的一节，数字不对会让人以为环境有问题。
已全部按实测重写，并新增 `test_doc_counts_match_actual`：
直接跑 `verify_claims` 与 `pytest --collect-only`，把真实值对回文档。
（实测有效：把 `71/71` 改成 `99/99`，测试立刻报 `实际 71/71`。）

### 冷克隆实测结果（全部通过）
```
env_check     ok=true
validate      ok=true, 0 issues
build         31 秒，exit 0
verify_claims 71/71
pytest        275 passed, 1 skipped
```
总一致率 0.9913、退出轴 0.8896，与本机完全一致；`output/` 由 `build.py` 自动创建。

### 纯标准库这条也真验了
系统 Python 3.9.6 跑通，数字相同。再用 `python3 -S`（屏蔽 site-packages，
等价于无任何三方包）复跑，仍是同一组数字，且报告正确回显：

```
config_warnings: ['缺少 pyyaml，未加载 config/replay_config.yaml，使用内置默认值']
```

说明缺 pyyaml 不会静默降级——YAML 值与内置默认值逐项对齐。

### 缺陷台账 33 → 34 项

---

## 0.12.8 — 2026-11-13

这一轮核对**验证文档里的表格本身**是否成立——逐张拿真实数据复算。
查出一个影响所有对比数字的缺陷。

### 缺陷 32：`time_tolerance_minutes` 根本不参与判定

`§3.6 参数敏感性` 那张表写着四档容差结果**完全一致**，我当时的解释是
「退出时刻差是整分钟离散值，工时点比较天然精确」。**这个解释是错的。**

真正原因：四处判定都写死了

```python
status = "match" if gap == 0 else "divergent"
```

`time_tolerance_minutes` 只影响**配对搜索半径**，不影响**判决**。
所以把容差从 0 调到 5，结果一模一样——不是结论稳，是参数没生效。

实测影响：201 条退出时间冲突中，**65 条**差值 ≤1 分钟，本该算作容差内的抖动。

修复后四档真正分化：

| 容差 | 总一致率 | 退出轴 | 冲突数 |
|---|---|---|---|
| 0 | 0.9895 | 0.8667 | 379 |
| 1（默认） | **0.9913** | **0.8896** | **314** |
| 2 | 0.9920 | 0.8991 | 287 |
| 5 | 0.9931 | 0.9121 | 250 |

**主结论方向不变**（`inconclusive` / `negative` / `exit_eval` 100%），
但所有数字都更新了。

### 缺陷 33：`oos_check.IN_SAMPLE` 是硬编码基准

修好容差后主样本变成 0.9913 / 0.8896，但 `IN_SAMPLE` 仍写 0.9895 / 0.8667，
复现判定会拿旧基准比新结果。已同步，并加测试以实际报告反查。

### 修复
- `aligner.py` 四处判定改为 `abs(gap) <= tol_minutes`
- `oos_check.py` 更新 `IN_SAMPLE`
- 新增测试：
  - `test_verdict_tolerance_actually_changes_verdict`（tol=2 divergent / tol=3 match）
  - `test_entry_and_signal_axes_honour_tolerance`
  - `tests/test_oos_check.py`（4 例，此前该脚本零测试覆盖）
- 证据文档：§3.6 表重写并保留更正说明、§3.1/§4/§5.3 数字更新、
  样本外表更新（exit 0.8879、合计 0.9921）、账本体积表按实际重算
- 缺陷台账 31 → 33 项

### 一句反省
上一轮我"核对"了 §3.6 的表格，看到四档数字一致就接受了，还顺着文档的
错误解释复述了一遍。**数字与文档一致 ≠ 数字是对的**——这次是拿参数
真的拨一遍才发现的。

---

## 0.12.7 — 2026-11-13

这一轮验证**「真实 JEV 日志到位后零改动接入」**这个核心承诺是否成立。
结论：代码没问题，但**契约文档漏了一条必需字段**，照文档准备的日志会被直接拒收。

### 缺陷 30：契约没写 `date`，纯契约日志无法加载

把合成日志剥成「只保留 `log_contract.md` 列出的字段」，`run()` 立刻失败：

```
LoadError: 记录 0 在多日模式下缺 date 字段，无法归属到具体交易日
```

`ts` 只有 `HH:MM`，多日夹具下加载器无法判断记录属于哪一天。
`log_contract.md` 通篇没提 `date`——**照着文档准备的真实日志会被拒收**。

补上 `date` 后可完整跑通，且 `log_source` 正确判为 `actual`、
一致率与合成日志相同（0.9895）。这同时证明：合成器附带的
`_synthetic` / `cross_day` 等字段**不是必需**的。

### 缺陷 31：`validate.py` 对同一问题只报无关的 warn

同一个缺 `date` 的目录，`validate.py` 报的是：

```
[warn] log_symbol_not_in_bars: 300 个序列在日志里但不在 K 线里
ok: true
```

真正原因是缺 `date`，诊断却把修复方向指向标的代码。已改为报
`missing_date_in_multiday`（`severity=error`，`ok=false`）。

### 修复
- `log_contract.md` 补 `date` 字段（标注"多日必需"）并说明内部字段非必需
- `README.md` / `references/data_access.md` 同步这条前提
- `validate.py` 增加多日缺 `date` 的 error 检查
- 新增测试：
  - `test_contract_only_logs_load_end_to_end`（纯契约日志端到端，判为 `actual`）
  - `test_multiday_logs_without_date_are_rejected_with_clear_error`
  - `test_validate_flags_missing_date_in_multiday`
  - `test_normalize_multiday_uses_date_for_series_key`
- 缺陷台账 29 → 31 项

### 验收（真实 panda 数据）不变
36,086 可比 / 0.9895；exit 0.8667；价值 negative（82.6% 由 `t_plus_1` 驱动）；
样本外 5 项结构复现、显著性减弱（p 7e-06 → 0.0488）。
`alignment_conclusion.verdict` 仍为 **inconclusive**（日志仍是合成）。

---

## 0.12.6 — 2026-11-13

这一轮核对**文档字段表**与**实际产物**是否一致。查出 3 个真实缺陷。

### 缺陷 27：`config` 静默接受拼错的键

`input_data` 对未知字段一直报 `unknown_field`（注释写明"刻意不做静默忽略"），
但 `config` 把拼错的键默默 `_deep_merge` 进去：

```python
run({}, config={"time_tolerence_minutes": 5})   # 拼错
# 实际生效的仍是默认值 1，评测跑完看着正常，结果却与预期不符
```

修复：`load_config` 校验未知键，抛 `ConfigError(code="unknown_config")`。
`ConfigError` 定义在 `config.py` 内以免循环导入。

### 缺陷 28：`ledger.aggregate.by_axis` 各轴键集不一致

api_guide 写"每个轴：`match` / `divergent` / `one_sided`"，但实际
**只有 exit 轴**有 `divergent`——其余四轴零冲突时该键整个消失。
按文档写 `row["divergent"]` 会直接 KeyError，`comparable == match + divergent`
也无从校验。

修复：每轴固定输出 `match` / `divergent`（零也写）。
实测修正后五轴均满足 `comparable == match + divergent`。

### 缺陷 29：`sign_test_p` 被舍入成 0.0

符号检验 wins=484 / losses=727（n=1,211），精确二项 p = **3.0e-12**，
但报告用 `round(p, 6)` 把它压成 `0.0`。读者会当成"p 恰为 0"——
统计上不可能，也会误判证据强度。

修复：改用 `float(f"{p:.4g}")`，小值保留科学计数法。

### 核对通过的项（无需改动）
- api_guide 列出的 7 个 config 键全部实传入 `run(config=...)` 并确认生效
- `summary` 的 11 个字段、`alignment_conclusion`、`value_assessment`
  各子块字段与文档一致
- 15 个顶层返回字段齐全（`artifacts` 属 `run()` 返回值，不在 `report.json`，
  文档该节标题正是「返回值」，无误）

### 文档更新
- api_guide 补充 `config` 未知键的处理口径
- api_guide 补 `comparable_retention`，并说明**可大于 1**（`breakout_field` 实测 1.002）
- api_guide 标明 `reason` 仅在 `skipped=true` 时出现（原表列为常驻字段，误导）
- 缺陷台账 26 → 29 项

### 结果
`verify_claims` 71/71；全量测试全部通过。

---

## 0.12.5 — 2026-11-13

按验证文档用**真实 panda 数据**跑了一整套验收，查出两个缺陷。

### 缺陷 23：多日 manifest 只打印、从不落盘

`fixtures/manifest.json` 长期描述的是「最后一天」而不是整套夹具：

| 字段 | manifest 声称 | 磁盘实际 |
|---|---|---|
| `bar_count` | 72,000 | **1,008,000** |
| `log_record_count` | 0 | **34,590** |
| `dates` | 不存在 | 14 个交易日 |

根因：`build()` 每构建一天都会覆盖写一次 `manifest.json`，
而 `main()` 把合并后的多日 manifest **只 `print` 没写盘**。
报告里的 `provenance.fixture_manifest` 直接引用它，等于对外错报夹具规模。

### 缺陷 26：夹具压缩包不可重现

`gzip.open(..., "wb")` 会把**当前时间**写进 gzip 头。同一份数据每次重建
都得到不同字节流，`fixture_fingerprint` 每次都变——「冻结夹具」名不副实，
`compare_baseline` 还会无故报不可比。改用 `GzipFile(..., mtime=0)`。

实测：`250b7572` → `685dec07`（重建后）→ 修复后连压两次都是 `8f140eb4`。
解压后的 K 线内容三次完全一致，只有 gzip 头不同。

### 修复
- `main()` 合并结果写盘；`build()` 改用 `mtime=0` 压缩
- 新增 `test_manifest_describes_the_actual_fixtures`：以磁盘实际
  K 线根数、日志条数、日期列表反查 manifest（实测能抓出 72000 vs 1008000）
- 新增 `test_bar_gzip_is_reproducible`：gzip 头 MTIME 必须为 0
- 按实际夹具重建 manifest 并重新压包

### 顺带修正
- 证据文档第 6 节缺陷台账从 22 项补到 26 项
- 新增 `test_defect_ledger_count_matches_rows`：标题的「N 项」必须等于表行数且编号连续

### 真实数据验收结果（未变）
14 交易日 / 300 只全期固定标的 / 4,200 序列：合计 36,086 可比、0.9895；
价值 negative，82.6% 由 `t_plus_1` 驱动；样本外 11 天结构性结论全部复现，
唯显著性减弱（p 7e-06 → 0.0488）。
`alignment_conclusion.verdict` 仍为 **inconclusive**（日志仍是合成）。

---

## 0.12.4 — 2026-11-13

验证「README / 证据文档里的结构性声明是否与实际一致」。

### 发现
1. **README 的 `scripts/` 目录树漏了 7 个文件**（`data_loader.py`、
   `adapt_logs.py`、`credentials.py`、`trade_audit.py`、`knob_efficacy.py`、
   `value_decomposition.py`），`references/` 也漏了 `validation_evidence.md`。
   **英文版 `README.en.md` 漏得更多**（同样的 7 个，外加 `oos_check.py`、
   `data_quality_audit.py`、`controls_check.py`、`verify_claims.py`、`config.py`）。
   读者照树结构去找会找不到。
2. **证据文档的逐文件用例数整体失真**：8 个文件与 `pytest --collect-only`
   的实际收集数不符（如 `test_report.py` 写 24 实为 26、
   `test_semantics.py` 写 15 实为 13）。`verify_claims` 只对账关键指标，不管这张表。
3. **证据表格漏列 `test_fixture_universe.py`**。
4. 1.0d 节写「4 例」，实际只有 3 例（后来那条第 4 例早已被删）。

### 修复
- README（中/英）目录树补全脚本与 reference 条目
- 逐文件用例数按 `pytest --collect-only` 的实际收集数全部改正
- 表格补上 `test_fixture_universe.py`
- `test_doc_commands.py` 新增 3 条防漂移用例：
  - **证据表格的测试文件集合 == `tests/` 实际文件集合**
  - **证据表格每个文件的用例数 == pytest 实际收集数**（以 `--collect-only` 为唯一真相，
    避免手数 `def` 被参数化/fixture 干扰）
  - **README（中/英）的 `scripts/` 目录树必须列全所有脚本**
- 已实测：把 `test_aligner.py` 的数字改成 99，新测试立刻失败并报 `99 vs 15`

### 结果
`verify_claims` 71/71；全量 205 passed / 1 skipped。

## 0.12.3 — 2026-11-13

验证「文档里写的命令能不能跑」，发现整篇 `data_access.md` 是别的 skill 的模板。

### 发现
`references/data_access.md` 通篇写着 `scripts/fixture_generator.py`、
`replay_engine.py`、`constraints_evaluator.py`——**这些都不是本 skill 的文件**。
读者照文档跑会直接报"文件不存在"。

（早前重写过一次，但某次 `rsync --delete` 把发布副本的旧版本反向覆盖了回来。）

### 修复
- 整篇重写 `data_access.md`：只列真实存在的脚本、凭证解析、实测接口口径
- 新增 `tests/test_doc_commands.py`（4 例）：
  文档引用的每个脚本必须存在、禁止他 skill 脚本名、脚本需 docstring、语法可解析

### 逐条实跑
env_check / validate / data_quality_audit --offline / verify_claims / build 全部 exit 0。

202 passed / 1 skipped；claims 71/71。


## 0.12.2 — 2026-11-13

补上冻结基线功能的测试。README 与 api_guide 都写了 freeze/compare/list，
但此前**零测试覆盖**。

### 端到端验证
三种操作全部跑通。核心行为确认：

| 场景 | comparable | deltas |
|---|---|---|
| 同一 config_hash | true | 逐项 delta |
| 改一个旋钮 | **false** | **null**（并列出 changed_fields） |

**不可比时拒绝给 delta** 是整个机制的意义——若悄悄给差值，
读者会拿两次不可比的运行做比较。

### 新增
`tests/test_compare_baseline.py`（7 例），含"异配置必须拒绝"。
198 passed / 1 skipped；claims 71/71。


## 0.12.1 — 2026-11-13

样本外复现上轮的 T+1 拆解结论。

### 新增
- `value_decomposition.py` 支持 `--bars-dir` / `--ref-dir`，可换夹具做复现

### 样本外结果（2026-09，11 天，零重叠）
| 项 | 样本内 | 样本外 |
|---|---|---|
| 总差值 | −0.3749% | −0.1960% |
| `t_plus_1` 贡献 | −0.3098% | −0.3000% |
| `t_plus_1` 占总差值 | 82.6% | **153%** |
| 其余七个合计 | −0.0155%（5 个为正） | **+0.0204%（全部为正）** |

**样本外更强**：只有 `t_plus_1` 是负贡献。两段独立行情给出同一机制。

### 一个必须标注的差异
- 「T+1 是唯一负向驱动」——两段样本**一致**，稳健；
- 「关掉 T+1 后显式语义显著更优」——样本内 p=0.036 显著，
  **样本外只是方向一致（inconclusive）**，强度不足。

不能把后半句当稳定结论引用。


## 0.12.0 — 2026-11-13

拆解价值结论：`negative` 的 82.6% 来自 `t_plus_1` 一个旋钮。**修正了此前的解读。**

### 发现
`value_assessment` 把「显式语义」与「字面直译」整体比较，但两者有 8 个旋钮不同。
逐旋钮拆解后：

| 旋钮 | Δ均值（从 naive 拨到参考值） |
|---|---|
| **t_plus_1** | **−0.3098%** |
| cooldown_bars | −0.0125% |
| bar_timestamp | −0.0000% |
| wait_bars | +0.0026% |
| breakout_field | +0.0208% |
| entry_price | +0.0236% |
| baseline_price | +0.0241% |
| persistence_bars | +0.0276% |

**`t_plus_1` 贡献了总差值的 82.6%**，其余七个合计仅 −0.0155%（五个还是正向）。

### 决定性检验
| 参考语义 | 均值净收益 | 与 naive 比 |
|---|---|---|
| 含 T+1 | −0.5599% | `negative` |
| **关 T+1** | **−0.1009%** | **`positive`（p=0.036）** |

去掉 T+1，显式语义反而显著优于字面直译。

### 机制
含 T+1 时当日平仓 **n=0**，全部 1,422 笔转为跨日持仓（承担隔夜跳空）。
关 T+1 时 3,032 笔全部当日平仓。这才是收益变差的直接原因。

### 修正的结论
此前表述「语义显式化劣化回放收益」**是错的**。准确说法是：
**T+1 约束把日内策略变成隔夜策略，收益显著下降；这与语义是否显式无关。**

新增 `scripts/value_decomposition.py` + 4 个测试。


## 0.11.2 — 2026-11-13

新增**报告内部自洽检查**，并修复由此发现的字段不一致。

### 发现
`by_axis` 的每个轴只存具体状态名（`jev_missing` 等），没有 `one_sided`
汇总字段。于是"各轴 one_sided 加起来是 0，total 却是 979,320"——
看起来像数据错乱，实际是命名不统一，读者无法从 by_axis 加总校验 total。

### 修复
- 每轴补 `one_sided` 汇总字段

### 新增
- `verify_claims` 增加 10 项内部自洽检查：
  summary↔aggregate、by_axis 加总、per_day 加总、total 恒等式
- `tests/test_validation_claims.py` +3 例（含篡改必被抓）

claims 33 → **71 项**。


## 0.11.1 — 2026-11-13

端到端验证 `oos_check.py`（此前只用缓存测过 judge 函数），修复凭证与退出码缺陷。

### 发现
**缺陷 29：凭证值带引号导致 URL 非法。**
`~/.pandadata/pandadata.env` 写的是 `export X="abc"`，解析保留了双引号，
`base_url` 变成 `"https://..."`，报 `unknown url type: "https`。
三个脚本各有一份解析逻辑，都有这个 bug。

**缺陷 30：`oos_check` 无凭证时抛堆栈且退出码为 0。**
脚本崩了却报成功。

### 修复
- 新增 `scripts/credentials.py`：去引号、别名回退、URL 合法性校验，
  三个脚本统一接入
- `oos_check` 捕获异常 → 结构化 JSON + `exit 2`
- `tests/test_credentials.py`（6 例）

### 端到端实测（3 天 × 100 只）
| 合计可比 | 1,597 | 一致率 0.9925 |
| 归因 | exit_eval 100% | 复现 |
| 价值 | inconclusive, p=0.083 | **不复现** |

3 天不足以复现价值结论（11 天 p=0.0488，14 天 p=7×10⁻⁶）——
显著性对样本量高度敏感。工具如实报 `NOT FULLY REPLICATED`。


## 0.11.0 — 2026-11-13

验证 CI 流水线本身。此前每轮都在说"CI 会跑这些步骤"，但从未按 CI 顺序真跑过。

### 发现 1：流水线从未成功解析
`validate.yml` 里 `- name: Unit tests (slow: verdict discrimination)` 的冒号
没加引号，YAML 把 `slow` 当成键——**整个文件无效**。这条流水线从来没跑起来过。

修复并新增 `tests/test_ci_config.py`（4 例）：YAML 合法性、必需步骤齐全、
build 必须排在 tests 之前、每个 run 非空。

### 发现 2：账本 185 MB / 96% 是无信息量记录
| jev_missing | 979,246 | 96.44% |
| match | 35,707 | 3.52% |
| divergent | 379 | 0.04% |

前两类不是差异（`jev_missing` = 日志没记这一根；`match` = 一致），
真正需要逐行追溯的只有 453 行。

新增 `ledger_mode`（默认 `diff`）：**185 MB → 78 KB，缩减 99.96%**。
需要全量时设 `ledger_mode: full`。

同时把分日聚合写进 `report.per_day`，`verify_claims` 不再读大文件。

### 按 CI 顺序在冷克隆上实跑
env_check / validate / build / verify_claims 全部 exit 0，claims 61/61。


## 0.10.0 — 2026-11-13

新增**外部日志适配层**。所有测试日志都出自本库 `log_synth`，格式必然兼容——
这不构成对"真实日志能否接入"的验证。

### 实测发现
| 外部写法 | 直接加载 | 后果 |
|---|---|---|
| `price`（应为 entry_price） | 成功但丢字段 | 入场价轴不可比，静默 |
| `side`（应为 signal） | 成功但丢字段 | 信号轴不可比，静默 |
| `hit: "false"` | 加载成功 | `bool("false") == True`，**命中判反** |

`validate.py` 报 `warn` 但 `ok` 仍为 true——可以带着缺陷跑出结论。

### 新增
- `scripts/adapt_logs.py`：显式字段映射
  - 通用同义词（timestamp→ts、code→symbol、matched→hit…）
  - 按 kind 细化映射
  - 布尔规范化（1/0、"true"/"false" → 真正的 bool）
  - 缺必需字段直接报错，不让它进入对齐
- `tests/test_adapt_logs.py`（15 例）

### 修复
28. **文件名转换把 `a.jsonl` 写成 `a.jsonll`**：输出目录为空，
    函数却返回 `ok: true`。"成功但什么都没做"比报错更危险。

### 时间格式兼容性（实测 5 种）
ISO 时间戳、`20261110 094100`、`0941`、日期与时间分字段、毫秒精度——全部正确解析。


## 0.9.0 — 2026-11-13

新增**旋钮功效审计**：验证每个语义旋钮是否真的影响重放。

### 为什么
"语义对齐"的前提是每个旋钮都真实生效。若某个旋钮接进配置却对输出
毫无影响，它就是个装饰性参数——对齐它毫无意义，而报告仍会显示
"该旋钮一致"。这类沉默失效比报错难发现得多。

### 新增
- `scripts/knob_efficacy.py`：逐旋钮换备选值，比较整份交易指纹
  （信号索引/入场时点与价/退出时点与价/原因/状态）
- `tests/test_knob_efficacy.py`（3 例）
- CI 增加 `knob_efficacy.py --days 2`

### 实测（3 天 / 900 序列）
**10/10 旋钮全部有效**：

| 旋钮 | 信号数 | 指纹 |
|---|---|---|
| bar_timestamp | 278→278 | 变化 |
| baseline_price | 278→272 | 变化 |
| breakout_field | 278→332 | 变化 |
| breakout_includes_current | 278→**0** | 变化 |
| persistence_bars | 278→433 | 变化 |
| wait_bars | 278→278 | 变化 |
| entry_price | 278→278 | 变化 |
| exit_eval | 278→278 | 变化 |
| t_plus_1 | 278→552 | 变化 |
| cooldown_bars | 278→279 | 变化 |

**关键方法点**：四个旋钮的信号数没变但指纹变了——它们改的是时点与价格，
不改变触发次数。只看信号数会把它们误判成"无效果"。

### 顺带印证
`breakout_includes_current=True` 时信号归零（`close > max(含自身)` 恒假）。
这正是 `naive_literal` 设为 `False` 的原因——那不是字面直译，而是配置错误。


## 0.8.2 — 2026-11-13

补上分钟缺口检测。重放器按「根数」计窗口与持有期，缺口会让语义静默失真。

### 发现
实测确认：构造一段缺 10 根的序列，重放器正常产出信号，
`bars_to_entry` 仍是 1——**缺口凭空消失，不报任何错**。
真实分钟线（停牌、低流动性小票）必然有缺口，而当前夹具恰好是完整的，
所以这个路径从未被触发过。

### 新增
- `data_loader.find_gaps()`：检测分钟缺口，**排除午休**（11:30→13:01）
- `validate.py` 报 `minute_gaps`：缺 < 500 根 `warn`，≥ 500 根 `error`
- `tests/test_data_loader.py` +5 例：缺口检测、午休排除、真实夹具零缺口

### 实测
真实夹具 4,200 序列：**除午休外零缺口**。
实现时踩到的坑：不排除午休的话，每条序列都会报一个假缺口（跨 91 分钟）。

### 对真实日志的意义
JEV 日志覆盖的标的若含停牌/小票，缺口几乎必然出现。
届时先看 `validate.py` 的 `minute_gaps`，再决定剔除标的
还是改用「时间跨度」而非「根数」做窗口计算。


## 0.8.1 — 2026-11-13

验证**统计函数本身**。此前所有 p 值和置信区间都出自手写实现，
但从没验证过这些实现对不对。

### 发现
`scripts/metrics.py` 的 `sign_test_p` / `wilson_interval` / `welch_test` /
`paired_delta_ci` 全部是手写。若双尾算错、公式写反、分母用错，
报告里所有"显著"都会失去意义，而此前的测试只覆盖了输出形状与判定分支。

### 新增
- `tests/test_metrics_correctness.py`（15 例，0.07 秒）
- 三种独立手段：
  1. **精确值对比**——符号检验与二项分布精确双尾值逐点比对，误差 0
  2. **蒙特卡洛**——Wilson 覆盖率 0.9473（名义 95%）；Welch Type-I 0.0510（名义 0.05）
  3. **手工公式**——t / se / 区间与手写数学式对比

### 灵敏性验证
把 `sign_test_p` 的双尾 `tail * 2` 改成 `tail`，5 个参数化用例立刻全红。
说明这组测试确实能抓到实现错误。

### 顺带修复
27. **per_day 校验依赖执行顺序**：它读 `output/ledger.jsonl`，但 CI 里
    `pytest` 排在 `build.py` 之前，导致缺文件报错。
    → CI 顺序调整为 build 先于 tests（并注释说明原因）
    → 缺 ledger 时 `verify_claims` 显式报错并返回非零，而不是静默跳过


## 0.8.0 — 2026-11-13

新增**逐笔核对**。此前所有验证都在统计层面（一致率、显著性、覆盖率），
从未独立重算过单笔交易的入场价、退出价与收益。

### 新增
- `scripts/trade_audit.py`：从原始 K 线反查入场/退出那两根，
  独立重算 gross/net，与 replayer 记录比对。
  **不复用 replayer 内部函数**，避免用同一个错误验证自己。
- 核对六点：入场价、退出价（按 exit_reason 分派）、gross、net、股数、持仓根数
- `tests/test_trade_audit.py`（4 例，含"故意改价必被抓"）
- CI 增加 `trade_audit.py --sample 300`

### 实测
| 收官周期 | 1,422 |
| 核对笔数 | **1,422（全量）** |
| 其中跨日 | 1,422 |
| 失败 | **0** |

### 人工复核纪要
首笔跨日交易 `000001.SZ@20261027 → @20261028`：
入场 10:29 @11.48（原始 K 线 open 一致）、次日 09:31 @11.43 max_hold 退出、
gross −0.43554% / net −0.57554%，全部与记录吻合。

复核时曾误用前一日的 K 线序列比对，得出"入场价差 2%"的假警报——
周期带 `entry_series` 字段，必须按它反查。这也说明核对方向本身要防错。


## 0.7.2 — 2026-11-13

修正 §3.5 分日稳定性表的陈旧数字，并把日度数字纳入自动校验。

### 修复
26. **分日稳定性表停留在旧样本**：v0.6.1 换样本（7,000 → 4,200 序列）后，
    这张 14 行表仍是旧值。claims 与 stale-token 扫描都没覆盖表格内的日度数字。
    → claims 新增 `per_day` 段（14 天 × 可比/冲突，共 28 项）
    → `verify_claims` 直接读 `output/ledger.jsonl` 按日聚合核对
    → 已验证：篡改任一天冲突数会被抓到

### 按真实数据重算
| 项 | 旧（7,000 序列） | 新（4,200 序列） |
|---|---|---|
| 日度一致率范围 | 0.9712–1.0000 | **0.9617–1.0000** |
| 最低日 | 20261106 (0.9712) | 20261029 (0.9617) |
| 最高冲突日 | 20261103 (73) | 20261103 (90) |

结论不变：没有单日主导总体。


## 0.7.1 — 2026-11-13

揭示并记录一个此前被含糊带过的方法论问题：**"归因 100% 锁定 exit_eval"
很大程度是同义反复**。

### 发现
合成日志用的 `jev_assumed` 档位与参考语义**只差 1 个旋钮**（`exit_eval`）：
`bar_close` vs `bar_high_low`。其余 17 个旋钮完全一致。

因此"归因锁定 exit_eval、解释 100%"能证明的只是：
链路接通、差异能被正确定位、没有凭空产生别的差异。
**不能证明**多旋钮场景下的定位能力。

### 多旋钮失效实测
| 日志侧真实差异 | 差异数 | 归因判定 | 首位 | 解释率 |
|---|---|---|---|---|
| 仅 exit_eval | 379 | single_knob | exit_eval | 100% ✓ |
| 仅 wait_bars | 4,522 | single_knob | wait_bars | 100% ✓ |
| exit_eval + wait_bars | 4,649 | multi_knob | wait_bars | 92.0% |

**两个旋钮同时不同时，归因把 `exit_eval` 完全漏掉**——只报 wait_bars。
单旋钮消融只能回答"改对某一个能少多少差异"，两个都错时改对一个仍剩大量差异。

结论：`verdict=multi_knob` 时必须人工逐项核对，不能只看 `top_knob`。

### 新增
- `tests/test_attribution.py` +2 例，固定单旋钮可定位 / 多旋钮必标不适用
- 验证文档 §4.0 记录该风险与失效实测

### 对结论的影响
不影响已报告的数字，但**降低了"归因 100%"的证据权重**。
真实 JEV 日志与我们的语义差几个旋钮，目前未知——这正是必须等真实日志的原因。


## 0.7.0 — 2026-11-13

新增**样本外复现**。此前所有结论只来自 2026-10-26 至 11-12 这一段行情，
无法排除"结论只是那段行情的产物"。

### 新增
- `scripts/oos_check.py`：用完全不相交的日期重跑，逐项判断结构结论是否复现
  - 默认取 2026-09 的 11 个交易日（与主样本零重叠）
  - 自动拉数、建夹具、评测都在临时目录，不污染 `fixtures/`
  - 区分"结构结论复现"与"显著性强度复现"——两者是不同的事

### 实测（样本外 2026-09）
| 指标 | 样本内 | 样本外 | 复现 |
|---|---|---|---|
| condition | 1.0000 | 1.0000 | ✓ |
| signal/wait/entry | 1.0000 | 1.0000 | ✓ |
| exit | 0.8667 | 0.8650 | ✓ |
| 合计 | 0.9895 | 0.9904 | ✓ |
| 归因首位 | exit_eval 100% | exit_eval 100% | ✓ |
| 价值 verdict | negative | negative | ✓ |

**显著性是唯一未复现的项**：p 从 7×10⁻⁶ 减弱到 **0.0488**，
距 0.05 仅 0.0012——方向一致但仍显著，属**边缘证据**。
工具会把这一项单列为未复现，而不是笼统宣称全部复现。

### 顺带修复
25. `build_fixtures.build()` 的 fingerprint 依赖当日日志文件，而日志由
    `generate_logs()` 稍后统一生成——单独调用 `build()` 会 FileNotFoundError。
    → 只对已存在的文件计算指纹


## 0.6.3 — 2026-11-13

修正验证文档中 5 处**上一版样本**的陈旧数字，并加上自动扫描防止再犯。

### 修复
24. **文档陈旧数字未被检出**：v0.6.1 换了样本（7,000 → 4,200 序列）后，
    文档里仍有 5 处旧值没被任何检查发现——`claims` 只守护 33 个关键指标，
    表格里其余数字无人看管。
    → `verify_claims.py` 增加 `scan_stale_tokens`，扫已知历史 token
      （`1,680,000` / `46,642` / `58,110` 等）
    → 标注了版本号的历史叙述行豁免，避免误伤
    → 新增 3 个测试，含"故意插入必须被抓到"

### 按真实数据重跑后修正的表格
- 容差敏感性：0.9913/0.8751/503 → **0.9895/0.8667/379**（tol 0/1/2 三档完全一致）
- 区分度对照：全部 8 项按 5 天 × 300 标的重跑
- 冷克隆一致率、条件轴覆盖率、结论段同步更新


## 0.6.2 — 2026-11-13

修复对照实验的**空转**问题：改了旋钮却零差异的对照，什么也证明不了。

### 修复
23. **空转对照未被识别**：比对样本缩到 2 天 × 60 标的后，`exit_eval` 与
    `signal_gain_pct` 产生 0 条差异，却被判为「判定器正确判 consistent」。
    实际是样本太小，这两个旋钮改不动任何交易——对照根本没生效。
    → `controls_check.py` 增加 `vacuous` 判定：零差异的阴性对照标为未生效
      并计入失败
    → `--quick` 子集提高到 **5 天 × 300 标的**，每个旋钮产生 93–3,723 条差异
    → 单元测试同步提高子集，并断言每个阴性对照 `divergent > 0`

### 实测
5 天 × 300 标的下对照组 **9/9 通过**：
`exit_eval` 93、`signal_gain_pct` 128、`entry_price` 840、
`persistence_bars` 1,160、`baseline_price` 1,217、`wait_bars` 1,240、
`breakout_field` 2,132、`bar_timestamp` 3,723（条差异）。


## 0.6.1 — 2026-11-13

修复样本设计缺陷：标的池逐日变化，导致跨日持仓传递形同虚设。

### 修复
21. **标的池逐日变化**：每天按当日 `get_trade_list` 各自抽样。实测相邻日
    重合度最低 **18.6%**，14 天交集仅 **66 只**（并集 1,366）。后果是昨天买入
    的股票今天可能根本不在样本里——**跨日持仓与 T+1 相关结论失去基础**。
    → 改为取所有交易日 `trade_list` 的**交集**，全期固定标的池
    → 新增 `tests/test_fixture_universe.py` 守住（2 例）
22. **覆盖率闸门误杀全样本证据**：规则是"覆盖率 <10% 一律 inconclusive"，
    但全样本 Welch 检验不依赖配对、不受覆盖率影响。本次全样本 p=7×10⁻⁶ 显著，
    却被一并否掉。→ 覆盖率只约束配对检验；全样本显著时采用全样本结论。

### 样本重生成
- 标的：每日 500（逐日变化）→ **每日期 300（全期固定）**
- 序列 7,000 → **4,200**，分钟线 1,680,000 → **1,008,000**

### 实测（14 日 / 4,200 序列）
| 轴 | 可比 | 一致率 |
|---|---|---|
| condition | 28,754 | 1.00 |
| signal | 1,496 | 1.00 |
| wait | 1,496 | 1.00 |
| entry | 1,496 | 1.00 |
| exit | 2,844 | 0.8667 |
| 合计 | 36,086 | 0.9895 |

归因不变：`exit_eval` 解释 379 条退出差异的 100%。

**价值评估 = `negative`**（依据换成全样本）：
配对覆盖率仅 4.37% 不可外推；改用全样本 Welch 检验 27,987 vs 1,422，
均值差 −0.3749%，p=7×10⁻⁶，显著更差。

与 v0.4.1 的关系：那一版撤回 `negative` 是对的（当时没有全样本证据）；
现在补上了，且方向一致，结论才重新成立。**结论没变，证据基础换了。**

数据质量：ST 4.67%、触涨停 1.76%、触跌停 0.64%，上界 4.67%（`moderate`）。


## 0.6.0 — 2026-11-13

量化「未建模状态」在样本中的实际占比。此前只在文档里写"不含 ST/停牌/涨跌停"，
从没测过这个缺口有多大——这是结论适用范围里最大的未知。

### 新增
- `scripts/data_quality_audit.py`：数据质量审计
  - 有凭证时取真实 ST / 停牌名单（`get_st_list` / `get_suspended_list`）
  - 无凭证时按板块口径算涨跌停可达性（主板 10% / 创业板科创 20% / 北交 30%）
  - **离线时 ST/停牌标为「未核验（null）」，绝不报成 0**
- 审计结果写入 `fixtures/manifest.json`，并在报告
  `applicability.unmodeled_market_states` 回显
- `tests/test_data_quality_audit.py`（6 例）
- claims 新增 `data_quality` 段（6 项），文档数字同样被测试守着

### 实测（14 日 / 7,000 序列）
| 检查项 | 占比 |
|---|---|
| ST 标的 | **4.20%**（294 序列 / 46 只） |
| 停牌日 | 0.00% |
| 触及涨停 | 2.24% |
| 触及跌停 | 0.64% |

未建模占比上界 **4.20%**，判定 `moderate`。

进一步实测影响：ST 标的产生了 **47 个信号、41 笔收官交易**，
占全部交易的 **2.04%**——这些在真实市场受 5% 涨跌幅约束，回放未体现。


## 0.5.1 — 2026-11-13

冷克隆验收：从 GitHub 全新克隆到 /tmp，逐项复跑，结果与本机完全一致。
过程中发现一处静默降级缺陷。

### 验收方式
```bash
git clone git@github.com:quantskills/skill-jev-history-replay.git /tmp/jev-cleanroom
cd /tmp/jev-cleanroom
python3 scripts/build.py && python3 scripts/verify_claims.py && python3 -m pytest tests/ -q
```
结果：0.9913 总一致率，各轴数字与本机相同；27/27 claims；113 passed。
另用系统 Python 3.9（无 pyyaml / pytest）跑 build.py，同样跑通且数字相同。

### 修复
20. **代码默认值与 YAML 不一致**：`config.py` 的 `logs_dir` 默认 `None`，
    而 `replay_config.yaml` 是 `fixtures/logs`。缺 pyyaml 时走默认值，
    悄悄进入合成模式——用的是 `log_synth` 现生成的日志，而非 `fixtures/logs`
    里的文件。本次因夹具本身就是合成的而没暴露，**真实日志接入后会静默读不到**。
    → 逐项对齐默认值与 YAML；新增 `test_code_defaults_match_yaml_config` 守住。
    → 缺 pyyaml 时记录降级原因，并在报告 `provenance.config_warnings` 回显；
      新增 `test_missing_pyyaml_is_reported` 守住。


## 0.5.0 — 2026-11-13

新增**判定器区分度对照**。此前所有测试都在合成日志下跑，而合成日志必然
`inconclusive`——一个永远返回 `inconclusive` 的判定器也能全部通过。
真实日志到位后能不能正确区分三种结论，从未被验证过。

### 新增
- `scripts/controls_check.py`：受控阳性/阴性对照
  - 用参考语义生成日志后抹掉 `_synthetic` 标记，使其被当作真实日志
  - 阳性：完全一致 → 必须 `consistent` 且 0 冲突
  - 阴性：单旋钮差异 × 8 → 判定必须随之变化
- `tests/test_validation_claims.py` +1 例：微缩版对照进单元测试
- CI 增加 `controls_check.py --quick`

### 修复
18. **`consistent` 只看一致率**：`exit_eval` 差一个旋钮产生 503 条真实冲突，
    一致率 0.9913 被误判为 `consistent`。样本越大，真差异越容易被稀释。
    → 加绝对冲突门槛。
19. **绝对门槛设成"≤5 条"**：60 标的子集下 3 条冲突又落回 `consistent`。
    → 改为**必须为 0**。"一致"不接受默认的冲突容忍额度。

### 实测对照（9/9 通过）
| 日志侧差异 | 一致率 | 冲突 | 判定 |
|---|---|---|---|
| 完全一致 | 1.0000 | 0 | `consistent` ✓ |
| `exit_eval` | 0.9913 | 503 | `minor_divergence` |
| `signal_gain_pct` | 0.9436 | 939 | `minor_divergence` |
| `t_plus_1` | 0.9541 | 2,666 | `minor_divergence` |
| `entry_price` | 0.9174 | 4,967 | `minor_divergence` |
| `persistence_bars` | 0.8848 | 6,833 | `minor_divergence` |
| `baseline_price` | 0.8910 | 6,581 | `minor_divergence` |
| `breakout_field` | 0.8119 | 14,068 | `minor_divergence` |
| `bar_timestamp` | 0.5935 | 23,416 | `inconsistent` |

两个缺陷都是对照实验抓出来的，不是凭空想到的。


## 0.4.1 — 2026-11-13

**撤回 v0.4.0 的 `negative` 结论。** 它建立在 3.74% 的配对子样本上，不可外推。

### 修复
17. **配对覆盖率过低仍给 verdict**：配对检验只比"两套语义都选出同一笔交易"的周期。
    本案例基线 45,507 周期、当前 2,014 周期，配对仅 1,701（覆盖率 **3.74%**）。
    3.74% 的子样本被当成全样本证据，报出假的 `negative`。
    → 新增硬门槛：覆盖率 < 10% 一律 `inconclusive`；
    `decision_changes.coverage_sufficient=false` 显式标注。

### 新增
- `metrics.welch_test()` / `metrics.all_closed_returns()`：不依赖配对的全样本检验
- 报告 `effect_size.full_sample_welch`：全样本 Welch 检验结果
- `tests/test_report.py` +5 例：覆盖率门槛、Welch 检验

### 更正后的结论
| 口径 | 结果 |
|---|---|
| 配对子样本（覆盖率 3.74%） | 738 胜 / 949 负，p≈0 —— **不可外推** |
| 全样本 Welch（45,507 vs 2,014） | 均值差 −0.087%，**p=0.35，不显著** |

**结论**：语义选择巨大改变交易行为（信号 47,669→2,480），
但收益差异**不可证** —— 既不能宣称改善，也不能宣称劣化。


## 0.4.0 — 2026-11-13

样本扩到 14 个交易日 / 500 标的，价值评估从 `inconclusive` 反转为 `negative`。

### 修复
16. **`build_fixtures` 逐日生成日志**：生成当天看不到次日，所有周期都停在 open，
    跨日退出记录永远为空，退出轴退化为 0 可比。
    → 新增 `generate_logs()`，**全部交易日一起跑一次重放再按日切分**。
    （v0.3.1 的 7 日 fixture 侥幸有退出记录，是因为当时手工全量重生成过；
    走 `build_fixtures` 的正常路径其实是坏的。）

### 样本扩大
- 交易日 7 → **14**（2026-10-26 至 11-12）
- 标的 200 → **500**/日
- 序列 1,400 → **7,000**，分钟线 336,000 → **1,680,000**
- 日志 11,188 → **55,630** 条

### 实测（14 日 / 7,000 序列）
| 轴 | 可比 | 一致率 |
|---|---|---|
| condition | 46,642 | 1.00 |
| signal | 2,480 | 1.00 |
| wait | 2,480 | 1.00 |
| entry | 2,480 | 1.00 |
| exit | 4,028 | 0.8751 |
| 合计 | 58,110 | 0.9913 |

归因不变：`exit_eval` 解释 503 条退出差异的 100%，`verdict=single_knob`。

**价值评估从 `inconclusive` 变为 `negative`**：
配对周期 314 → **1,701**，胜/负 151/160（p=0.65，不显著）
→ **738/949（p≈0，显著更差）**。

这是本轮最重要的结论：小样本下的"看起来没差别"不能当作"确实没差别"。
显式语义把交易砍掉 95%，但在 14 天样本上**显著劣化**回放收益。

### 顺带核实
12 条 ≥5 分钟的大偏差，JEV 侧退出时刻全部是 09:31——
`bar_high_low` 在次日首根触价止损，`bar_close` 要等收盘确认。
逐条证据与归因结论一致。


## 0.3.1 — 2026-11-13

补充两项此前缺失的验证：分日稳定性、归因的适用边界。

### 新增
- **分日稳定性**（验证文档 §3.4）：7 个交易日逐日一致率 0.9546–1.0000，
  确认总体结论不由单日主导
- **参数敏感性**（§3.5）：时间容差 0/1/2/5 分钟下结果完全不变，
  说明一致率不是靠容差"调"出来的
- **归因适用边界**（§4.1 + 代码）：`joint_diagnosis` 字段。
  用 `naive_literal` 日志做反向检验，证明多旋钮同时偏移时单旋钮消融失效
  （逐个调到正确值，差异反而增加）。此时输出 `multiple_knobs_shifted`，
  不给半吊子的 `top_knob` 结论
- `tests/test_attribution.py` +2 例固定该边界

### 为什么
前几轮只报合计数字，无法回答"是否某一天撑起了结论"和"这个归因方法在什么情况下失效"。
方法的边界必须与结论一起交付。


## 0.3.0 — 2026-11-13

新增**文档与实现的自动对账**，把验证文档从"手抄的数字"变成"被测试守着的断言"。

### 新增
- `references/validation_claims.json`：验证文档声明的全部关键指标
- `scripts/verify_claims.py`：逐项与 `output/report.json` 比对，不符即非零退出
- `tests/test_validation_claims.py`（5 例）：
  - 真实跑端到端后与 claims 对账（不读过期 output）
  - `test_claim_checker_catches_drift`：篡改一项必须失败，证明校验器不是摆设
  - 证据文档中引用的一致率必须与 claims 一致
  - claims 内部加总自洽（comparable = match + divergent 等）
- CI 在 `build.py` 之后追加 `verify_claims.py`，文档漂移会直接让流水线红

### 为什么
前几轮出现过两次"文档说 0.9176、实现改后变成 0.8590"的情况。
人工复核靠不住，把对账变成测试才能长期成立。

### 实测
104 个测试全通过；25 项 claims 对账全通过。


## 0.2.2 — 2026-11-13

消除全部单边缺失，把被藏起来的真实差异还原为差异。

### 修复
13. 退出计划混进入场候选池 → 入场轴只取 `plan == "enter"`（entry 轴 390 条假 `jev_only` 归零）
14. 配对容差与判定容差混用 → 拆成两个参数。「差 2 分钟」原先先配对失败、
    再被记成单边缺失，真实差异被藏起来（exit 轴 32 条假 `replay_only` 归零）
15. 容差外无回退配对 → 最近邻回退并标记 `low_confidence_pairing`
16. 校验器对退出计划误报缺 `wait_bars` → 退出类计划只校验退出字段

### 实测（7 日 / 1,400 序列 / 336,000 根）
| 轴 | 可比 | 一致率 |
|---|---|---|
| condition | 9,406 | 1.00 |
| signal | 501 | 1.00 |
| wait | 501 | 1.00 |
| entry | 501 | 1.00 |
| exit | 780 | 0.8590 |
| 合计 | 11,689 | 0.9906 |

**一致率从 0.9949 降到 0.9906 不是变差**：v0.2.1 的 exit 0.9176 是虚高的，
51 条真实时点差因配对失败被藏成单边缺失；现在它们被正确地算作差异。
单边项已全部消除（entry `jev_only` 390→0，exit `replay_only` 32→0）。

归因不变：`exit_eval` 解释 110 条退出差异的 100%，`verdict=single_knob`。


## 0.2.1 — 2026-11-13

退出轴从「0 可比」修到「716 可比 / 0.9176」，并把 59 条差异完整归因到单一旋钮。

### 修复
10. 合成日志从不写跨日退出记录 → 入场日写 `plan(enter)` + `cross_day_pending`，
    退出日写 `plan(exit)` + 卖出 `fill`
11. `exit_series` 在周期尚未退出时被写成当天 → 仅当 `exit_time` 存在时定格
12. 消融用 `symbols` 视图、主流程用 `by_series` → 统一，否则真实成因归不出来
13. 归因一律拒绝"可比项减少"的旋钮 → 改为区分「配对消失」与「冲突消失」：
    `raw_explained > lost_comparable` 且保有率 ≥ `min_comparable_retention`

### 实测（7 日 / 1,400 序列 / 336,000 根）
| 轴 | 可比 | 一致率 |
|---|---|---|
| condition | 9,406 | 1.00 |
| signal | 501 | 1.00 |
| wait | 501 | 1.00 |
| entry | 501 | 1.00 |
| exit | 716 | 0.9176 |
| 合计 | 11,625 | 0.9949 |

归因：`exit_eval` 解释 100% 的退出差异，`verdict=single_knob`。
价值评估：信号 9,979 → 501，配对 314 周期，胜 151 负 160，p=0.65 → `inconclusive`
（可靠负结果：语义巨大改变交易行为，收益改善未可证）。


## 0.2.0 — 2026-11-13

多日真实数据验收。本轮在 3 个连续交易日、300 标的（900 序列）上跑通，
并修复了 9 处只在多日/T+1 场景下才暴露的缺陷。

### 新增
- **多日支持**：`fixtures/bars` 支持多个交易日；序列键为 `symbol@date`，
  单日时沿用裸代码
- **跨日持仓传递**：`_carry_forward` 把当日未平仓带到下一交易日，T+1 真实结算
- **逐序列对齐**：`replay_all` 同时返回 `symbols`（标的级合并）与
  `by_series`（逐日视图）；跨日周期的入场记入场日、退出记退出日
- `tests/test_cross_day.py`：6 个用例固定跨日行为
- `references/validation_evidence.md`：真实数据验收记录

### 修复
1. 止损/止盈分支绕过 T+1 检查 → 四条退出路径统一走 `_exit_or_defer`
2. 单日 + T+1 下无任何周期能收官 → 跨日传递（此前能收官全靠缺陷 1）
3. 跨日持仓每天新建周期对象 → 复用同一对象，次日原地补退出信息
4. 跨日周期被重复计数 → 按对象身份去重
5. 多日构建时日志混入其他交易日 → 按日期切分生成
6. 前收价按裸代码取 → 改按 `symbol@date`
7. 合并视图导致信号日期错标 → `log_synth` 遍历 `by_series`
8. 归因把"配对打散"当成"解释差异" → `alignment_preserved` 守卫
9. 合成日志 provenance 缺档位信息 → 回显 `logged_semantics.knobs`

### 实测（3 日 / 900 序列）
| 轴 | 可比 | 一致率 |
|---|---|---|
| condition | 5,985 | 1.00 |
| signal | 117 | 1.00 |
| wait | 117 | 1.00 |
| entry | 117 | 1.00 |
| exit | 0 | null（跨日粒度差异，见验证记录 §3.2） |

价值评估：字面直译基线 vs 显式语义，配对 148 周期，胜 93 负 53，p=0.0012 → `positive`。
对齐结论仍为 `inconclusive`（日志为合成）。


## 0.1.0 — 2026-11-12

首个版本。目标：把「JEV 盯盘条件」与「历史回放器」之间的语义差异变成可观测、可归因、可复现的账本。

### 新增

**语义层**
- `scripts/semantics.py`：11 个判定旋钮 + 10 个风控参数的命名档位注册表，
  含 `semantics_hash`（SHA-256 前 16 位）。任何旋钮变化都会改变哈希，
  从而禁止与旧结果直接比较。
- `references/semantics_matrix.md`：旋钮全表、`wait_bars` 精确定义、档位说明。

**重放层**
- `scripts/replayer.py`：确定性重放器。无随机数、无时钟依赖、无外部服务；
  条件判断 → 信号 → 等待 → 入场 → 退出全链路。
  记录 `wait_bars`（配置值）与 `bars_to_entry`（实际根数差）两个字段，避免歧义。

**对齐层**
- `scripts/aligner.py`：五轴差异账本（condition / signal / wait / entry / exit）。
  - 条件轴两轮对齐：先精确时刻，再容差内"未被精确匹配"的记录，杜绝一次判断记两行。
  - 单边缺失（`jev_missing` / `replay_only` / `jev_only`）与真实冲突（`divergent`）分开统计。
  - `one_sided` 不进一致率分母——稀疏记录是记录习惯，不是语义冲突。

**归因层**
- `scripts/attribution.py`：单旋钮消融。解释率 = (基线差异 − 换旋钮后差异) / 基线差异。
  - 守卫：换旋钮导致可比项减少时 `explained` 强制为 0，
    防止"把配对打散"被误判成"解释掉差异"。
  - 替代值选取规则固定，保证可复现。

**价值评估**
- `scripts/report.py`：以 `naive_literal`（不做领域推断的字面直译）为冻结基线，
  报告决策改变、配对收益差、Wilson 区间与符号检验。
  - 方向由符号检验决定（多数周期是否改善），均值差只作幅度参考。
  - 样本不足或方向不显著 → `inconclusive`，不因均值方向单独下结论。

**日志**
- `scripts/log_synth.py`：无真实日志时按 `jev_assumed` 档位合成四类记录。
  每条记录带 `_synthetic: true`，报告据此判定 `log_source`，改名无效。
- `references/log_contract.md`：字段契约与最小示例。

**数据**
- `scripts/fetch_data.py` / `scripts/build_fixtures.py`：从 `panda_data` 拉取真实分钟线。
- `fixtures/`：300 标的 × 240 根（2026-11-12）真实分钟线、前收价、合成日志、指纹清单。

**工具**
- `scripts/validate.py`：契约校验，区分「字段缺失」（接入问题）与「语义不一致」（研究问题）。
- `scripts/env_check.py`：环境自检，缺 `panda_data` 报 warn 不报 blocked。
- `scripts/compare_baseline.py`：冻结基线 freeze / compare / list，`config_hash` 不一致时拒给 delta。

### 实测基线（2026-11-12，300 标的，单日）

| 指标 | 值 |
|---|---|
| 条件轴一致率 | 1.00（1,576 项） |
| 信号轴一致率 | 1.00（168 项） |
| 等待轴一致率 | 1.00（168 项） |
| 入场轴一致率 | 1.00（168 项） |
| 退出轴一致率 | 0.80（282 项） |
| 总体可比一致率 | 0.9767 |
| 归因结论 | `single_knob`，`exit_eval` 解释 100% 的差异 |
| 对齐结论 | `inconclusive`（日志为合成，链路已验证） |

价值评估：显式语义 vs 字面直译，信号数 168 vs 870，配对周期 89，
胜 38 / 负 46 / 平 5，符号检验 p=0.445 → `inconclusive`
（换语义显著改变交易，收益改善未可证）。

### 已知限制

- 单日、A 股分钟级；不含跨日持仓、除权除息、停牌与涨跌停建模
- 不建模撮合排队与部分成交
- 合成日志的结论只能是 `inconclusive`
- 日志缺可选字段时对应轴退化为不可比，不编造一致

### 验证

```bash
python3 scripts/env_check.py     # ok=true
python3 scripts/validate.py      # ok=true
python3 scripts/build.py         # 生成 report.json + ledger.jsonl
python3 -m pytest tests/ -v      # 86 passed
```