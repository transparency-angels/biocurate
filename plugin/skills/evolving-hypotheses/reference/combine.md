# Operator: combine

Merge two hypotheses that each explain part of the phenomenon into one that
explains more than either.

## When it applies

- Two hypotheses cover different steps of the same process.
- Two hypotheses are ranked close and their reviews praise different things.
- One has the mechanism and the other has the testable readout.

It does not apply when the two are near-duplicates. Check `dedup_cluster` in
`co-scientist:hypotheses_list`: same cluster means combining produces a
paraphrase, not a synthesis.

## Procedure

1. Name the strongest mechanism in A and the strongest in B, one sentence each,
   taken from the reviews rather than from the hypotheses' own claims.
2. List every contradiction between them. Be specific: same entity with
   opposite direction, incompatible timescales, mutually exclusive
   localisations.
3. For each contradiction, state how the combination resolves it. "Both could
   be true in different compartments" is a resolution. "The contradiction is
   minor" is not.
4. Write the combined mechanism with specific entities, steps and anticipated
   outcomes.
5. State one experiment that distinguishes the combination from **both**
   parents. If the combination predicts nothing the parents do not, it is not
   worth recording.

## Failure mode

Stapling. A hypothesis that says "mechanism A operates, and also mechanism B
operates" is two hypotheses in one document. A real combination has the parts
interacting: one gates the other, one supplies the substrate for the other, one
explains why the other is tissue-specific.

If you cannot state the interaction, do not record the combination.

## Recording

`strategy="combine"`, `parent_ids` set to both parents.
