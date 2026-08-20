---
name: grounding-claims
description: Checks that the citations and evidence behind a hypothesis, review or write-up actually say what they are claimed to say, and reports the ones that do not. Use when the user asks to verify sources, check citations, confirm a claim is supported, or before publishing, sharing or acting on anything the co-scientist produced. Produces a per-claim verdict of supported, contradicted, not-found or unreachable.
---

# Grounding claims

Machine-generated hypotheses cite real-looking sources that sometimes do not
say what the text claims. This skill checks that, one claim at a time. Run it
before anything leaves the session: a shared write-up, a grant paragraph, a
decision to run an experiment.

## What gets checked

For each factual claim:

1. Does the url resolve?
2. Does the excerpt actually appear on that page?
3. Does the source support the claim, or merely mention the topic?
4. Does it support the **direction** of the claim? Activation is not
   inhibition, correlation is not causation, mouse is not human.

Check 4 catches the most errors. A source that discusses the right molecules in
the wrong direction reads as support to anyone skimming.

## Where the sources are

- `co-scientist:hypothesis_get` returns the hypothesis, its reviews, and its
  `artifact`. The citation list with urls and excerpts is in there: at
  `artifact.citations` for an agent-recorded hypothesis, and under
  `artifact.record` for one the engine's Generation agent wrote.
- Review evidence rows carry `claim`, `url` and `excerpt`, which is exactly
  the triple you need.
- Tool provenance from a session run records which urls an agent actually
  opened. A citation that appears in a hypothesis but in no tool call was not
  read by the agent that cited it. Treat those first.

## Workflow

```
- [ ] 1. Extract every factual claim with its source
- [ ] 2. Fetch each source
- [ ] 3. Verdict each claim
- [ ] 4. Record the finding
- [ ] 5. Report
```

### 1. Extract

List the claims as a table before checking anything: claim, url, excerpt. Work
from the list. Checking claims as you read prose means missing the ones stated
without a citation at all, which are the worst kind.

Claims with no source go in the list too, marked as uncited.

### 2. Fetch

Fetch each url. Search the page for the excerpt. If the page is paywalled, try
the abstract, the preprint, or the DOI landing page, and say which one you
checked.

### 3. Verdict

| Verdict | Meaning |
|---|---|
| `supported` | The source states the claim, in the claimed direction, in the claimed system. |
| `partial` | The source supports a weaker version. Say which weaker version. |
| `contradicted` | The source states the opposite, or the opposite direction. |
| `not_found` | The page resolves but does not contain the claim or the excerpt. |
| `unreachable` | The url is dead, or nothing verifiable is accessible. |
| `uncited` | The text makes the claim with no source. |

`not_found` and `unreachable` are not the same failure. A fabricated excerpt on
a real page is a much worse sign than a dead link.

### 4. Record

Findings belong in the database, not only in the chat. Use
`co-scientist:review_record` with `kind="verification"`, a body listing the
per-claim verdicts, and `evidence` rows carrying the sources you actually
checked. Set `verdict="disproved"` when a load-bearing claim is contradicted.

If the hypothesis should be taken out of contention, follow with
`co-scientist:feedback_add`, `kind="rejection"` and the hypothesis id.

### 5. Report

Lead with the failures. State how many claims you checked and how many are
supported. Never report "sources check out" unless you fetched every one.

## Rules

- Never mark a claim supported from memory. Fetch the page.
- Never cite a source in your own write-up that you did not open.
- Quote the excerpt you found, not the excerpt that was claimed, when they
  differ. The difference is the finding.
- If you could not check something, say so explicitly rather than leaving it
  out of the count.

## Related

If the project also uses a ScientistOS research graph, record the checked
claims there at the evidence level the lineage actually supports, rather than
asserting them at full strength on the basis of one source.
