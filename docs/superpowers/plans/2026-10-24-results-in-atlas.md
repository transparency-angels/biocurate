# Results, Attachments and Live Timeline in Atlas: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Everything a researcher sees lives in MongoDB Atlas: their uploaded attachments, every result, and a live per-session timeline. It is served by an API whose responses match the React app's existing types.

**Architecture:**
- New storage repos follow the existing `dual(sqlite_fn, atlas_fn)` seam:
  - `blobs`: GridFS on Atlas, a BLOB table on SQLite;
  - `attachments`, `timeline`, `analysis`, `syntheses`.
- Agents write results through those repos instead of artifact files.
- Session planning sees an inventory of the attachments before anything is analysed.
- The FastAPI app gains the routes the React app needs. Its SSE stream adds `timeline_message` events, read from a change stream on Atlas.

**Tech Stack:** Python 3.11+, PyMongo async (`AsyncMongoClient`, `gridfs.AsyncGridFSBucket`), aiosqlite, FastAPI + sse-starlette, pypdf, python-docx (new), pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-10-24-results-in-atlas-design.md`. Read §§6, 7, 9, 11 and 12 before any task; §12 overrides earlier sections where they differ.

## Global Constraints

- All database access goes through `co_scientist/storage/repos/<m>.py`.
  - Each public async function exists in both `storage/sqlite/<m>.py` and `storage/atlas/<m>.py` with the same signature. `test_repo_parity` enforces this, and `test_no_raw_sql` must stay green.
  - Exception: library upload ingestion and session-scoped library search are Atlas-only (spec §11).
- Atlas collections are reached only via `AtlasConn.coll(name)`.
  - GridFS bucket names are `conn.prefix + <bucket>`, with the buckets `attachments` and `plots`.
  - Use the PyMongo async API, not Motor.
- SQLite schema changes go in new migrations starting at `0006_`, in `co_scientist/storage/migrations/`.
- Timeline writes are best-effort. A failure is logged with the exception type only and never raised into an agent.
- Never put `str(exc)` of a PyMongo error into API responses, timeline text or logs; use fixed text plus `type(e).__name__`. Never log or return `MONGODB_URI` or API keys.
- **Upload limits:** 5 files per request, 25 MB each, extensions `.pdf .docx .txt .csv .zip`.
  - Zip contents: `[attachments] max_unzipped_mb = 512`, at most 50 members. Accepted member extensions are `.pdf .docx .txt .csv`; nested zips are skipped.
  - Per session: `[attachments] max_session_mb = 125`, counting the stored, unpacked bytes.
  - Globally: `[attachments] max_total_mb = 2048`. Exceeding it returns HTTP 413.
- Offline `uv run pytest -q` must pass with no network. Atlas tests run only with `CO_SCI_ATLAS_TESTS=1`, on auto-dropped `t<ulid>_` collections.
- `uv run ruff check co_scientist scripts` must be clean. Keep added lines ≤ 100 characters.
- Commit messages are plain conventional commits, with **no `Co-Authored-By` line and no Claude or model names**.
- Don't edit anything under `frontend/`; the teammate owns it. Response shapes must match `frontend/src/types/research.ts`, `researchOverview.ts` and `researchEvents.ts`.

## Review Focus

1. **Zip safety.** A crafted zip with `../` member names, absolute paths, a huge declared-vs-actual size, or 10,000 members must be refused or contained, never written outside the store and never exhausting memory. → `test_unzip_rejects_traversal_bomb_and_member_flood` (Task 2).
2. **Upload with no data at all.** A researcher attaches only PDFs, or nothing. The data-analysis agent must never run, and the session must still produce hypotheses. → `test_plan_without_tabular_attachments_skips_analysis` (Task 7).
3. **Concurrent timeline appends.** Four workers post at once. `seq` must stay unique and gap-free per session on both backends. → `test_timeline_concurrent_appends_unique_seq` (Task 3).
4. **Large per-sample payloads.** About 24k samples per candidate. Each `analysis_points` document must stay under 16 MB, and `/research` must not load every candidate's points for every hypothesis. → `test_points_doc_size_for_24k_samples` (Task 5), `test_research_loads_only_linked_points` (Task 11).
5. **Reconnecting SSE client.** The browser `EventSource` reconnects after a drop and must not miss or duplicate timeline messages. → `test_events_stream_resumes_timeline_after_seq` (Task 12).

---

### Task 1: Blob store and attachment repo

**Files:**
- Create:
  - `co_scientist/models/attachment.py`
  - `co_scientist/storage/sqlite/blobs.py`, `co_scientist/storage/atlas/blobs.py`, `co_scientist/storage/repos/blobs.py`
  - `co_scientist/storage/sqlite/attachments.py`, `co_scientist/storage/atlas/attachments.py`, `co_scientist/storage/repos/attachments.py`
  - `co_scientist/storage/migrations/0006_blobs_attachments.sql`
- Modify:
  - `co_scientist/storage/repos/__init__.py` (import the new modules)
  - `co_scientist/storage/atlas/indexes.py`: `attachments_meta(session_id, uploaded_at)`, and a unique `attachments_meta(session_id, sha256, filename)`
  - `co_scientist/config.py` and `config/default.toml`: a new `[attachments]` section with `max_files = 5`, `max_file_mb = 25`, `max_unzipped_mb = 512`, `max_zip_members = 50`, `max_session_mb = 125` and `max_total_mb = 2048`
  - `co_scientist/tests/unit/test_repo_parity.py`: add `blobs` and `attachments` to its module list
- Test: `co_scientist/tests/unit/test_repos.py` (`any_conn`), `co_scientist/tests/unit/test_config.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class AttachmentMeta` with:
    - `id: str`, `session_id: str`, `filename: str`
    - `content_type: str`, `size: int`, `sha256: str`
    - `kind: Literal["tabular", "document"]`
    - `status: Literal["stored", "ingested", "analysed", "failed"]`
    - `blob_id: str`, `uploaded_at: datetime`, `error: str | None`
  - `blobs`:
    - `put(conn, bucket: str, name: str, data: bytes, metadata: dict) -> str` returns `blob_id`;
    - `get(conn, bucket: str, blob_id: str) -> bytes`;
    - `delete(conn, bucket: str, blob_id: str) -> None`;
    - Atlas uses `AsyncGridFSBucket(conn.db, bucket_name=conn.prefix + bucket)`, with `blob_id` being `str(ObjectId)`. SQLite uses a table `blobs(id TEXT PK, bucket, name, data BLOB, metadata TEXT, created_at)`.
  - `attachments`:
    - `insert(conn, meta: AttachmentMeta) -> bool` (False on a duplicate `(session_id, sha256, filename)`);
    - `list_for_session(conn, session_id) -> list[AttachmentMeta]` (by `uploaded_at`);
    - `fetch(conn, attachment_id) -> AttachmentMeta | None`;
    - `set_status(conn, attachment_id, status, error=None) -> None`;
    - `session_bytes(conn, session_id) -> int`;
    - `total_bytes(conn) -> int`;
    - `older_than(conn, cutoff: datetime) -> list[AttachmentMeta]`;
    - `delete(conn, attachment_id) -> None`, which removes the meta only; callers delete the blob.
  - `AttachmentsCfg` on `Config.attachments`.

- [ ] **Step 1: Write failing tests** on `any_conn`:
  - `test_blob_roundtrip_large` puts 20 MB of random bytes, then `get` returns them identical (on Atlas this is above the 16 MB document cap, so it exercises GridFS chunking);
  - `test_attachment_insert_dedupes_and_lists_in_order`;
  - `test_attachment_bytes_accounting` (`session_bytes` and `total_bytes` sum `size`);
  - `test_attachment_set_status_and_older_than`;
  - `test_attachments_cfg_defaults` (offline).
- [ ] **Step 2: Run** `uv run pytest -q co_scientist/tests/unit/test_repos.py -k "blob or attachment"`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the models, both backends, the dispatchers, the migration, indexes and config.
- [ ] **Step 4: Run** the same command, then `CO_SCI_ATLAS_TESTS=1` on the same selection, then the full offline suite. Expected: PASS. Confirm no `t…_` collections or GridFS buckets are left behind; the `drop_prefixed` teardown must also drop `<prefix>attachments.files`, `.chunks`, and the same for `plots`. Add those names to its sweep if it misses them.
- [ ] **Step 5: Commit** `feat(storage): blob store and attachment repo (GridFS on Atlas)`.

---

### Task 2: Upload intake: validation and safe unzip (pure)

**Files:**
- Create: `co_scientist/attachments/__init__.py`, `co_scientist/attachments/intake.py`
- Test: `co_scientist/tests/unit/test_attachment_intake.py`

**Interfaces:**
- Consumes: `AttachmentsCfg` (Task 1).
- Produces:
  - `@dataclass(frozen=True) class IncomingFile`: `filename: str`, `data: bytes`, `content_type: str`, `kind: Literal["tabular", "document"]`.
  - `@dataclass class IntakeResult`: `files: list[IncomingFile]`, `skipped: list[str]` (each `"<name>: <reason>"`).
  - `class IntakeError(ValueError)`, carrying `status_code: int` (400 or 413).
  - `def accept_uploads(uploads: list[tuple[str, bytes, str]], cfg: AttachmentsCfg) -> IntakeResult`.
- Rules (spec §12):
  - `.csv` and `.txt` are `tabular`; `.pdf` and `.docx` are `document`.
  - **Request level:** more than `max_files` uploads, any upload over `max_file_mb`, or a disallowed extension raises `IntakeError(400)`.
  - **Zip:**
    - read with `zipfile.ZipFile(io.BytesIO(data))`;
    - for each member, the filename is `PurePosixPath(name).name`, and empty names, directories and names starting with `.` or `__MACOSX` are skipped;
    - members with a disallowed extension, or nested `.zip` files, are skipped and recorded in `skipped`;
    - read each member in 1 MB chunks with a running total, and abort with `IntakeError(413)` once the total passes `max_unzipped_mb`, regardless of declared sizes;
    - more than `max_zip_members` accepted members raises `IntakeError(413)`;
    - duplicate filenames inside one zip get a ` (2)` suffix.
  - Content type: from the extension, not from what the client sends.

- [ ] **Step 1: Write failing tests**, all building zips in memory with `zipfile`:
  - `test_accepts_plain_files_and_classifies_kind`;
  - `test_rejects_too_many_and_too_large_and_bad_extension` (status codes 400 and 413);
  - `test_unzip_flattens_paths_and_skips_junk` (`a/b/c.csv` gives `c.csv`; `__MACOSX/x` and `.DS_Store` are skipped; `inner.zip` is skipped with a reason);
  - `test_unzip_rejects_traversal_bomb_and_member_flood`:
    - `../../etc/x.csv` is stored as `x.csv`, never with a path;
    - a member whose actual size exceeds the limit but whose declared size is small, written with a patched `ZipInfo.file_size`, raises 413;
    - 51 tiny CSVs raise 413.
- [ ] **Step 2: Run** `uv run pytest -q co_scientist/tests/unit/test_attachment_intake.py`. Expected: FAIL.
- [ ] **Step 3: Implement** `intake.py`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `feat(attachments): validate uploads and unzip safely`.

---

### Task 3: Timeline repo and best-effort poster

**Files:**
- Create:
  - `co_scientist/models/timeline.py`
  - `co_scientist/storage/{sqlite,atlas,repos}/timeline.py`
  - `co_scientist/storage/migrations/0007_timeline.sql`
  - `co_scientist/timeline.py`
- Modify:
  - `co_scientist/storage/atlas/indexes.py`: unique `timeline(session_id, seq)`, plus a `timeline_counters` collection
  - `co_scientist/orchestrator/events.py`: no change to `Event`, only the doc comment listing `timeline_message`
  - `co_scientist/tests/unit/test_repo_parity.py`: add the new module to its list
- Test: `co_scientist/tests/unit/test_repos.py`, `co_scientist/tests/unit/test_timeline.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class TimelineMessage` with:
    - `session_id: str`, `seq: int`, `ts: datetime`
    - `role: Literal["system", "user", "assistant"]`
    - `agent: str | None`, `kind: str`, `title: str`, `body_markdown: str`
    - `refs: list[str]`
  - The repo:
    - `append(conn, session_id, *, role, agent, kind, title, body_markdown, refs) -> TimelineMessage`. It allocates `seq` atomically: on Atlas via `find_one_and_update({"_id": session_id}, {"$inc": {"seq": 1}}, upsert=True, return_document=AFTER)` on `timeline_counters`; on SQLite inside `BEGIN IMMEDIATE` with `MAX(seq)+1` under the same per-connection lock pattern as `sqlite/tournaments.py`.
    - `list_for_session(conn, session_id, *, after_seq: int = 0, limit: int = 500) -> list[TimelineMessage]`, ascending by `seq`.
  - The poster, `co_scientist/timeline.py`: `async def post(conn, session_id: str, *, kind: str, title: str, body: str = "", agent: str | None = None, refs: list[str] | None = None) -> None`.
    - It calls `timeline_repo.append`, then `GLOBAL_BUS.publish(session_id, "timeline_message", msg_as_payload)`.
    - It catches `Exception`, logs `timeline_post_failed` with the type only, and never raises.
  - The payload shape (also the `/timeline` item shape): `{"seq", "ts" (epoch ms), "role", "agent", "kind", "title", "body_markdown", "refs"}`.

- [ ] **Step 1: Write failing tests:**
  - `test_timeline_append_and_list_after_seq` (`any_conn`);
  - `test_timeline_concurrent_appends_unique_seq` (`any_conn`: `asyncio.gather` of 20 appends gives `seq` exactly 1..20);
  - `test_timeline_post_never_raises` (offline: a repo stub that raises; `post` returns None and logs);
  - `test_timeline_post_publishes_bus_event` (offline: subscribe to `GLOBAL_BUS`, receive `timeline_message` with the payload shape above).
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** offline, then with `CO_SCI_ATLAS_TESTS=1`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(timeline): per-session timeline with atomic seq`.

---

### Task 4: Citations, evidence and data evidence stored on rows

**Files:**
- Modify:
  - `co_scientist/storage/atlas/hypotheses.py` (`_to_doc` / `_from_doc`: add `citations`, `data_evidence`)
  - `co_scientist/storage/atlas/reviews.py` (add `evidence`, `assumptions`)
  - `co_scientist/storage/sqlite/hypotheses.py`, `co_scientist/storage/sqlite/reviews.py`
  - `co_scientist/storage/migrations/0008_results_on_rows.sql`, adding `citations TEXT`, `data_evidence TEXT` and `evidence TEXT`, `assumptions TEXT`, all as JSON
- Test: `co_scientist/tests/unit/test_atlas_mappers.py`, `co_scientist/tests/unit/test_repos.py`

**Interfaces:**
- Produces: `hypotheses.fetch` / `fetch_many` / `list_for_session` / `top_by_elo` return `Hypothesis` objects with `citations` (including `line_range`) and `data_evidence` populated, and the review functions return `Review` with `evidence` and `assumptions`.
- Signatures are unchanged.
- Rows written before migration 0008 read back as `[]` / `None`.

- [ ] **Step 1: Write failing tests:**
  - `test_hypothesis_roundtrip_keeps_citations_and_data_evidence` (`any_conn`: `line_range="L3-L5"` and a `data_evidence` dict survive);
  - `test_review_roundtrip_keeps_evidence_and_assumptions` (`any_conn`);
  - `test_old_rows_without_new_columns_read_as_empty` (SQLite: insert via raw SQL without the new columns);
  - the mapper round-trip tests are updated.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement**, and update the "Citations live in the JSON artifact" comments.
- [ ] **Step 4: Run** offline and on Atlas. Expected: PASS.
- [ ] **Step 5: Commit** `feat(storage): keep citations and evidence on hypothesis and review rows`.

---

### Task 5: Per-sample values from `analysis.py`, and the analysis results repo

**Files:**
- Modify: `co_scientist/analysis.py`, in `_screen_single_matrix` (lines ~253-332) and `profile`
- Create: `co_scientist/storage/{sqlite,atlas,repos}/analysis.py`, `co_scientist/storage/migrations/0009_analysis.sql`
- Modify: `co_scientist/storage/atlas/indexes.py` (`analysis_points(session_id, candidate_key)` unique), and `test_repo_parity.py` (add `analysis` to its module list)
- Test: `co_scientist/tests/unit/test_statistical_analysis.py`, `co_scientist/tests/unit/test_repos.py`

**Interfaces:**
- **`analysis.py` change:**
  - Track the sample id alongside each duration, in a list parallel to `durations[i][group]`.
  - For each *nominally significant* candidate, attach `points: list[dict]` with `{"sample_id", "group": "altered" | "unaltered", "value": os_months}`, and `candidate_key = f"{biomarker}|{alteration_type}|{drug}"`.
  - `profile_dataset(...)` returns `report["points"]: dict[candidate_key, list[dict]]`. Candidates in `report["candidates"]` gain `candidate_key`, but carry no points inline.
  - Everything else about the report is unchanged.
- **The `analysis` repo:**
  - `save_report(conn, session_id, report: dict) -> None` upserts `_id = session_id`. Fields: `summary_markdown`, `tests`, `methods`, `candidates`, `selection`, `sample_count`, `drugs`, `plots: list[{name, blob_id, content_type}]` and `created_at`.
  - `fetch_report(conn, session_id) -> dict | None`.
  - `save_points(conn, session_id, candidate_key, *, metric: str, unit: str, points: list[dict]) -> None` (upsert).
  - `fetch_points(conn, session_id, candidate_keys: list[str]) -> dict[str, dict]`, which returns only the requested keys.
  - SQLite stores JSON text.

- [ ] **Step 1: Write failing tests:**
  - `test_profile_returns_points_for_significant_candidates_only` (the existing synthetic fixture in `test_statistical_analysis.py`: every point's group is `altered` or `unaltered`, the counts match `altered_samples` / `unaltered_samples`, and the key format is as above);
  - `test_analysis_report_roundtrip` (`any_conn`);
  - `test_fetch_points_returns_only_requested_keys` (`any_conn`);
  - `test_points_doc_size_for_24k_samples` (`any_conn`: save 24,000 points, fetch them back, and assert `len(bson.encode(doc)) < 16 * 1024 * 1024` on the Atlas param).
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** offline and on Atlas, plus `test_data_analysis.py` and `test_data_driven_outputs.py`, which must still pass. Expected: PASS.
- [ ] **Step 5: Commit** `feat(analysis): keep per-sample survival values and store analysis results`.

---

### Task 6: Data-analysis agent reads attachments and writes to the database

**Files:**
- Modify: `co_scientist/agents/data_analysis.py`, and `co_scientist/agents/metareview.py` (`_dataset_summary`, line ~585: read `analysis.fetch_report(...)["summary_markdown"]` instead of `summary.md`)
- Test: `co_scientist/tests/unit/test_data_analysis.py`, `co_scientist/tests/unit/test_data_driven_outputs.py`

**Interfaces:**
- Consumes:
  - `attachments.list_for_session` / `fetch` and `blobs.get` (Task 1);
  - `analysis.save_report` / `save_points` (Task 5);
  - `timeline.post` (Task 3).
- **New task payload:** `{"attachment_ids": list[str]}`, where the `data_dir` key is removed.
- **The agent:**
  1. Write each selected attachment's bytes to `tempfile.TemporaryDirectory()` under its **original filename**, because `analysis.py` matches files by name.
  2. Run `profile_dataset(tmpdir, ...)`.
  3. Store plot PNGs via `blobs.put(conn, "plots", name, bytes, {"session_id": ...})`.
  4. Call `analysis.save_report` (with `plots` metadata), and `save_points` for each candidate with `metric="os_months"`, `unit="months"`.
  5. Set the attachments' status to `analysed`, or to `failed` with a fixed-text error.
  6. Post the timeline message `dataset_profiled` (title "Dataset profiled", body: sample count, drugs, number of candidates).
- **No more data-analysis files:** it no longer writes `data_analysis/*` files. `TaskResult.extra` keeps its keys, except that `artifact_path` becomes `None`.
- **Dataset not found:** `DatasetNotFoundError` returns `kind="data_profiled"` with no candidates, as today, and posts the timeline message `dataset_unusable`.

- [ ] **Step 1: Write failing tests:**
  - `test_profile_from_attachments_stores_report_points_and_plots` (`any_conn`: put the synthetic dataset as attachments, run the agent, then `fetch_report` has the summary and plots, `fetch_points` has every candidate key, and the session artifact dir has no `data_analysis/` folder);
  - `test_unusable_attachments_mark_failed_and_post_timeline`;
  - update `test_data_driven_outputs.py`, so the overview's dataset pointer now comes from `fetch_report`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** offline and on Atlas. Expected: PASS.
- [ ] **Step 5: Commit** `feat(data-analysis): analyse uploaded attachments and store results in the database`.

---

### Task 7: The planning step decides from an attachment inventory

**Files:**
- Modify:
  - `co_scientist/agents/supervisor.py`: lines ~100-135 (bootstrap), ~206-250 (`_parse_goal`), and the removal of `_detect_data_presence` (~691)
  - `config/prompts/parse_goal.md`
  - `co_scientist/agents/schemas.py`: `RECORD_RESEARCH_PLAN_TOOL`'s `data_sources` description becomes attachment ids
- Create: `co_scientist/attachments/inventory.py`
- Test: `co_scientist/tests/unit/test_supervisor_planning.py`

**Interfaces:**
- Produces:
  - `async def build_inventory(conn, cfg, session_id) -> list[dict]`, giving one entry per attachment: `{"id", "filename", "kind", "size", "header": list[str] | None, "sample_rows": list[list[str]] | None}`. For tabular files it decodes the first 64 KB only, reading the header and up to 3 rows with `table_delimiter`; documents get no header or rows.
  - `_parse_goal(deps, session, goal, preferences_text, inventory)` renders the inventory into the prompt as a fenced block. That block is untrusted text, so it goes through the existing quoting helpers in `co_scientist/safety/quoting.py`.
  - `plan.data_sources` is filtered to ids present in the inventory **and** of kind `tabular`, and `plan.has_dataset` is forced `False` when that filtered list is empty.
- **Bootstrap:**
  - If `plan.has_dataset`, enqueue `ProfileDataset` with `{"attachment_ids": plan.data_sources}`; otherwise enqueue `n_initial` generation tasks.
  - Before either, post the timeline message `attachments_received`, listing names, kinds and sizes, when there are any attachments.
  - The keyword and `data_dir` detection goes away. When parsing fails, the fallback plan is `has_dataset=False`.

- [ ] **Step 1: Write failing tests**, using the fake LLM pattern from `test_data_driven_outputs.py`:
  - `test_inventory_reads_header_and_three_rows_only`;
  - `test_plan_without_tabular_attachments_skips_analysis` (only a PDF attached and the LLM claims `has_dataset=True`: no `ProfileDataset` is enqueued, `n_initial` generation tasks are);
  - `test_plan_selects_only_known_tabular_ids` (the LLM returns one valid id, one unknown id and one PDF id; the payload has just the valid one);
  - `test_parse_goal_failure_defaults_to_no_dataset`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the full offline suite. Expected: PASS. Any test that relied on `data/` auto-detection is updated to attach its data instead; list each in the report.
- [ ] **Step 5: Commit** `feat(supervisor): plan from an attachment inventory before analysing`.

---

### Task 8: Document uploads go into the library (Atlas-only)

**Files:**
- Create: `co_scientist/library/uploads.py`
- Modify:
  - `co_scientist/storage/atlas/library.py`: `upsert_passages` gains keyword-only `source: str = "europepmc"` and `session_id: str | None = None`, stored on every passage;
  - `co_scientist/storage/atlas/indexes.py`: add the `library_text_v2` / `library_vec_v2` definitions, which are the v1 definitions plus `session_id` and `source` as filter fields (token in text, filter in vector);
  - `co_scientist/config.py` and `config/default.toml`: `LibraryCfg.search_index` and `vector_index` defaults change to the v2 names;
  - `co_scientist/library/search.py`: `build_hybrid_pipeline` / `hybrid_search` gain keyword-only `session_id: str | None`;
  - `co_scientist/tools/builtins/library.py`: pass `ctx.session_id`;
  - `pyproject.toml`: add `python-docx>=1.1`, and re-lock `uv.lock`.
- Create: `scripts/backfill_library_source.py`, a one-off that sets `source="europepmc"` on passages missing it, idempotently, with `--dry-run`.
- Test: `co_scientist/tests/unit/test_library_uploads.py`, `co_scientist/tests/unit/test_library_search.py`, `co_scientist/tests/atlas/test_hybrid_search.py`

**Interfaces:**
- **Parsing:** `def parse_document(filename: str, data: bytes, attachment_id: str) -> tuple[PaperMeta, list[Passage]]`.
  - PDFs are read with `pypdf.PdfReader`, DOCX with `docx.Document`.
  - Paragraphs are split as in `jats._split_text` with `max_chars`.
  - Anchors are `UPLOAD{attachment_id[:12]}#p{n}` and `kind="paragraph"`, and `PaperMeta.pmcid` holds `UPLOAD{attachment_id[:12]}`.
- **Ingest:** `async def ingest_attachment(conn, cfg, meta: AttachmentMeta) -> int`. It reads the blob, parses it, and upserts with `source="upload"` and `session_id=meta.session_id`. It sets the attachment's status to `ingested`, or `failed` with an error, and returns the number of passages.
- **URLs:** for uploads, `passage_url` returns `upload://{attachment_id}#{fragment}`.
- **Search scope:** the filter is `{"$or": [{"source": "europepmc"}, {"session_id": session_id}]}` in both branches of `$rankFusion`. With `session_id=None` the filter is `{"source": "europepmc"}`.
- **Indexes:** register the v2 specs. The v1 specs stay registered too, so `ensure_indexes` leaves them alone. Dropping v1 is a manual owner action, documented in Task 13.

- [ ] **Step 1: Write failing tests:**
  - `test_parse_pdf_and_docx_into_anchored_passages` (generate a 2-page PDF in memory with `pypdf`'s writer, or a fixture under `co_scientist/tests/fixtures/uploads/`, and a DOCX with `python-docx`);
  - `test_build_hybrid_pipeline_session_scope_filter` (the filter appears in both branches);
  - Atlas: `test_upload_passages_visible_only_to_their_session` (ingest an upload for session A; `hybrid_search` for A finds it, for B it doesn't; Europe PMC passages are found by both).
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.** Wire `ingest_attachment` so it's called for every `document` attachment right after upload (Task 11), on Atlas only.
- [ ] **Step 4: Run** offline and on Atlas. Expected: PASS. Then run `scripts/backfill_library_source.py --dry-run` against the real library and report the count, but **do not run it without `--dry-run`**; that is for the owner.
- [ ] **Step 5: Commit** `feat(library): searchable uploaded documents, scoped to their session`.

---

### Task 9: The final synthesis is stored in the database

**Files:**
- Create: `co_scientist/storage/{sqlite,atlas,repos}/syntheses.py`, `co_scientist/storage/migrations/0010_syntheses.sql`, `co_scientist/overview.py`
- Modify:
  - `co_scientist/agents/metareview.py` (~line 695: `syntheses.save` instead of `write_json(... "synthesis" ...)`; `overview_path` becomes `f"db:syntheses/{session.id}"`)
  - `co_scientist/agents/supervisor.py` (`_write_simple_overview` saves a minimal synthesis: `overview.markdown` = the body, `sources` = `[]`)
  - `co_scientist/cli.py` (~478, `report`), `co_scientist/web/app.py` (~186, the overview page), `co_scientist/mcp/session_server.py` (~663)
  - `test_repo_parity.py` (add `syntheses` to its module list)
- Test: `co_scientist/tests/unit/test_repos.py`, `co_scientist/tests/unit/test_data_driven_outputs.py`, `co_scientist/tests/unit/test_session_mcp.py`

**Interfaces:**
- **The repo:** `syntheses.save(conn, session_id, doc: dict) -> None` upserts `_id = session_id`; `syntheses.fetch(conn, session_id) -> dict | None`.
- **The reader helper:** `co_scientist/overview.py` has `async def load_overview_markdown(conn, cfg, session) -> str | None`.
  - For `final_overview` starting with `db:syntheses/`, it returns `syntheses.fetch(...)["overview"]["markdown"]`.
  - Otherwise, for legacy sessions, it reads the file as before, including the cite-lines JSON case.
- `cli report`, the web overview page and the MCP `session_overview` tool use this helper.

- [ ] **Step 1: Write failing tests:**
  - `test_synthesis_roundtrip` (`any_conn`);
  - `test_metareview_saves_synthesis_to_db_not_file` (no `final/synthesis.json` on disk; `fetch` has `overview.markdown` with the dataset pointer);
  - `test_load_overview_markdown_db_and_legacy_file`;
  - update `test_data_driven_outputs.py` to read from `syntheses.fetch`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** offline and on Atlas. Expected: PASS.
- [ ] **Step 5: Commit** `feat(metareview): store the final synthesis in the database`.

---

### Task 10: Agents post timeline messages at milestones

**Files:**
- Modify:
  - `co_scientist/agents/generation.py` (after a successful hypothesis insert)
  - `co_scientist/agents/reflection.py` (after a review)
  - `co_scientist/agents/ranking.py` (after an applied match)
  - `co_scientist/agents/evolution.py`
  - `co_scientist/agents/metareview.py` (`overview_ready`)
  - `co_scientist/agents/supervisor.py` (`session_done`)
- Test: `co_scientist/tests/unit/test_timeline_milestones.py`

**Interfaces:**
- Consumes `timeline.post` (Task 3).
- **Messages** (`kind`: title / body):

  | `kind` | title | body |
  |---|---|---|
  | `hypothesis_created` | the hypothesis title | first sentence of the summary; refs `[hid]` |
  | `review_completed` | "Review: <verdict>" | the scores line |
  | `match_result` | "<winner title> beat <loser title>" | the new Elo values |
  | `evolution_completed` | "Evolved: <title>" | |
  | `overview_ready` | "Research overview ready" | |
  | `session_done` | "Session finished" | the stop reason |
- **Sampling:** post `match_result` only for the first 10 matches of a session, and then every 10th, so the timeline doesn't flood. Use `tournaments.count_matches`. The sampling threshold is a module constant.

- [ ] **Step 1: Write failing tests:**
  - `test_generation_posts_hypothesis_created`, using the fake LLM pattern;
  - `test_match_result_sampling`: drive 25 applied matches through `RankingAgent` with a fake verdict, and exactly matches 1-10 and 20 post;
  - `test_milestone_post_failure_does_not_fail_agent`: monkeypatch `timeline_repo.append` to raise; the agent's `TaskResult` is unchanged.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the full offline suite. Expected: PASS.
- [ ] **Step 5: Commit** `feat(timeline): agents post milestones as they happen`.

---

### Task 11: API routes for the React app

**Files:**
- Modify: `co_scientist/web/app.py`
- Create: `co_scientist/web/research_view.py` (pure mapping)
- Test: `co_scientist/tests/unit/test_web_api.py`, `co_scientist/tests/unit/test_research_view.py`

**Interfaces:**
- **`POST /api/sessions`** (multipart: `question: str`, `files: list[UploadFile]` (optional), `budget_usd: float | None`)
  1. Read the uploads.
  2. `accept_uploads` (Task 2): on `IntakeError`, respond with its status code and the message.
  3. Check the `max_session_mb` and `max_total_mb` limits with `attachments.session_bytes` / `total_bytes`: 413.
  4. Create the session row.
  5. Store each file with `blobs.put` + `attachments.insert`.
  6. On Atlas, `ingest_attachment` each document.
  7. Start the `Supervisor` with `asyncio.create_task`, as `create_session` does today, but with the session id known up front.
  8. Return `{"session_id": ...}` with status 201.
- **`Supervisor.run_session`** gains an optional `session_id: str | None` parameter, so the API can create the session row first. Only add what's needed.
- **`GET /api/sessions/{id}/timeline?after_seq=0`** returns `{"messages": [...]}` (Task 3 shape).
- **`GET /api/sessions/{id}/research`** returns a `ResearchSession` matching `frontend/src/types/research.ts` exactly: `{"id", "isDemo": false, "hypotheses": [Hypothesis]}`.
  - The mapping is in `research_view.to_research_session(session_id, hypotheses, report, points_by_key)`.
  - Hypotheses are those in `in_tournament` and `pinned`, or `reviewed` when none are in the tournament yet. They are sorted by Elo (descending, with nulls last), and `rank` is 1-based.
  - `abstract` is the first paragraph of `full_text`, and `explanation` is the rest.
  - `dataSummary` is `{description, metric, unit}`, from `data_evidence` and the candidate. `dataPoints` are the `{id: sample_id, label: sample_id, group, value}` points for the hypothesis's `data_evidence["candidate_key"]`, or `[]`.
  - `sources` map `citations` into `SourceRecord`, deriving `publication` and `evidenceType` as in spec §11. `upload://` URLs become `url: null`.
  - Only the `candidate_key`s referenced by the returned hypotheses are fetched.
- **`GET /api/sessions/{id}/synthesis`**, `/overview` and `/sources`: same response shapes as today, now read from `syntheses.fetch`, with 404 when missing.
- **`GET /api/sessions/{id}/analysis`** returns `analysis.fetch_report` minus the `blob_id`s, with each plot given a `url` of `/api/sessions/{id}/plots/{name}`.
- **`GET /api/sessions/{id}/plots/{name}`** returns `image/png` bytes via `blobs.get`, or 404 when the name isn't in the report.
- **`GET /api/sessions/{id}/attachments`** returns `{"attachments": [{id, filename, kind, size, status}]}`.
- **Errors and IDs:**
  - Route handlers catch `PyMongoError` and return 503 with fixed text.
  - `session_id` path parameters are validated against `^ses_[0-9A-Z]{26}$`, giving 400 otherwise. This also closes the path-from-URL issue in the cite-lines endpoints.
- **CLI:** `co-scientist attachments prune --older-than DAYS [--yes]` lists old attachments with `older_than`, deletes their blobs and metadata, and prints a dry-run list unless `--yes`.

- [ ] **Step 1: Write failing tests**, using FastAPI `TestClient` on a SQLite `tmp_cfg` with the supervisor start monkeypatched to a no-op:
  - `test_post_sessions_stores_files_and_returns_id`;
  - `test_post_sessions_rejects_oversize_and_bad_ext` (400 and 413);
  - `test_post_sessions_enforces_session_and_total_quota` (413);
  - `test_research_matches_frontend_shape`: assert the exact key sets of `ResearchSession`, `Hypothesis`, `SourceRecord`, `DataPoint` and `DataSummary`, copied from `frontend/src/types/research.ts`;
  - `test_research_excludes_rejected_and_quarantined`;
  - `test_research_loads_only_linked_points` (spy on `analysis.fetch_points`);
  - `test_synthesis_routes_read_db`;
  - `test_plots_route_streams_png_and_404s_unknown`;
  - `test_bad_session_id_is_400`;
  - `test_prune_dry_run_then_yes`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** offline, then the Atlas variants of the upload and research tests (`any_conn`-style parametrisation of the app config). Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): routes the React app needs, served from the database`.

---

### Task 12: SSE stream carries timeline messages, from a change stream on Atlas

**Files:**
- Modify: `co_scientist/web/app.py`, `api_events` (~line 299)
- Create: `co_scientist/storage/atlas/watch.py` and `co_scientist/storage/sqlite/watch.py`, behind `co_scientist/storage/repos/watch.py`
- Modify: `test_repo_parity.py` (add `watch` to its module list)
- Test: `co_scientist/tests/unit/test_web_events.py`, `co_scientist/tests/atlas/test_watch.py`

**Interfaces:**
- **Watching:** `watch.timeline_after(conn, session_id, after_seq: int) -> AsyncIterator[TimelineMessage]`.
  - On Atlas, it first yields `list_for_session(after_seq)`, then follows a change stream (`conn.coll("timeline").watch([{"$match": {"operationType": "insert", "fullDocument.session_id": session_id}}])`), skipping any `seq <= last_yielded`.
  - On SQLite, it yields the backlog, then polls `list_for_session` every 1 s.
  - It closes cleanly when the consumer stops.
- **`api_events`:**
  - It keeps today's replay of the last 25 `events`, and today's in-process bus for the existing event names.
  - It adds `timeline_message` SSE events from `watch.timeline_after`, starting at `?after_seq=` or the browser's `Last-Event-ID`.
  - Each timeline SSE event sets `id: <seq>`, so `EventSource` reconnects send `Last-Event-ID`.
  - Duplicates of the same `seq` arriving from both the bus and the watcher are dropped by `seq`.

- [ ] **Step 1: Write failing tests:**
  - `test_events_stream_includes_timeline_messages` (SQLite: post 3 messages, open the stream, receive 3 `timeline_message` events with `id` 1..3);
  - `test_events_stream_resumes_timeline_after_seq` (open with `Last-Event-ID: 2`, receive only `seq` 3+, with no duplicates when the bus also publishes);
  - Atlas: `test_watch_delivers_inserts_from_another_connection`, which inserts via a second `AtlasConn` and receives the message through the change stream within 5 s.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** offline and on Atlas. Expected: PASS.
- [ ] **Step 5: Commit** `feat(api): stream timeline messages, via change streams on Atlas`.

---

### Task 13: Documentation and frontend handoff

**Files:**
- Modify:
  - `docs/storage-integration.md`: new collections and buckets; the upload flow; the planning inventory; the API table; the `timeline_message` SSE event and `Last-Event-ID`; the v2 library indexes, with the owner action to drop v1 after the switch; the backfill script; prune.
  - `README.md` "Built on MongoDB Atlas": add rows for GridFS, change streams and the new collections.
- Create: `docs/frontend-api.md`, written for the UI teammate:
  - every route, with request and response examples;
  - the TypeScript interfaces for `TimelineMessage`, `AnalysisReport` and `AttachmentInfo`, which don't exist in `frontend/src/types` yet;
  - the one-line change of adding `'timeline_message'` to `KNOWN_EVENT_NAMES`;
  - a note that `frontend/src/data/mock*.ts` must be committed now that `.gitignore` is anchored to `/data/`.
- [ ] **Step 1:** Write the docs. Every route and field named must exist in the code; verify by grep.
- [ ] **Step 2:** Run `uv run pytest -q`, `uv run ruff check co_scientist scripts`, and once `CO_SCI_ATLAS_TESTS=1 uv run pytest -q`. All must be green.
- [ ] **Step 3:** Commit `docs: storage, API and frontend handoff for results in Atlas`.
