---
name: ranking-hypotheses
description: Compares two hypotheses head to head in a structured scientific debate and records the outcome as a tournament match, updating both Elo ratings in the co-scientist database. Use when the user asks which hypothesis is better, asks to compare, rank, or pit hypotheses against each other, or wants the tournament advanced by hand. Produces a recorded match with a rationale and the Elo change.
---

# Ranking hypotheses

You are acting as the Ranking agent. A match is a structured debate between two
hypotheses, decided on stated criteria, and recorded so the Elo tournament and
the meta-review see it.

**A comparison that is not recorded does not exist.** Call
`co-scientist:match_record` before reporting a winner.

## When a match is worth running

Match pairs that are close and informative:

- similar Elo, so the outcome carries information
- both already reviewed, so the debate has material to work with
- different `dedup_cluster`, so you are comparing ideas rather than paraphrases

Do not match a reviewed hypothesis against an unreviewed one. Review it first;
the debate has nothing to weigh otherwise.

The engine picks pairs this way automatically during a run. Hand-running
matches is for when the user wants a specific comparison settled.

## Workflow

```
- [ ] 1. Fetch both hypotheses with their reviews
- [ ] 2. Run the debate
- [ ] 3. Decide on the criteria, not on style
- [ ] 4. Record the match
- [ ] 5. Report the outcome and the new ratings
```

### 1. Fetch

`co-scientist:hypothesis_get` for each. You need the full text and every
review. A hypothesis with a `disproved` review usually loses, and you should
know that before debating.

Both must be in the same session. The tool refuses a cross-session pair.

### 2. Debate

Work through three to five turns. Do not skip to the verdict.

- **Turn 1.** State both hypotheses and their reviews in your own words.
- **Middle turns.** Put the strongest case for each in turn, then the strongest
  objection to each. Ask the clarifying questions a panel would ask. Where the
  reviews disagree with each other, resolve it or say it is unresolved.
- **Final turn.** Judge.

Argue both sides properly. A debate where one side is strawmanned produces a
result that is worth nothing.

### 3. Decide

Compare on these, in this order:

1. **Correctness.** Can it be true given the literature and its own reviews?
2. **Novelty.** Is it new relative to what is published?
3. **Testability.** Is there a discriminating experiment, not just a
   confirmatory one?
4. **Specificity.** Is the mechanism stated in enough detail to act on?
5. **Feasibility.** Can the experiment actually be run under the session's
   constraints?

Correctness dominates. A more exciting hypothesis that is probably wrong loses
to a duller one that is probably right. This is the single most common way a
tournament goes wrong, and it is the reason the criteria are ordered.

If the session's research plan states its own criteria, those come first. They
are in `co-scientist:session_status` under `research_plan`.

There are no draws. If it is genuinely close, pick on correctness and say in the
rationale that it was close.

### 4. Record

Call `co-scientist:match_record` with `hyp_a`, `hyp_b`, `winner` (`"a"` or
`"b"`), `rationale`, and `mode`:

- `mode="debate"` when you ran the multi-turn debate above. This is the default
  for hand-run matches.
- `mode="pairwise"` for a single direct comparison without the debate turns.

The `rationale` should be the deciding argument in two or three sentences, in
the terms of the criteria. Not a summary of both hypotheses.

Matches are idempotent per pair per round. A second identical call moves no
Elo and returns `elo_applied: false`, which protects the ratings from
accidental repeats. To rematch a pair deliberately, for example after new
evidence, pass a fresh `round_id` such as `"rematch-after-2026-review"` and say
why in the rationale.

### 5. Report

Give the winner, the deciding reason, and the Elo change from the tool
response. Include `k_factor` context if the user asks why the move was large:
new entrants move faster than seasoned ones.

## Reading the result

- Elo is a within-session preference ordering, not a probability of being
  correct.
- A single match barely moves a seasoned hypothesis. Do not present one match as
  a verdict on an idea.
- If both hypotheses were unranked, the tool gives them the configured starting
  Elo and puts them in the tournament. That is the normal entry path.

## Rules

- Never record a winner you did not argue for.
- Never record a match to make a ranking look tidier.
- If one hypothesis is simply better documented rather than better, say that in
  the rationale. Documentation quality is not one of the criteria.
