# Operator: out_of_box

Generate a genuinely different hypothesis using existing ones only as analogy.
This is the operator for when the whole session has converged on one framing
and the ranking is just sorting variants of it.

## When it applies

- The top hypotheses all share the same assumption, and the meta-review says so.
- Reviews keep finding the same weakness across unrelated hypotheses, which
  usually means the framing is the problem.
- The user asks for something the field has not tried.

Use it sparingly. Most sessions need better versions of good ideas, not
stranger ideas.

## Procedure

1. Name the assumption every current hypothesis shares. Write it as a single
   sentence. This is the hard step; do it explicitly rather than in your head.
2. Ask what the phenomenon would look like if that assumption were false.
3. Look for an analogy in an adjacent field where the same pattern is explained
   differently: a different level of organisation, a different causal
   direction, a physical rather than biochemical explanation, a population
   effect rather than a molecular one.
4. Build the new mechanism from that analogy with specific entities and steps.
   Analogy is the source of the idea, not a substitute for the mechanism.
5. State what it predicts that no current hypothesis predicts. If there is no
   such prediction, it is not out of the box, it is a restatement.

## Failure mode

Novelty theatre. Unusual vocabulary, exotic entities, no mechanism, no
prediction. It reads as creative and reviews as empty, and it will score
well on novelty and badly on everything else.

The guard is step 5. A hypothesis that predicts nothing new is not new.

The second failure mode is direct replication of the analogy's source field.
The analogy supplies the shape of the explanation, not the entities.

## Recording

`strategy="out_of_box"`, `parent_ids` set to the hypotheses that inspired it.
Include them even though the result is not derived from their content: the
provenance is what lets the meta-review see how the session explored.
