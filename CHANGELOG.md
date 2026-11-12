# CHANGELOG

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