# JEV 盯盘条件与历史回放语义对齐

核对 JEV 记录的盯盘判断与一个可复现的历史回放器是否语义一致，并把差异逐项归因。

## ⚠️ 免责声明

- **仅供研究与教育用途**：本 skill 是量化研究的对齐与复盘工具，不构成任何形式的投资建议、理财建议或交易推荐。
- **不保证收益**：所有输出为历史数据上的模拟回放结果，不代表实际交易表现，也不预测未来。
- **风险边界**：回放按规则价一次性撮合，不建模排队、部分成交、流动性与滑点分布；结论仅适用于 `applicability` 段声明的范围内。使用者应自行承担全部研究与应用风险。
- **非官方背书**：本项目为 QuantSkills 社区项目，未经专业审计或监管机构认证，不代表任何第三方官方结论。

## 它解决什么问题

同一条盯盘规则、同一份 K 线，JEV 侧记录的信号时点和自己写的回放器经常对不上。
差异往往不在规则本身，而在那些**没人写下来、但代码必须做**的解释选择：

- 分钟线时间戳代表这一分钟的**开始**还是**结束**？
- "突破前 20 根高点"里，20 根**含不含当前根**？
- "信号后等待"是等 1 根，还是在下一根开盘就买？
- 退出按**收盘价**还是按**触价**判定？
- A 股 T+1 到底有没有生效？

这些选择每一个都会改变逐根判断和成交价，但看代码和看文档都很难发现。
本 skill 把它们全部变成**命名的旋钮**，然后：

1. 用显式语义跑一遍重放；
2. 把 JEV 日志按同一时间轴对齐；
3. 输出逐项差异账本（条件/信号/等待/入场/退出五轴）；
4. 逐个旋钮做消融，回答"到底是哪个选择造成了这处差异"。

## 目录结构

```
├── SKILL.md                        ← 技能设计书
├── README.md                       ← 本文件
├── README.en.md                    ← English version
├── LICENSE                         ← GPL-3.0
├── INSTALL.md                      ← 多平台安装指南
├── requirements.txt                ← 运行依赖（仅夹具生成需要）
├── requirements-dev.txt            ← 测试依赖
├── skill.json                      ← Skill 元数据
├── CHANGELOG.md                    ← 版本记录
├── agents/                         ← 运行时适配器
│   ├── cursor-rule.mdc
│   ├── portable-loader.md
│   └── openai.yaml
├── config/
│   └── replay_config.yaml          ← 语义旋钮与判定阈值
├── scripts/
│   ├── build.py                    ← 标准入口 run(input_data, config=None)
│   ├── run_eval.py                 ← 编排：加载 → 重放 → 对齐 → 归因 → 报告
│   ├── semantics.py                ← 语义旋钮注册表与哈希
│   ├── data_loader.py              ← K线/日志读取、缺口检测、序列键
│   ├── replayer.py                 ← 确定性重放器
│   ├── aligner.py                  ← 五轴差异账本
│   ├── attribution.py              ← 单旋钮消融归因
│   ├── log_synth.py                ← 合成日志（无真实日志时）
│   ├── adapt_logs.py               ← 外部日志字段映射适配
│   ├── report.py                   ← 报告组装与判定规则
│   ├── metrics.py                  ← Wilson 区间 / 符号检验
│   ├── trade_audit.py              ← 逐笔价格/算术反查
│   ├── knob_efficacy.py            ← 旋钮接线有效性核验
│   ├── value_decomposition.py      ← T+1 等旋钮的收益拆解
│   ├── compare_baseline.py         ← 冻结基线 freeze/compare/list
│   ├── credentials.py              ← 凭证加载（唯一实现）
│   ├── fetch_data.py               ← 拉取分钟 K 线（需凭证）
│   ├── build_fixtures.py           ← 生成发布用夹具
│   ├── validate.py                 ← 日志契约校验
│   ├── oos_check.py                ← 样本外复现（需凭证）
│   ├── data_quality_audit.py       ← 未建模状态占比
│   ├── controls_check.py           ← 判定器区分度对照
│   ├── verify_claims.py            ← 文档数字对账
│   ├── env_check.py                ← 环境自检
│   └── config.py                   ← 配置合并
├── tests/                          ← 单元测试（纯合成数据，秒级）
├── references/
│   ├── api_guide.md                ← 接口与字段
│   ├── log_contract.md             ← 日志契约
│   ├── semantics_matrix.md         ← 语义旋钮全表与取值含义
│   ├── data_access.md              ← 数据接入说明
│   └── validation_evidence.md      ← 验收证据与缺陷记录
├── fixtures/                       ← 已发布夹具（确定性）
│   ├── bars/                       ← 分钟 K 线
│   ├── reference/                  ← 前收与当日 OHLC
│   ├── logs/                       ← JEV 侧日志（当前为合成）
│   └── manifest.json               ← 指纹与生成参数
└── output/                         ← 运行结果（.gitignore 排除）
```

## 快速开始

```bash
# 1. 环境自检（无需凭证）
python3 scripts/env_check.py

# 2. 检查夹具与日志契约
python3 scripts/validate.py

# 3. 完整对齐评测（无需凭证）
python3 scripts/build.py

# 4. 单元测试
pip install -r requirements-dev.txt
python3 -m pytest tests/ -v
```

## 怎么读报告

先看三个地方，顺序不能反：

1. **`provenance.log_source`** — 是 `actual` 还是 `synthetic`。
   合成日志下的对齐结论恒为 `inconclusive`，这是刻意的：它只能证明链路跑通。
2. **`ledger.aggregate.by_axis`** — 五个轴各自的一致率。
   某一轴显著低，就是问题所在（例如只看 `exit` 一致率 0.80，说明退出判定口径不同）。
3. **`attribution.ranked`** — 哪个旋钮解释了这些差异。
   报告的 `explained_rate` 要求"换旋钮后可比项不减少"才算解释；
   一个把配对全部打散的旋钮不会得到高分。

### 实例

本地 300 只标的、单日 240 根分钟线的实测结果：

| 指标 | 值 |
|---|---|
| 条件轴一致率 | 1.00（1,576 项） |
| 信号轴一致率 | 1.00（168 项） |
| 等待轴一致率 | 1.00（168 项） |
| 入场轴一致率 | 1.00（168 项） |
| 退出轴一致率 | 0.80（282 项） |
| 归因结论 | `single_knob`：`exit_eval` 解释 100% 的差异 |

即：条件、信号、等待、入场四段完全对得上，唯一分歧在"退出按哪个价判定"。

## 一个重要口径

日志侧常常**只在状态翻转时**写一条 `condition` 记录。于是重放器逐根都有判断，
日志却只有少数几根有记录。这类 `jev_missing` 是**记录习惯差异**，不是语义冲突。

因此本 skill 把 `one_sided` 单列，不放进一致率分母。
把它混进去会得到"一致率只有 2%"这种毫无意义、且会误导决策的数字。

## 数据来源

- 分钟 K 线与前收价：`panda_data` 的 `get_stock_min` / `get_stock_daily`，
  **仅夹具生成阶段调用**，见 `references/data_access.md`
- JEV 日志：调用方提供的只读文件
- 对齐与回放：纯标准库，不访问任何外部服务

## 替换成真实 JEV 日志

把真实日志按 `references/log_contract.md` 的字段放进 `fixtures/logs/`，重跑 `build.py` 即可。
回放器、对齐器、归因器都无需改动。若日志缺少可选字段，对应轴会退化为不可比，
而不是编造一致——报告里会明确写出来。

> **多日夹具下每条记录必须带 `date`（`YYYYMMDD`）**。`ts` 只有 `HH:MM`，
> 加载器无法据此判断记录属于哪一天，缺 `date` 会直接抛
> `LoadError("missing_log_field")`。单日夹具可省略。
> 合成日志附带的 `_synthetic` / `cross_day` 等字段是内部标记，真实日志不需要写。

## 许可

GPL-3.0-only，见 `LICENSE`。

本项目为 QuantSkills 社区项目，未经专业审计。使用者应自行评估适用性。