# JEV 日志契约 / Log Contract

本文件定义 `fixtures/logs/*.jsonl` 的字段。真实 JEV 日志按此格式转换后即可直接接入，
回放器与对齐器无需改动。

---

## 1. 通用要求

- 格式：JSON Lines（每行一个对象），文件后缀 `.jsonl`；也接受 `.json`（数组）与 `.json.gz`。
- 时间字段 `ts`：`HH:MM`、`HHMMSS`、`HH:MM:SS` 或完整 `YYYY-MM-DD HH:MM:SS` 均可，
  加载时统一归一化为 `HH:MM`。
- 只读：本 skill 从不修改日志文件。
- 同一标的同一 `kind` 的记录按 `ts` 排序；同一时刻多条按出现顺序保留。

### 顶层通用字段

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `ts` | str | ✅ | 记录时刻 |
| `kind` | str | ✅ | `condition` / `signal` / `plan` / `fill` |
| `symbol` | str | ✅ | 标的代码，须与 K 线文件中的代码字符串完全一致 |
| `date` | str | **多日必需** | 交易日 `YYYYMMDD`。**多日夹具下必需**，单日可省略 |

> ⚠️ **多日模式必须有 `date`**。`fixtures/bars/` 里有多个交易日时，加载器无法
> 从 `ts`（只有 `HH:MM`）推断记录属于哪一天，直接抛
> `LoadError("missing_log_field")`。单日夹具可省略，此时由文件名补全。
>
> 合成日志会在每条记录上附带 `date`、`_synthetic`、`cross_day` 等内部字段；
> 这些**不是契约要求**，真实日志不需要写。只要满足本表字段即可接入。

---

## 2. `condition` —— 条件判断记录

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `hit` | bool | ✅ | 该时刻条件是否成立 |
| `reference` | float | 推荐 | 突破参照价（窗口内最高价等） |
| `baseline` | float | 推荐 | 涨幅基准价 |
| `gain_pct` | float | 推荐 | 相对基准的涨幅（小数，0.01 = 1%） |

**记录习惯说明（重要）**：真实系统通常只在**状态翻转**时写这条记录，
而不是每根 K 线都写。本 skill 把"重放有判断、日志无记录"标为 `jev_missing`，
作为**单边缺失**单独统计，不计入一致率分母。这不是语义分歧。

若日志侧确实每根都写，一致率会覆盖全部 K 线，信息量更大，两者都可以。

---

## 3. `signal` —— 信号记录

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `signal` | str | ✅ | 信号类型，如 `buy` |
| `wait_bars` | int | 推荐 | 该信号后计划空过的根数 |

信号轴按 `ts` 与重放信号做**带容差的一对一贪心配对**（默认容差 ±1 分钟）。

---

## 4. `plan` —— 计划（入场/退出意图）

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `plan` | str | ✅ | 计划类型，如 `enter` |
| `entry_time` | str | 推荐 | 计划入场时刻 |
| `entry_price` | float | 推荐 | 计划入场价 |
| `wait_bars` | int | 推荐 | 信号到入场空过的根数 |
| `exit_time` | str | 推荐 | 计划/实际退出时刻 |
| `exit_reason` | str | 推荐 | `take_profit` / `stop_loss` / `max_hold` / `force_exit_time` / `end_of_data` |
| `net_return_pct` | float | 可选 | 该周期净收益（小数） |
| `qty` | int | 可选 | 计划数量 |

`plan` 记录用于 `wait` / `entry` / `exit` 三轴。缺 `wait_bars` 时等待轴不可比，
缺 `entry_price` 时价格比较跳过，缺 `exit_reason` 时只比时点。

---

## 5. `fill` —— 成交回执

| 字段 | 类型 | 必需 | 说明 |
|---|---|---|---|
| `side` | str | ✅ | `buy` / `sell` |
| `price` | float | 推荐 | 成交价 |
| `qty` | int | 可选 | 成交数量 |
| `status` | str | 可选 | `filled` / `partial` / `rejected` |

当前版本的账本以 `plan` 为对齐主依据；`fill` 保留用于后续扩展
（成交价与计划价的差异分析）。`fill` 记录缺失不影响现有五轴。

---

## 6. 来源标记

合成日志的每条记录带 `"_synthetic": true`。报告据此判定 `log_source`：

- 任一条记录带该标记 → `synthetic`
- 全都不带 → `actual`

也可以用配置 `log_source: actual|synthetic` 强制覆盖（仅用于调试），
但正式报告不应使用强制覆盖。

**为什么要记录级标记**：如果靠目录名或人工声明判断来源，
一份合成日志被改名放进 `fixtures/logs/` 就会被误当成真实数据。
标记跟着数据走，改名无效。

---

## 7. 最小可用示例

```jsonl
{"ts":"09:41","kind":"condition","symbol":"600519.SH","hit":true,"reference":1435.0,"baseline":1439.0,"gain_pct":0.0021}
{"ts":"09:42","kind":"condition","symbol":"600519.SH","hit":true,"reference":1435.0,"baseline":1439.0,"gain_pct":0.0035}
{"ts":"09:42","kind":"signal","symbol":"600519.SH","signal":"buy","wait_bars":1}
{"ts":"09:44","kind":"plan","symbol":"600519.SH","plan":"enter","entry_time":"09:44","entry_price":1445.0,"wait_bars":1,"exit_time":"10:15","exit_reason":"take_profit"}
{"ts":"09:44","kind":"fill","symbol":"600519.SH","side":"buy","price":1445.5,"qty":600,"status":"filled"}
```

---

## 7.5 字段名不一致时用适配器

真实系统的字段名通常与本文契约不同。不要手改日志，也不要靠猜——
用 `scripts/adapt_logs.py` 显式声明映射：

```bash
python3 scripts/adapt_logs.py --map-example            # 看模板
python3 scripts/adapt_logs.py --src raw/ --dst adapted/
python3 scripts/validate.py --logs-dir adapted/
```

它会把 `timestamp→ts`、`code→symbol`、`matched→hit`、`action→signal`
等常见同义词自动映射，并把 `1/0`、`"true"/"false"` 规范成真正的 `bool`。
**适配后仍缺必需字段会直接报错**，不会让缺陷数据进入对齐。

> 注意 `hit: "false"` 这类字符串：直接加载会因 `bool("false") == True`
> 把"未命中"读成"命中"。适配器会正确转成 `False`。

---

## 8. 契约校验

接入前先跑：

```bash
python3 scripts/validate.py --bars-dir fixtures/bars --logs-dir path/to/your/logs
```

输出区分两类问题：

| severity | 含义 | 处理方式 |
|---|---|---|
| `error` | 必需字段缺失 / 格式非法 | 必须修正，否则无法对齐 |
| `warn` | 推荐字段缺失 | 可继续，但对应轴会退化 |

`ok: false` 表示存在 `error`，此时不应解读对齐结论。