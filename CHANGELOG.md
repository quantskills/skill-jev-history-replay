# CHANGELOG

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