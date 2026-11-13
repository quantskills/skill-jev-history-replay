# 数据接入说明 / Data Access

**核心结论先说**：

> 对齐与回放阶段**不需要任何凭证、不访问任何外部服务**，只读本地 fixture。
> 只有「重新生成夹具」和「样本外复现」两步才调用 `panda_data`。

---

## 1. 调用 panda_data 的脚本

| 脚本 | 用途 | 何时调用 |
|---|---|---|
| `scripts/fetch_data.py` | 拉取指定日期的分钟 K 线与前收价 | 手动取数 |
| `scripts/build_fixtures.py` | 生成整套夹具（K线 + 前收 + 合成日志 + 质量审计） | 重建夹具 |
| `scripts/oos_check.py` | 样本外复现（自动拉数 → 建夹具 → 评测） | 复现检验 |
| `scripts/data_quality_audit.py` | 量化未建模状态占比；**无凭证时自动降级为离线模式** | 审计 |

其余脚本（`build.py` / `validate.py` / `adapt_logs.py` / `trade_audit.py` /
`knob_efficacy.py` / `value_decomposition.py` / `compare_baseline.py` /
`verify_claims.py` / `controls_check.py` / `env_check.py`）**不 import panda_data**。

### 依赖

| 项 | 值 |
|---|---|
| 包名 / 版本 | `panda-data==1.0.6`（`requirements.txt` 已固定） |
| Python | `>=3.10` |
| 认证入口 | `panda_data.init_token(username=..., password=..., base_url=...)` |
| 凭证解析 | `scripts/credentials.py`（**唯一实现**） |

---

## 2. 凭证

| 环境变量 | 别名 | 含义 |
|---|---|---|
| `PANDA_DATA_USERNAME` | `DEFAULT_USERNAME` | 账号 |
| `PANDA_DATA_PASSWORD` | `DEFAULT_PASSWORD` | 密码 |
| `PANDA_DATA_BASE_URL` | `JAVA_SERVICE_BASE_URL` | 服务地址 |

```bash
export PANDA_DATA_USERNAME=<username>
export PANDA_DATA_PASSWORD=<password>
export PANDA_DATA_BASE_URL=<base_url>
```

**兼容本地文件**：`~/.pandadata/pandadata.env`，每行 `KEY=VALUE` 或
`export KEY=VALUE`。值可以带引号（`export X="abc"`），`credentials.py` 会自动去引号。

> **踩过的坑**：曾直接把值 strip 进 URL，引号被带进去，panda_data 报
> `unknown url type: "https`。现已统一到 `scripts/credentials.py`，
> 并校验 `base_url` 必须以 `http://` / `https://` 开头。

**缺失时行为**：抛 `CredentialError`，调用方转成结构化 JSON 并返回**非零退出码**。
不会静默降级成"没有数据"。

---

## 3. 实际用到并被验证的接口

| 接口 | 签名要点 | 用途 |
|---|---|---|
| `get_stock_min` | `symbol=[...], start_date, end_date, fields=[...]` | 单日分钟 K 线，240 根/标的 |
| `get_stock_daily` | `symbol=[...], start_date, end_date, fields=[...]` | 前收 `pre_close` 与当日 OHLC |
| `get_prev_trade_date` | `date='YYYYMMDD', exchange='SH', n=1` | 前一交易日 |
| `get_trade_list` | `date='YYYYMMDD', exchange='SH'` | 当日可交易标的池 |
| `get_st_list` | `start_date, end_date, is_st=True` | ST 名单 |
| `get_suspended_list` | `start_date, end_date, is_suspended=True` | 停牌名单 |

> **实测口径（2026-11-13，panda-data 1.0.6）**
> - 分钟线时间戳是**该分钟结束时刻**：09:31 覆盖 09:30–09:31；每日 240 根。
>   这是 `semantics.bar_timestamp` 默认 `bar_end` 的依据。
> - `get_trade_list` 的 `exchange` 只接受 `SH` / `HK` / `US`，传 `SZ` 报 `100006`；
>   A 股全市场用 `exchange='SH'` 一次取回（含深市代码）。
> - **`pre_close` 不总等于前一交易日的 `close`**：实测 5/4,200 条序列不同，
>   源于除权除息或数据源自身的 pre_close 口径。夹具忠实复制 panda 返回值，
>   不做二次调整。若你的基准定义是"前一交易日收盘价"，需要自行处理除权。
> - **集合竞价会让日线 `open` 与分钟线首根 `open` 不同**：实测 2/4,200 条，
>   最大差 1.385%。本 skill 的 `baseline_price=day_open` 取**分钟线首根**，
>   详见 `semantics_matrix.md`。参考语义用 `prev_close`，不受影响。
> - `get_stock_min` 支持一次传多标的（实测 300 标的、72,000 根，约 3 秒）。
> - `get_prev_trade_date` 在 1.0.6 中是 `date=` 而非 `nature_date=`。

> 契约以 [`quantskills/skill-pandadata-api`](https://github.com/quantskills/skill-pandadata-api)
> 为准。SDK 签名曾变更，凭记忆调用容易失败。

---

## 4. 已发布夹具（默认路径，不需要凭证）

| 文件 | 内容 |
|---|---|
| `fixtures/bars/{date}.json.gz` | 300 只 × 240 根分钟线 × 14 日 |
| `fixtures/reference/{date}.json` | 每标的前收与当日 OHLC |
| `fixtures/logs/{date}.jsonl` | JEV 侧日志（**合成**） |
| `fixtures/manifest.json` | 指纹、生成参数、`logged_profile`、数据质量审计 |

### 合成日志不是 JEV 真实输出

`fixtures/logs/*.jsonl` 由 `scripts/log_synth.py` 按 `jev_assumed` 档位、
基于**同一份真实分钟线**生成。因此：

- 对齐结论恒为 `inconclusive`，报告在 `provenance.log_source` 标 `synthetic`；
- 真实 JEV 日志到位后，**直接替换 `fixtures/logs/` 即可**，
  回放器/对齐器/归因器都不用改；此时 `log_source` 自动变 `actual`。
- **多日夹具要求每条记录带 `date`（`YYYYMMDD`）**，否则
  `LoadError("missing_log_field")`。这条曾只在代码里要求、文档没写，
  照文档准备的真实日志会被直接拒收。

字段契约见 `references/log_contract.md`。若字段名与契约不同，
先用 `scripts/adapt_logs.py` 显式映射，不要手改日志。

---

## 5. 为什么对齐阶段完全离线

```
fetch_data / build_fixtures  ──(panda_data)──▶  fixtures/*
                                                    │
                                                    ▼
build.py / run_eval  ──(只读本地文件)──▶  replayer → aligner → attribution → report
```

- `replayer.py` / `aligner.py` / `attribution.py` / `metrics.py` 纯标准库
- CI 不安装 panda_data，测试 80 秒内跑完
- clone 后直接 `python3 scripts/build.py` 即可，无需账号

---

## 6. 复现命令

```bash
# 完整对齐（无需凭证）
python3 scripts/build.py
python3 scripts/verify_claims.py

# 环境与契约自检
python3 scripts/env_check.py
python3 scripts/validate.py

# 数据质量审计（无凭证时自动离线）
python3 scripts/data_quality_audit.py

# 再生夹具（需要凭证）
export PANDA_DATA_USERNAME=...
export PANDA_DATA_PASSWORD=...
export PANDA_DATA_BASE_URL=...
python3 scripts/build_fixtures.py --date 20261104,...,20261112 --universe 300

# 样本外复现（需要凭证）
python3 scripts/oos_check.py
```