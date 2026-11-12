# JEV Watch-Condition / History-Replay Semantic Alignment

Check whether JEV's recorded watch conditions and a reproducible historical replayer mean the same thing, and attribute every difference to a specific interpretation choice.

## ⚠️ Disclaimer

- **Research and education only.** This skill is an alignment and replay tool for quantitative research. It is not investment advice, financial advice, or a trading recommendation of any kind.
- **No performance guarantee.** All output is simulated replay over historical data. It does not represent actual trading results and does not predict future returns.
- **Risk boundary.** Replay assumes a single full fill at a rule-derived price. It does not model queueing, partial fills, liquidity, or slippage distribution. Conclusions hold only within the scope declared in the `applicability` block. Users bear all risk of research and application.
- **No official endorsement.** This is a QuantSkills community project. It has not been professionally audited or certified by any regulator, and does not represent any third party's official conclusion.

## What Problem It Solves

Given one watch rule and one set of bars, JEV's recorded signal times and a hand-written replayer often disagree. The cause is usually not the rule but the **interpretation choices nobody wrote down**:

- Does a minute timestamp mark the **start** or the **end** of that minute?
- In "breaks the prior 20-bar high", does the window **include the current bar**?
- Is "wait after signal" one bar, or an immediate next-open fill?
- Is exit evaluated on the **close** or on the **touched price**?
- Did A-share T+1 actually apply?

Each of these changes the per-bar decision and fill price, and none of them is visible from either the code or the prose alone. This skill turns all of them into **named knobs**, then:

1. Replays once under explicitly declared semantics;
2. Aligns the JEV log on the same time axis;
3. Emits a per-item difference ledger across five axes;
4. Ablates one knob at a time to answer "which choice caused this difference".

## Directory Layout

```
├── SKILL.md / README.md / README.en.md
├── LICENSE                         ← GPL-3.0
├── INSTALL.md
├── requirements.txt / requirements-dev.txt
├── skill.json / CHANGELOG.md
├── agents/                         ← Runtime adapters
├── config/replay_config.yaml       ← Knobs and decision thresholds
├── scripts/
│   ├── build.py                    ← Standard entry: run(input_data, config=None)
│   ├── run_eval.py                 ← Orchestration
│   ├── semantics.py                ← Knob registry and hash
│   ├── replayer.py                 ← Deterministic replayer
│   ├── aligner.py                  ← Five-axis difference ledger
│   ├── attribution.py              ← Single-knob ablation
│   ├── log_synth.py                ← Synthetic log fallback
│   ├── report.py                   ← Report assembly and verdict rules
│   ├── metrics.py                  ← Wilson interval, sign test
│   ├── compare_baseline.py         ← freeze / compare / list
│   ├── fetch_data.py               ← Minute bars (credentials required)
│   ├── build_fixtures.py           ← Published fixture builder
│   ├── validate.py                 ← Log contract validator
│   └── env_check.py                ← Environment self-check
├── tests/                          ← Unit tests (synthetic data, sub-second)
├── references/
│   ├── api_guide.md
│   ├── log_contract.md
│   ├── semantics_matrix.md
│   └── data_access.md
└── fixtures/                       ← Published, deterministic fixtures
```

## Quick Start

```bash
python3 scripts/env_check.py     # no credentials needed
python3 scripts/validate.py      # check the fixture / log contract
python3 scripts/build.py         # full alignment run
python3 -m pytest tests/ -v      # unit tests
```

Python API:

```python
from scripts.build import run

report = run({
    "bars_dir": "fixtures/bars",
    "logs_dir": "fixtures/logs",
    "semantics": {"wait_bars": 2, "entry_price": "signal_close"},
})
print(report["alignment_conclusion"])
```

## Reading the Report

Read these three, in this order:

1. **`provenance.log_source`** — `actual` or `synthetic`. Under `synthetic`, the alignment verdict is always `inconclusive` by design: synthetic logs only prove the pipeline runs, they cannot characterise JEV.
2. **`ledger.aggregate.by_axis`** — per-axis match rate. A low axis is where the problem is.
3. **`attribution.ranked`** — which knob explains the differences. A knob only scores if the number of comparable items does not shrink; a knob that simply destroys the pairing scores zero.

### Measured Example

300 symbols, one trading day, 240 minute bars each:

| Axis | Match rate | Items |
|---|---|---|
| condition | 1.00 | 1,576 |
| signal | 1.00 | 168 |
| wait | 1.00 | 168 |
| entry | 1.00 | 168 |
| exit | 0.80 | 282 |
| Attribution | `single_knob` — `exit_eval` explains 100% | |

Condition, signal, wait and entry agree completely; the only disagreement is which price the exit is evaluated on.

## One Important Accounting Rule

Log systems usually write a `condition` record **only when state flips**, while the replayer evaluates every bar. Those `jev_missing` rows are a **recording-habit difference**, not a semantic conflict.

This skill therefore reports `one_sided` separately and keeps it out of the match-rate denominator. Blending them in produces a "2% match rate" that is meaningless and would misdirect the investigation.

## Data Access

- Bars and previous close: `panda_data` `get_stock_min` / `get_stock_daily`, **fixture generation only** — see `references/data_access.md`
- JEV logs: read-only files supplied by the caller
- Alignment and replay: pure standard library, no external service

## Plugging In Real JEV Logs

Drop real logs into `fixtures/logs/` following `references/log_contract.md`, then rerun `build.py`.
The replayer, aligner and attribution need no changes. If a field is missing, the corresponding axis becomes non-comparable and the report says so rather than fabricating agreement.

## License

GPL-3.0-only. See `LICENSE`.

Community project, not professionally audited. Users must assess applicability themselves.