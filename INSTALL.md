# Multi-Platform Install Guide

This package contains one evaluation skill:

- `skill-jev-history-replay`: JEV watch-condition / history-replay semantic alignment.

---

## Requirements

- Python 3.10+
- `pip install -r requirements-dev.txt` for tests (pytest + PyYAML)
- `panda-data==1.0.6` only if you regenerate fixtures (see `scripts/build_fixtures.py`); the alignment run itself needs no external dependency and no credentials

---

## Claude Code

```bash
# macOS / Linux
cp -R skill-jev-history-replay ~/.claude/skills/
```

```powershell
# Windows (PowerShell)
New-Item -ItemType Directory -Force "$HOME\.claude\skills"
Copy-Item ".\" "$HOME\.claude\skills\skill-jev-history-replay" -Recurse -Force
```

Invoke:

```
/skill-jev-history-replay
```

Or import from any agent:

```python
import sys
sys.path.insert(0, "~/.claude/skills/skill-jev-history-replay")
from scripts.build import run

report = run({"bars_dir": "fixtures/bars", "logs_dir": "fixtures/logs"})
```

---

## Codex (OpenAI)

Use `agents/openai.yaml` as the tool definition, or register manually:

```json
{
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "skill_jev_history_replay",
        "description": "Align JEV watch conditions with a deterministic replayer. Emits a five-axis difference ledger (condition, signal, wait, entry, exit) and a single-knob ablation that attributes divergences to explicit interpretation choices.",
        "parameters": {
          "type": "object",
          "properties": {
            "bars_dir": {
              "type": "string",
              "description": "Minute bar directory. Defaults to fixtures/bars."
            },
            "logs_dir": {
              "type": "string",
              "description": "JEV log directory. Missing or empty triggers synthetic mode."
            },
            "output_dir": {
              "type": "string",
              "description": "Output directory. Defaults to output/."
            },
            "semantics": {
              "type": "object",
              "description": "Semantics knob overrides, e.g. {\"wait_bars\": 1, \"entry_price\": \"next_open\"}."
            },
            "run_attribution": {
              "type": "boolean",
              "description": "Run single-knob ablation. Defaults to true."
            }
          }
        }
      }
    }
  ]
}
```

---

## Cursor

Copy `agents/cursor-rule.mdc` into your project's `.cursor/rules/` directory.

---

## Hermes / OpenClaw

Use `agents/portable-loader.md` as the loader description. Both platforms can also consume
`agents/openai.yaml` as the tool schema.

```bash
hermes register ./skill-jev-history-replay --loader agents/portable-loader.md
```

---

## Verifying the install

```bash
cd skill-jev-history-replay
python3 scripts/env_check.py     # expect ok=true, blocked=0
python3 scripts/validate.py      # expect ok=true
python3 -m pytest tests/ -v      # expect all pass
python3 scripts/build.py         # writes output/report.json + output/ledger.jsonl
```

`env_check.py` reports missing `panda_data` as a warning, not a blocker — alignment never needs it.

---

## Regenerating fixtures (optional, needs credentials)

```bash
export PANDA_DATA_USERNAME=<username>
export PANDA_DATA_PASSWORD=<password>
export PANDA_DATA_BASE_URL=<service_base_url>

python3 scripts/build_fixtures.py --date 20261112 --universe 300
```

See `references/data_access.md` for the full data-access contract.