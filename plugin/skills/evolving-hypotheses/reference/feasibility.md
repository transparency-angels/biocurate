# Operator: feasibility

Keep the scientific claim, change how it would be tested, so that it can
actually be done with what exists now.

## When it applies

- The mechanism is plausible and novel but the proposed experiment needs a
  method, model or reagent that does not exist or is out of reach.
- The review scored testability well and feasibility badly.
- The session's constraints (timescale, available assays, sample access) rule
  out the stated approach.

The constraints are in `co-scientist:session_status` under `research_plan`.
Read them; feasibility is judged against those, not against an unlimited lab.

## Procedure

1. State what makes the original infeasible, precisely. Not "it is hard" but
   "it needs single-cell resolution in live tissue over 72 hours".
2. Survey what current methods can do for this specific measurement. Search;
   do not rely on memory of what was possible.
3. Propose the alternative route to the same discriminating result. It may be a
   different readout, a different model system, a proxy measurement with a
   stated validity argument, or a staged design where a cheap step gates an
   expensive one.
4. Confirm the new route still distinguishes this hypothesis from the leading
   alternative. A feasible experiment that no longer discriminates is a loss,
   not a gain.
5. State the resource envelope: rough time, rough cost, what has to be in the
   lab already.

## Failure mode

Weakening the test to fit the budget. If the cheaper experiment cannot separate
this hypothesis from its rival, you have made it easier to run and useless to
run. Say the hypothesis is not currently testable rather than recording a
feasible non-test.

The core claim must survive unchanged. If you find yourself editing the
mechanism to fit the method, the right operator is `simplify`, not
`feasibility`.

## Recording

`strategy="feasibility"`, `parent_ids` set to the single parent.
