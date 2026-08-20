# Security

## Reporting a vulnerability

Report privately through
[GitHub Security Advisories](https://github.com/Ahmad-Jaradat-Space/Co-Scientist/security/advisories/new).
Do not open a public issue for a vulnerability.

Include what you did, what happened, and what you expected. A proof of concept
helps. Expect an acknowledgement within a week.

## What this project handles

Running a session means giving an autonomous agent an API key or a signed-in
subscription CLI, letting it fetch arbitrary web pages, and letting it write to
a local database. The parts worth knowing about:

**Credentials.** Keys come from the environment only, never from a config file.
Under a subscription CLI backend, `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` are
stripped from the subprocess environment so a call cannot silently fall back to
metered billing. A test asserts this.

**Prompt injection.** Fetched pages and search results are untrusted input. They
are quoted and delimited before reaching a model, and there is a classifier plus
a citation verifier in `co_scientist/safety/`. Treat these as defence in depth,
not a guarantee. Do not run sessions against goals where a hostile page could do
real damage if a model followed it.

**Citations.** The citation verifier enforces that a model may only cite URLs it
actually fetched, using the provenance log the MCP server writes. This is why
evidence rows require a URL and an excerpt. It catches fabricated citations, not
misread ones.

**The MCP session server.** `co-scientist mcp-server` lets any connected agent
start a session, which spends money or subscription quota, and writes to your
database. On a shared machine run it with `--read-only`, or set
`COSCI_ALLOW_START=0`, which refuses `session_start` and `session_resume` while
leaving reads working.

**Artifacts on disk.** Session artifacts, transcripts and logs land under
`data/`, which is gitignored. They contain the full text of every model call.
Treat that directory as sensitive before sharing it.

## Scope

Findings in this repository are in scope. Findings in the model providers, the
agent CLIs, or the literature APIs belong to those projects.
