You are synthesizing the final research overview for a domain scientist based on a tournament-style multi-agent investigation of the following research goal.

Goal: {{ goal }}

Scientist preferences:
{{ preferences | default('') }}

Latest system feedback:
{{ system_feedback | default('(none)', true) }}

Top-ranked hypotheses (ordered by tournament Elo, with their reviews and winning debate rationales):
{{ top_hypotheses_block }}

Sources the investigation actually consulted (with line numbers `[L#]` from the extracted text). Every URL below appeared in a search or fetch result during generation or review — these are the only citations you may use:
{{ sources | default('(no literature sources were recorded for this session)', true) }}

Your job is to produce a coherent research overview that the scientist can act on. Structure your response as follows:

# Executive summary
(3-5 sentences: what the tournament converged on and why it matters.)

# Main research directions
For each direction, write a short section with:
- **The direction.** A name and a one-sentence claim.
- **Why it's promising.** Reference 1-3 supporting hypotheses by their IDs and the strongest evidence each carries.
- **Open questions.** What would need to be true for this direction to pan out? What could falsify it?
- **First experiment.** A concrete, near-term experiment the scientist could run within one quarter.

# Convergence and divergence
Briefly note which hypotheses converged on similar mechanisms and which directions are genuinely orthogonal alternatives.

# Caveats and limitations
What did the system not explore? Where was the literature thin? Where would a domain expert most likely disagree with the tournament's verdict?

Use markdown formatting. Cite hypothesis IDs as `[H-...]` inline.

Citations: cite sources with their source tag and line number(s) as `[S#, L#-L#]` (or `[S#, L#]`) inline, e.g. `[S1, L3-L5]` or `[S2, L12]`, referencing the line numbers (`[L#]`) from the consulted source excerpts/documents.

# Sources section formatting:
Close with a `# Sources` section listing each `[S#]` tag you used with its full URL. Under each `- [S#] <URL>` line, provide 2-3 indented sub-bullets (using `  - `) that concisely summarize the key findings, mechanisms, or evidence from the excerpt:
```markdown
# Sources

- [S1] https://...
  - <Key factual finding or biological observation from excerpt>
  - <Receptor, signaling axis, or molecular pathway identified>
  - <Functional outcome or physiological consequence observed>
- [S2] https://...
  - <Key finding from excerpt>
  - <Mechanistic consequence from excerpt>
```

**Use only URLs from the source list above — never invent one, and never cite a URL that is not listed.** If the list is empty, say so plainly and mark literature claims as requiring the scientist's verification.
