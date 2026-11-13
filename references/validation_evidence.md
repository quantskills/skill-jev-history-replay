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
当前覆盖 **71 项**：
- 33 项关键指标
- 28 项分日数字（14 天 × 可比/冲突）
- **10 项内部自洽**（见下）

#### 报告内部自洽检查

这些数字由**不同代码路径**算出：`summary` 来自 `run_eval`，
`aggregate` 来自 `aligner`，`per_day` 又一次聚合。任一处口径不一致，
读者就会拿到互相矛盾的数，而单看每个字段都"像是对的"。

| 检查 | 说明 |
|---|---|
| `summary.*` vs `aggregate.total.*` | 一致率与冲突数必须相同 |
| `by_axis` 各轴加总 = `total` | match / divergent / one_sided 三项 |
| `per_day` 各日加总 = `total` | 同上 |
| `total.comparable = match + divergent` | 恒等式 |
| `total.rows = match + divergent + one_sided` | 恒等式 |

**由此发现并修复的缺陷**：`by_axis` 的每个轴只存了具体状态名
（`jev_missing` 等），没有 `one_sided` 汇总字段。于是"各轴 one_sided
加起来是 0，total 却是 97 万"——看起来像数据错乱，实际是命名不统一。
现已为每轴补 `one_sided` 汇总。

**灵敏性**：篡改 `summary.divergence_items` 后，检查立刻报
`consistency.summary.divergent: actual=999 expected=379`。
测试里还有一条 `test_claim_checker_catches_drift`，故意篡改一项来证明
这个校验器不是摆设。

**本文档的数字不是手抄的，是被测试守着的。** v0.4.0 把样本从 7 日扩到 14 日时，
正是这条测试先红，才逼着文档同步更新。

---

## 1. 单元测试

```bash
python3 -m pytest tests/ -q -m "not slow"   # 127 passed, 47 秒
python3 -m pytest tests/ -q -m slow         # 区分度对照，约 2 分钟
```

| 项 | 结果 |
|---|---|
| 用例总数 | 203（201 通过 + 1 跳过 + 1 慢测单独跑） |
| 失败 | 0 |
| 环境 | Python 3.12.12 / 3.11.16 |
| 全量耗时 | 快测约 47 秒；慢测（区分度对照）另约 2 分钟 |

| 文件 | 用例数 | 覆盖 |
|---|---|---|
| `test_semantics.py` | 15 | 旋钮取值校验、哈希敏感性、**默认值与 YAML 一致**、降级可见、**config 未知键必报错**、**文档所列 config 键全部生效** |
| `test_data_loader.py` | 21 | 格式容错、gzip、字段校验、重复检测、**分钟缺口与午休排除**、**多日 series 键带日期**、**代码大小写/空格归一** |
| `test_replayer.py` | 19 | 条件判断、连续性、等待/入场、四条退出路径、T+1、时间边界、**强平推迟不重复累加 bars_held** |
| `test_cross_day.py` | 6 | 跨日持仓传递、未平仓如实上报、单日行为不变 |
| `test_aligner.py` | 18 | 五轴对齐、配对唯一性、单边缺失、差异分类、容差分离、**每轴 match/divergent 必须存在**、**容差必须真正改变判定** |
| `test_attribution.py` | 11 | 单旋钮解释率、视图一致性、**多旋钮漏报成因** |
| `test_report.py` | 31 | verdict 判定、覆盖率门槛、零冲突门槛、Welch 检验、**p 值不得被舍入为 0**、**任一轴零可比不得判 consistent**、**reason 里的 p 值不得显示为 0** |
| `test_end_to_end.py` | 11 | 输入校验、来源判定、产物落盘、确定性 |
| `test_validation_claims.py` | 13 | **文档数字对账**、防漂移、区分度对照、**陈旧数字扫描** |
| `test_data_quality_audit.py` | 7 | 板块分类、涨跌停口径、**离线时上界必须为 unknown 而非部分值**、报告回显 |
| `test_trade_audit.py` | 4 | **逐笔价格/算术反查**、跨日覆盖、故意改价必被抓 |
| `test_doc_commands.py` | 9 | **文档引用的脚本必须存在 / 可解析**、**证据表格与实际测试文件一致**、**表格用例数 = pytest 收集数**、**README 目录树列全脚本**、**缺陷标题数 = 表行数**、**文档里的命令输出计数与实际一致** | **文档引用的脚本必须存在 / 可解析**、**证据表格与实际测试文件一致**、**表格用例数 = pytest 收集数**、**README 目录树列全脚本**、**缺陷标题数 = 表行数** |
| `test_compare_baseline.py` | 8 | **冻结基线**、同配置给 delta、异配置拒绝、结构化错误、**仅 config_hash 变也要列出** |
| `test_value_decomposition.py` | 4 | **T+1 强制隔夜**、拆解前提、summary 形状 |
| `test_credentials.py` | 6 | **引号去除**、别名回退、缺凭证结构化报错、非法 URL 拒绝 |
| `test_ci_config.py` | 4 | **CI 配置合法**、步骤齐全、build 先于 tests |
| `test_ledger_mode.py` | 3 | **账本瘦身**、full 可回溯、per_day 入报告 |
| `test_adapt_logs.py` | 22 | **外部日志字段映射**、布尔规范化、缺字段必失败、**纯契约日志可端到端接入**、**多日缺 date 必报错（加载器与 validate 两处）**、**无法判定的 hit 必报错**、**时间戳写法不影响结论** |
| `test_knob_efficacy.py` | 3 | **旋钮全部接线**、指纹稳定性、含当前根必归零 |
| `test_metrics_correctness.py` | 15 | **统计函数正确性**：精确值对比、蒙特卡洛 Type-I/覆盖率 |
| `test_fixture_universe.py` | 5 | **14 日标的池恒定**、每条序列 K 线完整、**manifest 与实际夹具对账**、**gzip mtime=0 可重现**、**夹具日志与当前重放一致** |
| `test_oos_check.py` | 4 | **IN_SAMPLE 基准与当前报告一致**、judge 能识别显著性减弱 |
| `test_multi_knob_docs.py` | 5 | **多旋钮表内部一致**、仅 exit_eval 行与报告一致、**naive 消融表单项不解释**、**wait_bars/合并数可在真实夹具复现**（slow）、**naive 消融表可复现**（slow） |
| `test_report_consistency.py` | 5 | **divergence_items 四处同口径**、各轴 divergent 加总、**non_match_rows 单列**、per_day 加总=total、inline 截断标记 |
| `test_fixture_integrity.py` | 4 | **pre_close 口径**、日线 high/low/close 与分钟线一致、**day_open 取首根**、文档写明口径 |
| `test_conclusion_consistency.py` | 7 | **§9 的数字与报告对账**：总体/退出轴一致率、未建模上界、**不得再称容差结果不变**、ST 占比两处一致、**样本长度敏感性已声明**、**方向翻转可复现**（slow） |
| `test_release_compliance.py` | 7 | **免责声明四点**、INSTALL 五平台、SPDX 许可证、三处 name 一致、无占位符、**无凭证/内网/邮箱泄露**、entry 存在 |
| `test_runtime_adapters.py` | 9 | **适配器文件齐备**、声明的脚本/entry 存在、**旋钮清单与代码一致**、版本与 skill.json 一致、**README 实例数字与报告一致** |

---

## 1.0a CI 流水线本身

所有轮次都声称「CI 会跑这些步骤」，但从未按 CI 顺序真跑过。

### 发现：流水线从未成功解析

`.github/workflows/validate.yml` 里有一行：

```yaml
- name: Unit tests (slow: verdict discrimination)
```

冒号没加引号，YAML 把 `slow` 当成键——**整个文件是无效 YAML**。
这条流水线从来没跑起来过，而此前每轮都在引用它。

修复后加了 `tests/test_ci_config.py`（4 例）：YAML 合法性、必需步骤齐全、
`build` 必须排在 `tests` 之前（`per_day` 校验依赖它）、每个 `run` 非空。

### 按 CI 顺序在冷克隆上实跑

```bash
git clone ... /tmp/jev-ci && cd /tmp/jev-ci
python3 scripts/env_check.py      # exit 0
python3 scripts/validate.py       # exit 0, issues []
python3 scripts/build.py          # exit 0
python3 scripts/verify_claims.py  # 79/79 OK
```

### 由此发现的账本体积问题

`build.py` 若写出全量账本，会有约 **185 MB / 1,015,406 行**：

| 状态 | 行数 | 占比 |
|---|---|---|
| `one_sided`（多为 `jev_missing`） | 979,320 | **96.45%** |
| `match` | 35,772 | 3.52% |
| `divergent` | 319 | 0.03% |
| `open_position` | 74 | 0.01% |

前两类合计 99.96%，但**它们不是差异**：`jev_missing` 是"日志没记这一根"，
`match` 是一致。真正需要逐行追溯的只有 393 行（319 divergent + 74 open_position）。

新增 `ledger_mode`（默认 `diff`）：只写需要看的记录。
**185 MB → 68 KB（69,454 字节），缩减 99.96%**。需要全量时设 `ledger_mode: full`。

同时把分日聚合写进 `report.per_day`，让 `verify_claims` 不必再读那个大文件。

---

## 1.0b 统计函数正确性

报告里所有 p 值和置信区间都出自 `scripts/metrics.py` 的手写实现。
此前从未验证过这些实现本身——符号检验的双尾算错、Wilson 公式写反、
Welch 的分母用错，都会让所有"显著"失去意义。

用三种独立手段验证（`tests/test_metrics_correctness.py`，15 例，0.07 秒）：

| 函数 | 验证方式 | 结果 |
|---|---|---|
| `sign_test_p` | 与二项分布精确双尾值逐点对比（含 100:60、950:738） | 误差 **0** |
| `wilson_interval` | 与手写公式对比 + 蒙特卡洛覆盖率 | 公式值一致；覆盖率 **0.9473**（名义 95%） |
| `welch_test` | t/se 与手工公式对比 + 蒙特卡洛 Type-I 错误率 | t 一致；Type-I **0.0510**（名义 0.05） |
| `paired_delta_ci` | 与手工均值/区间对比 | 一致 |

**灵敏性验证**：把符号检验的 `tail * 2` 改成 `tail`（单尾），
5 个参数化用例立刻全部失败。说明这组测试不是摆设。

> 这些验证的是"实现是否符合统计定义"，不是"统计方法是否适用于本数据"。
> 后者由 §5 的覆盖率闸门与 §4.5 的样本外复现共同约束。

---

## 1.0d 文档命令可执行性

一条容易被忽略的验收项：**文档里写的命令，是否真能跑**。

### 发现：整篇 data_access.md 是别的 skill 的模板

`references/data_access.md` 曾通篇写着 fixture_generator.py、
replay_engine.py、constraints_evaluator.py——**这些都不是本 skill 的文件**。
读者照文档跑会直接报"文件不存在"。

（早前重写过一次，但后来某次 `rsync --delete` 把发布副本的旧版本反向覆盖了回来。）

### 修复
- 整篇重写 `data_access.md`，只列本 skill 真实存在的脚本与接口
- 新增 `tests/test_doc_commands.py` 的脚本存在性/可解析性用例：
  - **文档里作为命令或路径出现的每个 `scripts/*.py` 必须真实存在**
  - 每个脚本要有模块 docstring
  - 每个脚本语法可解析

  > 注：早期版本还有一条"禁止出现其它 skill 脚本名"的用例，因为会同时命中
  > 本节自己的反例叙述（`fixture_generator.py` 作为"不存在"的例子被提到）而删除。
  > 真正的防线是第一条：只有写成 `python3 ` + `scripts/` 路径、或行内代码包住
  > `scripts/` 路径这种**让读者去执行**的写法才被收集并校验；正文里的普通提及不算。

### 逐条实跑文档命令
| 命令 | 退出码 |
|---|---|
| `python3 scripts/env_check.py` | 0 |
| `python3 scripts/validate.py` | 0 |
| `python3 scripts/data_quality_audit.py --offline` | 0 |
| `python3 scripts/verify_claims.py` | 0 |
| `python3 scripts/build.py` | 0 |

### 补充：静态结构类声明同样会漂移

命令能跑，不等于读者能照文档找到文件。本轮又查出两类结构失真：

| 问题 | 实际 |
|---|---|
| `README.md` 的 `scripts/` 目录树 | 漏列 7 个脚本 |
| `README.en.md` 同处 | 漏列 12 个脚本 |
| 两份 README 的 `references/` | 均漏列 `validation_evidence.md` |
| 本证据文档的逐文件用例数 | **8 个文件与 pytest 收集数不符**（如 `test_report.py` 写 24 实为 26、`test_semantics.py` 写 15 实为 13） |
| 本证据文档的测试清单 | 漏列 `test_fixture_universe.py` |

`verify_claims` 只对账关键研究指标，不检查这类结构性描述，所以它们一直没人发现。

修复后加了三条**以实际文件/实际收集结果为唯一真相**的测试：

| 测试 | 断言 |
|---|---|
| `test_readme_trees_list_every_script` | 两份 README 的树都列全 `scripts/*.py` |
| `test_evidence_table_lists_every_test_file` | 表格的测试文件集合 == `tests/` |
| `test_evidence_table_counts_match_collection` | 表格每格 == `pytest --collect-only` 计数 |

第三条特意用 pytest 自己的收集结果，而不是数 `def`——参数化与 fixture
会让两者不等（当前 `def` 数 194，实际收集 206）。

---

## 1.0c 冻结基线（freeze / compare / list）

README 与 `api_guide.md` 都写了这个功能，但此前**没有任何测试覆盖**。
本轮端到端跑通三种操作：

```bash
python3 scripts/compare_baseline.py freeze output/report.json --name t1
python3 scripts/compare_baseline.py list
python3 scripts/compare_baseline.py compare output/report.json --against baselines/t1.json
```

### 核心行为：不可比时拒绝给 delta

| 场景 | `comparable` | `deltas` | 说明 |
|---|---|---|---|
| 同一 config_hash | `true` | 逐项 delta | 可比 |
| 改一个旋钮（`wait_bars`） | **`false`** | **`null`** | 列出 `changed_fields: ["semantics_hash"]` |

实测（改 `wait_bars` 后与基线比较）：

```json
{
  "comparable": false,
  "changed_fields": ["semantics_hash"],
  "deltas": null,
  "note": "config_hash 不一致，差异不可解读；请确认语义、夹具或日志来源是否变化"
}
```

这是整个机制的意义所在——若它悄悄给出一个差值，读者会拿两次**不可比**的运行
做比较，还以为在比同一件事。

### 后补的测试
`tests/test_compare_baseline.py`（7 例）：freeze 落盘、同配置给 delta、
**异配置拒绝 delta**、list 元数据、缺文件与坏 JSON 的结构化错误。

---

## 1.1 冷克隆验收（不依赖任何本地残留）

```bash
git clone git@github.com:quantskills/skill-jev-history-replay.git /tmp/jev-cleanroom
cd /tmp/jev-cleanroom
python3 scripts/env_check.py      # ok=true
python3 scripts/validate.py       # ok=true, 0 issues
python3 scripts/build.py          # 约 31 秒
python3 scripts/verify_claims.py  # 79/79
python3 -m pytest tests/ -q       # 275 passed, 1 skipped
```

实测（v0.12.8，从 `origin/main` 全新 clone 到 /tmp）：各项全过，
总一致率 0.9912、退出轴 0.8878，与本机**完全一致**。`output/` 在 clone 后
不存在，由 `build.py` 自动创建——不依赖任何预生成产物。

### 纯标准库可跑

系统自带 Python 3.9.6 下 `python3 scripts/build.py` 跑通，数字完全相同
（0.9912 / 0.8878）。再用 `python3 -S`（屏蔽 site-packages，等价于无任何
三方包）复跑，仍得同一组数字，且报告正确回显降级原因：

```
config_warnings: ['缺少 pyyaml，未加载 config/replay_config.yaml，使用内置默认值']
```

对齐与回放确实为零三方依赖；缺 pyyaml 不会静默降级——YAML 里的值与
内置默认值逐项对齐，只丢 YAML 注释与可覆盖性。

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
| 标的数 | **300 / 日**，**全期固定同一批** |
| 序列数 | **4,200**（`symbol@date`） |
| 分钟线 | **1,008,000 根** |
| 日志记录 | 见 `fixtures/manifest.json` |

#### 标的池必须全期固定（v0.6.1 修复）

早期版本每天按**当日** `get_trade_list` 各自抽样，池子天天变。
实测相邻交易日重合度最低只有 **18.6%**，14 天交集仅 **66 只**（并集 1,366）。
后果很直接：昨天买入的股票今天可能根本不在样本里，**跨日持仓传递形同虚设**，
T+1 相关结论失去基础。

修复：取所有交易日 `trade_list` 的**交集**，再按代码排序等距抽样。
现 14 天标的池完全一致（`tests/test_fixture_universe.py` 守住）。
交集本身也保证了样本内没有中途退市/停牌断档。

**抽样方法**：`get_trade_list(exchange='SH')` 取全市场，按代码排序后等距抽样。
不按当日涨跌筛选——那会让结论只对"涨了的股票"成立。

### 2.1 扩大样本的后果

7 日 → 14 日、200 → 500 标的，配对周期从 314 增到 1,701。
符号检验从"不显著"（p=0.65）变为"显著偏负"（p≈0）。

但这**不构成结论**：配对覆盖率只有 3.74%（见 §5.1）。
v0.4.0 据此报的 `negative` 已被撤回，现为 `inconclusive`。
教训是双向的——小样本的"没差别"和外推到全样本的"有差别"，都不能轻信。

---

## 2.9 逐笔核对（价格与收益算术）

前面的验证都是统计层面的。统计对，不代表每一笔的算术都对——入场价取错行、
成本算反、收益公式写错，都可能被整体一致率掩盖。

`scripts/trade_audit.py` 独立重算：从原始 K 线找出入场/退出那两根，
重算 gross/net，与 replayer 记录比对，**不复用 replayer 内部函数**。

```bash
python3 scripts/trade_audit.py --sample 99999   # 全量（默认只抽 200 笔）
```

> 默认 `--sample 200`。要复现下表必须显式放大 `--sample`，
> 否则看到的是「抽样 200、全部通过」，与「全量」不是一回事。

| 项 | 结果 |
|---|---|
| 收官周期 | 1,422 |
| 核对笔数 | **1,422（全量）** |
| 其中跨日 | 1,422 |
| 失败 | **0** |

核对的六个点：

| 检查 | 内容 |
|---|---|
| 入场价 | `next_open` 模式取 `entry_time` 那根的 `open`，必须完全相等 |
| 退出价 | 按 `exit_reason` 分派：`max_hold` 取 open、`force_exit_time` 取 close、触价类须落在该根 `[low, high]` 内 |
| gross | `(exit - entry) / entry`，容差 1e-7 |
| net | `gross - (fee_bps + slippage_bps) × 2 / 10000` |
| 股数 | 必须是 `lot_size` 的整数倍 |
| 持仓根数 | 必须为正 |

**抽样也会抓错**：改动一笔的入场价 1%，核对器立刻报「入场价不符」并连带
gross/net 不符（`test_audit_detects_wrong_entry_price`）。

### 人工复核纪要

首笔跨日交易 `000001.SZ@20261027 10:27 信号 → 10:29 入场 @11.48`：

- 原始 K 线 `000001.SZ@20261027` 的 10:29 那根 open = **11.48** ✓
- 次日 `000001.SZ@20261028` 09:31 open = **11.43**，`max_hold` 按 open 退出 ✓
- gross = (11.43 − 11.48) / 11.48 = **−0.43554%**，与记录一致 ✓
- net = gross − (5 + 2) × 2 / 10000 = **−0.57554%**，与记录一致 ✓

> 复核时曾误用 `000001.SZ@20261026` 的 K 线去比对，得出"入场价差 2%"的结论。
> 实际是序列取错——周期带 `entry_series` 字段，必须按它反查。
> 这也说明**核对方向本身要防错**，不能凭直觉。

---

## 3. 端到端对齐

```bash
python3 scripts/env_check.py    # ok=true, blocked=0
python3 scripts/validate.py     # ok=true
python3 scripts/build.py        # 约 31 秒
```

### 3.1 五轴结果

| 轴 | 可比项 | 一致 | 冲突 | 一致率 |
|---|---|---|---|---|
| condition | 28,754 | 28,754 | 0 | **1.00** |
| signal | 1,496 | 1,496 | 0 | **1.00** |
| wait | 1,496 | 1,496 | 0 | **1.00** |
| entry | 1,496 | 1,496 | 0 | **1.00** |
| exit | 2,844 | 2,525 | 319 | **0.8878** |
| **合计** | **36,086** | **35,767** | **319** | **0.9912** |

> **样本变更说明**：v0.6.1 修掉了标的池不一致的缺陷，序列从 7,000 降到 4,200
> （300 × 14，全期固定）。数字随之变化，但**结构结论不变**：
> 四轴一致率 1.00，退出轴 0.87 左右，归因仍锁定 `exit_eval`。

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
| `jev_missing`（condition） | 979,246 | 日志只在状态翻转时写，重放逐根判断 |

条件轴覆盖率 2.85%（28,754 / 1,008,000 根）。这**不进入一致率分母**。
混算会得到"一致率 2.8%"这种误导性数字。

### 3.35 分钟缺口（重放器按「根数」计，缺口会静默失真）

`breakout_window` / `max_hold_bars` / `bars_to_entry` 全部按**根数**计算。
若某标的当天有分钟缺口（停牌、流动性枯竭、数据缺失），10 分钟的空档
会被当成 **0 根**——窗口回看范围和持有期都会失真，而且**不报任何错**。

实测确认这个行为：构造一段缺 10 根的序列，重放器正常产出信号，
`bars_to_entry` 仍是 1，缺口凭空消失。

**真实夹具检查结果：除午休外零缺口。**

| 项 | 结果 |
|---|---|
| 序列数 | 4,200 |
| 有缺口的序列 | **0** |
| 假缺口（午休 11:30→13:01） | 已排除 |

`data_loader.find_gaps()` 显式检测，`validate.py` 在发现缺口时报
`minute_gaps`：缺 < 500 根为 `warn`，≥ 500 根为 `error`。

> 午休必须排除，否则每条序列都会报一个假缺口（11:30 → 13:01 跨 91 分钟）。
> 这是实现该检测时踩到的第一个坑。

**真实 JEV 日志接入后**，若其覆盖的标的包含停牌/低流动性小票，
缺口几乎必然出现。届时应先看 `validate.py` 的 `minute_gaps`，
再决定是剔除这些标的还是改用「时间跨度」而非「根数」做窗口计算。

---

### 3.39 外部日志适配：真实格式接入时的第一步

所有测试用的日志都出自本库的 `log_synth`，格式必然兼容——**这不构成验证**。
真实 JEV 日志的字段名几乎不会和契约一致。

#### 实测：字段名不同会怎样

| 外部写法 | 直接加载 | 后果 |
|---|---|---|
| `"price": 11.5`（应为 `entry_price`） | **成功，但丢字段** | 入场价轴不可比，静默 |
| `"side": "buy"`（应为 `signal`） | **成功，但丢字段** | 信号轴不可比，静默 |
| `"code"` 而非 `"symbol"` | 报 `missing_log_field` | 明确失败 ✓ |
| `"hit": "false"`（字符串） | 加载成功 | `bool("false") == True`，**命中判反** |

`validate.py` 会把这些报成 `warn`，但 `ok` 仍为 `true`——**可以带着缺陷跑出结论**。

#### 新增 `scripts/adapt_logs.py`

把字段映射**显式声明**，而不是靠猜：

```bash
python3 scripts/adapt_logs.py --map-example          # 看映射模板
python3 scripts/adapt_logs.py --src raw/ --dst adapted/
```

| 能力 | 说明 |
|---|---|
| 通用同义词 | `timestamp→ts`、`code→symbol`、`type→kind`、`matched→hit`、`action→signal` 等 |
| 按 kind 细化 | 同一字段在不同记录类型里含义不同时可单独指定 |
| 布尔规范化 | `1/0`、`"true"/"false"`、`"yes"/"no"` 全部转成真正的 `bool`；**认不出的值报 `invalid_hit_value`，不默认成 False** |
| 缺字段即失败 | 适配后仍缺必需字段 → 报错，不让它进入对齐 |
| 未映射字段保留 | 不丢弃，便于追溯 |

**时间格式**直接加载即兼容（实测 5 种）：

| 写法 | 解析结果 |
|---|---|
| `2026-11-10T09:41:00` | 09:41 ✓ |
| `20261110 094100` | 09:41 ✓ |
| `0941` | 09:41 ✓ |
| `date` 与 `ts` 分字段 | 09:41 ✓ |
| `09:41:00.123`（毫秒） | 09:41 ✓ |

#### 适配中发现并修复的缺陷

**缺陷 28：文件名转换把 `a.jsonl` 写成 `a.jsonll`**，输出目录为空但函数
返回 `ok: true`。这是"成功但什么都没做"的典型——比报错更危险。
已加测试 `test_adapt_dir_writes_correct_filenames` 守着。

---

### 3.38 旋钮功效：每个语义旋钮是否真的影响输出

"语义对齐"的前提是每个旋钮都真实生效。若某个旋钮接进了配置、却对重放
毫无影响，它就是个**装饰性参数**——对齐它毫无意义，而报告仍会显示
"该旋钮一致"。这类沉默失效比报错难发现得多。

`scripts/knob_efficacy.py` 把每个旋钮单独换成备选值，比较整份交易的指纹
（全部周期的 信号索引/入场时点与价/退出时点与价/原因/状态）。

| 旋钮 | 改动 | 信号数变化 | 指纹 |
|---|---|---|---|
| `bar_timestamp` | `bar_end` → `bar_start` | 278 → 278 | **变化** |
| `baseline_price` | `prev_close` → `day_open` | 278 → 272 | **变化** |
| `breakout_field` | `high` → `close` | 278 → 332 | **变化** |
| `breakout_includes_current` | `False` → `True` | 278 → **0** | **变化** |
| `persistence_bars` | 2 → 1 | 278 → 433 | **变化** |
| `wait_bars` | 1 → 0 | 278 → 278 | **变化** |
| `entry_price` | `next_open` → `signal_close` | 278 → 278 | **变化** |
| `exit_eval` | `bar_close` → `bar_high_low` | 278 → 278 | **变化** |
| `t_plus_1` | `True` → `False` | 278 → 552 | **变化** |
| `cooldown_bars` | 10 → 0 | 278 → 279 | **变化** |

**10/10 全部有效**（3 天 / 900 序列的子集）。

注意三行的信号数没变但指纹变了——`bar_timestamp`、`wait_bars`、
`entry_price`、`exit_eval` 改的是**时点与价格**，不改变触发次数。
只看信号数会把它们误判成"无效果"，所以必须比整份交易指纹。

#### 顺带印证一个设计决定

`breakout_includes_current=True` 时信号归零：`close > max(close 含自身)`
恒假。这正是 `naive_literal` 里把它设为 `False` 的原因——那不是"字面直译"，
而是配置错误。价值评估要对比两种**都成立**的实现，不是一种实现和一种 bug。

---

### 3.4 数据质量审计：未建模状态占多大比重

`applicability.out_of_scope` 一直写着「不含停牌/ST/涨跌停建模」。
但"不含"不等于"无关"——本轮用 `scripts/data_quality_audit.py` 把缺口量化了。

| 检查项 | 占比 | 影响 |
|---|---|---|
| ST 标的 | **4.67%** | 5% 涨跌幅限制与特殊规则，本 skill 未区分 |
| 停牌日 | 0.00% | 样本内无停牌序列 |
| 触及涨停 | 1.76% | 重放仍在该价位照常成交 |
| 触及跌停 | 0.64% | 跌停时卖出实际可能无法成交 |

**未建模占比上界 4.67%，判定 `moderate`。**

实际影响可直接测：本样本中 ST 标的产生了 **52 个信号、47 笔收官交易**，
占全部交易的 **3.31%**（47/1,422）。这些交易在真实市场受 5% 涨跌幅约束，回放未体现。

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
| 20261026 | 1,547 | 0 | 1.0000 |
| 20261027 | 1,094 | 28 | 0.9744 |
| 20261028 | 4,032 | 10 | 0.9975 |
| 20261029 | 1,279 | 49 | 0.9617 |
| 20261030 | 1,597 | 6 | 0.9962 |
| 20261102 | 5,127 | 10 | 0.9980 |
| 20261103 | 2,494 | 90 | 0.9639 |
| 20261104 | 4,170 | 22 | 0.9947 |
| 20261105 | 4,651 | 50 | 0.9892 |
| 20261106 | 1,008 | 13 | 0.9871 |
| 20261109 | 1,551 | 3 | 0.9981 |
| 20261110 | 3,201 | 22 | 0.9931 |
| 20261111 | 2,857 | 53 | 0.9814 |
| 20261112 | 1,478 | 23 | 0.9844 |

14 天全部落在 **0.9617–1.0000**，没有单日主导总体。
首日无退出可比（没有更早持仓带入），末日持仓未退出（`open_position`），
均为结构原因，非缺陷。

> 这张表随样本变更同步过：v0.6.1 换样本前是 0.9712–1.0000（7,000 序列），
> 现为 0.9617–1.0000（4,200 序列）。日度数字已纳入 `per_day` 校验（见 §0）。

### 3.6 参数敏感性

| 时间容差 | 总一致率 | 退出轴一致率 | 冲突数 | 归因首位 |
|---|---|---|---|---|
| 0 分钟 | 0.9892 | 0.8632 | 389 | `exit_eval` 100% |
| 1 分钟（默认） | 0.9912 | 0.8878 | 319 | `exit_eval` 100% |
| 2 分钟 | 0.9919 | 0.8977 | 291 | `exit_eval` 100% |
| 5 分钟 | 0.9930 | 0.9117 | 251 | `exit_eval` 100% |

> **v0.12.8 更正**：这张表原先是四档完全相同（0.9895 / 0.8667 / 379），
> 我当时解释成"退出时刻差是整分钟离散值、比较天然精确"。**那是错的**——
> 真正原因是 `time_tolerance_minutes` **根本没参与判定**：四处判定都写死
> `"match" if gap == 0`，容差只影响配对搜索半径。参数调 0→5 结果不变，
> 不是结论稳，是参数没生效。修复后四档才真正分化（见上表）。
>
> 这也说明主结论数字会随容差变化：默认 1 分钟下是 **0.9912 / 0.8878 / 319**。
> 值本身的变化方向合理——放宽容差让 1–5 分钟的时点抖动不再算冲突。


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
| `exit_eval` | 0.9903 | 93 | `minor_divergence` | 不得 consistent |
| `signal_gain_pct` | 0.9569 | 128 | `minor_divergence` | 不得 consistent |
| `entry_price` | 0.9150 | 840 | `minor_divergence` | 不得 consistent |
| `persistence_bars` | 0.8814 | 1,160 | `minor_divergence` | 不得 consistent |
| `baseline_price` | 0.8804 | 1,217 | `minor_divergence` | 不得 consistent |
| `wait_bars` | 0.8745 | 1,240 | `minor_divergence` | 不得 consistent |
| `breakout_field` | 0.8246 | 2,132 | `minor_divergence` | 不得 consistent |
| `bar_timestamp` | 0.6074 | 3,723 | `inconsistent` | 不得 consistent |

**9/9 通过**（5 天 × 300 标的子集；每个阴性对照产生 93–3,723 条差异）。
注：`t_plus_1` 未列入本表——全期固定标的池下它的效果并入其它轴，单列会误导。复跑：

```bash
python3 scripts/controls_check.py           # 全量，约 3 分钟
python3 scripts/controls_check.py --quick   # 2 日 / 120 标的，约 2 分钟
```

#### 这组对照抓出的三个真实缺陷

**缺陷 A：只看比率的盲区。** 初版 `consistent` 门槛是"一致率 ≥ 0.98"。
`exit_eval` 差一个旋钮产生 503 条真实冲突，一致率 0.9913，被误判为 `consistent`
（数字为 v0.5.0 的 7,000 序列样本；当前样本、容差 1 分钟下是 314 条冲突）。
样本量越大，真差异越容易被"稀释"成高比率。

**缺陷 B：绝对容忍额度太宽。** 加绝对门槛时先设成"≤5 条冲突可忽略"。
结果 60 标的子集下 `exit_eval` 只产生 3 条冲突，又落回 `consistent`。
**"一致"的含义就是没有冲突**，不能给真实冲突留默认额度——现改为必须为 0。

**缺陷 C：空转对照。** 比对样本缩到 **2 天 × 60 标的**后，`exit_eval` 与
`signal_gain_pct` 产生 **0 条差异**，被误判为「判定器正确判 consistent」。

实际上那是**对照根本没生效**——样本太小，这两个旋钮改不动任何一笔交易。
改了旋钮却零差异的对照，什么也证明不了。

修复：`controls_check.py` 增加 `vacuous` 判定，零差异的阴性对照标为未生效
并计入失败；`--quick` 子集提高到 5 天 × 300 标的，使每个旋钮都有空间产生差异。

三条都是对照实验抓出来的，不是凭空想到的。

---

## 4. 归因

```bash
python3 -c "import json;print(json.load(open('output/report.json'))['attribution'])"
```

| 排名 | 旋钮 | 从 → 到 | 解释差异 | 解释率 |
|---|---|---|---|---|
| 1 | `exit_eval` | `bar_close` → `bar_high_low` | 319 | **100%** |

`verdict = single_knob`，`joint_diagnosis.applicable = true`。

### 4.0 这个 100% 有多大的信息量（重要）

合成日志用的 `jev_assumed` 档位，与参考语义 **只差 1 个旋钮**：

| 旋钮 | 参考语义 | 日志档位 |
|---|---|---|
| `exit_eval` | `bar_close` | `bar_high_low` |

其余 17 个旋钮完全一致。

因此「归因锁定 `exit_eval`、解释 100%」在相当程度上是**同义反复**：
我们拿一份只差 `exit_eval` 的日志去测，然后"发现"差异来自 `exit_eval`。

**它能证明的**：链路接通、差异能被正确定位、没有凭空产生别的差异。
**它不能证明的**：多个旋钮同时不同时的定位能力（见 §4.2，那种情形下方法失效）。

要看真实 JEV 日志与我们的语义到底差几个旋钮，必须等真实日志到位。
在拿到之前，不应把"归因 100%"当作强证据引用。

#### 多旋钮时的失效实测

构造不同档位的日志，看归因能否定位：

| 日志侧真实差异 | 差异数 | 归因判定 | 首位旋钮 | 解释率 |
|---|---|---|---|---|
| 仅 `exit_eval` | 319 | `single_knob` | `exit_eval` | **100%** ✓ |
| 仅 `wait_bars` | 2,954 | `single_knob` | `wait_bars` | **100%** ✓ |
| `exit_eval` + `wait_bars` | 3,092 | `multi_knob` | `wait_bars` | 90.1% |

**两个旋钮同时不同时，归因把 `exit_eval` 完全漏掉**——只报 `wait_bars`
解释 92%，而 `exit_eval` 也是真实成因。

原因：`wait_bars` 的影响量大（2,954 条差异），`exit_eval` 的影响被淹没在
它的残差里。单旋钮消融无法分离"两个都改了"的情况——它只能回答
"如果把某一个改对，差异会少多少"，而两个都错时，改对一个仍剩大量差异。

**结论**：`verdict=multi_knob` 时必须人工逐项核对，不能只看 `top_knob`。
报告已在 `joint_diagnosis` 里标注 `applicable=false`。

**解读**：319 条退出差异**全部**由「退出按收盘价还是按触价判定」造成。

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
| 基线（参考语义 vs naive 日志） | 20,767 |
| 只把 `bar_timestamp` 改成 naive 值 | 15,573 |
| 只把 `baseline_price` 改成 naive 值 | 20,841（**增加**） |
| 只把 `t_plus_1` 改成 naive 值 | 23,063（**增加**） |
| 全部改成 naive（等价于日志侧配置） | **0** |

真因确实是多旋钮同时偏移，但单旋钮消融给不出结论。
此时报告输出 `joint_diagnosis.diagnosis = "multiple_knobs_shifted"`，
而不是「`bar_timestamp` 解释 25.0%」这种半吊子结论。

**方法的边界必须与方法的结论一起交付。**

### 4.3 归因机制的两个守卫

| 缺陷 | 症状 | 修复 |
|---|---|---|
| 消融用 `symbols` 视图，主流程用 `by_series` | 两侧可比项口径不一致，真实成因归不出来 | 统一用 `by_series` |
| 一律拒绝"可比项减少"的旋钮 | 真实差异必然改变信号集，被误判为未归因 | 区分「配对消失」与「冲突消失」 |

---

## 4.5 样本外复现（2026-09，与主样本完全不重叠）

```bash
python3 scripts/oos_check.py            # 需凭证；11 天 × 300 只固定标的
```

主结论来自 2026-10-26 至 11-12。只在**一段**行情上成立的结论，可能只是那段
行情的产物。换到完全不相交的 2026-09（11 个交易日）重跑：

| 指标 | 样本内（10–11 月） | 样本外（9 月） | 复现 |
|---|---|---|---|
| condition | 28,754 / 1.0000 | 14,008 / **1.0000** | ✓ |
| signal / wait / entry | 各 1,496 / 1.0000 | 各 678 / **1.0000** | ✓ |
| exit | 2,844 / 0.8878 | 1,222 / **0.8830** | ✓ |
| 合计 | 36,086 / 0.9912 | 17,264 / **0.9917** | ✓ |
| 归因首位 | `exit_eval` 100% | **`exit_eval` 100%** | ✓ |
| 价值 verdict | `negative` | **`negative`** | ✓ |

**结构结论全部复现**：四轴一致率 1.00、退出轴 0.888 左右、归因锁定
`exit_eval`、价值方向为负。

### 但显著性强度没有复现（必须如实说明）

| 项 | 样本内 | 样本外 |
|---|---|---|
| 全样本 Welch p | **1.1×10⁻⁵** | **0.0461** |
| 均值差 | −0.3678% | −0.1960% |
| 样本量 | 27,987 vs 1,422 | 12,050 vs 611 |

> **两个"样本量"别混用**：下表 27,987 vs 1,422 与 12,050 vs 611 是
> **Welch 全样本检验**用的收官收益条数（每边全部已收盘周期）；
> 而 §4.5 上表的 36,086 / 17,264 是**账本可比项**（五轴逐项），
> exit 轴的 2,844 / 1,222 又是配对后的周期数。三者口径不同，
> 数量级差异是正常的，不是数据不一致。

样本外 p=0.0461，距 0.05 仅 **0.0039**。方向一致、但仍显著，
**属边缘证据**，不能与样本内的强结论等同看待。

`oos_check.py` 会把这一项标为未复现（`welch_significance_strength`），
而不是笼统报"全部复现"——方向复现和强度复现是两件事。

---

## 5. 价值评估

对比「显式语义」（当前配置）与「字面直译」（`naive_literal` 基线），
两者共用同一份真实分钟线与前收价，唯一受控变量是语义档位。

### 5.1 配对覆盖率不足，改用全样本检验

| 项 | 值 |
|---|---|
| 基线收官周期 | 27,987 |
| 当前收官周期 | 1,422 |
| 配对周期 | 1,223 |
| **配对覆盖率** | **4.37%** |

覆盖率低于 10% 门槛——配对检验只覆盖重叠部分的少数周期，**不可外推**。

但全样本 Welch 检验**不依赖配对**，不受覆盖率影响：

| 项 | 值 |
|---|---|
| 样本量 | 27,987 vs 1,422 |
| 均值差 | **−0.3678%** |
| 标准误 | 0.0835% |
| t | −4.405 |
| **p** | **1.1×10⁻⁵** |

### 5.2 判定规则（v0.6.1 修正）

| 情形 | 结论依据 |
|---|---|
| 覆盖率 ≥ 10% 且符号检验显著 | 用配对检验 |
| 覆盖率 < 10% 但全样本 Welch 显著 | **用全样本检验** |
| 两者都不满足 | `inconclusive` |

早先的规则是"覆盖率 <10% 一律 inconclusive"，那会把有效的全样本证据一并否掉。
覆盖率闸门只应约束配对检验——全样本检验本来就不受它影响。

### 5.25 拆解：`negative` 到底是谁造成的

`value_assessment` 把「显式语义」与「字面直译」当成两个整体比较，
但两者之间有 **8 个旋钮不同**。结论可能只由其中一个驱动。

```bash
python3 scripts/value_decomposition.py
```

| 配置 | 信号 | 收官 | 均值净收益 |
|---|---|---|---|
| naive（字面直译） | 29,346 | 27,987 | −0.1850% |
| reference（显式语义） | 1,496 | 1,422 | −0.5527% |
| **总差值** | | | **−0.3678%** |

#### 单旋钮贡献（从 naive 出发，只拨一个旋钮到参考值）

| 旋钮 | 信号 | 收官 | Δ均值 |
|---|---|---|---|
| **`t_plus_1`** | 2,553 | 2,419 | **−0.3098%** |
| `cooldown_bars` | 11,564 | 10,872 | −0.0125% |
| `bar_timestamp` | 29,346 | 28,035 | −0.0000% |
| `wait_bars` | 29,346 | 27,947 | +0.0026% |
| `breakout_field` | 19,070 | 18,289 | +0.0208% |
| `entry_price` | 29,346 | 27,947 | +0.0236% |
| `baseline_price` | 27,013 | 25,688 | +0.0241% |
| `persistence_bars` | 10,462 | 10,144 | +0.0276% |

**`t_plus_1` 一个旋钮贡献了总差值的 84.0%。** 其余七个合计仅 −0.0146%，
其中五个还是**正向**的。

#### 决定性检验：参考语义关掉 T+1

| 配置 | 信号 | 收官 | 均值净收益 | 与 naive 比 |
|---|---|---|---|---|
| 参考语义（含 T+1） | 1,496 | 1,422 | −0.5527% | `negative` |
| **参考语义（关 T+1）** | 3,135 | 3,032 | **−0.1009%** | **`positive`（p=0.036）** |

**去掉 T+1，显式语义反而显著优于字面直译。**

#### 机制：T+1 让所有交易变成隔夜持仓

| 配置 | 当日平仓 | 跨日持仓 |
|---|---|---|
| 含 T+1 | **n=0** | n=1,422（均值 −0.5527%） |
| 关 T+1 | n=3,032（均值 −0.1009%） | n=0 |

T+1 打开后，**没有一笔交易能在当日平仓**——全部转成承担隔夜跳空风险的跨日持仓。
这才是收益变差的直接原因。

#### 样本外复现（2026-09，11 天）

同一拆解在完全不相交的日期上重跑：

```bash
python3 scripts/value_decomposition.py \
  --bars-dir /tmp/jev-oos/fixtures/bars \
  --ref-dir /tmp/jev-oos/fixtures/reference
```

| 项 | 样本内（10–11 月） | 样本外（9 月） |
|---|---|---|
| naive 均值 | −0.1850% | −0.2394% |
| ref 均值 | −0.5527% | −0.4355% |
| **总差值** | **−0.3678%** | **−0.1960%** |
| `t_plus_1` 贡献 | −0.3090% | **−0.3000%** |
| `t_plus_1` 占总差值 | 84.0% | **153%** |
| 其余七个合计 | −0.0146%（5 个为正） | **+0.0204%（全部为正）** |
| 关 T+1 后 vs naive | +0.1019%，`positive`（p=0.036） | +0.0152%，`inconclusive`（正向但不显著） |

**样本外结论更强**：只有 `t_plus_1` 是负贡献，其余七个全部为正。
样本外 `t_plus_1` 贡献 153% > 100%，是因为其余旋钮合计为**正**，
把总量往回拉——这不影响"T+1 是唯一负向驱动"这一结论，反而更清楚。

两段完全独立行情给出同一机制，说明这不是某段行情的产物。

**但要如实标注一个差异**：样本外「关 T+1 后优于 naive」是**正向但不显著**
（`inconclusive`），样本内才达到 p=0.036。也就是说：

- 「T+1 是唯一负向驱动」——**两段样本一致**，稳健。
- 「关掉 T+1 后显式语义显著更优」——**样本内成立，样本外只是方向一致**，强度不足。

不能把后半句当作稳定结论引用。

#### 修正后的解读

之前把 `negative` 解读为「把隐式约定显式化会劣化回放收益」，**这个说法是错的**。

准确的说法是：

> **在长仓策略上施加 T+1 约束，会把日内策略变成隔夜策略，收益显著下降。
>  这与"语义是否显式"无关——关掉 T+1 后，显式语义反而更好。**

这是一个**有价值的负结果**，但它指向的是「A 股 T+1 对日内策略的代价」，
而不是「语义对齐没有价值」。两者是完全不同的结论。

### 5.3 结论

**verdict = `negative`。**

显式语义把交易次数砍掉 95%（27,987 → 1,422 个周期），
且这些交易的平均净收益**显著更差**：−0.3678%，p=1.1×10⁻⁵。

这是一个**可靠负结果**：把隐式约定显式化，在这 14 个交易日、300 只
全期固定标的的样本上，没有改善反而劣化了回放收益。

> **与 v0.4.1 的关系**：那一版因 3.74% 覆盖率撤回 `negative`，是对的——
> 当时没有独立的全样本证据。现在补上了 Welch 检验，且它与配对方向一致，
> 结论才重新成立。**结论没变，但证据基础从"不可外推的子样本"换成了"全样本"。**

#### ⚠️ 这个结论对样本长度高度敏感（实测，必须与结论一起交付）

把同一套语义在**连续缩短的时间窗口**上重跑（取最近 N 个交易日）：

| 交易日数 | naive 均值 | ref 均值 | 差值 | p | 方向 |
|---|---|---|---|---|---|
| 14（全部） | −0.1850% | −0.5527% | **−0.3678%** | 1.1e-05 | ref **更差** |
| 7 | −0.1850% | −0.1187% | **+0.1866%** | 0.101 | 反转，不显著 |
| 5 | — | — | **+0.9862%** | <0.001 | ref 更好 |
| 3 | −0.1829% | **+0.8118%** | **+0.9948%** | <0.001 | ref 更好 |
| 2 | — | — | **+1.2516%** | <0.001 | ref 更好 |

**方向在 7 天附近翻转。** 14 天的 `negative` 结论**不能外推**到更短窗口；
反过来，短窗口的 `positive` 也不能外推到这里。

已用官方 `evaluate_naive()` 交叉验证（非手工构造），14 天与 3 天两档结果一致。

**这意味着**：`negative` 是"这 14 个交易日"的结论，不是"显式语义普遍更差"。
把它当成普适判断会出错——在只有 2–5 天的样本上会得到完全相反的答案。

---

## 6. 验证中发现并修复的缺陷（56 项）

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
| 18 | **`consistent` 只看一致率** | 503 条真实冲突（v0.5.0 样本）被稀释成 0.9913，误判一致 | 加绝对冲突门槛，且必须为 0 |
| 19 | **绝对门槛设成"≤5 条"** | 60 标的子集下 3 条冲突又被判一致 | 改为 0；"一致"不接受默认容忍额度 |
| 20 | **代码默认值与 YAML 不一致** | 缺 pyyaml 时静默走合成模式，真实日志接入会读不到 | 逐项对齐 + 降级原因回显到报告 |
| 21 | **标的池逐日变化** | 14 天交集仅 66 只，跨日持仓传递形同虚设 | 取全期 trade_list 交集，固定标的池 |
| 22 | **覆盖率闸门误杀全样本证据** | 全样本 Welch p=7e-06 显著，却被覆盖率规则一并否掉 | 覆盖率只约束配对检验 |
| 23 | **多日 manifest 只 print 不落盘** | 仓库里的 `manifest.json` 长期描述「最后一天」：`bar_count 72000`（实际 1,008,000）、`log_record_count 0`（实际 34,590）、无 `dates`；报告 `provenance.fixture_manifest` 直接对外错报 | `main()` 合并结果写盘 + `test_manifest_describes_the_actual_fixtures` 以磁盘实际内容对账 |
| 24 | **证据文档逐文件用例数与实际不符** | 8 个文件错（如 `test_report.py` 写 24 实为 26） | 按 `pytest --collect-only` 全部改正 + 加防漂移测试 |
| 25 | **README 目录树漏列脚本** | 中文漏 7 个、英文漏 12 个；两份都漏 `validation_evidence.md` | 补全 + `test_readme_trees_list_every_script` |
| 26 | **夹具压缩包不可重现** | `gzip.open(...,"wb")` 把当前时间写进头部，同一份数据每次重建字节流不同 → `fixture_fingerprint` 每次都变，"冻结夹具"名不副实、`compare_baseline` 无故报不可比 | 改用 `GzipFile(..., mtime=0)` + `test_bar_gzip_is_reproducible` |
| 27 | **`config` 静默接受拼错的键** | `input_data` 对未知字段报 `unknown_field`（"刻意不做静默忽略"），`config` 却把 `time_tolerence_minutes: 5` 悄悄合并进去、真正生效的仍是默认值 1，评测跑完看着正常却与预期不符 | `load_config` 校验未知键抛 `ConfigError("unknown_config")`；补 `test_config_rejects_unknown_override_key` 与 `test_config_accepts_every_documented_key` |
| 28 | **`ledger.aggregate.by_axis` 各轴键集不一致** | 文档写"每个轴：match / divergent / one_sided"，但只有 exit 轴出现 `divergent`；按 `row["divergent"]` 取值会在四个轴上 KeyError，`comparable == match + divergent` 也无从校验 | 每轴固定输出 `match`/`divergent`（零也写）+ `test_every_axis_exposes_match_and_divergent_even_when_zero` |
| 29 | **`sign_test_p` 被舍入成 0.0** | n=1,211 时精确二项 p=3.0e-12，`round(p, 6)` 压成 `0.0`，读者会当成"p 恰为 0"——统计上不可能，也会误判证据强度 | 改用 `float(f"{p:.4g}")` 保留科学计数法 + `test_sign_test_p_never_rounds_to_zero` |
| 30 | **契约文档没写 `date`，照文档写的日志被拒收** | `log_contract.md` 通篇未提 `date`，但多日夹具下每条记录必须有它：`ts` 只有 `HH:MM`，加载器无法判断属于哪一天，直接 `LoadError("missing_log_field")`。实测把合成日志剥成"纯契约字段"后，`run()` 立刻失败 | 契约补 `date`（多日必需）+ README/data_access 同步；新增 `test_contract_only_logs_load_end_to_end` |
| 31 | **`validate.py` 对缺 `date` 只报无关 warn** | 同一个缺 `date` 目录，`validate.py` 给的是 `log_symbol_not_in_bars`（"300 个序列不在 K 线里"）且 `ok=true`，完全没指出真正原因，把修复方向指向标的代码而不是日期 | 多日且缺 `date` 时报 `severity=error` + `test_validate_flags_missing_date_in_multiday` |
| 32 | **`time_tolerance_minutes` 根本不参与判定** | 四处判定都写死 `"match" if gap == 0`，容差只影响配对搜索半径。把容差 0→1→2→5 调，结果**一模一样**；文档还把这个"四档一致"解释成"时刻差是整分钟离散值、比较天然精确"——把参数没生效说成了结论。真实影响：201 条退出时间冲突中 65 条差值 ≤1 分钟 | 四处改为 `abs(gap) <= tol_minutes`；`test_verdict_tolerance_actually_changes_verdict` 与 `test_entry_and_signal_axes_honour_tolerance` 锁住。修复后四档才真正分化（0.9895/0.9913/0.9920/0.9931） |
| 33 | **`oos_check.IN_SAMPLE` 硬编码基准会过期** | 修好容差后主样本变成 0.9913/0.8896，但 `IN_SAMPLE` 仍是 0.9895/0.8667，复现判定拿旧基准比新结果 | 同步基准 + `test_oos_check.py` 以 `output/report.json` 反查，主样本一变就红 |
| 34 | **§1.1 / §8 的验收数字长期过期** | 文档写 `verify_claims 27/27`（实际 71/71）、`pytest 113 passed`（实际 222）、`build 54 秒`（实际 31 秒）。这些数字从 v0.7 起就没跟上，而冷克隆验收正是最容易被人照抄的一节 | 按 v0.12.8 冷克隆实测重写；新增 `test_doc_counts_match_actual` 以实际值对账 |
| 35 | **`fetch_data.py` 直接运行必崩** | 漏了 `sys.path.insert(0, REPO_ROOT)`，直接 `python3 scripts/fetch_data.py` 会在 `_client()` 里 `from scripts.credentials import ...` 抛 ModuleNotFoundError。只在真正调用凭证时触发，`--help` 与单元测试都发现不了——按 §8 的复现命令手跑才暴露 | 补 sys.path + `test_fetch_data_can_run_as_script` |
| 36 | **`changed_fields` 不报告 `config_hash` 本身** | `comparable=false` 时 `changed_fields=[]`，而 note 还写着"请确认语义、夹具或日志来源是否变化"——只改了 config_hash 的话读者无从判断哪里变了 | 加 `cur_hash != base_hash` 判断 + `test_changed_config_hash_alone_is_reported` |
| 37 | **README（中/英）「实例」数字严重过时** | 写的是单日小样本（条件 1,576 项、退出 0.80 / 282 项），而仓库夹具是 14 天，读者跑 `build.py` 得到 28,754 / 0.8896，完全对不上。英文版同样错 | 按实际输出重写 + `test_readme_measured_numbers_match_report` |
| 38 | **`openai.yaml` 旋钮清单与代码三处不一致** | 声明 18 个旋钮，而 `REFERENCE_SEMANTICS` 可配置键是 23 个、`KNOB_VALUES` 可消融旋钮是 10 个——18 既不是前者也不是后者，是手抄残留 | 拆成 `x-semantics-knobs`（=23，可配置全集）与 `x-attribution-knobs`（=10，可消融子集），并加测试双向对账 |
| 39 | **`openai.yaml` 版本长期未跟** | `version: 0.1.0` 而 `skill.json` 已是 0.13.0 | 同步 + 测试锁住 |
| 40 | **CI 的 release hygiene 只查文件存在、不查内容** | 社区审核真正看的是：免责声明四个要点、INSTALL 五平台覆盖、SPDX 许可证标识、无占位符、无敏感信息。CI 只做了 `test -f`，内容全对不上也照样绿。 | 扩充 CI 步骤用 Python 断言实际内容；新增 `tests/test_release_compliance.py`（7 例）本地可跑 |
| 41 | **无法判定的 `hit` 被静默当成 False** | `hit: "也许"`、`hit: null` 落在旧白名单之外，被转成 `False`——把"不知道"变"没命中"。下游完全看不出来，属于最危险的一类静默降级 | 白名单外报 `invalid_hit_value`；补 `test_unrecognized_hit_is_an_error_not_false` 与 `test_hit_accepts_common_boolean_spellings` |
| 42 | **标的代码大小写不归一，导致全部对不上** | 日志写 `000001.sz`（或带空格）而 K 线是 `000001.SZ` 时，**一条也配不上**：全部变成 `jev_missing`、`comparable=0`、`match_rate=null`。报告完全看不出真正原因是大小写——表现成"日志与行情毫无关系" | 加载时统一 `strip().upper()`（K 线与日志两处）+ `test_symbol_case_and_whitespace_are_normalized` 等 2 例 |
| 43 | **§9「结论与边界」的数字无人校验** | 上界写 4.20%（实际 4.67%）、ST 交易占比写 2.04%（实际 3.31%）、「容差 0–5 分钟结果不变」在 v0.12.8 修好容差后已不成立。这一节是读者判断能不能信的依据，却一直没进 `verify_claims` | 按实测更正 + `tests/test_conclusion_consistency.py`（5 例）对账 |
| 44 | **`day_open` / `pre_close` 的口径从未写明** | `day_open` 取的是**分钟线首根 open**，不是日线 `open`；`pre_close` 也不总等于前一日 `close`（实测 5/4,200，除权所致）。两者此前都没写进文档，读者自己核对时会把正常的数据源口径当成夹具错误 | `semantics_matrix.md` 与 `data_access.md` 写明两条口径及实测影响面；`tests/test_fixture_integrity.py` 锁住"差异比例 <1% 且 close 严格相等" |
| 45 | **`alignment_conclusion.divergence_items` 报的是"非 match 行"而非"冲突数"** | 同一份报告里 `divergence_items=979,634`，而 `summary.divergence_items` 与 `total.divergent` 都是 314——差三个数量级，读者会以为有近百万条真实冲突。`verify_claims` 没覆盖这个字段，所以长期未被发现 | `divergence_items` 改用真实冲突数；`ledger.divergence_rows` 同步，另设 `non_match_rows` 保留原含义；`tests/test_report_consistency.py`（5 例）锁四处同口径 |
| 46 | **§4.2 多旋钮表在容差修复后整体过期** | `wait_bars` 单独 4,522（实际 2,963）、合并 4,649 / 92.0%（实际 3,096 / 90.3%）。结论本身仍成立（`multi_knob`、漏报 `exit_eval`），但数字全错 | 按实测重算 + `tests/test_multi_knob_docs.py`（含一条 slow 用例在真实夹具复现） |
| 47 | **§4.2 naive 消融表也整体过期** | 文档 7,206 / 5,489 / 7,261 / 8,742，实际 20,774 / 15,581 / 20,848 / 23,063。趋势（单项不解释、改两个反增、全改归零）不变，数值全错 | 按实测重算 + 在 `test_multi_knob_docs.py` 增加 slow 用例复现 |
| 48 | **`verify_claims` 的覆盖不全，同类缺陷反复出现** | 连续多轮都是"改逻辑→别处数字过期"：`divergence_items` 口径、`inline_truncated`、归因细项都没被检查。根因是核对项靠人工逐条加 | 内部一致性检查从 7 条扩到 13 条：`divergence_items` 四处同口径、`non_match_rows` 分解、归因 `explained <= baseline`、inline 上限与截断标记。总数 71 → 77 |
| 49 | **有轴零可比时仍判 `consistent`——"没验证"冒充"一致"** | 日志只写 `condition`、无任何 `signal`/`plan` 时，`signal`/`wait`/`entry`/`exit` 四轴 `comparable=0`，但总体因 2 条 condition 相符即判 `consistent`。exit 是**最关键的一轴**，完全没比过却说一致 | 加"每轴必须有可比项"门槛，未满足则 `inconclusive` 并在 `reason` 列出未验证的轴；补 2 例测试 |
| 50 | **价值结论 `reason` 里 p 值仍用 `round(p,6)`** | 字段层面的 `sign_test_p` 在 v0.12.6 已修，但 `reason` 文字里还留着 `round(p_value, 6)`：p=3.0e-12 会显示成 `p=0.0`。同一份报告里字段正确、文字却是错的 | 新增 `_fmt_p()` 统一格式化 + `test_value_reason_never_shows_p_as_zero` |
| 51 | **`jev_missing` 写成 1,633,358，超过总根数 1,008,000** | 一个**逻辑上不可能**的数字：单边缺失行数不可能多于该轴总根数。实际 979,246。这类错误只要做一次量级检查就能发现，但此前无人校验 | 按实测更正 + `verify_claims` 新增「`non_match_rows <= total_rows`」与「条件轴覆盖率与各轴一致」两条检查（77 → 79） |
| 52 | **离线审计把"上界"报成"已知项的最大值"** | 离线时 ST/停牌为 `null`（未核验），上界却取涨跌停的 **2.40%**，verdict 输出「未建模状态占比 2.40%，属可接受」。而在线实测上界是 **4.67%**——等于把"一半没查"说成"风险可接受"。这正是文档反复强调的"不能把未核验当 0"，却在聚合层漏了 | 有任一未核验项时上界置 `null`、级别 `unknown`，并给出 `unverified_components` 与 `known_components_max`；原测试断言"不为 None"正是固化了错误行为，已改 |
| 53 | **T+1 下强平推迟分支重复累加 `bars_held`，掩盖 30 条真实差异** | `force_exit_time` 分支在 `_exit_or_defer` 返回 False 后**没有 return**，循环继续；下一根仍过 `force_time`，再次进入该分支并累加 `bars_held`。14:45→15:00 的 15 根让它从 30 涨到 **360**（另有 34 笔 328–344）。次日 `held = bars_held + j + 1` 立刻超 max_hold，于是这些仓位**在次日第一根被当作"持有超时"平仓** | 推迟后立即 `return cycle`（与止损/止盈分支一致）+ `test_force_exit_defer_does_not_accumulate_bars_held` |
| 54 | **上一缺陷导致归因误判为 `single_knob`** | 修复缺陷 53 后，退出差异由 314 增至 **344**，`exit_eval` 解释率由 100% 降至 **91.3%**，归因判定由 `single_knob` 改为 **`multi_knob`**——此前那 30 条差异被错误地"解释掉了"。主数字随之变化：总一致率 0.9913→**0.9905**、退出轴 0.8896→**0.8790** | 全部文档数字与 `validation_claims.json` 按实测更新（claims 一次拦下 16 处偏差） |
| 55 | **修复重放后忘了重新生成夹具日志** | 改好 `bars_held` 缺陷后，`fixtures/logs/` 仍是旧代码产物。对齐时出现 **30 条"无法归因"** 的退出差异（日志判 max_hold、重放判 stop_loss），归因被迫降级 `multi_knob`——**不是语义分歧，是夹具过期**。重新生成后归因恢复 `single_knob` 100% | 重新生成日志 + `test_fixture_logs_match_current_replayer`（逐条比对，实测能抓出篡改） |
| 56 | **价值结论的样本长度敏感性从未记录** | `negative` 只在 14 天样本上成立。实测缩短到 7 天方向就**翻转**、3 天 ref 均值变成 **+0.9948%**（正面）。文档此前把 `negative` 当作该样本的可靠结论交付，没有说明它不可外推到更短窗口 | §5.3 新增敏感性子节（14/7/5/3/2 天实测）、§9 列为未验证；`test_value_conclusion_sensitivity_is_documented` + slow 用例复现翻转 |

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
| Python | 3.12.12（主）、3.9.6（系统自带，实测通过） |
| panda-data | 1.0.6（仅夹具再生） |
| 三方依赖 | 无（对齐与回放为纯标准库；`python3 -S` 实测通过） |
| 全量对齐 | 约 31 秒（4,200 序列 × 240 根，1,008,000 根） |
| 单元测试 | 约 160 秒（275 passed, 1 skipped） |

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
- 五轴全部可比：条件/信号/等待/入场一致率 1.00，退出轴 0.8878，总体 0.9912（容差 1 分钟）；
- 319 条退出差异被 `exit_eval` 单一旋钮完整解释（100%），
  大偏差的 JEV 侧时刻全部指向次日首根触价，与逐条证据一致；
- 14 天分日一致率见 §3.5，不由单日主导；
- 未建模状态占比已量化：ST 4.67%、触涨停 1.76%、触跌停 0.64%，
  上界 4.67%（`moderate`），ST 标的实际产生 3.31% 的交易（§3.4）；
- 容差 0/1/2/5 分钟下总一致率为 0.9892 / 0.9912 / 0.9919 / 0.9930，
  **随容差单调上升**（并非「结果不变」；见 §3.6 的 v0.12.8 更正说明）；
- 显式语义与字面直译的整体差异 **84.0% 由 `t_plus_1` 一个旋钮驱动**；
  关掉 T+1 后显式语义反而显著更优（p=0.036）。正确结论是
  「T+1 对日内策略有显著代价」，不是「语义显式化无价值」（见 §5.25）；
- **样本外复现**（2026-09，11 天）：结构结论全部复现，但显著性强度
  明显减弱（p=0.0461，边缘）——见 §4.5；
- 判定器有真实区分度：9 组阳性/阴性对照全部按预期判定（§3.6）。

**方法边界（已验证并记录）**：
- 单旋钮消融仅在「少数旋钮不同」时有效；多旋钮同时偏移时输出
  `multiple_knobs_shifted`，不给 `top_knob` 结论（见 §4.2）

**未验证**：
- **JEV 实际语义**——日志为合成数据，对齐 verdict 恒为 `inconclusive`；
- T+0 市场、多空双向、除权除息、停牌、涨跌停场景；
- **价值结论的跨样本稳定性**——已实测：缩短到 7 天以下方向会**翻转**
  （见 §5.3 的敏感性子节）。`negative` 只是这 14 天的结论，不可外推。

**结论据此成立的范围**：仅在 `applicability` 声明的 A 股分钟级单/多日场景，
且日志按 `log_contract.md` 提供记录时。

**要让对齐 verdict 变成 `consistent` / `inconsistent`**：把真实 JEV 日志按
`log_contract.md` 放进 `fixtures/logs/`，重跑 `build.py`。代码无需改动。