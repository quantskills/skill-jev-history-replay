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

## Dependencies

- Python 3.10+
- panda-data==1.0.6 (fixture generation only)
- PyYAML (optional)
- pytest (dev)

Read-only alignment. Never connects to a live account or places orders.
Research and educational use only. Not investment advice.