---
name: running-research-sessions
description: Starts, monitors, pauses, resumes and steers an AI co-scientist research session that generates and Elo-ranks novel scientific hypotheses from a research goal. Use when the user asks to run the co-scientist, start a research session, generate hypotheses for a scientific goal, check on a running session, or steer one with feedback. Produces a session id and a tournament-ranked set of hypotheses.
---

# Running research sessions

The engine takes a research goal and runs Generation, Reflection, an Elo
tournament, Evolution and Meta-review until a termination criterion fires. It
holds all state in SQLite. Your job is to frame the goal well, set the budget,
launch it, and report progress honestly.

A session takes minutes to hours and spends real money or subscription quota.
Never start one without an explicit go-ahead on the budget.

## Workflow

Copy this checklist and tick as you go:

```
- [ ] 1. Check the install (doctor)
- [ ] 2. Sharpen the research goal with the user
- [ ] 3. Show the cost estimate and get a go-ahead
- [ ] 4. Start the session
- [ ] 5. Poll until it finalises
- [ ] 6. Hand over the overview
```

### 1. Check the install

Call `co-scientist:doctor`. If `backend_ready` is false, stop and report
`backend_detail`. Nothing downstream works without a backend.

If `embeddings` says "hash fallback", say so once: dedup and tournament
pairings will be weaker. It is not a blocker.

### 2. Sharpen the goal

A vague goal produces vague hypotheses, and the tournament cannot fix that. A
good goal names three things:

- the **system** (organism, material, dataset, population)
- the **phenomenon** to explain or the **outcome** to achieve
- the **kind of answer** wanted (mechanism, target, intervention, design)

Bad: "research gut bacteria and IBD"

Good: "Propose testable mechanisms by which a specific gut bacterium drives
ileal inflammation in Crohn's disease, prioritising mechanisms that can be
tested in existing mouse models within one year."

Show the rewritten goal and let the user correct it before spending anything.

Constraints that are preferences rather than part of the question go in
`preferences`: preferred model systems, assays available, things already tried,
lines of work to avoid.

### 3. Estimate and confirm

Call `co-scientist:estimate_cost`. Report `total_usd` against `budget_usd`, and
surface `warning` verbatim if present. Then ask for a go-ahead. If the user
wants it cheaper, the levers are `budget_usd`, `wall_clock_seconds` and
`n_initial`; the deeper knobs (`max_ideas`, `max_matches_per_idea`) live in
config and change the estimate.

On a subscription CLI backend the dollar estimate is a proxy for quota, not a
bill. Say which one applies.

### 4. Start

Call `co-scientist:session_start` with `goal`, and with `preferences`,
`n_initial`, `budget_usd`, `wall_clock_seconds` as agreed. It returns a
`session_id`, a `pid` and a `log_path`, and the engine runs detached: it
survives this conversation ending.

Give the user the session id and tell them `co-scientist report <id>` prints the
overview later without an agent in the loop.

### 5. Poll

Call `co-scientist:session_status`. Poll on a slow cadence, a few minutes
apart, not in a tight loop. Between polls, do other work or stop and let the
user come back.

Read the fields like this:

| Field | What it tells you |
|---|---|
| `status` | running, paused, aborted, completed |
| `task_counts` | pending plus in-progress is the live work; a growing `dead` count is trouble |
| `hypothesis_states` | draft to reviewed to in_tournament is the healthy flow |
| `matches_played` | the tournament is only meaningful once this is well above the hypothesis count |
| `elo.spread` | narrow and stable means the ranking has converged |
| `budget_used_usd` | against `budget_usd` |
| `has_overview` | true means the meta-review has finalised |

If `status` is running but nothing moves across two polls, read `log_path`.
That file has the real error.

### 6. Hand over

When `has_overview` is true, switch to the **reading-research-overviews** skill.
Do not summarise the ranked list from `hypotheses_list` alone; the overview is
the meta-review's synthesis and carries the cross-hypothesis findings.

## Steering a session

`co-scientist:feedback_add` injects researcher feedback. A running session picks
it up at its next planning step, a paused one on resume.

- `kind="directive"` for "focus on transport mechanisms, not receptor binding"
- `kind="preference"` for softer steers
- `kind="pin"` with a `target` to protect a hypothesis from being retired
- `kind="rejection"` with a `target` to kill one

Pass the user's steer close to their own words. Do not editorialise it into
something more specific than they said.

## Pause, resume, abort

- `co-scientist:session_pause` drains workers and sleeps. Use it to stop the
  spend without losing state.
- `co-scientist:session_resume` picks up where it stopped, reclaiming expired
  task leases. Interrupted sessions resume cleanly; this is the normal recovery.
- `co-scientist:session_abort` is final. Confirm with the user first.

Finding a session the user names by topic: `co-scientist:session_list` returns
goals with ids, newest first.

## Rules

- Never start a session without an explicit go-ahead on the cost.
- Never invent a session id. Look it up.
- Report status from tool output, not from what you expect to be happening.
  If the run failed, say it failed and quote the log.
- If the server refuses with `session_start is disabled`, the install is
  deliberately read-only. Tell the user to start the run from the CLI.
