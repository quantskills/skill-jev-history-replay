# 数据接入说明 / Data Access

给需要复现或扩展本 skill 的其他 AI 阅读。**核心结论先说**：

> 评测执行阶段**不需要任何凭证、不访问任何外部服务**。
> 只有「再生夹具」这一步才调用 panda_data，且已生成的夹具已随仓库发布。

---

## 1. 通道一：panda_data Python SDK（仅再生夹具时使用）

| 项 | 值 |
|---|---|
| 包名 / 版本 | `panda-data==1.0.6`（见 `requirements.txt`，已固定） |
| Python | `>=3.10` |
| 认证入口 | `panda_data.init_token(username=..., password=..., base_url=...)` |
| SDK 服务根 | `https://pandadata.pandaaiquant.com`（SDK 默认值） |
| 调用位置 | `scripts/fixture_generator.py` |
| 使用时机 | **仅** `python3 scripts/fixture_generator.py` |

### 凭证：只从环境变量读取，绝不写入仓库

| 环境变量 | 含义 |
|---|---|
| `PANDA_DATA_USERNAME` | Pandadata 账号用户名 |
| `PANDA_DATA_PASSWORD` | 明文密码（SDK 内部自行哈希） |
| `PANDA_DATA_BASE_URL` | 服务地址（可选，缺省用 SDK 默认） |

```bash
export PANDA_DATA_USERNAME=<your_username>
export PANDA_DATA_PASSWORD=<your_password>
python3 scripts/fixture_generator.py --date 20251110
```

**兼容回退**：上游 SDK 也认 `DEFAULT_USERNAME` / `DEFAULT_PASSWORD` / `JAVA_SERVICE_BASE_URL`。本 skill 优先读 `PANDA_DATA_*`，缺失时回退到这三个历史变量（见 `_env_first()`）。

**本地凭证文件**：若环境变量不全，会尝试读 `~/.pandadata/pandadata.env`（`KEY=VALUE` 每行一条），用 `setdefault` 注入进程环境——同样不落盘到仓库。

**缺失时行为**：`_try_init_pandadata()` 返回 `None`，生成器退化为「仅手工夹具」模式并给出 warning，**不抛异常**。这是刻意的：保证无凭证环境仍可跑通。

### 实际用到的接口

| 接口 | 用途 |
|---|---|
| `get_suspended_list(start_date, end_date, is_suspended=True)` | 取停牌标的 |
| `get_st_list(start_date, end_date, is_st=True)` | 取 ST 标的 |
| `get_trade_list(start_date, end_date)` | 取在售股票列表 |
| `get_stock_daily(...)` | 取日线，构造涨跌停场景 |

> 契约以 [`quantskills/skill-pandadata-api`](https://github.com/quantskills/skill-pandadata-api) 为准（固定 commit `3f573a41`）。参数名、字段名以该仓库为准，不要凭记忆写。

---

## 2. 通道二：合成夹具（占多数，不需要凭证）

`fixtures/generated/` 共 **109** 个夹具，来源分布：

| 来源 | 数量 | 标记 |
|---|---|---|
| panda_data 真实数据 | 26 | 带 `"_source": "pandadata_*"` 字段 |
| 手工合成 | 83 | 无 `_source` 字段 |

### 真实数据衍生（26 个）

| 文件 | 量 | `_source` | 真实部分 |
|---|---|---|---|
| `suspended_*.json` | 9 | `pandadata_suspended` | 标的代码来自真实停牌列表 |
| `st_*.json` | 10 | `pandadata_st` | 标的代码来自真实 ST 列表 |
| `limit_up_*.json` | 7 | `pandadata_limit_up` | 标的代码来自真实交易列表 + 日线 |

> 注意：**代码是真实的，价格与盈亏是构造的**。例如 `suspended_000407_SZ_20251110.json` 用了真实停牌代码 `000407.SZ`，但 `price: 5.0`、`pnl_pct: -0.02` 是合成值——目的是稳定触发特定约束，而非还原当日行情。

### 手工合成（83 个）

按要触发的约束命名，覆盖 12 条硬约束的边界：

```
t_plus_1_*.json        10   当日买入锁定
position_limit_*.json  10   超仓位上限
force_close_*.json     10   强平窗口内买入
refusal_*.json         10   缺行情必须拒单
limit_up_down_*.json   10   涨跌停禁单
st_filter_*.json       10   ST 过滤
capital_check_*.json    5   资金不足
price_deviation_*.json  5   价格偏离（软约束）
suspended_*.json       10   停牌过滤
hk_normal / future_margin / crypto_t0   3   跨市场样例
```

这些是**确定性构造**的边界值，用于精确验证判定器，不依赖任何外部数据。

---

## 3. 为什么评测阶段完全离线

```
fixture_generator.py  ──(panda_data)──▶  fixtures/generated/*.json
                                              │
                                              ▼
run_eval.py / build.py  ──(只读本地 JSON)──▶  replay_engine
```

- `constraints_evaluator.py`、`replay_engine.py`、`injector.py` **不 import panda_data**，纯标准库
- `env_check.py` 在缺 panda_data 时报告 `warn` 而非 `blocked`——正是因为评测不需要它
- CI 不安装 panda_data，10 秒内跑完 166 个测试

**所以**：clone 之后直接 `python3 scripts/build.py` 就能跑，无需申请账号。

---

## 4. 给其他 AI 的三条操作约定

1. **不要试图把凭证写进代码、配置或文档**。只能用环境变量或 `~/.pandadata/pandadata.env`。仓库的 `.gitignore` 不保护凭证文件，泄露风险由使用者自负。
2. **不要假设真实价格**。带 `_source: pandadata_*` 的夹具，只有代码来自真实数据，数值是构造的。要真实行情请自行通过 `get_stock_daily_post` 获取。
3. **接口以契约为准**。`skill-pandadata-api` 的 commit `3f573a41` 是唯一权威来源。SDK 签名曾发生过变化（本 skill 的 v0.2 就把 `date=` 改成了 `start_date=`/`end_date=`），凭记忆调用容易失败。

---

## 5. 复现命令

```bash
# 完整评测（无需凭证）
python3 scripts/build.py

# 仅手工夹具（无需凭证）
python3 scripts/fixture_generator.py --manual-only

# 再生真实数据衍生夹具（需要凭证）
export PANDA_DATA_USERNAME=...
export PANDA_DATA_PASSWORD=...
python3 scripts/fixture_generator.py --date 20251110
```