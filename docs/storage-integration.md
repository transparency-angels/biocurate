# Storage and Atlas integration guide

This is the reference for everything the `feature/MongoDB` branch changed about
data storage. Read it before you integrate a feature that reads or writes data
(the researcher UI, uploaded material, statistics, citation locations), and
before you replace any database placeholder with real calls.

The README's "Built on MongoDB Atlas" section is the short public pitch. This
file is the working detail.

---

## 1. The rules for anyone touching data

1. **Never talk to a database directly.** Import a repo module, e.g.
   `from co_scientist.storage.repos import hypotheses as hyp_repo`, and call
   `await hyp_repo.fetch(conn, hid)`. No `aiosqlite`, no `pymongo`, no SQL, no
   `find()` outside `co_scientist/storage/`.
2. **Get a connection from `co_scientist.storage.db.connect(cfg)`.** It
   returns either an `aiosqlite.Connection` or an `AtlasConn`, depending on
   `[storage] backend`. Pass it through untouched. Its type is the `Conn` alias
   in `co_scientist/storage/__init__.py`.
3. **Every new repo function needs two implementations**, one for SQLite and
   one for Atlas, with the same signature and the same behaviour. Section 4
   walks through it.
4. **Two tests enforce this and will fail your PR:**
   - `co_scientist/tests/unit/test_repo_parity.py`: every public async
     function in `storage/sqlite/<m>.py` has a twin with the same name and
     parameters in `storage/atlas/<m>.py`, and is exposed by
     `storage/repos/<m>.py`.
   - `co_scientist/tests/unit/test_no_raw_sql.py`: no SQL statements in
     `.execute(...)` calls outside `storage/` (and `bench/`, which stays
     SQLite-only).
5. **Never commit secrets.** `MONGODB_URI` and `VOYAGE_API_KEY` live only in
   `.env` (gitignored). `.env.example` has empty placeholders.

---

## 2. How storage is laid out

```
co_scientist/storage/
├── __init__.py          Conn = aiosqlite.Connection | AtlasConn
├── db.py                connect(cfg) / init_db(cfg): picks the backend
├── repos/               ← THE ONLY THING CALLERS IMPORT
│   ├── _dispatch.py     dual(sql_fn, atlas_fn): routes on isinstance(conn, AtlasConn)
│   ├── hypotheses.py    insert = dual(_sql.insert, _atlas.insert), one line per function
│   └── …                (sessions, reviews, tournaments, tasks, transcripts,
│                         feedback, events, spans, embeddings)
├── sqlite/              reference implementation (the original repos, moved verbatim)
│   └── <m>.py
├── atlas/               PyMongo async implementation
│   ├── client.py        AtlasConn, connect_atlas, shutdown_clients (one client per URI,
│   │                    replaced when the running event loop changes)
│   ├── indexes.py       ensure_indexes, B-tree + search index definitions
│   ├── _codec.py        aware datetimes, iso() helpers
│   ├── library.py       evidence-library store (Atlas only, no SQLite twin)
│   └── <m>.py
├── schema.sql, migrations/   SQLite schema (unchanged for core tables)
```

**Choosing the backend.** It is set in `config/default.toml`, or in an overlay
TOML passed with the global `--config/-c` option
(`co-scientist -c atlas.toml run …`):

```toml
[storage]
backend = "atlas"          # runtime default; use "sqlite" for offline/local runs
atlas_db = "biocurate"     # the DB user only has readWrite here
atlas_prefix = ""          # collection-name prefix; tests set a unique one
```

`.env` needs `MONGODB_URI` (`mongodb+srv://<user>:<password>@<cluster>/`) and
`VOYAGE_API_KEY`. CI and offline unit tests use SQLite fixtures and need no
network; Atlas tests opt in with `CO_SCI_ATLAS_TESTS=1`.

**The Atlas client.** It is `pymongo.AsyncMongoClient` (not Motor), created
with `tz_aware=True` and `tlsCAFile=certifi.where()`; the Mac dev machine
needed certifi for TLS. There is one cached client per URI per running event
loop, and stale-loop entries are discarded. `AtlasConn.close()` is a no-op,
because the client is shared. `AtlasConn.coll("tasks")` returns the collection
with the prefix applied. Always use `coll()`, never `conn.db[...]`, or tests
will write into the real collections.

**`co-scientist init`** calls `init_db`. On Atlas this runs `ensure_indexes`,
which creates every collection and B-tree index, plus any missing search
index. It is idempotent: it never updates or drops an existing index.

---

## 3. What is stored where

> **Search index definitions are never updated in place.** `ensure_indexes`
> creates a missing index and leaves an existing one alone. Changing
> `embeddings.dim`, `library.embedding` or an index name on a cluster that
> already has the index requires dropping and recreating it. That is an owner
> action; do not automate it.

### Core collections (one per former SQLite table)

`_id` is the model's existing string id, except in `events`, which uses an
ObjectId.

| Collection | Holds | Notes |
|---|---|---|
| `sessions` | `Session` | `research_plan`, `config_snapshot` stored as subdocuments |
| `hypotheses` | `Hypothesis` | ids hash in the session id (`ids.hypothesis_id`), so there are no cross-session collisions. `citations` and `data_evidence` are fields on the row (see below) |
| `reviews` | `Review` | |
| `tournament_matches` | `TournamentMatch` | |
| `elo_journal` | one doc per applied Elo update, `_id = match_id` | makes Elo updates idempotent |
| `tasks` | `Task` (durable agent queue) | lease times are epoch-ms ints |
| `transcripts` | LLM call records + cost | |
| `system_feedback` | human / meta-review feedback | |
| `events` | structured event log (`tool_call`, …) | `payload` is a subdocument |
| `spans` | tracing spans | `attrs` merged server-side on `end` |
| `embeddings_meta` | which hypotheses are embedded with which model | unique `(hypothesis_id, model)` |
| `hypothesis_vectors` | Voyage vectors for dedup/similarity | Atlas only (SQLite uses FAISS files) |
| `library` | evidence passages (Europe PMC and uploaded documents) | Atlas only, see §5 |
| `attachments_meta` | one doc per uploaded file (metadata only) | SQLite table `attachments`. The bytes are in the GridFS `attachments` bucket (§12) |
| `timeline` | per-session progress messages, unique `(session_id, seq)` | SQLite table `timeline` (§13) |
| `timeline_counters` | per-session `seq` allocator | Atlas only |
| `analysis_reports` | one data-analysis report per session, `_id = session_id` | plots are in the GridFS `plots` bucket |
| `analysis_points` | survival points per `(session_id, candidate_key)` | feeds the UI's `dataPoints` |
| `syntheses` | the final overview and sources, `_id = session_id` | referenced from the session as `db:syntheses/<id>` |

Citations and evidence are fields on the rows: `hypotheses` (`citations`,
`data_evidence`) and `reviews` (`evidence`, `assumptions`). Rows written before
SQLite migration `0008_results_on_rows.sql` read back as empty.

**GridFS buckets** (binary content; `AsyncGridFSBucket`, in `storage/atlas/blobs.py`):

| Bucket | Holds | Collections created |
|---|---|---|
| `attachments` | the uploaded files | `attachments.files`, `attachments.chunks` |
| `plots` | the PNG survival plots | `plots.files`, `plots.chunks` |

With a collection prefix (tests) the bucket name is prefixed too. On SQLite both
buckets are rows of the `blobs` table, keyed by bucket name. Callers use the
`storage.repos.blobs` repo (`put`, `get`, `delete`) and never touch GridFS directly.

**SQLite migrations for these** (`storage/migrations/`): `0006_blobs_attachments`
(`blobs`, `attachments`), `0007_timeline`, `0008_results_on_rows`, `0009_analysis`
(`analysis_reports`, `analysis_points`), `0010_syntheses`.

### Indexes (`co_scientist/storage/atlas/indexes.py`)

- **B-tree.** These mirror `schema.sql`, plus:
  - `tasks_queue_v2` `(session_id, status, priority, created_at, _id)` covers the claim sort;
  - **unique partial `tasks_idempotency_key`**;
  - `mat_hyp_a` / `mat_hyp_b`;
  - `hv_sess`;
  - `library_pmcid`;
  - `att_sess` and unique `att_dedupe` `(session_id, sha256, filename)` on `attachments_meta`, so the same file twice in one session is stored once;
  - unique `timeline_sess_seq` `(session_id, seq)`;
  - unique `analysis_pts_key` `(session_id, candidate_key)`.
- **Search indexes**, declared as `SearchIndexSpec` entries in `SEARCH_INDEX_SPECS`:

| Name | Collection | Type | Definition |
|---|---|---|---|
| `library_text` | `library` | Atlas Search | `lucene.english` on `text` and `title`; `kind`, `pmcid` as token; `year` number |
| `library_vec` | `library` | Vector Search, **Automated Embedding** | `autoEmbed` on `text`, model `voyage-4`; filters `kind`, `year` |
| `library_text_v2` | `library` | Atlas Search | `library_text` plus `session_id` and `source` as token fields (§14) |
| `library_vec_v2` | `library` | Vector Search, Automated Embedding | `library_vec` plus `session_id` and `source` filter fields (§14) |
| `hyp_vec` | `hypothesis_vectors` | Vector Search | `embedding`, `numDimensions = embeddings.dim` (1024), `dotProduct`; filter `session_id` |

To add a search index, append a `SearchIndexSpec(collection, name, type,
definition_fn)` to `SEARCH_INDEX_SPECS`. `ensure_indexes` creates it if it
is missing. Use `wait_for_search_index(coll, name)` when a test or script needs
it queryable.

---

## 4. Adding or changing a repo function

Say the UI needs `hypotheses.search_titles(conn, session_id, text) -> list[Hypothesis]`.

1. **SQLite:** add it to `co_scientist/storage/sqlite/hypotheses.py`. Follow
   the style there: `async with conn.execute(...) as cur`, and `await
   conn.commit()` after writes.
2. **Atlas:** add the same signature, taking `conn: AtlasConn`, to
   `co_scientist/storage/atlas/hypotheses.py`. Use `conn.coll("hypotheses")`
   and the module's `_from_doc` / `_to_doc` mappers.
3. **Dispatcher:** add one line to `co_scientist/storage/repos/hypotheses.py`:
   `search_titles = dual(_sql.search_titles, _atlas.search_titles)`.
4. **Test:** write it in `co_scientist/tests/unit/test_repos.py` against the
   `any_conn` fixture. It runs on SQLite by default, and on both backends with
   `CO_SCI_ATLAS_TESTS=1`.
5. **New collection?** Add its B-tree indexes to `BTREE_INDEXES` in
   `indexes.py`, plus a SQLite migration in `storage/migrations/`.

### Parity rules learned the hard way

All of these are encoded in the existing code. Copy the patterns.

- **Timestamps:**
  - BSON dates are **millisecond** precision. Compare at ms granularity in tests; `_now()` in `test_repos.py` truncates.
  - Functions that return **dicts** (not models) must return timestamps as `.isoformat()` strings (`…+00:00`), never `datetime`. SQLite stores text, and the CLI, web and MCP JSON output depends on it.
- **`INSERT OR IGNORE` → `insert_one`** with `DuplicateKeyError` mapped to `False`.
- **`UPDATE … rowcount > 0` → `matched_count > 0`**, not `modified_count`. SQLite counts a same-value rewrite as applied.
- **`LIMIT`:**
  - Mongo `limit(0)` means *unlimited*, and `$limit: 0` is an error. Guard `limit <= 0 → []`.
  - SQLite `LIMIT -1` means unlimited, but no caller passes negatives.
- **`NULL` ordering:** Mongo sorts nulls last on descending, like SQLite. Add `_id` as a final tie-break for deterministic order.
- **Values starting with `$` inside pipeline updates** must be wrapped in `{"$literal": …}`, as in `tasks.fail`'s `last_error` and the spans attrs merge.
- **Atomic multi-step updates** go server-side, as pipeline updates or `find_one_and_update`, not read-then-write in Python.
- **Never put `str(exc)` from a PyMongo error into user-visible or LLM-visible text.** It can contain host details. Use a fixed message plus `type(e).__name__`.

### Concurrency and transactions (already implemented)

- **`tasks.claim_one`:** a single `find_one_and_update` on `{session_id, status: "pending"}`, sorted by `priority, created_at, _id`. Two workers can never claim the same task; tested with 10 concurrent claims.
- **`tasks.fail`:** one atomic pipeline `find_one_and_update` that increments attempts and chooses dead or pending server-side.
- **`tasks.reclaim_expired_leases`:** server-side pipeline updates (dead-letter, then requeue).
- **`tournaments.record_match_result`:** a multi-document transaction (`start_session` + `with_transaction`) that does the whole Elo update. Inside it, it reads both hypotheses' current `elo` and `matches_played`, computes `update_elo`, inserts `elo_journal{_id: match_id}`, updates both hypotheses (`$set elo`, `$inc matches_played`), then writes the in-transaction before/after values onto the match row. Callers never pass precomputed Elo. When two overlapping transactions update the same hypothesis, the loser gets a `WriteConflict` (a `TransientTransactionError`); `with_transaction` re-runs the callback, which re-reads the committed values. Do not catch `WriteConflict` yourself. It returns an `AppliedElo`, or `None` when `match_id` is already journaled (nothing written), and raises `ValueError` (nothing written) if a hypothesis is missing. Guarantees: on Atlas, concurrent matches lose no update. On SQLite, `record_match_result` calls are serialised per connection (reads happen after `BEGIN IMMEDIATE`, under a per-connection lock), but other writers sharing that connection use implicit transactions without the lock and can still interleave with its transaction; with 4 workers on one connection a concurrent write can join it. This predates the fix. A failed `BEGIN IMMEDIATE` is not rolled back, so it cannot discard another writer's uncommitted work. Tested for idempotency, rollback on a mid-transaction failure, retry on `TransientTransactionError`, and 6 concurrent matches on one hypothesis (the journal rows must chain and Elo must stay zero-sum).

---

## 5. Evidence library (Atlas only)

This is the passage-level evidence store. The code is in `co_scientist/library/`
and `co_scientist/storage/atlas/library.py`.

### Data model

Each document in `library` is one **passage**:

```
_id = anchor_id   e.g. "PMC13612970#s3.p8", "PMC13612970#alz71873-fig-0004", "PMC1#abstract.p1"
pmcid, title, doi, year, journal       (paper metadata, repeated per passage)
kind      "abstract" | "paragraph" | "figure" | "table"
section   "Results > Microglial uptake"  (heading path)
label     "Figure 4" | None
text      passage text (≤ library.max_passage_chars, 2000; long paragraphs split .1, .2)
ordinal   position in the paper
url       https://europepmc.org/article/PMC/<pmcid>#<fragment>
ingested_at
```

Anchor rules (`co_scientist/library/jats.py`):

| Element | Anchor |
|---|---|
| figure / table with an XML `id` | `PMC…#<id>` |
| figure / table without an `id` | `#s<i>.f<n>` / `#s<i>.t<n>` |
| paragraph without an `id` | `#s<i>.p<j>`, where `i` is the top-level section (0 outside any section) |
| abstract paragraph | `#abstract.p<j>` |
| repeated anchor within one paper | `~2`, `~3` suffix (stripped from the URL) |

Figures embedded in a paragraph are lifted out as their own passages. Lists,
boxed text and similar wrappers are walked.

### Ingest

- **CLI:** `co-scientist library ingest "<query>" --max-papers 10`, then `co-scientist library stats`.
- **Python:**
  ```python
  from co_scientist.library.ingest import ingest_query
  report = await ingest_query(conn, cfg, "TREM2 microglia", max_papers=10)
  ```
- **What it does:** searches Europe PMC for open-access full-text papers, fetches the JATS XML (at most 4 at a time), parses it, and upserts each passage keyed by its anchor.
- **Re-running does not duplicate:** ingest upserts passages by anchor. See `failed` below for the partial-write caveat.
- **`IngestReport` fields:**
  - `papers`, `passages`;
  - `skipped`: no full text or unparseable XML;
  - `already_present`;
  - `failed`: `"pmcid: ErrorType: msg"`, for network or DB errors. Re-running retries
    them, but a partial write can leave the paper marked present, so a retry may count
    it as `already_present` and skip the missing passages. Check `library stats` after a
    failure.
- **Embeddings:** with `library.embedding = "auto"` (the default), Atlas Automated Embedding embeds the passages server-side, so the app sends none.
- **Swappable storage:** ingest writes through the `LibraryStore` protocol (`has_paper`, `upsert_passages`), so another store can be dropped in.

### Search

```python
from co_scientist.library.search import hybrid_search
hits = await hybrid_search(conn, cfg, "microglial phagocytosis", k=8, kind="figure")  # kind optional
# -> list[LibraryHit(anchor_id, pmcid, title, section, kind, label, text, url,
#                    fused_score, rerank_score)]
```

How it works:
- **Hybrid query:** one aggregation whose first stage is `$rankFusion`, with a `text` branch (`$search` on `library_text`) and a `vector` branch (`$vectorSearch` on `library_vec` with `query: {text: …}`), weighted 1:1.
- **Rerank:** the fused hits are reranked by Voyage `rerank-2.5`. With no key, or if the rerank call fails, hits pass through with `rerank_score=None`.
- **Version note:** this works on the cluster's MongoDB 8.0.34. `$scoreFusion` and Atlas native rerank are not available there.

From the command line: `co-scientist library search "<query>" --k 8 --kind figure`.

### Agent tool

`search_library` (`co_scientist/tools/builtins/library.py`) is registered only
when `backend = "atlas"`. It is allowlisted for Generation, Reflection and
Evolution, and their prompts list it among the search tools.

- **Input:** `{query, k (1–20, default 8), kind?}`.
- **Output:** `{query, n, hits: [{anchor_id, pmcid, title, section, kind, label, text (≤800 chars), url, score, rerank_score}]}`.
- **Errors:** never raises into the agent loop. It returns `is_error` with a readable message for:
  - a non-Atlas backend;
  - an empty library;
  - an index that is still building (live observation: `OperationFailure` code 8, "cannot query search index … while in state INITIAL_SYNC");
  - any `PyMongoError`.

---

## 6. Hypothesis vectors (dedup and similarity)

Agents get a store from `make_vector_store(cfg, conn, session_id, dim)`
(`co_scientist/vectors/factory.py`):
- **SQLite backend:** `FaissStore`.
- **Atlas backend:** `AtlasVectorStore` (`co_scientist/vectors/atlas_store.py`). Vectors come from Voyage `voyage-3-large` (1024-d) and are stored in `hypothesis_vectors`.

How `AtlasVectorStore` works:
- **`search`** runs `$vectorSearch` on `hyp_vec`, filtered by `session_id`. Scores are converted back to cosine (`2*score - 1`).
- **Recent vectors:** every `add` stamps `updated_at` (set on every write) on the vector doc, and
  `load_or_create` seeds the 30 s lag window from it. A store built by another worker (the
  dedup query and the commit each build their own) therefore still scores a peer's fresh write
  exactly and merges it over a full but stale index result.
- **Fallback:** it falls back to exact in-memory search when the index returns too few hits or errors. A missing index returns 0 hits without an error.
- **`similarity` / `cosine_matrix` / `ids`** run in memory, for Ranking's pairing and Proximity's clustering.
- **Dedup threshold:** `vectors.dedup_cosine_threshold = 0.92`. Measured with real Voyage: a near-duplicate scored 0.989 and an unrelated hypothesis 0.684.

---

## 7. Tests

| Command | What runs |
|---|---|
| `uv run pytest -q` | ~550 tests, offline, SQLite only; Atlas tests skipped. This is what CI runs. |
| `CO_SCI_ATLAS_TESTS=1 uv run pytest -q` | Everything, plus every `any_conn` repo test on Atlas, plus `co_scientist/tests/atlas/`. Test fixtures build B-tree indexes only, so no search-index waits. About 5 min; 820 passed on 2026-10-25. |
| `CO_SCI_ATLAS_TESTS=1 CO_SCI_ATLAS_SEARCH_TESTS=1 uv run pytest -q` | Also runs the `atlas_search` tests (hybrid search, vector store), which wait for Atlas Search index builds: several minutes each. Run when search code changes. |

- **Isolation:** Atlas tests use a fresh `t<ulid>_` collection prefix inside `biocurate` and drop *only* those collections on teardown. The guard is in `co_scientist/tests/atlas_support.py` (regex `^t[0-9a-z]{10,}_$`); real collections are never touched.
- **Secrets:** unit tests never read your `.env`; an autouse fixture strips it. Atlas tests opt back in explicitly.
- **Known flake:** an occasional transient Atlas "Error connecting to Search Index Management service" (code 125) during index creation. A rerun passes.

---

## 8. Integrating the in-flight features

The UI, uploads, stats and citation-location features currently use
placeholders for database access. Here is how each should connect.

### Researcher UI (prompt input, browsing sessions and hypotheses)

The FastAPI app (`co_scientist/web/app.py`) already uses repos only. The HTML
pages are `/`, `/sessions/new`, `/sessions/{id}`,
`/sessions/{id}/hypotheses/{hid}` and `/sessions/{id}/overview`. The JSON routes
for the React app are listed in §11a and documented in full in
[frontend-api.md](frontend-api.md). Useful reads:
- `sessions.list_with_stats(conn, limit=…)`;
- `hypotheses.list_for_session(conn, sid)`, `top_by_elo`;
- `reviews.list_for_hypothesis`;
- `tournaments.list_for_hypothesis`;
- `events.recent`;
- `obs/metrics.session_metrics`.

Replace each placeholder with one of these. If a needed query doesn't exist,
add a repo function as described in §4.

### Attached material

Implemented: see §12 (upload flow), §14 (scoped library search) and
[frontend-api.md](frontend-api.md) for the routes. Documents become session-scoped
library passages (`source: "upload"`, `session_id`), so agents find and cite them
through `search_library`. Raw files are in the GridFS `attachments` bucket, with
metadata in `attachments_meta`. Don't store large binaries inside passage documents.

### Statistical analysis on the material

- **Simple aggregates** (counts per kind, year or section, passages per paper,
  citation counts): add repo functions using Mongo aggregation pipelines on the
  Atlas side. That's another visible Atlas use.
- **Real statistics:** compute in Python, but **store the results through a repo**
  (new collection plus a SQLite table, with both implementations).

### Exact citation location ("which line contributed")

Line-level citation came in with the `feature/cite-lines` work (PR #1). The pieces:

- **Fetched text is numbered.** `web_fetch` prefixes each line it returns with `[L1]`, `[L2]` and so on.
- **Agents are told to cite lines.** Agents that have `web_search` get `SYSTEM_CITATION_POLICY` (`co_scientist/safety/quoting.py`) appended to their system prompt. It asks them to cite as `[S#, L#-L#]`.
- **Citations carry the range.** `CitedPaper.line_range` (`models/hypothesis.py`) and `Evidence.line_range` (`models/review.py`) are optional strings, for example `"L3-L5"`.
- **The verifier ignores line markers.** `citation_verifier._normalize` strips `[S#, L#]` markers before checking that an excerpt appears at its URL.

**Storage impact: none beyond the row fields.** Citations and evidence are stored on the `hypotheses` and `reviews` rows on both backends (`citations`, `data_evidence`, `evidence`, `assumptions`), so `line_range` is persisted with them. If the UI needs to *query* citations, for example "every hypothesis citing PMC123", add a collection or table through a repo (§4) rather than parsing the rows in the UI.

**Library passages.** Every `search_library` hit also has a stable `anchor_id`, the full passage `text`, and a `url` that carries the `#fragment`. They are available if citation tracing wants passage-level anchors in addition to line numbers.

---

## 9. Merge checklist

- [ ] Git did not record `storage/repos/*.py -> storage/sqlite/*.py` as a rename. An edit made
      to `storage/repos/<m>.py` on `main` will not follow the move: port it by hand into
      `storage/sqlite/<m>.py`, add the Atlas twin in `storage/atlas/<m>.py`, and add a
      `dual(...)` line in `storage/repos/<m>.py`. `test_repo_parity` fails if any of these is missed.
- [ ] Rebase feature branches onto `feature/MongoDB`. It moved
      `storage/repos/*` into `storage/sqlite/*` and rewrote call sites in
      `cli.py`, `web/app.py`, `mcp/session_server.py`, `agents/supervisor.py`,
      `obs/metrics.py` and `orchestrator/termination.py`.
- [ ] Replace placeholders with repo calls. Run `uv run pytest -q`:
      `test_repo_parity` and `test_no_raw_sql` must pass.
- [ ] Run `CO_SCI_ATLAS_TESTS=1 uv run pytest -q` once, against Atlas.
- [ ] Run `co-scientist -c <atlas overlay> init` on the real cluster after
      merging. It creates any new indexes.
- [ ] Keep the shipped runtime default on Atlas; use a local config overlay to select SQLite when needed.

## 10. Live verification (2026-10-24)

Two short research sessions on the real cluster (provider `gemini`, $3 cap each):

| | Session 1 | Session 2 (after fixes) |
|---|---|---|
| Spend | $0.64 | $0.83 |
| Tasks | 11 done, 0 stuck/dead | 1 dead (Generation budget share exhausted), 0 stuck |
| `search_library` calls | 5, all errored (`db=None` bug) | **19 ok, 0 errors; 39 distinct anchors returned** |
| Hypotheses citing library anchors | 0 | **1 of 1** (`PMC13388181#F2`, `PMC13388181#s3.p5`) |
| Valid tournament matches | 0 (verdicts truncated at 2048 tokens) | 0 (only 1 hypothesis, so nothing to rank) |
| Atlas errors | none | none |

Fixes landed between the runs:
- tools now receive the agent's DB connection, both in-process and in the MCP subprocess (`618911c`, `24bb2f9`);
- `[ranking] max_output_tokens` defaults to 8192 (`24dc274`).

Still not seen in a real run:
- **Elo transaction:** it has only been verified by the live-Atlas tests (idempotency, rollback, transient retry, concurrent matches). Concurrent matches on one hypothesis no longer lose updates: an earlier version `$set` an Elo computed before the debate, so overlapping matches overwrote each other's delta. The update is now computed inside the transaction (see section 4). To exercise it in a session, raise the budget or the Generation share in `[budget_shares]` so at least 2–3 hypotheses reach the tournament. Generation's 19 library searches used its whole 0.72 share in run 2.
- **Voyage rerank:** it hit `RateLimitError` 21 times in run 2 and fell back to fused order, because accounts without a payment method get very low rate limits. A payment method was added the same day, and 10 back-to-back `rerank-2.5` calls then all succeeded in 3 s.
- **Orphan artifact:** one hypothesis artifact was written to disk with no DB row or vector. It was probably a dedup-suppressed near-duplicate, but no event records it.

## 11. Known gaps (deliberately deferred)

- **Hybrid search:** doesn't request `scoreDetails` (useful for showing fusion in the Atlas UI).
- **Dedup:** emits no log line when it flags a duplicate.
- **Ingest:** a partially written paper is treated as present on re-ingest and never back-filled. A non-404 HTTP error and a parse crash both land in `failed`.
- **`search_library`:** in `library.embedding = "client"` mode (unused; default is `auto`), embedder errors inside hybrid search aren't caught by the tool.
- **Indexes:** the old `tasks_queue` index is now a redundant prefix of `tasks_queue_v2`.
- **SQLite write isolation:** `record_match_result` is serialised only against itself on a shared connection. Other repos write through implicit transactions without a lock, so they can interleave with it (and with each other). Follow-up: a connection-wide write lock, or one connection per worker.
- **Not used:** Atlas Stream Processing.

---

## 11a. API routes (JSON)

All under the `/api/sessions/{session_id}` router unless noted. The router checks
the id against `^ses_[0-9A-Z]{26}$` (400 otherwise), and any `PyMongoError` becomes
a 503 with the fixed text `database unavailable` (the real error is logged by type
only). Details, examples and TypeScript types: [frontend-api.md](frontend-api.md).

| Route | Reads or writes | Repo |
|---|---|---|
| `POST /api/sessions` (multipart: `question`, `files`, `budget_usd`) | creates the session, stores attachments, starts the run | `attachments.store`, `sessions` |
| `GET ""` (the session row) | `sessions` | `sessions.fetch` |
| `GET /research` | ranked hypotheses in the React `ResearchSession` shape | `hypotheses`, `analysis`, `attachments`, library journals (Atlas) |
| `GET /timeline?after_seq=` | `timeline` | `timeline.list_for_session` |
| `GET /events` (SSE) | event replay plus the timeline watcher, §13 | `events.recent`, `storage/watch.py` |
| `GET /overview`, `/sources`, `/synthesis` | `syntheses` (falls back to legacy JSON files on disk) | `syntheses.fetch` |
| `GET /analysis` | `analysis_reports`, with each plot's `blob_id` replaced by a `url` | `analysis.fetch_report` |
| `GET /plots/{name}` | PNG from the `plots` bucket | `blobs.get` |
| `GET /attachments` | `attachments_meta` | `attachments.list_for_session` |
| `GET /metrics` | counters | `obs/metrics` |
| `POST /pause`, `/resume`, `/abort`, `/feedback` | session status, feedback | `sessions`, `feedback` |

Error codes: 400 malformed id or intake rejection, 404 not found, 413 oversize or
over quota, 422 missing form field, 503 database unavailable.

## 12. Uploads, attachments and the planning inventory

**Flow** (`POST /api/sessions`, or `co-scientist run --attach FILE`, repeatable):

1. `attachments/intake.py` `accept_uploads` validates names and types (`.pdf`,
   `.docx`, `.csv`, `.txt`, `.zip`), unzips safely and tracks the unpacked byte
   budget. Rejections raise `IntakeError` with status 400 (bad request, one file
   over `max_file_mb`, too many files, corrupt zip) or 413 (zip too large, too many
   entries or members).
2. `Supervisor.prepare_session` creates the session row first, then
   `attachments/store.py` `store_incoming` checks the quotas
   (`AttachmentQuotaError`, mapped to 413), writes each file to the GridFS
   `attachments` bucket and inserts an `attachments_meta` row (`status: "stored"`).
3. On Atlas, documents (PDF, DOCX) are parsed by `library/uploads.py`
   `ingest_attachment` into library passages, scoped to the session (§14). The
   attachment becomes `ingested`, or `failed` with a fixed message. A timeline
   message of kind `attachments_received` lists what was stored and skipped.
4. The planning step receives an inventory (`attachments/inventory.py`
   `build_inventory`): per attachment `id`, `filename`, `kind`, `size`, and for
   tabular files the `header` and up to 3 `sample_rows` (the first 64 KB is read;
   cells are cut at 100 characters, columns at 200). The plan decides which
   attachments go to `ProfileDataset`.
5. `DataAnalysisAgent` copies the chosen attachments into a temporary directory,
   profiles them, and stores the report (`analysis_reports`), per-candidate points
   (`analysis_points`) and plots (GridFS `plots`). Nothing is written under
   `data/artifacts/`.

**Limits** (`[attachments]` in config, `AttachmentsCfg`):

| Key | Default | Meaning |
|---|---|---|
| `max_files` | 5 | files per request |
| `max_file_mb` | 25 | one uploaded file |
| `max_unzipped_mb` | 512 | total unpacked bytes per request |
| `max_zip_members` | 50 | files taken from zips per request |
| `max_session_mb` | 512 | stored bytes per session |
| `max_total_mb` | 2048 | stored bytes across all sessions |

**Retention.** There is no TTL. Clean up by hand:

```bash
co-scientist attachments prune --older-than 30          # dry run: lists what would go
co-scientist attachments prune --older-than 30 --yes    # delete
```

Prune deletes the GridFS file, the metadata row and (Atlas, documents) the
session-scoped library passages.

## 13. Timeline and the live stream

`timeline` holds the messages shown in the UI. `seq` is allocated per session
(SQLite: `MAX+1` inside `BEGIN IMMEDIATE`; Atlas: the `timeline_counters`
collection) and the unique `(session_id, seq)` index backs it. Agents post with
`co_scientist/timeline.py` `post()`, which never raises: it appends the row, then
publishes `timeline_message` on the in-process bus. The wire shape is
`to_payload` (`seq`, `ts` in epoch ms, `role`, `agent`, `kind`, `title`,
`body_markdown`, `refs`).

**`GET /api/sessions/{id}/events`** merges two sources into one SSE stream:

- the in-process bus (same process as the poster), and
- `storage/watch.py` `timeline_after`: on Atlas a **change stream** on `timeline`
  (so a message inserted by another process, such as `co-scientist run` in a second
  terminal, still reaches the browser); on SQLite a poll. Not a `dual()` repo,
  because it is an async generator.

`timeline_message` events carry `id: <seq>` and the flat timeline payload (not
the bus envelope). The start point is the larger of `?after_seq=` and the
`Last-Event-ID` header. Messages can arrive out of `seq` order and can repeat
across reconnects, so the server dedupes with a set of seen `seq`s (not a
high-water mark, which would drop a late lower one), and clients must also dedupe
and sort by `seq`. If the watcher fails, only its error type is logged and the bus
events continue. Frontend usage: [frontend-api.md](frontend-api.md) section 6.

The change stream needs a replica set, which every Atlas cluster is.

## 14. Library v2 indexes, scoping and the backfill

Uploaded documents share the `library` collection with Europe PMC papers. A
passage carries `source` (`"europepmc"` or `"upload"`) and, for uploads,
`session_id` and `attachment_id`. The paper id of an upload is
`UPLOAD<last 12 chars of the attachment id>` (`upload_pmcid`).

The v1 indexes (`library_text`, `library_vec`) cannot filter on `session_id` or
`source`, so `ensure_indexes` also creates **`library_text_v2`** and
**`library_vec_v2`**, which can (`LIBRARY_TEXT_INDEX_V2`,
`library_vec_definition(scoped=True)`). Config names: `LibraryCfg.scoped_search_index`
and `scoped_vector_index`.

How search picks an index (`library/search.py`):

- `scoped_indexes_ready` checks that both v2 indexes are queryable (cached; a
  negative result is rechecked after 60 s). When ready, `build_hybrid_pipeline(...,
  scoped=True)` filters server-side to Europe PMC passages plus the caller's own
  session uploads.
- Until then, v1 is queried without a filter, over-fetched, and other sessions'
  uploads are dropped in Python (`_visible`). Nothing leaks between sessions in
  either mode; scoped search just returns fuller result lists.

**Owner actions** (search indexes are never updated in place or dropped by code):

1. Run `co-scientist -c <atlas overlay> init` once so the v2 indexes are created.
   Wait for both to reach `queryable` (the app switches over by itself).
2. Once v2 is serving, **drop the v1 indexes `library_text` and `library_vec`** in
   Atlas by hand to stop paying for them. Do this only after both v2
   indexes are queryable: until then the app falls back to v1, and a dropped v1
   index would make library search fail.
3. Optional: backfill `source` on old passages. Search treats a passage without
   `source` as Europe PMC, so this is only tidiness:

```bash
uv run python scripts/backfill_library_source.py -c atlas.toml --dry-run   # count
uv run python scripts/backfill_library_source.py -c atlas.toml             # set source=europepmc
```

It touches only documents lacking `source`, so re-running is a no-op. `atlas.toml`
is a config overlay with `[storage] backend = "atlas"`.

## 15. Docs for the front end

[frontend-api.md](frontend-api.md) has every route with request and response
examples, error codes, the SSE contract, and the TypeScript types the UI needs
(`TimelineMessage`, `AttachmentInfo`, `AnalysisReport`).

