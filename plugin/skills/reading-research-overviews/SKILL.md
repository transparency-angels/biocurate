---
name: reading-research-overviews
description: Reads and explains the output of an AI co-scientist session, including the final research overview, the Elo-ranked hypotheses, and the reviews behind them. Use when the user asks what the co-scientist found, what the top hypotheses are, what a session produced, what an Elo score means here, or asks for the results to be summarised or written up. Produces an honest reading with the known failure modes checked.
---

# Reading research overviews

The output of a session is a ranked set of hypotheses plus a meta-review
synthesis. Reading it well means separating what the tournament established
from what it merely preferred, and checking for the failure modes this system
produces.

## Get the material

1. `co-scientist:session_status` to confirm the session finished and see
   `matches_played` and `elo`.
2. `co-scientist:overview_get` for the meta-review synthesis. This is the
   headline output.
3. `co-scientist:hypotheses_list` for the ranking.
4. `co-scientist:hypothesis_get` for any hypothesis you are going to discuss in
   detail. It returns the full text, every review, and the match history.

Never summarise from the ranked list alone. The overview carries the
cross-hypothesis findings, which are often the most useful part.

## What Elo does and does not mean

Elo here is the outcome of simulated pairwise scientific debates between
hypotheses in this session. It is a within-session preference ordering.

- It is **not** a probability of being correct.
- It is **not** comparable across sessions or across models.
- It is only meaningful once a hypothesis has played several matches. Check
  `matches_played` before quoting a rank.
- A hypothesis with a high Elo and a damning review is common. Elo reflects
  debate performance, and a well-argued wrong idea wins debates.

Quote Elo with its match count: "top-ranked, Elo 1287 over 14 matches".

## Read the reviews, not just the rank

For each hypothesis you present, pull `hypothesis_get` and read its reviews.
Weight the review over the rank when they disagree, and say so.

Look at:

- `verdict`: `disproved` or `other_more_likely` outranks any Elo score.
- `scores.correctness`: low correctness with high novelty is the classic
  attractive-but-wrong pattern.
- assumption checks marked `implausible`: one implausible load-bearing
  assumption sinks the mechanism regardless of rank.

## Failure modes to check before presenting

Run these checks on the top hypotheses. They are the ones this system actually
produces, not hypothetical ones.

1. **Mechanism direction reversed.** The hypothesis claims a receptor or
   pathway is inhibited where the literature shows activation, or the reverse.
   Check the cited sources actually support the stated direction.
2. **Anticipated outcome already published.** An "expected result" that is
   established fact makes the experiment confirmatory, not discriminating. Search
   for the claimed outcome before calling it a prediction.
3. **Internal inconsistency.** Two claims in the same hypothesis that cannot
   both hold. Read the full text end to end looking for this specifically.
4. **Quantitative implausibility.** Concentrations, rates or effect sizes that
   the stated mechanism cannot deliver. Check the numbers.
5. **Novelty by relabelling.** A known mechanism with new terminology. Search
   the mechanism in plain words, not the hypothesis's own phrasing.

When a check fails, say which one and why, and record it with
`co-scientist:review_record` so the finding is in the graph rather than only in
the chat. See the **reviewing-hypotheses** skill for the recording format.

## Presenting

A useful write-up has:

- the research goal as the session actually ran it
- the top hypotheses, each with its mechanism in two or three plain sentences,
  its rank and match count, and its strongest objection
- the cross-hypothesis findings from the overview: shared assumptions, shared
  weaknesses, clusters
- the discriminating experiments: what would tell competing hypotheses apart
- what the session did not cover

State clearly that these are machine-generated hypotheses requiring expert
review. They are a starting point for a scientist, not a finding.

## Rules

- Do not upgrade a hypothesis to a claim. The system proposes; it does not
  establish.
- Do not quote a citation you have not checked resolves. See the
  **grounding-claims** skill.
- If the session ended on budget or wall-clock rather than Elo stability, say
  so: the ranking had not converged.
