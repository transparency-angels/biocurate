---
name: benchmarking-models
description: Compares several LLMs head to head on the same research goal using the co-scientist cross-model Elo bench, with optional gold-set scoring, and reads the results. Use when the user asks which model is best for hypothesis generation, wants to compare models or backends on a research task, asks to run a bench, or asks what the bench results show. Produces a cross-Elo ranking with per-candidate hypotheses and gold-set hits.
---

# Benchmarking models

The bench runs N candidate models on one research goal and settles them in a
cross-model Elo tournament judged by a separate model. It is the tool for
"which model should I use for this", and for checking that a change to prompts
or config actually helped.

This runs through the CLI, not the MCP tools. It spends real budget on every
candidate.

## Before running

1. Check the backend with `co-scientist:doctor`.
2. Decide the budget. The cap is per candidate, so five candidates at three
   dollars is fifteen dollars plus the judge budget.
3. Get an explicit go-ahead on that total.

## Running

Reproduce the paper's comparison:

```bash
co-scientist bench "Identify hypotheses about X" \
  --preset paper \
  --judge claude_cli:sonnet
```

Compare your own candidates:

```bash
co-scientist bench "Identify hypotheses about X" \
  -c opus=claude_cli:opus \
  -c sonnet=claude_cli:sonnet \
  -c gpt=openai:gpt-5.6-sol \
  --judge claude_cli:sonnet \
  --budget-per-candidate 3.0 \
  --judge-budget 5.0
```

Candidate syntax is `label=backend:model[@mode]`. Mode `pipeline` is the
default and runs the full agent loop. Mode `direct` is a single raw model call
with no tools, which is the honest baseline for "does the multi-agent structure
earn its cost".

Useful flags:

- `--n` hypotheses per candidate, default 2
- `--matches` tournament matches per pair, default 2
- `--goldset` scores against a known answer key; `--preset paper-aml` bundles
  one. Pass `none` to disable a preset's default.

Choose the judge deliberately. Judging with one of the candidates biases the
result toward it. A capable model that is not in the field is the right choice.

## Reading the results

`docs/BENCH_RESULTS.md` is generated from the bench database and holds every
bench ever run on this code: per-candidate Elo, every hypothesis produced,
gold-set hits, and file pointers. Read it rather than re-running a bench that
already exists.

When you report a bench:

- Give Elo with the match count. Two matches per pair is a weak signal, and a
  small Elo gap over few matches means nothing.
- Report gold-set hits separately from Elo. They measure different things: Elo
  is debate performance, gold-set recall is whether it found the known answers.
- Report cost per candidate. A model that ranks second at a fifth of the cost
  is often the right pick.
- Name the judge. The result is conditional on it.

## Rules

- Never present a bench result without the judge and the match count.
- Never compare Elo across different benches. Ratings are only meaningful
  within the tournament that produced them.
- If a candidate errored out or hit its budget cap partway, say so. A truncated
  candidate's rating is not comparable to a complete one's.
- Do not run a bench to settle a question a previous bench already answered.
  Check `docs/BENCH_RESULTS.md` first.
