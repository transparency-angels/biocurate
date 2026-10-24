# Atlas Backend, Vector Dedup, and Evidence Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run biocurate on MongoDB Atlas, with Atlas Vector Search + Voyage for hypothesis dedup and similarity, and a passage-level evidence library behind Atlas Search, `$rankFusion` hybrid search and Voyage rerank, exposed to agents as `search_library`.

**Architecture:** A new `[storage] backend = "sqlite" | "atlas"` setting. `storage.db.connect(cfg)` returns either an `aiosqlite.Connection` or an `AtlasConn`. The SQLite repos move to `storage/sqlite/`, their Atlas twins live in `storage/atlas/`, and each `storage/repos/<name>.py` becomes a thin dispatcher that routes on the connection type, so callers and the 418 offline tests keep their imports. Vectors go behind a `VectorStore` protocol: FAISS for SQLite, `AtlasVectorStore` for Atlas. The library is Atlas-only.

**Tech Stack:** Python 3.11+, PyMongo async API (`pymongo.AsyncMongoClient`, pymongo ≥ 4.13, **not Motor**), certifi, voyageai, httpx, stdlib `xml.etree.ElementTree`, pytest + pytest-asyncio.

**Spec:** Decisions 1–3 from the hackathon kickoff, restated here because there is no separate spec file:
1. Add `[storage] backend`. Move the raw SQL outside `storage/repos/` (in `mcp/session_server.py`, `bench/runner.py`, `obs/metrics.py`, `cli.py`, `agents/supervisor.py`, `orchestrator/termination.py`, `web/app.py`) into repos. Implement the core repos on Atlas with PyMongo async. Skip the `bench_*` tables (bench stays SQLite-only). Use a multi-document transaction for `tournaments.apply_elo_update`, `find_one_and_update` for the task claim, and a unique index on `idempotency_key`.
2. Atlas Vector Search + Voyage instead of FAISS for hypothesis duplicate detection and for the similarity score Ranking uses for pairing.
3. A `library` collection of papers split into passages, with figure, table and paragraph anchors from Europe PMC JATS full text. It gets an Atlas Search index, a vector index, `$rankFusion` hybrid search and Voyage rerank, exposed as the agent tool `search_library`.

Pitch: *"an AI co-scientist with traceable evidence, built on Atlas."*

**Cluster facts (probed 2026-10-24):** MongoDB 8.0.34, FCV 8.0, 3-node replica set (M10-class: 2 cores, 1.8 GB). `$rankFusion` runs (8.0 feature flag on). `$scoreFusion` is unavailable. Native rerank is unavailable (it needs 8.3), so rerank calls the Voyage API. An `autoEmbed` vector index definition was **accepted** but had not reached READY after 60 s on an empty collection. Task 2 settles that question. Python on the dev Mac needs `tlsCAFile=certifi.where()`.

## Global Constraints

- `[storage] backend` defaults to `"sqlite"`. `pytest` with no env vars runs the existing 418 tests offline and they must all still pass. Atlas tests are skipped unless `CO_SCI_ATLAS_TESTS=1`.
- Never print, log or commit `MONGODB_URI` or `VOYAGE_API_KEY`. `AtlasConn.__repr__` must not include the URI. Read both through `Secrets` (`.env`).
- The DB user has `readWrite` on database `biocurate` only. All Atlas collections live in `biocurate`. Tests isolate themselves with a collection-name prefix (`storage.atlas_prefix`), never a separate database.
- Async client: `pymongo.AsyncMongoClient(uri, tz_aware=True, tlsCAFile=certifi.where(), appname="biocurate")`.
- Dependencies to add to `pyproject.toml`: `pymongo>=4.13`, `certifi>=2024.2.2`. Keep `faiss-cpu` (the SQLite path still uses it).
- Every public async function in `storage/sqlite/<m>.py` has a same-named twin in `storage/atlas/<m>.py` (enforced by a test). The library has no SQLite twin.
- Document `_id` = the model's existing string id (hypothesis id, task id, …). `events` uses ObjectId.
- Datetimes are stored as BSON dates (UTC) and come back as aware `datetime`. Lease times stay epoch-ms ints, as in SQLite.
- Ask the project owner before anything that costs money or is hard to undo: creating search indexes that bill embedding tokens on a large collection, any collection drop outside the test prefix, cluster changes.
- Ruff line length 100; match existing module docstring + comment density.

## Review Focus

1. **Vector index lag:** a hypothesis embedded seconds ago is not yet visible to `$vectorSearch`, so a near-duplicate from the same generation batch slips through. Expected: it is still caught. → `test_atlas_vector_search_sees_just_added_vector` (Task 7).
2. **Score normalization:** Atlas `vectorSearchScore` for `dotProduct` is `(1 + cos) / 2`, not cosine, so a 0.92 dedup threshold compared against the raw score silently changes meaning. Expected: `search()` returns cosine. → `test_atlas_vector_search_returns_cosine` (Task 7).
3. **Re-applied Elo update** (worker crash and retry, transaction retry): expected no double count. → `test_apply_elo_update_is_idempotent` parametrized over both backends (Task 5).
4. **Concurrent claims:** two workers polling at once; expected each task leased exactly once. → `test_claim_one_concurrent_claims_are_exclusive` (Task 5).
5. **Messy JATS:** paragraphs without `id`, nested `<sec>`, a `<table-wrap>` with no caption, a non-OA article (`fullTextXML` 404). Expected: stable deterministic anchors, and ingest skips and reports the 404 instead of aborting. → `test_parse_jats_fallback_anchors_are_stable`, `test_ingest_skips_missing_fulltext` (Tasks 8, 9).

---

## Order of work (12–24 h, one MongoDB owner + Claude)

One person owns all MongoDB work. The other three teammates work on the rest of the app, so they must not be blocked by, or block, the storage seam. The order below puts the hackathon requirement first (Atlas as the core store), then the work that scores the most features per hour.

| # | Tasks | Unlocks | Est. |
|---|---|---|---|
| 1 | 2 (spike first, then client/config/indexes) | answers the autoEmbed / `$rankFusion` questions | ~2 h |
| 2 | 1 → 3 → 4 → 5 | **required:** the app runs on Atlas | ~8 h |
| 3 | 8 → 9 → 10 | Atlas Search, Vector Search, Hybrid Search, Automated Embedding, Voyage rerank | ~7 h |
| 4 | 6 → 7 | Voyage embeddings + Vector Search for dedup/pairing | ~4 h |
| 5 | 11 | E2E run, README, demo script | ~2 h |

**Cut line:** if time runs short, drop step 4 first. The library already demonstrates Vector Search and Voyage, and the SQLite/FAISS dedup path keeps working because `make_vector_store` falls back to FAISS until Task 7 lands. Never cut step 2.

**Can be handed to a teammate** (pure Python, no MongoDB knowledge needed, testable offline):
- Task 8 (JATS parser)
- Task 6 (VectorStore protocol refactor)
- the dashboard/demo parts of Task 11

**Coordination with teammates:**
- Task 1 touches `cli.py`, `web/app.py`, `mcp/session_server.py`, `agents/supervisor.py`, `obs/metrics.py` and `orchestrator/termination.py`. Announce it, and merge it early so their branches rebase onto it.
- After Task 3, teammates keep importing `storage.repos.*` as before. Any new repo function they add needs an Atlas twin; `test_repo_parity` fails otherwise.

---

### Task 1: Move raw SQL outside `storage/` into repos (SQLite only)

**Files:**
- Modify: `co_scientist/storage/repos/{sessions,hypotheses,tournaments,transcripts,feedback,events}.py`
- Modify: `co_scientist/cli.py:259-325,496`, `co_scientist/web/app.py:337,400`, `co_scientist/mcp/session_server.py:550-590,646,674,957,970,1026`, `co_scientist/agents/supervisor.py:232,470`, `co_scientist/obs/metrics.py:41-155`, `co_scientist/orchestrator/termination.py:97-115`
- Test: `co_scientist/tests/unit/test_repos.py`, new `co_scientist/tests/unit/test_no_raw_sql.py`

`bench/runner.py` is untouched: its SQL is all `bench_*`, which is out of scope. `models/task.py` has no SQL (a grep false positive on `agent.execute`).

**Interfaces:**
- Produces (new repo functions, all `async`, first arg `conn`):
  - `sessions.list_with_stats(conn, *, limit: int | None = None) -> list[dict]`: keys `id, status, research_goal, created_at, updated_at, n_hyps, top_elo`, newest `updated_at` first. (`session_server` renames `n_hyps` → `n_hypotheses` at its call site.)
  - `sessions.ids_created_since(conn, iso_ts: str) -> list[str]`
  - `sessions.ids_for_goal(conn, goal: str) -> list[str]` (newest first)
  - `sessions.set_research_plan(conn, session_id: str, plan: dict) -> None` (also bumps `updated_at`)
  - `hypotheses.count_by_state(conn, session_id) -> dict[str, int]`
  - `hypotheses.elo_range(conn, session_id) -> tuple[float | None, float | None, int]` (lo, hi, n with elo)
  - `hypotheses.top_elo_ids(conn, session_id, k: int) -> list[tuple[str, float]]` (pool states, elo not null, desc)
  - `hypotheses.pool_size(conn, session_id) -> int` (states `in_tournament`, `pinned`)
  - `tournaments.list_for_session(conn, session_id, *, limit: int) -> list[TournamentMatch]` (newest first)
  - `tournaments.list_for_hypothesis(conn, hypothesis_id) -> list[TournamentMatch]`
  - `tournaments.count_by_mode(conn, session_id) -> dict[str, int]`
  - `transcripts.durations_ms(conn, session_id) -> list[float]` (ascending)
  - `feedback.count_meta_review(conn, session_id) -> int` (kind `system_feedback`, source `meta_review`)
  - `events.tool_call_counts(conn, session_id) -> tuple[int, int]` (calls, errors where `payload.is_error` is true)
- Callers use existing functions where they fit: `sessions.fetch(...).final_overview`, `tasks.count_by_status`, `transcripts.usage_summary`, `hypotheses.top_by_elo` (leaderboard). `session_server._count_by` is deleted.

- [ ] **Step 1: Write the failing tests.** In `test_repos.py`, add one test per new function above (e.g. `test_list_with_stats_counts_hypotheses`: 2 sessions, 3 hyps in the first with elos 1200/1250/None → `n_hyps == 3`, `top_elo == 1250`; `test_elo_range_ignores_null`: → `(1200.0, 1250.0, 2)`; `test_tool_call_counts`: 3 `tool_call` events, one with `{"is_error": True}` → `(3, 1)`). Add `test_no_raw_sql.py::test_no_raw_sql_outside_storage`: walk `co_scientist/**/*.py` excluding `storage/`, `bench/`, `tests/`, and assert no line matches `r"\.execute\(\s*[\"']{1,3}\s*(SELECT|INSERT|UPDATE|DELETE)|executescript\(|_count_by\("`, with `re.I` and multi-line tolerant (search file text, not lines).
- [ ] **Step 2: Run.** `uv run pytest co_scientist/tests/unit/test_repos.py co_scientist/tests/unit/test_no_raw_sql.py -q`. Expected: FAIL (AttributeError on new functions; raw-SQL test lists the 7 files).
- [ ] **Step 3: Add the repo functions, then rewrite each call site to use them.** SQL moves verbatim. `metrics.session_metrics` derives `n_reviewed` / `n_in_tournament` from `count_by_state` in Python.
- [ ] **Step 4: Run.** `uv run pytest -q`. Expected: all pass (418 + new).
- [ ] **Step 5: Commit.** `refactor(storage): route all core-table SQL through repos`

---

### Task 2: Atlas connection, config, indexes, and the hour-0 spike

**Files:**
- Create: `co_scientist/storage/atlas/__init__.py`, `co_scientist/storage/atlas/client.py`, `co_scientist/storage/atlas/indexes.py`, `scripts/atlas_spike.py`
- Modify: `co_scientist/config.py` (`StorageCfg`, `Secrets`, new `LibraryCfg`), `config/default.toml` (`[storage]`, `[library]`), `co_scientist/storage/db.py` (`connect`, `init_db`), `pyproject.toml` (deps + pytest marker)
- Test: `co_scientist/tests/unit/test_atlas_client.py`, `co_scientist/tests/atlas/conftest.py`, `co_scientist/tests/atlas/test_indexes.py`

**Interfaces:**
- Produces:
  - `StorageCfg.backend: Literal["sqlite", "atlas"] = "sqlite"`, `StorageCfg.atlas_db: str = "biocurate"`, `StorageCfg.atlas_prefix: str = ""`
  - `Secrets.MONGODB_URI: str = ""`
  - `LibraryCfg` on `Config.library`: `embedding: Literal["auto", "client"] = "auto"`, `embed_model: str = "voyage-4"`, `rerank_model: str = "rerank-2.5"`, `search_index: str = "library_text"`, `vector_index: str = "library_vec"`, `max_passage_chars: int = 2000`
  - `class AtlasConn` (dataclass): `client: AsyncMongoClient`, `db: AsyncDatabase`, `prefix: str`; `def coll(self, name: str) -> AsyncCollection` (returns `db[prefix + name]`); `async def close(self) -> None` (no-op: the client is shared); `__repr__` shows only db name + prefix.
  - `async def connect_atlas(cfg: Config) -> AtlasConn`: one cached `AsyncMongoClient` per `(uri, running loop id)`, because the CLI calls `asyncio.run` repeatedly and an async client is loop-bound. Raises `RuntimeError("MONGODB_URI not set")` when empty.
  - `async def shutdown_clients() -> None`
  - `async def ensure_indexes(conn: AtlasConn, cfg: Config) -> None`: idempotent. B-tree indexes mirror `schema.sql` (`sessions(status, updated_at)`, `hypotheses(session_id, elo)`, `hypotheses(session_id, state)`, `reviews(hypothesis_id, created_at)`, `tasks(session_id, status, priority, created_at)`, **`tasks.idempotency_key` unique + partial on `{"idempotency_key": {"$type": "string"}}`**, `tournament_matches(session_id, created_at)`, `transcripts(session_id, started_at)`, `system_feedback(session_id, active, created_at)`, `events(session_id, ts)`, `events(event, ts)`, `spans(trace_id)`, `embeddings_meta(hypothesis_id, model)` unique, `library(pmcid)`). Search indexes are created only if missing by name: `hyp_vec` (Task 7 defines), `library_text`, `library_vec` (Task 9 defines). Exact definitions live as module constants in `indexes.py`.
  - `db.connect(cfg) -> aiosqlite.Connection | AtlasConn`; `db.init_db(cfg)` calls `ensure_indexes` on Atlas. `Conn = aiosqlite.Connection | AtlasConn` exported from `co_scientist/storage/__init__.py`; `AgentDeps.db` and `ToolCtx.db` are retyped to `Conn`.

- [ ] **Step 1: Spike (hour 0, before anything else).** `scripts/atlas_spike.py` uses prefix `spike_` in `biocurate`. It (a) inserts 20 short passages, creates an `autoEmbed` index (`{"type":"autoEmbed","modality":"text","path":"text","model":"voyage-4"}` + `filter` on `kind`), polls up to 10 min for `READY`, then runs `$vectorSearch` with `"query": {"text": ...}`; (b) creates a `search` index and runs `$rankFusion` with `$search` and `$vectorSearch` sub-pipelines; (c) runs a 2-collection transaction. It then drops its own `spike_*` collections. Run: `uv run python scripts/atlas_spike.py`. Record PASS/FAIL per check in the PR description. **If (a) fails or never reaches READY: set `library.embedding = "client"` in `default.toml`** (Track C then embeds passages with Voyage, index type `vector`). If (b) fails, Task 10 falls back to client-side RRF (see Task 10). Check first with the owner: is storage auto-scaling on (required for autoEmbed on M10+), and is the token billing OK.
- [ ] **Step 2: Write the failing tests.** `test_atlas_client.py` (offline): `test_backend_defaults_to_sqlite` (`Config().storage.backend == "sqlite"`); `test_connect_atlas_requires_uri` (empty secret → `RuntimeError`, message has no URI); `test_atlas_conn_repr_hides_uri`; `test_coll_applies_prefix` (`AtlasConn(..., prefix="t1_").coll("tasks").name == "t1_tasks"`, using `AsyncMongoClient("mongodb://localhost", connect=False)`). `tests/atlas/conftest.py`: `pytestmark` skip unless `CO_SCI_ATLAS_TESTS=1`; fixture `atlas_cfg` sets `backend="atlas"`, `atlas_prefix=f"t{ulid}_"`; fixture `atlas_conn` yields `connect_atlas(atlas_cfg)` after `ensure_indexes`, and on teardown drops **only** collections whose names start with that prefix. `test_indexes.py::test_ensure_indexes_is_idempotent`: call twice; second call raises nothing; `tasks` has a unique index on `idempotency_key`.
- [ ] **Step 3: Run.** `uv run pytest co_scientist/tests/unit/test_atlas_client.py -q` → FAIL. `CO_SCI_ATLAS_TESTS=1 uv run pytest co_scientist/tests/atlas -q` → FAIL.
- [ ] **Step 4: Implement** the config fields, `client.py`, `indexes.py` and the `db.py` dispatch. Register the `atlas` marker in `pyproject.toml`.
- [ ] **Step 5: Run both commands.** Expected: PASS; plain `uv run pytest -q` still all green with atlas tests skipped.
- [ ] **Step 6: Commit.** `feat(storage): add Atlas connection, backend setting, and index bootstrap`

---

### Task 3: Split repos into SQLite implementations + dispatchers; dual-backend test fixture

Depends on Task 1 (repo surface final) and Task 2 (`AtlasConn`).

**Files:**
- Move (`git mv`): `co_scientist/storage/repos/{embeddings,events,feedback,hypotheses,reviews,sessions,spans,tasks,tournaments,transcripts}.py` → `co_scientist/storage/sqlite/`
- Create: `co_scientist/storage/repos/_dispatch.py`, new thin `co_scientist/storage/repos/<same names>.py`, `co_scientist/storage/atlas/<same names>.py` (stubs that raise `NotImplementedError`, filled in Tasks 4 and 5)
- Modify: `co_scientist/tests/conftest.py`
- Test: `co_scientist/tests/unit/test_repo_parity.py`

**Interfaces:**
- Produces:
  - `def dual(sql_fn, atlas_fn)`: returns an `async` wrapper (with `functools.wraps(sql_fn)`) that calls `atlas_fn` when `isinstance(conn, AtlasConn)` and `sql_fn` otherwise.
  - Each `repos/<m>.py` has one explicit line per public function, e.g. `insert = dual(_sql.insert, _atlas.insert)`. `spans.span` (the `asynccontextmanager`) is defined in `repos/spans.py` on top of the dispatched `start` / `end`.
  - Fixture `any_conn` in `tests/conftest.py`, parametrized `["sqlite", "atlas"]`. The `atlas` param is skipped unless `CO_SCI_ATLAS_TESTS=1` and reuses the prefix/teardown logic from Task 2 (move that helper into `tests/conftest.py`).
- [ ] **Step 1: Write the failing test.** `test_repo_parity.py::test_every_sqlite_repo_function_has_atlas_twin`: for each module name, `{n for n, f in vars(sqlite_mod).items() if inspect.iscoroutinefunction(f) and not n.startswith("_")} == {same for atlas_mod}` and each name exists on `repos.<m>`.
- [ ] **Step 2: Run.** `uv run pytest co_scientist/tests/unit/test_repo_parity.py -q` → FAIL (modules missing).
- [ ] **Step 3: Do the move, dispatchers and stubs.** Switch every test in `test_repos.py` from fixture `conn` to `any_conn`.
- [ ] **Step 4: Run.** `uv run pytest -q`. Expected: all green, Atlas params skipped.
- [ ] **Step 5: Commit.** `refactor(storage): dispatch repos by backend`

---

### Task 4: Atlas repos: sessions, hypotheses, reviews, feedback, transcripts, events, spans, embeddings

Depends on Task 3. The modules are independent, so they can be done (or reviewed) one at a time.

**Files:**
- Modify: `co_scientist/storage/atlas/{sessions,hypotheses,reviews,feedback,transcripts,events,spans,embeddings}.py`
- Test: `co_scientist/tests/unit/test_repos.py` (runs under `any_conn`), new `co_scientist/tests/unit/test_atlas_mappers.py`

**Interfaces:**
- Consumes: `AtlasConn.coll(name)`; collection names equal the SQLite table names (`sessions`, `hypotheses`, `reviews`, `system_feedback`, `transcripts`, `events`, `spans`, `embeddings_meta`).
- Produces: twins with identical signatures and return types. Each module has pure helpers `_to_doc(model) -> dict` and `_from_doc(doc) -> Model`. JSON-text columns (`research_plan`, `config_snapshot`, `parent_ids`, `payload`, `attrs_json`) become native subdocuments or arrays.
- Semantics that need care:
  - `INSERT OR IGNORE` becomes `insert_one`, catching `DuplicateKeyError` → `False`.
  - `set_state_if` and `init_tournament` are a single `update_one` with the guard in the filter (`{"_id": id, "state": {"$in": [...]}}` / `{"_id": id, "elo": None}`); return `modified_count > 0`.
  - `sessions.add_usage` uses `$inc`.
  - `list_for_session` without state sorts `[("elo", -1), ("created_at", 1)]`. Mongo puts nulls last on a descending sort, which matches the SQL `NULLS LAST`.
  - `sessions.list_with_stats` is one aggregation: `$lookup` on hypotheses with `$group` count/max.
  - `events.tool_call_counts` filters `{"event": "tool_call"}` and counts `payload.is_error == True`.
  - `transcripts.durations_ms` computes `$dateDiff` in ms, sorted ascending.
- [ ] **Step 1: Write the failing tests.** `test_atlas_mappers.py` (offline): `test_hypothesis_doc_roundtrip` (`_from_doc(_to_doc(h)) == h` for a hypothesis with `parent_ids=["a","b"]`, `elo=None`); same for Session (nested `research_plan`), Review and Task.
- [ ] **Step 2: Run.** `uv run pytest co_scientist/tests/unit/test_atlas_mappers.py -q` → FAIL. `CO_SCI_ATLAS_TESTS=1 uv run pytest co_scientist/tests/unit/test_repos.py -q` → Atlas params FAIL with `NotImplementedError`.
- [ ] **Step 3: Implement the twins.**
- [ ] **Step 4: Run both commands.** Expected: PASS on both backends.
- [ ] **Step 5: Commit.** `feat(storage): implement core repos on Atlas`

---

### Task 5: Atlas repos: tasks queue and tournaments (claim, idempotency, Elo transaction)

Depends on Task 3.

**Files:**
- Modify: `co_scientist/storage/atlas/tasks.py`, `co_scientist/storage/atlas/tournaments.py`
- Test: `co_scientist/tests/unit/test_repos.py`

**Interfaces:**
- Produces twins of every `tasks` and `tournaments` function, as in Task 3.
- Required mechanics:
  - `tasks.enqueue`: `insert_one`; `DuplicateKeyError` (on `_id` or the unique `idempotency_key`) → `False`.
  - `tasks.claim_one`: `find_one_and_update({"session_id": s, "status": "pending"}, {"$set": {status: "leased", lease_owner, lease_expires_at, started_at}}, sort=[("priority", 1), ("created_at", 1)], return_document=ReturnDocument.AFTER)`.
  - `tasks.fail`: one `find_one_and_update` with `$inc attempts`, then a conditional dead/requeue `update_one` keyed on the returned `attempts`.
  - `tasks.reclaim_expired_leases`: two `update_many` calls with **pipeline updates** so `attempts + 1 >= max_attempts` and `last_error` concatenation (`$concat: [{"$ifNull": ["$last_error", ""]}, " [lease expired]"]`) happen server-side. Order and return value match SQLite.
  - `tournaments.apply_elo_update`: inside `async with conn.client.start_session() as s:` → `await s.with_transaction(cb)`. `cb` inserts `elo_journal {_id: match_id, …}`, then `update_one` ×2 on hypotheses (`$set elo`, `$inc matches_played: 1`), then `update_one` on `tournament_matches`, all with `session=s`. A `DuplicateKeyError` out of the transaction → return `False`.
- [ ] **Step 1: Write the failing tests** (in `test_repos.py`, on `any_conn`):
  - `test_apply_elo_update_is_idempotent`: call twice with the same `match_id` → `True` then `False`; both hypotheses end with `matches_played == 1` and `elo == elo_*_after`.
  - `test_claim_one_concurrent_claims_are_exclusive`: enqueue 5 tasks, `asyncio.gather` 10 `claim_one` calls → 5 distinct ids + 5 `None`.
  - `test_reclaim_expired_leases_dead_letters_at_max_attempts`: a leased task with `attempts=2`, expired lease, `max_attempts=3` → `{"requeued": 0, "dead": 1}`, `last_error` ends with `"[lease expired; max attempts]"`.
  - `test_enqueue_duplicate_idempotency_key_returns_false`: different ids, same key → `True, False`.
  - The existing `test_task_queue_claim_and_idempotency` already covers ordering.
- [ ] **Step 2: Run.** `CO_SCI_ATLAS_TESTS=1 uv run pytest co_scientist/tests/unit/test_repos.py -q -k "elo or claim or reclaim or idempotency"` → the Atlas params FAIL; the SQLite params pass, which confirms the tests encode current behaviour.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the same command, then plain `uv run pytest -q`. Expected: PASS / all green.
- [ ] **Step 5: Commit.** `feat(storage): Atlas task queue and transactional Elo updates`

---

### Task 6: `VectorStore` protocol; remove FAISS internals from agents (offline)

Independent of storage; start at hour 0.

**Files:**
- Create: `co_scientist/vectors/base.py`, `co_scientist/vectors/factory.py`
- Modify: `co_scientist/vectors/store.py` (add `similarity`), `co_scientist/agents/ranking.py:219-285`, `co_scientist/agents/generation.py:215-262`, `co_scientist/agents/evolution.py:265-320`, `co_scientist/agents/proximity.py:29-120`
- Test: `co_scientist/tests/unit/test_vectors.py`

**Interfaces:**
- Produces:
  - `class VectorStore(Protocol)`: `n: int` (property); `async load_or_create() -> None`; `async add(hypothesis_id: str, vec: np.ndarray) -> int`; `async save() -> None`; `async search(vec: np.ndarray, k: int) -> list[tuple[str, float]]` (cosine, descending); `async cosine_matrix() -> np.ndarray`; `def ids() -> list[str]` (row order of `cosine_matrix`); `def similarity(a_id: str, b_id: str) -> float | None`.
  - `FaissStore` implements it. `similarity` moves the current `RankingAgent._similarity` body (two `reconstruct` calls + dot). `ids()` returns the offset-ordered id list.
  - `def make_vector_store(cfg: Config, db: Conn, session_id: str, dim: int) -> VectorStore` in `factory.py`: returns `FaissStore` unless `isinstance(db, AtlasConn)`. The Atlas branch imports `AtlasVectorStore` lazily (Task 7; until then it raises `NotImplementedError`).
  - Agents call only `make_vector_store(...)` and protocol methods. `RankingAgent._similarity(store, a, b)` becomes `store.similarity(a.id, b.id) if store else None`. Proximity's clustering uses `store.ids()` instead of `hypothesis_at`.
- [ ] **Step 1: Write the failing tests.** `test_faiss_store_similarity_matches_dot`: add two known unit vectors → `similarity(a, b) == pytest.approx(float(va @ vb))`, and `None` for an unknown id. `test_faiss_store_satisfies_protocol`: `isinstance(FaissStore(...), VectorStore)` (mark the Protocol `@runtime_checkable`). `test_make_vector_store_defaults_to_faiss`.
- [ ] **Step 2: Run.** `uv run pytest co_scientist/tests/unit/test_vectors.py -q` → FAIL.
- [ ] **Step 3: Implement and switch the four agents over.**
- [ ] **Step 4: Run.** `uv run pytest -q`. Expected: all green (the existing ranking/proximity tests prove no behaviour change).
- [ ] **Step 5: Commit.** `refactor(vectors): agents depend on a VectorStore protocol`

---

### Task 7: `AtlasVectorStore` (Atlas Vector Search + Voyage)

Depends on Tasks 2 and 6.

**Files:**
- Create: `co_scientist/vectors/atlas_store.py`
- Modify: `co_scientist/vectors/factory.py`, `co_scientist/storage/atlas/indexes.py` (`HYP_VEC_INDEX`)
- Test: `co_scientist/tests/atlas/test_atlas_vector_store.py`, `co_scientist/tests/unit/test_vectors.py`

**Interfaces:**
- Consumes: `VectorStore` (Task 6), `AtlasConn` (Task 2), `make_embedder` (unchanged; Voyage `cfg.embeddings.model`, normalized vectors).
- Produces:
  - `class AtlasVectorStore(VectorStore)`, `__init__(self, cfg, conn: AtlasConn, session_id: str, dim: int)`. Collection `hypothesis_vectors`: `{_id: hypothesis_id, session_id, model, embedding: list[float], created_at}`.
  - `load_or_create` loads this session's vectors into memory, so `similarity` / `cosine_matrix` / `ids` stay synchronous for Ranking's pairing loop.
  - `add` upserts the doc, updates the in-memory map and returns the ordinal.
  - `save` is a no-op.
  - `search` runs `$vectorSearch` on index `hyp_vec` with `filter: {session_id}`, `numCandidates = max(100, 20*k)`, projecting `vectorSearchScore`. It converts with `cos = 2*score - 1`, then **merges** exact dot products against in-memory vectors added within the last `30` s (index lag), dedups by id and returns the top k.
  - `HYP_VEC_INDEX = {"fields": [{"type": "vector", "path": "embedding", "numDimensions": cfg.embeddings.dim, "similarity": "dotProduct"}, {"type": "filter", "path": "session_id"}]}`.
  - `pure def vector_score_to_cosine(score: float) -> float`.
- [ ] **Step 1: Write the failing tests.** Offline: `test_vector_score_to_cosine` (`1.0→1.0`, `0.5→0.0`, `0.96→0.92`). Atlas: `test_atlas_vector_search_returns_cosine` (add orthogonal and identical unit vectors, wait until `hyp_vec` is queryable, search → identical ≈ 1.0, orthogonal ≈ 0.0); `test_atlas_vector_search_sees_just_added_vector` (add, then search immediately with no wait → id returned with cosine ≈ 1.0); `test_atlas_store_scoped_to_session` (a vector in session B never appears for session A).
- [ ] **Step 2: Run.** `uv run pytest co_scientist/tests/unit/test_vectors.py -q`, `CO_SCI_ATLAS_TESTS=1 uv run pytest co_scientist/tests/atlas/test_atlas_vector_store.py -q` → FAIL.
- [ ] **Step 3: Implement**, and wire the factory's Atlas branch.
- [ ] **Step 4: Run both.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(vectors): hypothesis dedup and similarity on Atlas Vector Search`

---

### Task 8: JATS parser and passage splitter (pure, offline)

Start at hour 0.

**Files:**
- Create: `co_scientist/library/__init__.py`, `co_scientist/library/jats.py`, `co_scientist/tests/fixtures/jats/with_ids.xml`, `co_scientist/tests/fixtures/jats/no_ids.xml` (trimmed real Europe PMC OA articles, < 30 KB each)
- Test: `co_scientist/tests/unit/test_jats.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Passage`: `anchor_id: str`, `pmcid: str`, `kind: Literal["abstract", "paragraph", "figure", "table"]`, `section: str`, `label: str | None`, `text: str`, `ordinal: int`
  - `@dataclass(frozen=True) class PaperMeta`: `pmcid, title, doi: str | None, year: int | None, journal: str | None`
  - `def parse_jats(xml: str, pmcid: str, *, max_chars: int = 2000) -> tuple[PaperMeta, list[Passage]]`
- Anchor rules:
  - Figure: `{pmcid}#{fig/@id}` (e.g. `PMC1234567#F2`); text is label + caption.
  - Table: `{pmcid}#{table-wrap/@id}`; text is label + caption + footnotes. With no caption, the text is the label alone; the table is never dropped.
  - Paragraph: `{pmcid}#{p/@id}` if present, else `{pmcid}#s{i}.p{j}` with `i` the 1-based top-level `<sec>` index (`0` for paragraphs outside a section) and `j` the 1-based paragraph index within it.
  - Abstract: `{pmcid}#abstract.p{j}`.
  - A paragraph longer than `max_chars` splits at sentence boundaries into `…#<anchor>.1`, `.2`.
  - `section` is the nearest ancestor `<sec><title>` path joined by `" > "`.
  - Whitespace is collapsed. Inline `<xref>` text is kept.
  - `<ref-list>`, `<ack>` and `<fn-group>` outside tables are skipped.
- [ ] **Step 1: Write the failing tests.**
  - `test_parse_jats_figure_and_table_anchors` (`with_ids.xml` → contains `PMC…#F1` kind figure whose text starts with its label; a `#T1` table).
  - `test_parse_jats_fallback_anchors_are_stable` (`no_ids.xml` parsed twice → identical anchor lists; a nested-section paragraph's `section` is `"Results > Subsection"`).
  - `test_parse_jats_splits_long_paragraph` (`max_chars=200` → anchors ending `.1`, `.2`, each `len(text) <= 200`).
  - `test_parse_jats_skips_references`.
  - `test_parse_jats_meta` (title, doi, year).
- [ ] **Step 2: Run.** `uv run pytest co_scientist/tests/unit/test_jats.py -q` → FAIL.
- [ ] **Step 3: Implement** with `xml.etree.ElementTree`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit.** `feat(library): parse Europe PMC JATS into anchored passages`

---

### Task 9: Library ingest: fetch, store, indexes, CLI

Depends on Tasks 2 and 8.

**Files:**
- Create: `co_scientist/library/fetch.py`, `co_scientist/library/ingest.py`, `co_scientist/storage/atlas/library.py`
- Modify: `co_scientist/storage/atlas/indexes.py` (`LIBRARY_TEXT_INDEX`, `library_vec_definition(cfg)`), `co_scientist/cli.py` (new `library` Typer sub-app)
- Test: `co_scientist/tests/unit/test_library_ingest.py`, `co_scientist/tests/atlas/test_library_store.py`

**Interfaces:**
- Consumes: `parse_jats`, `Passage`, `PaperMeta` (Task 8); `AtlasConn` (Task 2); `EuropePMCSearchTool` URL constant.
- Produces:
  - `async def fetch_jats(client: httpx.AsyncClient, pmcid: str) -> str | None`: GET `https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML`; 404 → `None`.
  - `async def search_oa_pmcids(client, query: str, max_papers: int) -> list[str]`: Europe PMC search with `({query}) AND OPEN_ACCESS:Y AND HAS_FT:Y`, returning `pmcid`s.
  - `@dataclass class IngestReport`: `papers: int`, `passages: int`, `skipped: list[str]`, `already_present: list[str]`
  - `async def ingest_query(conn: AtlasConn, cfg: Config, query: str, *, max_papers: int = 10, http: httpx.AsyncClient | None = None) -> IngestReport`
  - `storage/atlas/library.py`:
    - `async upsert_passages(conn, meta: PaperMeta, passages: list[Passage], *, embeddings: list[list[float]] | None = None) -> int`: bulk `ReplaceOne(upsert=True)` keyed `_id = anchor_id`. Doc fields: `pmcid, title, doi, year, journal, kind, section, label, text, ordinal, url = f"https://europepmc.org/article/PMC/{pmcid}#{fragment}"`, `ingested_at`, plus `embedding` when `library.embedding == "client"`.
    - `async has_paper(conn, pmcid) -> bool`
    - `async count(conn) -> int`
  - Indexes:
    - `LIBRARY_TEXT_INDEX`: `{"mappings": {"dynamic": False, "fields": {"text": {"type": "string", "analyzer": "lucene.english"}, "title": {"type": "string", "analyzer": "lucene.english"}, "section": {"type": "string"}, "kind": {"type": "token"}, "pmcid": {"type": "token"}, "year": {"type": "number"}}}}`
    - `library_vec_definition(cfg)`: `"auto"` → `[{"type": "autoEmbed", "modality": "text", "path": "text", "model": cfg.library.embed_model}, {"type": "filter", "path": "kind"}, {"type": "filter", "path": "year"}]`; `"client"` → a `vector` field on `embedding` with `numDimensions = cfg.embeddings.dim`, `dotProduct`, same filters. In client mode, `ingest_query` embeds passage text with `make_embedder`.
  - CLI: `co-scientist library ingest QUERY [--max-papers 10]` prints the `IngestReport`. `co-scientist library stats` prints the passage count and index statuses. Both exit with a clear message if the backend is not `atlas`.
- [ ] **Step 1: Write the failing tests.** Offline, with `httpx.MockTransport`: `test_ingest_skips_missing_fulltext` (search returns 2 pmcids, one `fullTextXML` 404s → `skipped == [that pmcid]`, `papers == 1`), `test_ingest_is_idempotent_per_paper` (fake `has_paper` → `True` puts the paper in `already_present` and makes no fetch). For these, `ingest_query` takes the store functions through a small `LibraryStore` protocol so tests pass a fake. Atlas: `test_upsert_passages_replaces_on_reingest` (same passages twice → `count` unchanged).
- [ ] **Step 2: Run.** `uv run pytest co_scientist/tests/unit/test_library_ingest.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** offline + `CO_SCI_ATLAS_TESTS=1 uv run pytest co_scientist/tests/atlas/test_library_store.py -q` → PASS. Manually: `uv run co-scientist library ingest "TREM2 microglia Alzheimer" --max-papers 5`, then `library stats` shows passages > 0 and both indexes READY.
- [ ] **Step 5: Commit.** `feat(library): ingest Europe PMC full text into Atlas`

---

### Task 10: Hybrid search + Voyage rerank + `search_library` tool

Depends on Task 9 (indexes exist). The pipeline builder and tool are offline-testable, so start them against fakes while Task 9 lands.

**Files:**
- Create: `co_scientist/library/search.py`, `co_scientist/tools/builtins/library.py`
- Modify: `co_scientist/tools/registry.py` (register + add to the generation/reflection/evolution allowlists at lines 30–44), `co_scientist/agents/generation.py:55` and `co_scientist/agents/reflection.py:54` (add `search_library` to the tool lists in the prompt text, telling the agent to cite the `anchor_id`), `co_scientist/cli.py` (`library search QUERY`)
- Test: `co_scientist/tests/unit/test_library_search.py`, `co_scientist/tests/unit/test_library_tool.py`, `co_scientist/tests/atlas/test_hybrid_search.py`

**Interfaces:**
- Produces:
  - `@dataclass class LibraryHit`: `anchor_id, pmcid, title, section, kind, label: str | None, text, url, fused_score: float, rerank_score: float | None`
  - `def build_hybrid_pipeline(cfg: Config, query: str, *, k: int, kind: str | None = None, query_vector: list[float] | None = None) -> list[dict]`: a pure function. The first stage is `$rankFusion` with pipelines `"text"` (`$search` on `cfg.library.search_index`, `text: {query, path: ["text", "title"]}`, then `$limit: 4*k`) and `"vector"` (`$vectorSearch` on `cfg.library.vector_index`, `query: {"text": query}` in auto mode or `queryVector` in client mode, `numCandidates: 20*k`, `limit: 4*k`, `filter: {kind}` when given). Weights are `{"text": 1, "vector": 1}`. After the fusion stage: `$limit: 4*k`, then `$project` of the LibraryHit fields plus `fused_score: {"$meta": "score"}`. When `kind` is set, the `$search` branch uses a `compound` with `filter: [{"equals": {"path": "kind", "value": kind}}]`.
  - `async def hybrid_search(conn: AtlasConn, cfg: Config, query: str, *, k: int = 8, kind: str | None = None) -> list[LibraryHit]`: runs the pipeline (client mode embeds the query first), then calls `rerank`.
  - `async def rerank(cfg: Config, query: str, hits: list[LibraryHit], top_k: int) -> list[LibraryHit]`: `voyageai.AsyncClient().rerank(query, [h.text for h in hits], model=cfg.library.rerank_model, top_k=top_k)`. Without `VOYAGE_API_KEY` it returns `hits[:top_k]` with `rerank_score=None`.
  - Fallback if the Task 2 spike showed `$rankFusion` can't wrap `$search`: run the two sub-pipelines separately and fuse client-side with `def rrf(lists: list[list[str]], k: int = 60) -> list[tuple[str, float]]`. Ship `rrf` in both cases (it's 10 lines and unit-tested).
  - `class SearchLibraryTool`: `name = "search_library"`; input `{query: str (required), k: int 1..20 default 8, kind: enum [paragraph, figure, table, abstract]}`. Output `{"query", "n", "hits": [{anchor_id, pmcid, title, section, kind, label, text (≤ 800 chars), url, score, rerank_score}]}`. `ToolResult(is_error=True)` with a readable message when `ctx.db` is not an `AtlasConn`, the library is empty, or the search index is not READY (`OperationFailure` mentioning the index).
  - Registry: register `SearchLibraryTool` only when `cfg.storage.backend == "atlas"`.
- [ ] **Step 1: Write the failing tests.**
  - `test_build_hybrid_pipeline_first_stage_is_rankfusion` (`list(p[0]) == ["$rankFusion"]`; both pipeline names present; vector branch has `query == {"text": q}` in auto mode).
  - `test_build_hybrid_pipeline_kind_filter` (`kind="figure"` adds the filter to both branches).
  - `test_build_hybrid_pipeline_client_mode_uses_query_vector`.
  - `test_rrf_orders_by_reciprocal_rank` (`rrf([["a","b"],["b","c"]])[0][0] == "b"`).
  - `test_rerank_without_key_passes_through`.
  - `test_search_library_tool_errors_on_sqlite`.
  - `test_registry_registers_search_library_only_on_atlas`.
  - Atlas: `test_hybrid_search_finds_figure_by_caption`. Upsert 3 passages: a figure caption containing a rare term plus 2 unrelated paragraphs. Wait for both indexes, then `hybrid_search(rare term, kind="figure")[0].anchor_id` is that figure.
- [ ] **Step 2: Run.** `uv run pytest co_scientist/tests/unit/test_library_search.py co_scientist/tests/unit/test_library_tool.py -q` → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** offline + `CO_SCI_ATLAS_TESTS=1 uv run pytest co_scientist/tests/atlas/test_hybrid_search.py -q` → PASS. Manually: `uv run co-scientist library search "microglial phagocytosis"` prints ranked hits with anchors and URLs.
- [ ] **Step 5: Commit.** `feat(library): hybrid search with rerank as the search_library tool`

---

### Task 11: End-to-end run on Atlas, docs, demo script

Final ~2 h. A teammate can draft the demo script and README section.

**Files:**
- Modify: `config/default.toml` (comment documenting `backend = "atlas"`), `README.md` (new "Built on MongoDB Atlas" section: which feature backs what, with a diagram of collections + indexes), `.env.example` (create if absent; empty `MONGODB_URI=` and `VOYAGE_API_KEY=` placeholders)
- Create: `docs/demo-script.md` (the 3-minute shot list)

- [ ] **Step 1:** `CO_SCI_ATLAS_TESTS=1 uv run pytest -q`. Expected: all pass on both backends. Then plain `uv run pytest -q`: all pass, Atlas skipped (what CI sees).
- [ ] **Step 2:** With `[storage] backend = "atlas"` set in the run's config TOML: `co-scientist init`, `co-scientist library ingest "<demo goal>" --max-papers 15`, then run a short session (small budget) to completion. Check in Atlas Data Explorer: hypotheses with Elo, `elo_journal` entries equal to the valid match count, `events` streaming, at least one `search_library` tool call whose citations carry `anchor_id`s.
- [ ] **Step 3:** Write `docs/demo-script.md`. Run the goal, show the dashboard, show a hypothesis citing `PMC…#F2` and open the passage. Then Atlas UI: collections, the `library_text` / `library_vec` / `hyp_vec` indexes, the `$rankFusion` pipeline in the aggregation builder with `scoreDetails`. Then the dedup log line.
- [ ] **Step 4:** Update the README and `.env.example`. Commit: `docs: document the Atlas backend and demo`.

---

## After this plan (if time remains)

- **Decision 4, Automated Embedding:** the library already uses it if the spike passes (`library.embedding = "auto"`). Adding an `autoEmbed` index on `hypotheses.summary` takes about 1 h: one more index constant, plus a "related hypotheses" query in the dashboard.
- **Decision 5, dashboard search box:** about 2 h. It's a `GET /api/search?q=` endpoint in `web/app.py` calling `hybrid_search`, plus a box on the session page.
- **Decision 6, Stream Processing:** needs a stream-processing instance, which costs money and needs owner approval first. Treat it as a stretch only.
