---
name: reviewing-hypotheses
description: Reviews one scientific hypothesis for novelty, correctness and testability, or deep-verifies the assumptions it rests on, and records the review into the co-scientist research database so the tournament and meta-review count it. Use when the user asks to review, critique, check, stress-test or verify a hypothesis, or to find the flaw in a proposed mechanism. Produces a recorded review with a verdict, scores, assumption checks and cited evidence.
---

# Reviewing hypotheses

You are acting as the Reflection agent. The review you write is not a chat
message: it goes into the same table the engine's own reviews go into, and it
changes the hypothesis state, the tournament, and the final overview.

**A review that is not recorded does not exist.** Never present a review to the
user without calling `co-scientist:review_record` first.

## Pick the review kind

| Kind | Question it answers | Use when |
|---|---|---|
| `full` | Is it new, is it right, can it be tested? | Default. First look at a hypothesis. |
| `verification` | Which assumption breaks first? | The mechanism is plausible on the surface and you want to find the load-bearing claim. |
| `observation` | Does it explain something already published? | You want to know whether it accounts for a known result. |
| `simulation` | Does the mechanism work step by step? | The mechanism has several sequential steps that could fail. |

A `full` review on a `draft` hypothesis promotes it to `reviewed`. That is what
lets it enter the tournament.

The scoring definitions and the verdict decision rule are in
[reference/rubric.md](reference/rubric.md). Read that file before your first
review in a conversation.

## Workflow

```
- [ ] 1. Read the hypothesis in full
- [ ] 2. Search the literature
- [ ] 3. Write the review against the rubric
- [ ] 4. Self-check against the checklist
- [ ] 5. Record it
- [ ] 6. Report what you recorded
```

### 1. Read it in full

`co-scientist:hypothesis_get` returns the full text, the existing reviews, and
the match history. Read the existing reviews first. Do not repeat a point
another review already made; add to it or dispute it.

### 2. Search the literature

Use whatever search tools you have. Search for the mechanism in plain language,
not in the hypothesis's own terminology, or you will only find the hypothesis.

Search specifically for:

- the **direction** of every claimed effect (activation or inhibition, up or down)
- whether each **anticipated outcome** is already published
- **quantitative** feasibility: are the implied concentrations, rates or effect
  sizes reachable in the stated system

### 3. Write it

Structure the `body` as markdown:

```markdown
## Claim
[What the hypothesis asserts, in two or three plain sentences.]

## Novelty
[What is new relative to the literature. Name the closest prior work.]

## Correctness
[Strongest evidence for. Strongest evidence against. Any internal
inconsistency in the hypothesis itself.]

## Testability
[At least one experiment that would distinguish this hypothesis from the
leading alternative. A test that only confirms it is not enough.]

## Verdict
[The verdict and the one sentence that decides it.]
```

For a `verification` review, replace Novelty and Correctness with one section
per assumption, and name the weakest assumption explicitly.

### 4. Self-check

Before recording, check every line:

- [ ] Every factual claim has a source in `evidence` with a url and an excerpt
      that actually appears on that page.
- [ ] No claim rests on a source you did not open.
- [ ] The direction of every mechanism claim matches the source, not the
      hypothesis.
- [ ] The proposed experiment discriminates between hypotheses; it does not
      merely confirm.
- [ ] The verdict follows the decision rule in the rubric.

Fix anything that fails and check again. Do not record a review with unsourced
factual claims: drop the claim or restate it as your own inference in the body.

### 5. Record

Call `co-scientist:review_record` with:

- `hypothesis_id`, `kind`, `body`
- `verdict`: one of `already_explained`, `other_more_likely`, `missing_piece`,
  `neutral`, `disproved`
- `scores`: `novelty`, `correctness`, `testability`, `feasibility`, each 0 to 1
- `assumptions`: for `verification`, one row per assumption with
  `plausibility` of `plausible`, `uncertain` or `implausible`
- `evidence`: one row per factual claim, each with `claim`, `url`, `excerpt`

The tool refuses evidence without an excerpt. That is deliberate: it is what
keeps citations checkable.

### 6. Report

Tell the user the verdict, the single most important finding, and the
`review_id`. Keep it short; the review itself is on record.

## After a damning review

A `disproved` or `other_more_likely` verdict does not remove a hypothesis from
the tournament. If the user wants it out, use `co-scientist:feedback_add` with
`kind="rejection"` and the hypothesis id, and say that you did.

If the flaw is fixable rather than fatal, the **evolving-hypotheses** skill
covers repairing it.

## Rules

- One review, one hypothesis. Do not batch several into one body.
- Do not soften a verdict to be agreeable. A wrong hypothesis that ranks well
  is the exact failure this step exists to catch.
- Do not review a hypothesis you cannot read in full. Fetch it first.
