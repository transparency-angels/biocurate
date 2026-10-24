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
backend = "atlas"          # default "sqlite"
atlas_db = "biocurate"     # the DB user only has readWrite here
atlas_prefix = ""          # collection-name prefix; tests set a unique one
```

`.env` needs `MONGODB_URI` (`mongodb+srv://<user>:<password>@<cluster>/`) and
`VOYAGE_API_KEY`. The default stays `sqlite` so CI and the offline tests need
no network.

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
| `hypotheses` | `Hypothesis` | ids hash in the session id (`ids.hypothesis_id`), so there are no cross-session collisions. **`citations` are not in the row**; they live in the hypothesis JSON artifact on disk, as on SQLite |
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
| `library` | evidence passages | Atlas only, see §5 |

### Indexes (`co_scientist/storage/atlas/indexes.py`)

- **B-tree.** These mirror `schema.sql`, plus:
  - `tasks_queue_v2` `(session_id, status, priority, created_at, _id)` covers the claim sort;
  - **unique partial `tasks_idempotency_key`**;
  - `mat_hyp_a` / `mat_hyp_b`;
  - `hv_sess`;
  - `library_pmcid`.
- **Search indexes**, declared as `SearchIndexSpec` entries in `SEARCH_INDEX_SPECS`:

| Name | Collection | Type | Definition |
|---|---|---|---|
| `library_text` | `library` | Atlas Search | `lucene.english` on `text` and `title`; `kind`, `pmcid` as token; `year` number |
| `library_vec` | `library` | Vector Search, **Automated Embedding** | `autoEmbed` on `text`, model `voyage-4`; filters `kind`, `year` |
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
- **`tournaments.apply_elo_update`:** a multi-document transaction (`start_session` + `with_transaction`). It inserts `elo_journal{_id: match_id}`, updates both hypotheses, then updates the match. A duplicate `match_id` returns `False` with nothing written. Tested for rollback on a mid-transaction failure, and for retry on `TransientTransactionError`.

---

## 5. Evidence library (Atlas only)

This is the "traceable evidence" part. The code is in `co_scientist/library/`
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
Evolution. Their prompts tell them to cite the returned `anchor_id`.

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
| `CO_SCI_ATLAS_TESTS=1 uv run pytest -q` | Everything, plus every `any_conn` repo test on Atlas, plus `co_scientist/tests/atlas/` (indexes, library store, hybrid search, vector store). About 15 min, mostly search-index builds. 592 passed on 2026-10-24. |

- **Isolation:** Atlas tests use a fresh `t<ulid>_` collection prefix inside `biocurate` and drop *only* those collections on teardown. The guard is in `co_scientist/tests/atlas_support.py` (regex `^t[0-9a-z]{10,}_$`); real collections are never touched.
- **Secrets:** unit tests never read your `.env`; an autouse fixture strips it. Atlas tests opt back in explicitly.
- **Known flake:** an occasional transient Atlas "Error connecting to Search Index Management service" (code 125) during index creation. A rerun passes.

---

## 8. Integrating the in-flight features

The UI, uploads, stats and citation-location features currently use
placeholders for database access. Here is how each should connect.

### Researcher UI (prompt input, browsing sessions and hypotheses)

The FastAPI app (`co_scientist/web/app.py`) already uses repos only. Existing
routes include `/sessions/new`, `/sessions/{id}`,
`/sessions/{id}/hypotheses/{hid}`, `/api/sessions/{id}`,
`/api/sessions/{id}/metrics`, `/api/sessions/{id}/events`, and the
pause/resume/abort/feedback endpoints. Useful reads:
- `sessions.list_with_stats(conn, limit=…)`;
- `hypotheses.list_for_session(conn, sid)`, `top_by_elo`;
- `reviews.list_for_hypothesis`;
- `tournaments.list_for_hypothesis`;
- `events.recent`;
- `obs/metrics.session_metrics`.

Replace each placeholder with one of these. If a needed query doesn't exist,
add a repo function as described in §4.

### Attached material ("attach and point material")

Recommended: turn attachments into **library passages**. They then become
searchable (text, vector, hybrid, rerank) and citable by agents through
`search_library`, at no extra cost.
- Parse the upload into `Passage` objects.
- Give each a stable anchor such as `UPLOAD<id>#p3` or `UPLOAD<id>#page2.p1`.
- Store them with `storage.atlas.library.upsert_passages(conn, meta, passages)`.
- Add a field such as `source: "upload" | "europepmc"` and, if uploads are per
  session, `session_id`. Add both as `filter` fields in `library_vec_definition`
  and as token fields in `LIBRARY_TEXT_INDEX`, so searches can be scoped.
- Store the raw file on disk under the session artifacts dir, as other
  artifacts are, or in a new collection through a repo. Don't store large
  binaries inside passage documents.

### Statistical analysis on the material

- **Simple aggregates** (counts per kind, year or section, passages per paper,
  citation counts): add repo functions using Mongo aggregation pipelines on the
  Atlas side. That's another visible Atlas use.
- **Real statistics:** compute in Python, but **store the results through a repo**
  (new collection plus a SQLite table, with both implementations).

### Exact citation location ("which line contributed")

There is already a base to build on:
- every library hit carries `anchor_id` plus the full passage `text`;
- agents are told to cite the anchor;
- `CitedPaper` (`co_scientist/models/hypothesis.py`) has `url` and an optional `excerpt`;
- `Evidence` (`co_scientist/models/review.py`) has `claim`, `url` and `excerpt`.

Suggested extension, so citations, the library and the UI share one shape:
1. Add optional `anchor_id: str | None` and `char_start/char_end: int | None`
   (or `sentence_index`) to `CitedPaper` and `Evidence`.
2. When an agent quotes an excerpt from a `search_library` hit, resolve it to
   offsets inside that passage's `text`. A normalised substring match is enough.
3. `co_scientist/safety/citation_verifier.py` exists but is not wired in yet.
   It checks that an excerpt appears at its URL, and can do the same against
   the library passage (no fetch needed).
4. The UI renders `url` (it already includes `#fragment`) and highlights
   `text[char_start:char_end]`.

Citations are stored in the hypothesis/review JSON artifacts, not the DB rows.
If the UI needs to query them, add a collection or table through a repo rather
than parsing artifacts in the UI.

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
- [ ] Don't commit a `backend = "atlas"` change to `config/default.toml`; use an overlay.

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
- **Elo transaction:** it has only been verified by the live-Atlas tests (idempotency, rollback, transient retry). To exercise it in a session, raise the budget or the Generation share in `[budget_shares]` so at least 2–3 hypotheses reach the tournament. Generation's 19 library searches used its whole 0.72 share in run 2.
- **Voyage rerank:** it hit `RateLimitError` 21 times in run 2 and fell back to fused order. Accounts without a payment method get very low rate limits. Add one on the Voyage dashboard before the demo; the free token allowance still applies.
- **Orphan artifact:** one hypothesis artifact was written to disk with no DB row or vector. It was probably a dedup-suppressed near-duplicate, but no event records it.

## 11. Known gaps (deliberately deferred)

- **Hybrid search:** doesn't request `scoreDetails` (useful for showing fusion in the Atlas UI).
- **Dedup:** emits no log line when it flags a duplicate.
- **Ingest:** a partially written paper is treated as present on re-ingest and never back-filled. A non-404 HTTP error and a parse crash both land in `failed`.
- **`search_library`:** in `library.embedding = "client"` mode (unused; default is `auto`), embedder errors inside hybrid search aren't caught by the tool.
- **Indexes:** the old `tasks_queue` index is now a redundant prefix of `tasks_queue_v2`.
- **Not used:** Atlas Stream Processing.
