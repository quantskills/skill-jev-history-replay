# skill-jev-history-replay

JEV watch-condition / history-replay semantic alignment.

## Overview

Given one watch rule and one set of minute bars, JEV's recorded times and a hand-written replayer often disagree. The cause is usually an interpretation choice nobody wrote down: does the timestamp mark bar start or bar end, does the breakout window include the current bar, is the wait one bar or an immediate next-open fill, is the exit judged on close or on the touched price.

This skill makes every such choice a named knob, replays deterministically, aligns against the JEV log, and reports a per-item difference ledger plus a single-knob ablation that says which choice explains the gap.

## Architecture

```
bars + JEV logs
      │
      ├─ replay(semantics) ──────────┐
      │                              ▼
      └─────────────────────── aligner (5 axes) ──▶ ledger.jsonl
                                            │
                                            ├──▶ attribution (single-knob ablation)
                                            ├──▶ value_assessment (vs literal baseline)
                                            └──▶ report.json
```

## Directory Structure

```
skill-jev-history-replay/
├── SKILL.md
├── README.md / README.en.md
├── LICENSE                     ← GPL-3.0
├── INSTALL.md
├── requirements.txt / requirements-dev.txt
├── skill.json
├── CHANGELOG.md
├── agents/
├── config/replay_config.yaml
├── scripts/
│   ├── build.py                ← run(input_data, config=None)
│   ├── run_eval.py
│   ├── semantics.py
│   ├── replayer.py
│   ├── aligner.py
│   ├── attribution.py
│   ├── log_synth.py
│   ├── report.py
│   ├── metrics.py
│   ├── compare_baseline.py
│   ├── fetch_data.py
│   ├── build_fixtures.py
│   ├── validate.py
│   ├── env_check.py
│   └── config.py
├── tests/
├── references/
└── fixtures/
```

## Quick Start

Work through the pre-flight checklist (`## 前置检查` in `SKILL.md`, mirrored in
`agents/openai.yaml` under `x-preflight`) before anything else: stop at the first
failing item and report only what is missing.

```bash
python3 scripts/env_check.py
python3 scripts/validate.py
python3 scripts/build.py
```

## Agent Integration

```python
import sys
sys.path.insert(0, "/path/to/skill-jev-history-replay")
from scripts.build import run

report = run({
    "bars_dir": "fixtures/bars",
    "logs_dir": "fixtures/logs",
    "semantics": {"bar_timestamp": "bar_end", "wait_bars": 1},
})
print(report["alignment_conclusion"], report["attribution"])
```

## Reading results

1. `provenance.log_source` — `synthetic` means the alignment verdict is `inconclusive` by construction
2. `ledger.aggregate.by_axis` — per-axis match rate; the weak axis is the problem
3. `attribution.ranked` — which knob explains the divergence

`one_sided` rows are kept out of the match-rate denominator: sparse logging is a recording habit, not a semantic conflict.

## Tests

```bash
pip install -r requirements-dev.txt
python3 -m pytest tests/ -v
```

Tests use in-memory synthetic data only; no network, no credentials.

## Data access (fixture regeneration only)

Fetch through PandaData MCP, then `python3 scripts/fetch_data.py --date <date> --from-mcp <dir>`:

```
mcp__pandadata__auth_status → mcp__pandadata__search_methods
  → mcp__pandadata__get_method_doc → mcp__pandadata__call_pandadata
```

| Need | Method |
|---|---|
| Minute bars | `get_stock_min` |
| Daily bars / previous close | `get_stock_daily` |
| Previous trading day | `get_prev_trade_date` |
| Trading universe | `get_trade_list` |
| ST / suspended | `get_st_list` / `get_suspended_list` |

```json
{"method": "get_stock_min",
 "params": {"symbol": ["600519.SH"], "start_date": "20261112", "end_date": "20261112"},
 "preview_rows": 2000}
```

Responses are truncated by byte limit; fetch one day per call with at most ~50
symbols. `scripts/mcp_source.py` rejects truncated results instead of using them.

## Dependencies

- Python 3.10+
- No third-party package at runtime; PyYAML optional
- pytest (dev)

Read-only alignment. Never connects to a live account or places orders.
Research and educational use only. Not investment advice.