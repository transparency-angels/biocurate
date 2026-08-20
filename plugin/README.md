# co-scientist Agent Plugin

Drive the AI co-scientist research engine from Claude Code, Codex CLI, or any
other agent that reads Agent Skills and MCP.

This is an [Agent Plugins 1.0](https://agent-plugins.org/specification)
directory: one `plugin.json`, one `mcp.json`, and a `skills/` folder. The same
directory works in every conformant client, so there is no Claude-only or
Codex-only copy to keep in sync.

## What it gives the agent

**One MCP server**, `co-scientist`, with fifteen tools covering the whole
session surface: start, resume, pause, abort, status, list, read hypotheses and
reviews, record a hypothesis, record a review, record a tournament match, add
feedback, read the final overview, estimate cost, and check the install.

**Seven skills**, which carry the judgement the tools cannot:

| Skill | What it does |
|---|---|
| `running-research-sessions` | Frames the goal, gates on cost, starts and monitors a session |
| `reading-research-overviews` | Reads the ranked output honestly, with the known failure modes checked |
| `reviewing-hypotheses` | Reviews one hypothesis against the rubric and records it |
| `ranking-hypotheses` | Runs a head-to-head debate and records the Elo match |
| `evolving-hypotheses` | Combine, simplify, feasibility, out-of-box, with parents recorded |
| `benchmarking-models` | Cross-model Elo bench and how to read it |
| `grounding-claims` | Checks that citations say what they are claimed to say |

## The rule that makes it work

The engine keeps all state: Elo, the task queue, dedup, embeddings, the token
budget, termination. The plugin does not reimplement any of it.

Everything an agent produces goes back in through the same repositories the
engine's own agents write to. A review Claude writes by hand and a review the
Reflection agent writes are the same row in the same table, counted the same
way. That is what keeps the tournament coherent and the meta-review complete.

The skills say this in plain terms: **output that is not recorded does not
exist.** An agent that describes a review in chat without calling
`review_record` has produced nothing the system can use.

## Install

The plugin talks to a local co-scientist install. Set that up first, from the
repository root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
co-scientist init
co-scientist doctor          # must report a ready backend
```

`doctor` has to pass before the plugin is useful. It needs either an API key
(OpenRouter by default) or a subscription CLI backend.

### Codex CLI

```bash
codex plugins install ./plugin
```

Or point at a catalogue scope: Codex searches local project, user config,
workspace, and remote registry, with local scopes shadowing remote ones.

### Claude Code

Copy or symlink the skills and register the MCP server:

```bash
ln -s "$PWD/plugin/skills/"* ~/.claude/skills/
claude mcp add co-scientist -- co-scientist mcp-server
```

### Other clients

Any client that reads Agent Plugins 1.0 loads the directory directly. Any
client that reads SKILL.md and MCP separately can take `skills/` and
`mcp.json` on their own.

## The `command` in mcp.json

`mcp.json` launches `co-scientist mcp-server`, which assumes the console script
is on `PATH`. If you installed into a virtualenv that the agent does not
activate, change the entry to an absolute path:

```json
{
  "command": "/path/to/repo/.venv/bin/co-scientist",
  "args": ["mcp-server"]
}
```

or run the module directly:

```json
{
  "command": "/path/to/repo/.venv/bin/python",
  "args": ["-m", "co_scientist.mcp.session_server"]
}
```

## Read-only installs

On a shared machine, or anywhere you do not want an agent able to spend budget
on its own:

```json
{
  "command": "co-scientist",
  "args": ["mcp-server", "--read-only"]
}
```

`session_start` and `session_resume` then refuse with an explanation, and
everything else keeps working. The same effect comes from setting
`COSCI_ALLOW_START=0` in the server's `env`.

## Configuration

The server reads the same config as the CLI. Point it at a specific file with
`COSCI_CONFIG` in the `mcp.json` `env` block. Other variables:

| Variable | Effect |
|---|---|
| `COSCI_CONFIG` | Path to an extra TOML config to overlay |
| `COSCI_ALLOW_START` | `0` refuses `session_start` and `session_resume` |
| `COSCI_START_TIMEOUT` | Seconds to wait for a spawned run to register, default 120 |

## Validating a change

```bash
python scripts/validate_plugin.py
python -m pytest co_scientist/tests/unit/test_plugin.py co_scientist/tests/unit/test_session_mcp.py
```

The validator checks spec conformance: permitted manifest fields, transport
types, skill frontmatter, name and directory agreement, body length, and that
every relative link resolves and stays one level deep.

The tests check the part a validator cannot: that no skill tells the agent to
call an MCP tool or CLI command that does not exist, and that the recording
discipline is actually stated in the skills that write.

## Companion skills

[google-deepmind/science-skills](https://github.com/google-deepmind/science-skills)
covers genomics, structural biology, cheminformatics and database lookups, and
installs alongside this plugin without conflict. The engine can also load those
skills directly as tools; see `[science_skills]` in the config.

## Costs

A session spends real money or subscription quota, and the engine runs
detached, so it keeps spending after the conversation ends. The
`running-research-sessions` skill gates every start on an explicit go-ahead
after showing `estimate_cost`. Keep that gate if you fork the skill.
