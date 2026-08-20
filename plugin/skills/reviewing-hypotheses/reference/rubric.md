# Review rubric

## Contents

- Scores: what each dimension means and how to place a number
- Verdicts: the decision rule
- Assumption decomposition
- Worked example

## Scores

Each score is 0 to 1. Place the number against the anchors, do not average a
vibe. Leave a score out rather than guessing when you have no basis for it.

### Novelty

Relative to the literature you actually searched, not to your general sense of
the field.

| Score | Anchor |
|---|---|
| 0.0 to 0.2 | The mechanism is published, possibly under different words. |
| 0.3 to 0.5 | The parts are all known; the combination is a modest step. |
| 0.6 to 0.8 | A specific new mechanism, transport step, or causal link that is not in the literature. |
| 0.9 to 1.0 | A mechanism no source anticipates, with a reason it was missed. |

Novelty by relabelling scores low. Search the mechanism in plain words before
scoring it high.

### Correctness

Whether the mechanism can be true given what is known.

| Score | Anchor |
|---|---|
| 0.0 to 0.2 | Contradicted by strong direct evidence, or internally inconsistent. |
| 0.3 to 0.5 | A load-bearing step conflicts with published data, or the numbers do not work. |
| 0.6 to 0.8 | Consistent with the literature; the untested steps are plausible. |
| 0.9 to 1.0 | Every step has direct support; only the assembly is untested. |

An internal inconsistency caps correctness at 0.2 regardless of the rest. Two
claims in one hypothesis that cannot both hold is a defect in the hypothesis,
not an open question.

### Testability

| Score | Anchor |
|---|---|
| 0.0 to 0.2 | No stated outcome would distinguish it from the alternatives. |
| 0.3 to 0.5 | Testable in principle; the experiment is not specified or not discriminating. |
| 0.6 to 0.8 | A concrete experiment with a stated readout that separates it from the leading alternative. |
| 0.9 to 1.0 | That experiment, plus a stated result that would kill the hypothesis. |

A confirmatory test is not a discriminating test. "We would see X" scores low if
the leading alternative also predicts X.

### Feasibility

Whether the discriminating experiment can actually be run: reagents, models,
sample access, timescale, cost. Score against the constraints the session was
given, not against an unlimited lab.

## Verdicts

Pick exactly one. Work down the list and take the first that applies.

1. **`disproved`** - a load-bearing claim is contradicted by strong direct
   evidence you cited, or the hypothesis is internally inconsistent. Reserve
   this for evidence, not for doubt.
2. **`already_explained`** - the phenomenon is accounted for by a published
   mechanism, and this hypothesis adds nothing that mechanism does not.
3. **`other_more_likely`** - a competing mechanism explains the same
   observations with fewer assumptions or better support. Name it.
4. **`missing_piece`** - the hypothesis is plausible but a required step is
   absent or unstated. Name the missing step.
5. **`neutral`** - none of the above. Plausible, novel enough, testable, and
   nothing decisive either way.

`neutral` is the default only after the other four have been ruled out. A
review that lands on `neutral` without engaging the literature is not a review.

## Assumption decomposition

For a `verification` review, list every claim the mechanism rests on. Rules:

- One testable claim per row. "The bacterium colonises the ileum" is a row.
  "The mechanism works" is not.
- Do not restate the hypothesis as an assumption.
- Classify each as `plausible`, `uncertain` or `implausible`, with a rationale
  grounded in a source. If the literature is silent, write that it is silent;
  silence is `uncertain`, not `plausible`.
- Name the weakest assumption, the one whose failure collapses the mechanism
  fastest, and propose the experiment that would settle it.

One `implausible` load-bearing assumption is enough for `disproved`, provided
the evidence is direct.

## Worked example

Hypothesis: a gut bacterium's enzyme releases a metabolite that antagonises a
nuclear receptor in the ileum, driving inflammation.

A weak review says the mechanism is interesting and plausible and scores it 0.7
across the board.

A real review does this:

1. Searches the receptor and the metabolite class together, and finds published
   data showing **agonism**, not antagonism.
2. Notes the hypothesis also claims the metabolite is poorly absorbed, which
   conflicts with the concentration its own mechanism needs at the receptor.
   That is an internal inconsistency.
3. Checks the anticipated outcome and finds it already published, so the
   proposed experiment is confirmatory.
4. Scores: novelty 0.6 (the transport step is genuinely new), correctness 0.15
   (direction reversed plus internal inconsistency), testability 0.3
   (experiment does not discriminate).
5. Verdict `disproved`, on the receptor direction, with the citation.
6. Records the review, then notes that the transport step is worth keeping and
   could be re-proposed without the receptor claim.

The last point matters. A fatal flaw in one claim does not make the whole
hypothesis worthless, and saying which part survives is the most useful thing a
review does.
