# 数据接入说明 / Data Access

**核心结论先说**：

> 对齐与回放阶段**完全离线**：只读本地 `fixtures/`，不访问任何外部服务，
> clone 后直接 `python3 scripts/build.py` 即可跑。
>
> 需要新数据时，取数由**阅读本 skill 的 AI 通过 PandaData MCP 工具完成**，
> 脚本只消费 agent 落盘的 JSON。skill 内不含账号、密码、token 或服务地址。

---

## 1. 流水线总览

```
① agent 调 MCP 取数                ② 落盘 JSON                 ③ 生成夹具           ④ 离线回放
mcp__pandadata__call_pandadata  →  /tmp/mcp/<date>/*.json  →  fetch_data.py      →  build.py
   auth_status                         get_stock_min.json       --from-mcp <dir>     replayer
   search_methods                      get_stock_daily.json                          aligner
   get_method_doc                      get_prev_trade_date.json                      attribution
   call_pandadata                      get_trade_list.json                           report
```

| 阶段 | 谁执行 | 是否联网 |
|---|---|---|
| ① 取数 | 阅读本 skill 的 AI（MCP 客户端） | 是（MCP + OAuth） |
| ② 落盘 | 同一个 AI，把 `call_pandadata` 返回原样写文件 | 否 |
| ③ 生成夹具 | `scripts/fetch_data.py --from-mcp` / `build_fixtures.py` | 否 |
| ④ 对齐回放 | `scripts/build.py` | 否 |

脚本侧**没有**任何 HTTP 客户端、取数组件依赖或凭证读取。

---

## 2. MCP 工具与调用顺序

服务器名 `pandadata`（Streamable HTTP，OAuth 登录，由客户端配置）。
模型可见的工具：

| 工具 | 用途 |
|---|---|
| `mcp__pandadata__auth_status` | 确认 OAuth 登录有效 |
| `mcp__pandadata__search_methods` | 按关键词找方法名 |
| `mcp__pandadata__get_method_doc` | 读方法签名、参数、返回列 |
| `mcp__pandadata__call_pandadata` | **真正取数** |

固定顺序：

```
auth_status  →  search_methods  →  get_method_doc  →  call_pandadata
```

`call_pandadata` 的参数：

```json
{"method": "get_stock_min", "params": {...}, "preview_rows": 2000}
```

`preview_rows` 只控制**本地预览**行数（0–2000），不改变服务端实际返回量。
返回信封：

```json
{"ok": true, "method": "get_stock_min", "params": {...},
 "result": ..., "request_id": "..."}
```

---

## 3. 数据需求 → 方法 → 参数 对照表

| 数据需求 | 方法 | 参数 | 返回形态 |
|---|---|---|---|
| 分钟 K 线 | `get_stock_min` | `symbol`(list), `start_date`(必填), `end_date`(必填), `fields`, `time_zone`, `frequency` | dataframe：`symbol, datetime, date, minute, open, high, low, close, volume, amount` |
| 日线与前收 | `get_stock_daily` | `symbol`(list), `start_date`(必填), `end_date`(必填), `fields`, `indicator`, `st` | dataframe：`date, symbol, open, high, low, close, pre_close, volume, amount, limit_up, limit_down, trade_status, name` |
| 前一交易日 | `get_prev_trade_date` | `date`(必填), `exchange`(可选), `n`(可选) | `{"date": "YYYYMMDD"}` |
| 当日可交易标的池 | `get_trade_list` | `date`(必填), `exchange`(可选) | `[{"date": "...", "symbol": "..."}]` |
| ST 名单 | `get_st_list` | `start_date`, `end_date`(必填), `is_st` | dataframe：`symbol, date, is_st` |
| 停牌名单 | `get_suspended_list` | `start_date`, `end_date`(必填), `is_suspended` | dataframe：`symbol, date, is_suspended` |

> `date=` 而不是 `nature_date=`。`get_trade_list` 的 `exchange='SH'`
> 一次取回 A 股全市场（含深市代码）；传 `SZ` 会报错。

---

## 4. 可复制的 MCP 调用示例

### 4.1 分钟线（**一天一取，窄区间**）

```json
{
  "method": "get_stock_min",
  "params": {
    "symbol": ["600519.SH", "000001.SZ"],
    "start_date": "20261112",
    "end_date": "20261112",
    "fields": ["symbol", "datetime", "date", "minute",
               "open", "high", "low", "close", "volume", "amount"],
    "time_zone": "Asia/Shanghai",
    "frequency": "1m"
  },
  "preview_rows": 2000
}
```

### 4.2 日线（含前一交易日，供 `pre_close` 使用）

```json
{
  "method": "get_stock_daily",
  "params": {
    "symbol": ["600519.SH", "000001.SZ"],
    "start_date": "20261111",
    "end_date": "20261112",
    "fields": ["symbol", "date", "open", "high", "low", "close", "pre_close"]
  },
  "preview_rows": 2000
}
```

### 4.3 前一交易日

```json
{"method": "get_prev_trade_date",
 "params": {"date": "20261112", "exchange": "SH", "n": 1}}
```

### 4.4 当日标的池

```json
{"method": "get_trade_list",
 "params": {"date": "20261112", "exchange": "SH"},
 "preview_rows": 2000}
```

### 4.5 ST / 停牌名单（整段日期一次取）

```json
{"method": "get_st_list",
 "params": {"start_date": "20261026", "end_date": "20261112", "is_st": true},
 "preview_rows": 2000}
```

```json
{"method": "get_suspended_list",
 "params": {"start_date": "20261026", "end_date": "20261112", "is_suspended": true},
 "preview_rows": 2000}
```

---

## 5. ⚠️ 截断：必须按窄日期区间分批

**实测：一次取 240 根分钟线，只回 180 行**，信封里是

```json
{"type": "dataframe", "row_count": 180, "total_rows": 240,
 "truncated": true, "truncation_reasons": ["byte_limit"]}
```

`preview_rows` 调大也不能解决——它只控预览。正确做法：

- 分钟线**一次一天、标的数尽量少**（建议 ≤ 50 只/次）；
- 标的更多时按代码段分批，分别落盘到不同目录，再合并；
- 拿到 `truncated: true` 时**不要落盘当完整数据**，缩小区间重取。

`scripts/mcp_source.py` 会检查 `truncated` 与 `row_count < total_rows`，
两种情况都抛 `MCPDataError(code="truncated_result")`，不会静默接受。

---

## 6. 落盘目录约定

```
<dir>/<date>/get_stock_min.json          # 必须是一天的窄区间结果
<dir>/<date>/get_stock_daily.json        # 覆盖前一交易日 + 当日
<dir>/<date>/get_prev_trade_date.json    # {"date": "..."}
<dir>/<date>/get_trade_list.json         # 当日标的池（可选）
<dir>/get_st_list.json                   # 整段日期（可选）
<dir>/get_suspended_list.json            # 整段日期（可选）
```

也可平铺为 `<dir>/<method>.<date>.json` 或 `<dir>/<method>.json`。
文件内容可以是**完整信封**，也可以直接是 `result`。

之后：

```bash
python3 scripts/fetch_data.py --date 20261112 --from-mcp <dir>
```

---

## 7. 解析器与错误码

`scripts/mcp_source.py`（纯标准库）负责：

| 校验 | 错误码 |
|---|---|
| 文件不存在 | `missing_mcp_file` |
| 不是合法 JSON | `invalid_mcp_json` |
| 信封 `ok=false` | 透传服务端 `code`（如 `auth_required`） |
| 缺少 `result` | `invalid_envelope` |
| 被截断 / 行数不一致 | `truncated_result` |
| 缺必需列 | `missing_columns` |
| 行宽与 columns 不符 | `ragged_rows` |
| 空表（未显式允许） | `no_data` |

---

## 8. 已发布夹具（默认路径，完全离线）

| 文件 | 内容 |
|---|---|
| `fixtures/bars/{date}.json.gz` | 300 只 × 240 根分钟线 × 14 日 |
| `fixtures/reference/{date}.json` | 每标的前收与当日 OHLC |
| `fixtures/logs/{date}.jsonl` | JEV 侧日志（**合成**） |
| `fixtures/manifest.json` | 指纹、生成参数、`logged_profile`、数据质量审计 |

### 口径备注（实测，随夹具一起冻结）

- 分钟线时间戳是**该分钟结束时刻**：09:31 覆盖 09:30–09:31；每日 240 根。
  这是 `semantics.bar_timestamp` 默认 `bar_end` 的依据。
- `pre_close` 不总等于前一交易日的 `close`（实测 5/4,200 条），源于除权除息
  或数据源自身的 `pre_close` 口径。夹具忠实复制返回值，不做二次调整。
- 集合竞价会让日线 `open` 与分钟线首根 `open` 不同（实测 2/4,200 条，
  最大差 1.385%）。`baseline_price=day_open` 取**分钟线首根**。

### 合成日志不是 JEV 真实输出

`fixtures/logs/*.jsonl` 由 `scripts/log_synth.py` 按 `jev_assumed` 档位、
基于**同一份真实分钟线**生成。因此：

- 对齐结论恒为 `inconclusive`，报告在 `provenance.log_source` 标 `synthetic`；
- 真实 JEV 日志到位后，**直接替换 `fixtures/logs/` 即可**，
  回放器/对齐器/归因器都不用改；此时 `log_source` 自动变 `actual`。
- **多日夹具要求每条记录带 `date`（`YYYYMMDD`）**，否则
  `LoadError("missing_log_field")`。

字段契约见 `references/log_contract.md`。若字段名与契约不同，
先用 `scripts/adapt_logs.py` 显式映射，不要手改日志。

---

## 9. 为什么对齐阶段完全离线

```
MCP 取数（agent）  ──▶  落盘 JSON  ──▶  fetch_data.py / build_fixtures.py  ──▶  fixtures/*
                                                                                    │
                                                                                    ▼
build.py / run_eval  ──(只读本地文件)──▶  replayer → aligner → attribution → report
```

- `replayer.py` / `aligner.py` / `attribution.py` / `metrics.py` 纯标准库
- CI 不安装任何取数组件，测试在分钟内跑完
- clone 后直接 `python3 scripts/build.py` 即可，无需登录、无需网络

---

## 10. 复现命令

```bash
# 完整对齐（离线）
python3 scripts/build.py
python3 scripts/verify_claims.py

# 环境与契约自检
python3 scripts/env_check.py
python3 scripts/validate.py

# 数据质量审计（无 MCP 落盘目录时自动只做 OHLC 推断）
python3 scripts/data_quality_audit.py --from-mcp <dir>
python3 scripts/data_quality_audit.py --offline

# 再生夹具（先让 agent 通过 MCP 取数并落盘）
python3 scripts/fetch_data.py --date 20261112 --from-mcp <dir>
python3 scripts/build_fixtures.py --date 20261104,...,20261112 --from-mcp <dir> --universe 300

# 样本外复现（同样先取数落盘）
python3 scripts/oos_check.py --from-mcp <dir>
```

---

## 11. 客户端登录

PandaData MCP 走 **OAuth** 登录，登录在 MCP 客户端完成（Claude Code 首次
调用 `mcp__pandadata__auth_status` 时会引导浏览器授权）。本 skill 不保存、
不传递任何凭证；`auth_status` 返回未登录时，由客户端重新授权后重试。