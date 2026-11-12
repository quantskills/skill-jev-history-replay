# 实测验证记录 / Validation Evidence

本文件记录在真实环境下跑出的结果，供审核方核对。
除「夹具再生」外，下列命令**均可由 clone 后直接复现，无需任何凭证**。

---

## 0. 文档与实现的绑定

验证文档最怕「写了数字、代码改了、没人复核」。本 skill 把文档里声明的
关键指标固化成 `references/validation_claims.json`，并由两处强制核对：

```bash
python3 scripts/verify_claims.py     # CI 中在 build.py 之后运行
python3 -m pytest tests/test_validation_claims.py -v
```

任一项与 `output/report.json` 不符即失败，并打印 `actual` vs `claimed`。
测试里还有一条 `test_claim_checker_catches_drift`，故意篡改一项来证明
这个校验器不是摆设。

**本文档的数字不是手抄的，是被测试守着的。** v0.4.0 把样本从 7 日扩到 14 日时，
正是这条测试先红，才逼着文档同步更新。

---

## 1. 单元测试

```bash
python3 -m pytest tests/ -q
```

| 项 | 结果 |
|---|---|
| 用例总数 | 121 |
| 通过 | 121 |
| 失败 | 0 |
| 环境 | Python 3.12.12 / 3.11.16 |
| 全量耗时 | 约 55 秒（含一次真实端到端跑） |

| 文件 | 用例数 | 覆盖 |
|---|---|---|
| `test_semantics.py` | 15 | 旋钮取值校验、哈希敏感性、**默认值与 YAML 一致**、降级可见 |
| `test_data_loader.py` | 17 | 格式容错、gzip、字段校验、重复检测、异常输入 |
| `test_replayer.py` | 20 | 条件判断、连续性、等待/入场、四条退出路径、T+1、时间边界 |
| `test_cross_day.py` | 6 | 跨日持仓传递、未平仓如实上报、单日行为不变 |
| `test_aligner.py` | 15 | 五轴对齐、配对唯一性、单边缺失、差异分类、容差分离 |
| `test_attribution.py` | 9 | 单旋钮解释率、视图一致性、真实差异可归因、多旋钮边界 |
| `test_report.py` | 24 | verdict 判定、覆盖率门槛、零冲突门槛、Welch 检验 |
| `test_end_to_end.py` | 9 | 输入校验、来源判定、产物落盘、确定性 |
| `test_validation_claims.py` | 6 | **文档数字与实现对账**、防漂移、**判定器区分度对照** |
| `test_data_quality_audit.py` | 6 | 板块分类、涨跌停口径、离线不把"未核验"当 0、报告回显 |

---

## 1.1 冷克隆验收（不依赖任何本地残留）

```bash
git clone git@github.com:quantskills/skill-jev-history-replay.git /tmp/jev-cleanroom
cd /tmp/jev-cleanroom
python3 scripts/env_check.py      # ok=true, blocked=0
python3 scripts/validate.py       # ok=true
python3 scripts/build.py          # 54 秒
python3 scripts/verify_claims.py  # 27/27
python3 -m pytest tests/ -q       # 113 passed
```

在 /tmp 的全新克隆上逐项复跑，结果与本机**完全一致**
（总一致率 0.9913，各轴数字相同）。clone 后 `output/` 不存在，
`build.py` 会自动创建——不依赖任何预生成产物。

### 纯标准库可跑

系统自带 Python 3.9（无 pyyaml、无 pytest）下 `python3 scripts/build.py`
同样跑通且**数字完全相同**。对齐与回放确实为零三方依赖。

### 由此发现并修复的缺陷

**缺陷 20：默认值与 YAML 不一致导致静默降级。**
`config.py` 的 `logs_dir` 默认值是 `None`，而 `replay_config.yaml` 写的是
`fixtures/logs`。缺 pyyaml 时走默认值 → 悄悄进入合成模式，
用的是 `log_synth` 现生成的日志，而不是 `fixtures/logs` 里的文件。
本次因夹具本身就是合成的而没暴露，但真实日志接入后会**静默读不到**。

修复：
- 默认值与 YAML 逐项对齐（新增测试 `test_code_defaults_match_yaml_config` 守住）
- 缺 pyyaml 时记录降级原因，并在报告 `provenance.config_warnings` 回显
  （测试 `test_missing_pyyaml_is_reported` 守住）

---

## 2. 夹具（真实数据）

```bash
python3 scripts/build_fixtures.py \
  --date 20261026,20261027,20261028,20261029,20261030,20261102,20261103,20261104,20261105,20261106,20261109,20261110,20261111,20261112 \
  --universe 500
```

| 项 | 值 |
|---|---|
| 数据源 | `panda-data==1.0.6`，`get_stock_min` / `get_stock_daily` |
| 交易日 | **14 个**（2026-10-26 至 2026-11-12，跨两周） |
| 标的数 | **500 / 日**（按代码排序后等距抽样） |
| 序列数 | **7,000**（`symbol@date`） |
| 分钟线 | **1,680,000 根** |
| 日志记录 | 55,630 条（`condition` 46,642 + `plan` 4,494 + `signal` 2,480 + `fill` 2,014） |

**抽样方法**：`get_trade_list(exchange='SH')` 取全市场，按代码排序后等距抽样。
不按当日涨跌筛选——那会让结论只对"涨了的股票"成立。

### 2.1 扩大样本的后果

7 日 → 14 日、200 → 500 标的，配对周期从 314 增到 1,701。
符号检验从"不显著"（p=0.65）变为"显著偏负"（p≈0）。

但这**不构成结论**：配对覆盖率只有 3.74%（见 §5.1）。
v0.4.0 据此报的 `negative` 已被撤回，现为 `inconclusive`。
教训是双向的——小样本的"没差别"和外推到全样本的"有差别"，都不能轻信。

---

## 3. 端到端对齐

```bash
python3 scripts/env_check.py    # ok=true, blocked=0
python3 scripts/validate.py     # ok=true
python3 scripts/build.py        # 约 54 秒
```

### 3.1 五轴结果

| 轴 | 可比项 | 一致 | 冲突 | 一致率 |
|---|---|---|---|---|
| condition | 46,642 | 46,642 | 0 | **1.00** |
| signal | 2,480 | 2,480 | 0 | **1.00** |
| wait | 2,480 | 2,480 | 0 | **1.00** |
| entry | 2,480 | 2,480 | 0 | **1.00** |
| exit | 4,028 | 3,525 | 503 | **0.8751** |
| **合计** | **58,110** | **57,607** | **503** | **0.9913** |

单边缺失：0（`open_position` 466 条是数据末尾仍未退出的持仓，不是差异）。

### 3.2 退出轴如何变成可比的

v0.2.0 时退出轴 `comparable=0`。根因有两层：

1. **合成日志从不写跨日退出记录**：`plan` 只写在入场日，`exit_time` 为 `None`。
2. **日志逐日生成**：生成当天时看不到次日，所有周期都停在 open。

修复后：

| 记录日 | 写入内容 |
|---|---|
| 入场日 | `signal` + `plan(enter)`，`cross_day_pending=true` |
| 退出日 | `plan(exit)` + `fill(side=sell)`，`cross_day=true` |

且**所有交易日一起跑一次重放再按日切分**（`build_fixtures.generate_logs`），
否则跨日退出的记录永远生成不出来。

### 3.3 单边缺失的口径

| 类型 | 数量 | 含义 |
|---|---|---|
| `jev_missing`（condition） | 1,633,358 | 日志只在状态翻转时写，重放逐根判断 |

条件轴覆盖率 2.78%（46,642 / 1,680,000 根）。这**不进入一致率分母**。
混算会得到"一致率 2.8%"这种误导性数字。

### 3.4 数据质量审计：未建模状态占多大比重

`applicability.out_of_scope` 一直写着「不含停牌/ST/涨跌停建模」。
但"不含"不等于"无关"——本轮用 `scripts/data_quality_audit.py` 把缺口量化了。

| 检查项 | 占比 | 影响 |
|---|---|---|
| ST 标的 | **4.20%**（294 / 7,000 序列，46 只） | 5% 涨跌幅限制与特殊规则，本 skill 未区分 |
| 停牌日 | 0.00% | 样本内无停牌序列 |
| 触及涨停 | 2.24% | 重放仍在该价位照常成交 |
| 触及跌停 | 0.64% | 跌停时卖出实际可能无法成交 |

**未建模占比上界 4.20%，判定 `moderate`。**

实际影响可直接测：本样本中 ST 标的产生了 **47 个信号、41 笔收官交易**，
占全部交易的 **2.04%**。这些交易在真实市场受 5% 涨跌幅约束，回放未体现。

```bash
python3 scripts/data_quality_audit.py            # 有凭证，含 ST/停牌名单
python3 scripts/data_quality_audit.py --offline  # 无凭证，只算涨跌停可达性
```

审计结果写入 `fixtures/manifest.json`，并在报告
`applicability.unmodeled_market_states` 回显。
**未核验时值为 `null` 而非 `0`**——"不知道"不许冒充"没有"。

### 3.5 分日稳定性（不是单日驱动）

| 交易日 | 可比 | 冲突 | 一致率 |
|---|---|---|---|
| 20261026 | 2,645 | 0 | 1.0000 |
| 20261027 | 1,792 | 39 | 0.9782 |
| 20261028 | 6,135 | 3 | 0.9995 |
| 20261029 | 2,033 | 54 | 0.9734 |
| 20261030 | 3,183 | 18 | 0.9943 |
| 20261102 | 8,171 | 4 | 0.9995 |
| 20261103 | 3,965 | 73 | 0.9816 |
| 20261104 | 6,503 | 38 | 0.9942 |
| 20261105 | 7,179 | 72 | 0.9900 |
| 20261106 | 1,805 | 52 | 0.9712 |
| 20261109 | 2,626 | 8 | 0.9970 |
| 20261110 | 5,135 | 34 | 0.9934 |
| 20261111 | 4,394 | 69 | 0.9843 |
| 20261112 | 2,544 | 39 | 0.9847 |

14 天全部落在 0.9712–1.0000，**没有单日主导总体**。
首日无退出可比（没有更早持仓带入），末日持仓未退出（`open_position`），
均为结构原因，非缺陷。

### 3.6 参数敏感性

| 时间容差 | 总一致率 | 退出轴一致率 | 冲突数 | 归因首位 |
|---|---|---|---|---|
| 0 分钟 | 0.9913 | 0.8751 | 503 | `exit_eval` 100% |
| 1 分钟 | 0.9913 | 0.8751 | 503 | `exit_eval` 100% |
| 2 分钟 | 0.9913 | 0.8751 | 503 | `exit_eval` 100% |
| 5 分钟 | 0.9913 | 0.8751 | 503 | `exit_eval` 100% |

结论对容差不敏感——日志与重放的退出时刻差是**整分钟**的离散值。
这也说明当前一致率不是靠容差"调"出来的。

---

### 3.7 判定器区分度（阳性/阴性对照）

一个**永远返回 `inconclusive`** 的判定器也能"通过"所有合成日志测试——
因为合成日志下本来就应该 inconclusive。那样等到真实日志到位，
判定器能不能正确区分三种结论，根本没被验证过。

`scripts/controls_check.py` 做受控对照：用参考语义生成日志后**抹掉
`_synthetic` 标记**（使其被当作真实日志），再看判定器能否随语义差异变化。

| 日志侧差异 | 一致率 | 冲突数 | 判定 | 期望 |
|---|---|---|---|---|
| 完全一致（阳性对照） | 1.0000 | 0 | `consistent` | ✓ |
| `exit_eval` | 0.9913 | 503 | `minor_divergence` | 不得 consistent |
| `signal_gain_pct` | 0.9436 | 939 | `minor_divergence` | 不得 consistent |
| `t_plus_1` | 0.9541 | 2,666 | `minor_divergence` | 不得 consistent |
| `entry_price` | 0.9174 | 4,967 | `minor_divergence` | 不得 consistent |
| `persistence_bars` | 0.8848 | 6,833 | `minor_divergence` | 不得 consistent |
| `baseline_price` | 0.8910 | 6,581 | `minor_divergence` | 不得 consistent |
| `breakout_field` | 0.8119 | 14,068 | `minor_divergence` | 不得 consistent |
| `bar_timestamp` | 0.5935 | 23,416 | `inconsistent` | 不得 consistent |

**9/9 通过。** 复跑：

```bash
python3 scripts/controls_check.py           # 全量，约 3 分钟
python3 scripts/controls_check.py --quick   # 2 日 / 120 标的，约 2 分钟
```

#### 这组对照抓出的两个真实缺陷

**缺陷 A：只看比率的盲区。** 初版 `consistent` 门槛是"一致率 ≥ 0.98"。
`exit_eval` 差一个旋钮产生 503 条真实冲突，一致率 0.9913，被误判为 `consistent`。
样本量越大，真差异越容易被"稀释"成高比率。

**缺陷 B：绝对容忍额度太宽。** 加绝对门槛时先设成"≤5 条冲突可忽略"。
结果 60 标的子集下 `exit_eval` 只产生 3 条冲突，又落回 `consistent`。
**"一致"的含义就是没有冲突**，不能给真实冲突留默认额度——现改为必须为 0。

这两条都是对照实验抓出来的，不是凭空想到的。

---

## 4. 归因

```bash
python3 -c "import json;print(json.load(open('output/report.json'))['attribution'])"
```

| 排名 | 旋钮 | 从 → 到 | 解释差异 | 解释率 |
|---|---|---|---|---|
| 1 | `exit_eval` | `bar_close` → `bar_high_low` | 503 | **100%** |

`verdict = single_knob`，`joint_diagnosis.applicable = true`。

**解读**：503 条退出差异**全部**由「退出按收盘价还是按触价判定」造成。

### 4.1 大偏差的成因已核实

12 条偏差 ≥5 分钟的记录，其 JEV 侧退出时刻**全部是 09:31**。逐条追查后确认：

| 标的 | 参考语义（`bar_close`） | 日志侧（`bar_high_low`） |
|---|---|---|
| `300024.SZ@20261106` | 09:42 stop_loss | 09:31 stop_loss |
| `301276.SZ@20261105` | 09:50 max_hold | 09:31 stop_loss |

`bar_high_low` 在**次日首根就触价止损**，`bar_close` 要等收盘确认后才触发。
这不是配对噪声，正是 `exit_eval` 两个档位导致的真实行为差别——
归因结论与逐条证据一致。

### 4.2 归因的适用边界（重要）

单旋钮消融的前提是「只有少数旋钮不同」。当**多个旋钮同时不同**时，
逐一把单个旋钮调到正确值并不会让差异明显下降——方法本身失效。

用 `naive_literal` 档位生成一份日志（与参考语义有 8 个旋钮不同）做反向检验：

| 操作 | 差异数 |
|---|---|
| 基线（参考语义 vs naive 日志） | 7,206 |
| 只把 `bar_timestamp` 改成 naive 值 | 5,489 |
| 只把 `baseline_price` 改成 naive 值 | 7,261（**增加**） |
| 只把 `t_plus_1` 改成 naive 值 | 8,742（**增加**） |
| 全部改成 naive（等价于日志侧配置） | **0** |

真因确实是多旋钮同时偏移，但单旋钮消融给不出结论。
此时报告输出 `joint_diagnosis.diagnosis = "multiple_knobs_shifted"`，
而不是「`bar_timestamp` 解释 23.8%」这种半吊子结论。

**方法的边界必须与方法的结论一起交付。**

### 4.3 归因机制的两个守卫

| 缺陷 | 症状 | 修复 |
|---|---|---|
| 消融用 `symbols` 视图，主流程用 `by_series` | 两侧可比项口径不一致，真实成因归不出来 | 统一用 `by_series` |
| 一律拒绝"可比项减少"的旋钮 | 真实差异必然改变信号集，被误判为未归因 | 区分「配对消失」与「冲突消失」 |

---

## 5. 价值评估

对比「显式语义」（当前配置）与「字面直译」（`naive_literal` 基线），
两者共用同一份真实分钟线与前收价，唯一受控变量是语义档位。

| 指标 | 基线（字面直译） | 当前（显式语义） |
|---|---|---|
| 信号数 | 47,669 | 2,480 |
| 收官周期 | 45,507 | 2,014 |
| 每周期净收益均值 | −0.166% | −0.253% |
| 净收益合计 | −75.589% | −5.094% |

### 5.1 为什么结论是 `inconclusive`（v0.4.1 更正）

**v0.4.0 曾报 `negative`，那是错的，本轮已撤回。**

配对检验只比"两套语义都选出同一笔交易"的周期。本案例两者交易集合差异极大：

| 项 | 值 |
|---|---|
| 基线收官周期 | 45,507 |
| 当前收官周期 | 2,014 |
| 配对周期 | 1,701 |
| **配对覆盖率** | **3.74%**（1,701 / 45,507） |

3.74% 的样本不足以代表全样本 —— 配对检验几乎测的只是重叠部分那少数几笔。
报告现在有硬门槛：**配对覆盖率 < 10% 一律 `inconclusive`**，
并在 `decision_changes.coverage_sufficient=false` 显式标注。

### 5.2 全样本独立佐证

为不受配对影响，另做不依赖配对的 Welch 两样本检验：

| 项 | 值 |
|---|---|
| 样本量 | 45,507 vs 2,014 |
| 均值差 | −0.0868% |
| 标准误 | 0.0929% |
| t | −0.935 |
| **p** | **0.350** |

全样本检验同样**不显著**。两种口径一致指向 `inconclusive`。

### 5.3 结论

显式语义把交易次数砍掉 95%（47,669 → 2,480），但：

- 配对子样本（3.74% 覆盖率）显示方向偏负（738 胜 / 949 负，p≈0），
- 全样本 Welch 检验显示均值差 −0.087%、**p=0.35，不显著**。

**正确结论**：语义选择巨大地改变了交易行为，但在这 14 个交易日、500 只标的的样本上，
**收益差异不可证** —— 既不能宣称改善，也不能宣称劣化。

v0.4.0 的 `negative` 是选择性样本造成的假阳性，本轮修正了判定规则，
并把这个陷阱固化成测试（`test_low_pairing_coverage_forces_inconclusive`）。

---

## 6. 验证中发现并修复的缺陷（16 项）

以下都不是构造的测试用例，而是在真实数据上跑出来的：

| # | 缺陷 | 症状 | 修复 |
|---|---|---|---|
| 1 | 止损/止盈分支绕过 T+1 检查 | 同一天里强平被推迟、止损却能当日成交 | 四条退出路径统一走 `_exit_or_defer` |
| 2 | 单日 + T+1 下无任何周期能收官 | `closed_count=0`（此前能收官全靠缺陷 1） | 跨日持仓传递 `_carry_forward` |
| 3 | 跨日持仓每天新建周期对象 | 入场日的周期停在 open，退出轴永远配不上 | 复用同一对象 |
| 4 | 跨日周期被重复计数 | 同一笔在 `cycles` 与 `exit_cycles` 各出现一次 | 按对象身份去重 |
| 5 | 多日构建时日志混入其他交易日 | `20261110.jsonl` 里出现 20261112 的记录 | 按日期切分 |
| 6 | 前收价按裸代码取 | 多日下取到别的交易日的前收 | 按 `symbol@date` 取值 |
| 7 | 合并视图导致信号日期错标 | 各日信号全被标成最后一天 | `log_synth` 遍历 `by_series` |
| 8 | 归因把"配对打散"当成"解释差异" | 假 100% 解释率 | `alignment_preserved` 守卫 |
| 9 | 合成日志缺档位信息 | 不知道按哪套语义生成 | 回显 `logged_semantics.knobs` |
| 10 | 合成日志从不写跨日退出记录 | 退出轴 `comparable=0` | 入场日/退出日分别写 `plan` |
| 11 | `exit_series` 在未退出时被写成当天 | 入场日视图比对错记录 | 仅当 `exit_time` 存在时定格 |
| 12 | 消融与主流程使用不同视图 | 真实成因归不出来（0%） | 统一用 `by_series` |
| 13 | 退出计划混进入场候选池 | entry 轴 390 条假 `jev_only` | 入场轴只取 `plan=="enter"` |
| 14 | 配对容差与判定容差混用 | 差 2 分钟先配对失败、再记成单边缺失 | 拆成两个参数 |
| 15 | 容差外无回退配对 | 两侧都有这笔交易却记成单边缺失 | 最近邻回退 + 低置信标记 |
| 16 | **`build_fixtures` 逐日生成日志** | 当日看不到次日，所有周期停在 open，退出记录为空 | 全部交易日一起跑再按日切分 |
| 17 | **配对覆盖率过低仍给 verdict** | 3.74% 的子样本被当成全样本证据，报出假的 `negative` | 覆盖率 <10% 强制 `inconclusive`，并补全样本 Welch 检验 |
| 18 | **`consistent` 只看一致率** | 503 条真实冲突被大样本稀释成 0.9913，误判一致 | 加绝对冲突门槛，且必须为 0 |
| 19 | **绝对门槛设成"≤5 条"** | 60 标的子集下 3 条冲突又被判一致 | 改为 0；"一致"不接受默认容忍额度 |
| 20 | **代码默认值与 YAML 不一致** | 缺 pyyaml 时静默走合成模式，真实日志接入会读不到 | 逐项对齐 + 降级原因回显到报告 |

---

## 7. 错误路径

| 场景 | 结果 |
|---|---|
| 空字符串输入 | `ReplayError: empty_input` |
| 未知字段 | `ReplayError: unknown_field`，列出允许字段 |
| `bars_dir` 不存在 | `ReplayError: bars_dir_not_found` |
| K 线缺字段 / high<low / 价格非正 | `ReplayError: missing_bar_field` / `invalid_bar_field` |
| 同标的同分钟重复 | `ReplayError: duplicate_bar` |
| 语义旋钮取值非法 | `ReplayError: invalid_semantics` |
| 日志 `kind` 非法 | `LoadError: invalid_log_kind` |
| 多日模式日志缺 `date` | `LoadError: missing_log_field` |
| 缺 panda_data | `env_check` 报 `warn` 而非 `blocked` |
| `config_hash` 不一致时比对基线 | `comparable=false`，不给 delta |
| 非交易日拉数据 | `FetchError: no_data`，退出码 2 |

---

## 8. 复现环境

| 项 | 值 |
|---|---|
| Python | 3.12.12（主）、3.11.16 |
| panda-data | 1.0.6（仅夹具再生） |
| 三方依赖 | 无（对齐与回放为纯标准库） |
| 全量对齐 | 约 54 秒（7,000 序列 × 240 根） |
| 单元测试 | 约 55 秒 |

```bash
git clone https://github.com/quantskills/skill-jev-history-replay
cd skill-jev-history-replay
pip install -r requirements-dev.txt
python3 scripts/env_check.py
python3 scripts/validate.py
python3 -m pytest tests/ -v
python3 scripts/build.py
python3 scripts/verify_claims.py
```

---

## 9. 结论与边界

**已验证**：
- 五轴全部可比：条件/信号/等待/入场一致率 1.00，退出轴 0.8751，总体 0.9913；
- 503 条退出差异被 `exit_eval` 单一旋钮完整解释（100%），
  大偏差的 JEV 侧时刻全部指向次日首根触价，与逐条证据一致；
- 14 天分日一致率 0.9712–1.0000，不由单日主导；
- 未建模状态占比已量化：ST 4.20%、触涨停 2.24%、触跌停 0.64%，
  上界 4.20%（`moderate`），ST 标的实际产生 2.04% 的交易（§3.4）；
- 容差 0–5 分钟结果不变；
- 显式语义与字面直译的收益差异**不可证**：配对覆盖率仅 3.74%，
  全样本 Welch 检验 p=0.35，两种口径都不显著；
- 判定器有真实区分度：9 组阳性/阴性对照全部按预期判定（§3.6）。

**方法边界（已验证并记录）**：
- 单旋钮消融仅在「少数旋钮不同」时有效；多旋钮同时偏移时输出
  `multiple_knobs_shifted`，不给 `top_knob` 结论（见 §4.2）

**未验证**：
- **JEV 实际语义**——日志为合成数据，对齐 verdict 恒为 `inconclusive`；
- T+0 市场、多空双向、除权除息、停牌、涨跌停场景。

**结论据此成立的范围**：仅在 `applicability` 声明的 A 股分钟级单/多日场景，
且日志按 `log_contract.md` 提供记录时。

**要让对齐 verdict 变成 `consistent` / `inconsistent`**：把真实 JEV 日志按
`log_contract.md` 放进 `fixtures/logs/`，重跑 `build.py`。代码无需改动。