# Operator: simplify

Strip a hypothesis to its load-bearing claim. This is the repair operator: when
a review kills one step, simplify is how you find out whether the rest stands
on its own.

## When it applies

- A review found a fatal flaw in one claim while praising another.
- The mechanism has steps that no prediction depends on.
- The hypothesis is hard to test because it asserts too much at once.

## Procedure

1. List every claim the hypothesis makes, one per line.
2. Mark each as load-bearing or ornamental. A claim is load-bearing only if
   removing it changes what the hypothesis predicts. Be strict: most
   hypotheses carry two or three load-bearing claims and a lot of scaffolding.
3. Delete the ornamental ones. Delete any load-bearing claim a review
   contradicted.
4. State what is left as one sentence at the top of the full text.
5. Re-derive the mechanism and the anticipated outcomes from that sentence
   alone. They must still be specific. If they collapse into vagueness, the
   claim you deleted was doing the work and the hypothesis does not survive
   simplification. Say so rather than recording a hollow version.
6. Propose an experiment that is easier to run on the simplified version than
   on the original, and say why it is easier.

## Failure mode

Simplifying into a truism. "The microbiome affects inflammation" is simple,
testable in principle, and worthless. The test is whether the simplified claim
still discriminates against the obvious alternative.

The second failure mode is quiet deletion: dropping the claim a review attacked
without saying you dropped it. Always include a "Changes from parent" section
naming what was removed and why.

## Recording

`strategy="simplify"`, `parent_ids` set to the single parent.
