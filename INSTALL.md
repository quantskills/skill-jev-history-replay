# Multi-Platform Install Guide

This package contains one evaluation skill:

- `skill-jev-history-replay`: JEV watch-condition / history-replay semantic alignment.

---

## Requirements

- Python 3.10+
- `pip install -r requirements-dev.txt` for tests (pytest + PyYAML)
- The runtime and the alignment run need **no third-party package and no login**. To regenerate fixtures, an MCP-capable AI client fetches data (see below)

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
# 0. Work through the pre-flight checklist (## 前置检查) in SKILL.md first.
python3 scripts/env_check.py     # expect ok=true, blocked=0
python3 scripts/validate.py      # expect ok=true
python3 -m pytest tests/ -v      # expect all pass
python3 scripts/build.py         # writes output/report.json + output/ledger.jsonl
```

`env_check.py` needs neither network nor login — alignment is fully offline.

---

## Regenerating fixtures (optional, needs an MCP client)

Data is fetched by the **AI reading this skill** through the PandaData MCP
server (`pandadata`, Streamable HTTP). Login is **OAuth performed by your MCP
client** — this skill stores no account identifier, password or token.

Call order:

```
mcp__pandadata__auth_status → mcp__pandadata__search_methods
  → mcp__pandadata__get_method_doc → mcp__pandadata__call_pandadata
```

If `auth_status` reports not signed in, complete the OAuth browser flow in your
client and retry; there is nothing to configure inside this skill.

Example call:

```json
{"method": "get_stock_min",
 "params": {"symbol": ["600519.SH"], "start_date": "20261112",
            "end_date": "20261112"},
 "preview_rows": 2000}
```

Write each raw response to `<dir>/<date>/<method>.json`, then:

```bash
python3 scripts/fetch_data.py --date 20261112 --from-mcp <dir>
python3 scripts/build_fixtures.py --date 20261112 --from-mcp <dir> --universe 300
```

> ⚠️ Responses are truncated by byte limit (measured: 240 minute rows returned
> as 180). Fetch narrow ranges — one day per call, ~50 symbols or fewer.

See `references/data_access.md` for the full contract (methods, parameters,
on-disk layout, truncation handling, error codes).