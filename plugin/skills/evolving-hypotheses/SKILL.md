---
name: evolving-hypotheses
description: Improves an existing scientific hypothesis by combining it with another, simplifying it, making it feasible, or reimagining it out of the box, and records the result as a new hypothesis with its parents in the co-scientist database. Use when the user asks to improve, fix, merge, simplify, repair or rethink a hypothesis, or to salvage the good part of one that a review broke. Produces a new draft hypothesis linked to its parents.
---

# Evolving hypotheses

You are acting as the Evolution agent. Evolution never edits a hypothesis in
place. It produces a **new** hypothesis that records its parents, so both stay
in the tournament and the ranking decides which survives.

**A new hypothesis that is not recorded does not exist.** Call
`co-scientist:hypothesis_record` with `parent_ids` set.

## Pick the operator

Choose by what is wrong, not by what sounds interesting. Each operator has a
reference file with its procedure and its failure mode; read the one you pick.

| Operator | Use when | Reference |
|---|---|---|
| `combine` | Two hypotheses each explain part of the phenomenon | [reference/combine.md](reference/combine.md) |
| `simplify` | The mechanism has a broken or unnecessary step | [reference/simplify.md](reference/simplify.md) |
| `feasibility` | The mechanism is plausible but untestable as stated | [reference/feasibility.md](reference/feasibility.md) |
| `out_of_box` | The whole framing is stuck and the field's assumptions need dropping | [reference/out-of-box.md](reference/out-of-box.md) |

If a review found a fatal flaw in one claim but the rest holds, `simplify` is
almost always the right operator: cut the broken claim and see whether what is
left still explains the phenomenon.

## Workflow

```
- [ ] 1. Read the parents and their reviews
- [ ] 2. Name what is wrong, in one sentence
- [ ] 3. Pick the operator and read its reference file
- [ ] 4. Write the new hypothesis
- [ ] 5. Check it is actually different
- [ ] 6. Record it with its parents
- [ ] 7. Review it
```

### 1. Read the parents

`co-scientist:hypothesis_get` for each parent. Read the reviews. Evolution
without the reviews just reshuffles words.

### 2. Name the defect

Write one sentence: what specifically fails. "The receptor direction is
reversed." "The experiment does not discriminate." "It needs a cell type the
tissue does not contain."

If you cannot write that sentence, do not evolve the hypothesis. Review it
first.

### 4. Write it

The new hypothesis needs:

- **title**: one line naming the mechanism
- **summary**: about three sentences stating the mechanism. This is the text
  that gets embedded for dedup and clustering, so it must carry the mechanism,
  not tease it
- **full_text**: markdown for a domain expert, covering the mechanism step by
  step, what it predicts, and the experiment that would test it
- **citations**: sources you actually read

State what changed relative to the parents in the full text, in a short
"Changes from parent" section. Reviewers need it and so does the meta-review.

### 5. Check it is different

Compare your summary against the parents. If a domain expert would call it the
same idea with different words, you have not evolved anything. Go back to step
2 or drop it.

The engine's Proximity agent will cluster near-duplicates anyway, but a
duplicate wastes tournament matches before it does.

### 6. Record

`co-scientist:hypothesis_record` with `session_id`, `title`, `summary`,
`full_text`, `strategy` set to the operator name, and `parent_ids`. The tool
derives `created_by="evolution"` from the parents being present.

It enters as a `draft`. Recording is idempotent on the summary: an identical
summary returns the existing id and adds nothing.

### 7. Review it

An unreviewed hypothesis cannot compete. Switch to the
**reviewing-hypotheses** skill and give it a `full` review. Do not assume the
child inherits the parent's review; the defect you fixed may have moved rather
than gone.

## Rules

- Never delete or overwrite a parent. The tournament decides, not you.
- Never record an evolution without `parent_ids`. Provenance is the point.
- Do not evolve a hypothesis to make it sound better. Evolve it to fix a named
  defect. Rewording to taste is how a session fills up with paraphrases.
- One operator per new hypothesis. If two things are wrong, fix one, record it,
  review it, then fix the next.
