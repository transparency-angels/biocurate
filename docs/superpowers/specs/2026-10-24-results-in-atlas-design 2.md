# Results, attachments and live timeline in Atlas: design

Date: 2026-10-24 · Owner of the database side: the MongoDB track owner · UI: the
React app in `frontend/` (built by a teammate, currently on mock data)

## 1. Intent

A researcher opens the React UI, types a research question and attaches their own
material. Everything they then see comes from MongoDB Atlas:
- the live progress of the run;
- every result (hypotheses with their citations, reviews, the data-analysis report and its plots, the final synthesis with its sources);
- the attachments themselves.

Nothing the researcher reads is served from files on the server. They can leave and
come back to the session later and it is all still there.

Why: the hackathon's MongoDB track requires Atlas to be the core store. Results today
are written as files under `data/artifacts/<session>/`, and the database holds only
the outline (rows without citations, evidence or reports). The UI is built against
mock modules that are meant to be swapped for the real API without UI changes. This
design defines that API and the storage behind it.

## 2. Goals

1. **Attachments in Atlas.**
   - The UI's composer submits `{question, files}`: up to 5 files, 25 MB each, PDF, DOCX, TXT or CSV (`frontend/src/features/research/attachments.ts`, `types.ts`).
   - Files are stored in Atlas GridFS, because single documents cap at 16 MB and the sample tables are up to 33 MB.
   - Each file is tagged with its session, and the agents read them from there.
2. **All results in Atlas.** These are written to the database instead of, or in addition to, files:
   - hypothesis citations (with `line_range`) and `data_evidence`;
   - review evidence and assumption checks;
   - the data-analysis report (summary, test table, methods, candidates) and its Kaplan-Meier plots (GridFS);
   - the final synthesis (overview and sources) in the JSON shape the cite-lines work defined and the UI's `researchOverview.ts` already parses.
3. **A live timeline.** Agents append short, human-readable messages to a per-session timeline as milestones happen. The UI receives them live, and on reconnect gets the history.
4. **An HTTP API the React app can switch to unchanged.** Responses match the UI's existing types (`frontend/src/types/research.ts`, `researchOverview.ts`, `researchEvents.ts`).
5. **Both backends keep working.** Every new repo function has a SQLite twin, so `test_repo_parity` and the offline CI suite stay green. The demo and the app run on Atlas.

## 3. Non-goals (for now)

- **Answering follow-up questions in the chat.** The timeline's message schema leaves room for `role: "user"` messages and replies, but no agent answers them yet. The owner deferred this until the chat UI exists.
- **Building or restyling UI screens.** The teammate owns `frontend/`. This work only adds the API it calls, plus at most the thin "real source instead of mock" switch where the UI already has a seam (`createSseEventSource`).
- **Moving debugging data into Atlas.** That covers raw LLM transcripts, the web-fetch cache and MCP capture records. These stay on disk.
- **Migrating existing sessions' artifact files into the database.**
- **Running the friend's `scripts/load_to_mongo.py` or `scripts/biomarker_summary.py` as part of a session.** They stay standalone developer tools (see §8).

## 4. Anti-goals (failure even if it technically works)

- **The UI showing something the database doesn't have**, such as results read from a file after this lands.
- **A failure in the timeline or attachment handling crashing a research session.** Timeline writes are best-effort; a lost message must never fail an agent.
- **Secrets or cluster host names reaching the UI, the timeline or logs.**
- **Unbounded storage growth.** Many judges uploading 5 × 25 MB at once is expected; attachment size and count are enforced server-side, not just in the browser.

## 5. Constraints

- **Storage seam.** Everything goes through `co_scientist/storage/repos/*`, using `dual(sqlite_fn, atlas_fn)`, with no direct driver calls outside `storage/`. This is enforced by `test_repo_parity` and `test_no_raw_sql`. The PyMongo async API (`AsyncMongoClient`, and GridFS via `pymongo.asynchronous` / `AsyncGridFSBucket`) is used; Motor is not.
- **Collection access.** Atlas collections are accessed via `AtlasConn.coll(name)`, so test prefixes apply. GridFS buckets also need the prefix, using `bucket_name = prefix + "attachments"`.
- **Cluster.** M10, MongoDB 8.0.34, so change streams are available.
- **Events contract.** The UI's existing event contract, `GET /api/sessions/{id}/events` with named SSE events, must keep working as documented in `frontend/src/types/researchEvents.ts`. New event names may be added; the UI keeps unknown events in its activity log and ignores them for state.
- **Repo hygiene.** Commits carry no Co-Authored-By lines or model names.

## 6. Decisions made in conversation

Each item says whether the owner decided it or it is the designer's call.

- **Results go in the database, not JSON files** (owner). The cite-lines JSON shapes are kept as the document shape, but stored in Atlas.
- **The data-analysis agent gets its data from the UI's attachments** (owner), not from `data/`.
- **Follow-up answering is deferred** (owner).
- **When the plan selects tabular attachments (CSV, TXT) for analysis** (see §12), the data-analysis agent pulls them from GridFS into a temporary directory, keeping their original filenames because `analysis.py` matches files by name pattern, and runs the existing `analysis.py` unchanged. *(Designer's call: the least invasive glue; the analysis code expects a folder.)*
- **Document attachments (PDF, DOCX) become evidence-library passages** tagged `source: "upload"` and `session_id`. `search_library` then finds them alongside Europe PMC passages, scoped to that session plus the shared library. PDF text extraction uses `pypdf` (already a dependency); DOCX needs a new dependency, `python-docx`. *(Designer's call.)*
- **Timeline transport:**
  - Each timeline message is stored in a `timeline` collection.
  - It is also published as a new SSE event `timeline_message` on the existing `/api/sessions/{id}/events` stream, so the UI needs no second connection.
  - On Atlas, the SSE endpoint reads new events and timeline messages from a change stream, so a session started by a different process (CLI, another worker) still streams. The in-process bus remains for SQLite.
  - *(Designer's call.)*

## 7. Data model (Atlas; SQLite twins mirror it)

### 7.1 `attachments` (GridFS bucket) + `attachments_meta` collection
- **GridFS file metadata:** `session_id`, `filename`, `content_type`, `size`, `sha256`, `kind` (`"tabular" | "document"`), `uploaded_at`.
- **`attachments_meta`:** one document per file, holding the same fields plus `gridfs_id` and processing status (`stored | ingested | analysed | failed`, with `error`). It is the queryable index; GridFS holds the bytes.
- **SQLite:** a table with a BLOB column (the 25 MB cap fits) and the same metadata columns.

### 7.2 Results on existing documents
- **`hypotheses`:** gains `citations` (the list of `CitedPaper` dicts, including `line_range`) and `data_evidence`. The Atlas mapper writes and reads them; today it drops them on purpose (`storage/atlas/hypotheses.py`). SQLite adds JSON text columns via a migration.
- **`reviews`:** gains `evidence` and `assumptions`, handled the same way.
- **Files:** the hypothesis and review artifact JSON files keep being written for now. Debugging relies on them, and the plugin path reads them. The UI and API read only the database.

### 7.3 `analysis_reports`
One document per session (`_id = session_id`), holding:
- `summary_markdown`;
- `tests` (list of rows);
- `methods`;
- `candidates`;
- `plots` (list of `{name, gridfs_id, content_type}`, with PNGs in a `plots` GridFS bucket);
- `created_at`.

It replaces `data_analysis/summary.md`, `statistical_tests.csv` and the PNG files as what the API serves.

### 7.4 `syntheses`
One document per session (`_id = session_id`). It contains exactly the cite-lines `synthesis.json` content (`overview`, `sources`, `sources_list`, `generated_at`). `sessions.final_overview` points at it (`"db:syntheses/<session_id>"`), in place of a file path. The simple fallback overview written by the supervisor becomes a minimal `syntheses` document too.

### 7.5 `timeline`
- **Fields:** `session_id`, `seq` (monotonic per session), `ts`, `role` (`"system"` now, `"user" | "assistant"` reserved), `agent`, `kind`, `title`, `body_markdown`, `refs` (ids of hypotheses, sources or attachments mentioned).
- **Index:** `(session_id, seq)` unique.
- **Kinds written now (designer's call):**
  - `attachments_received`
  - `dataset_profiled` (with headline stats)
  - `documents_ingested`
  - `hypothesis_created` (title + one-line summary)
  - `review_completed` (verdict)
  - `match_result` (winner and new Elo, sampled)
  - `evolution_completed`
  - `overview_ready`
  - `session_done`

## 8. Relationship to the teammates' scripts

`scripts/load_to_mongo.py` drops and rebuilds `samples`, `treatments` and `genes` from `data/`. `scripts/biomarker_summary.py` writes `workspace/*.md`. Both predate the decision that data comes from attachments. They stay as standalone tools, outside the session pipeline. The loader currently stores gene *numbers* instead of names; the header row of the alteration matrices is misread. That is reported to its author and not fixed here.

## 9. API the React app switches to

All routes are under `/api` in `co_scientist/web/app.py`. They are JSON unless noted.

| Route | Returns (UI type) | Source |
|---|---|---|
| `POST /api/sessions` (multipart: `question`, `files[]`) | `{session_id}` | creates the session, stores attachments, starts the run |
| `GET /api/sessions/{id}` | existing session JSON (status etc.) | `sessions` |
| `GET /api/sessions/{id}/events` | SSE (existing names + `timeline_message`) | `events` + `timeline` |
| `GET /api/sessions/{id}/timeline` | list of timeline messages | `timeline` |
| `GET /api/sessions/{id}/research` | `ResearchSession` (`research.ts`) | `hypotheses` + `reviews` + `analysis_reports` |
| `GET /api/sessions/{id}/synthesis` | synthesis JSON (`researchOverview.ts` raw types) | `syntheses` |
| `GET /api/sessions/{id}/analysis` | analysis report JSON | `analysis_reports` |
| `GET /api/sessions/{id}/plots/{name}` | PNG bytes | `plots` bucket |
| `GET /api/sessions/{id}/attachments` | list of attachment metadata | `attachments_meta` |

`/overview` and `/sources` (from the cite-lines work) are re-pointed from files to `syntheses` and keep their response shape.

Mapping to the UI's `Hypothesis`:
- `rank` is the Elo order; `title` and `summary` come straight from the hypothesis;
- `abstract` is the first paragraph of `full_text`, and `explanation` is the rest;
- `dataSummary` and `dataPoints` come from `data_evidence` and `analysis_points` (§12), and are empty when there is no dataset;
- `sources` come from `citations`, with `evidenceType` and `publication` derived as in §11.

## 10. What is left to the builder

- Exact repo function names and signatures, following the existing module style.
- How the change-stream SSE reader resumes after a reconnect (resume tokens versus a `seq` / `ts` cursor).
- The SQLite migration numbering and column types.
- Which timeline messages are sampled versus always written, within the kinds in §7.5, so a long tournament doesn't flood the timeline.
- Server-side limits enforcement: 5 files, 25 MB, the four extensions, and content-type sniffing.

## 11. Calls made after the builder check

These are the designer's calls. The owner can override any of them.

- **Timeline messages reach the UI as a named SSE event `timeline_message`.**
  - The UI's `createSseEventSource` only listens for names in `KNOWN_EVENT_NAMES`, so the teammate adds `'timeline_message'` to that list. That is a one-line change.
  - This design defines the payload (§7.5 fields) and the response shapes of `/timeline`, `/analysis` and `/attachments`. A copy of them as TypeScript types is handed to the teammate in `docs/storage-integration.md`.
  - Until that one-line change lands, the UI simply doesn't show timeline messages. Nothing breaks.
- **Library scoping uses new, versioned search indexes**, `library_text_v2` and `library_vec_v2`. They add `session_id` and `source` as filter fields. The config switches to them once they are queryable. The live v1 indexes are not dropped, which avoids search downtime and the owner-only drop-and-recreate.
- **Document uploads (ingestion into the library, and searching it) are Atlas-only**, like the library itself. On SQLite, uploads are stored but not ingested. This is an explicit exception to goal 5, which applies to the repos.
- **`SourceRecord` derivation:**
  - `publication`: the library passage's `journal` when the citation URL matches a library passage `url`; otherwise the URL's host name.
  - `evidenceType`: `"Dataset"` for citations of uploaded tabular data. `"Review"` when the title or journal matches a review pattern (`review`, `meta-analysis`). `"Clinical study"` for clinical-trial patterns (`trial`, `cohort`, `patients`). `"Experimental study"` otherwise.
  - Uploaded documents are cited with the URL `upload://<attachment_id>#<anchor>`, and the API maps that to a null `url`, so the card shows "Source link unavailable".
- **`/research` returns** hypotheses in `in_tournament` and `pinned` (and `reviewed`, if the tournament hasn't started yet), ranked by Elo. `rejected`, `quarantined` and `retired` are never returned.
- **Storage limits:**
  - per request: 5 files and 25 MB each;
  - per session: 125 MB;
  - globally: a configurable `[attachments] max_total_mb` (default 2048). Uploads are rejected with 413 when it would be exceeded.
  - No TTL; cleanup is a manual command `co-scientist attachments prune --older-than <days>`.

## 12. Owner decisions after the builder check

- **Zipped uploads are accepted (owner).**
  - The UI may send a `.zip`; the server unpacks it and stores each member as its own attachment, inheriting the session.
  - The 25 MB limit applies to the upload. Unpacked content is limited separately, so the demo set (one metadata table plus three matrices of about 34 MB each) fits:
    - total unpacked size: `[attachments] max_unzipped_mb`, default 512;
    - number of members: 50.
  - Each member must have one of the accepted extensions (PDF, DOCX, TXT, CSV); other members are skipped and reported in the timeline.
  - Nested zips are not unpacked.
  - Path components are discarded (no `..`, no absolute paths), and the size is checked while streaming, not from the header, as a zip-bomb guard.
- **Attachments are not routed straight to the data-analysis agent (owner).**
  - The session's planning step, the goal parse that builds the `ResearchPlan`, sees an inventory of the attachments first: name, size, kind, plus for tabular files the header row and a few sample rows.
  - It decides `has_dataset` and `data_sources` (the specific attachment ids to analyse), using the fields PR #2 already added to `ResearchPlan`.
  - The data-analysis agent runs only when the plan sets `has_dataset`, and only on the chosen files. An upload that holds only papers, or tables that aren't analysable data, never triggers it.
  - The current `data_dir` / `_detect_data_presence` path is replaced by this inventory.
  - PDFs and DOCX files are still ingested into the library independently of the plan, since that is retrieval, not analysis.
- **This supersedes** §6's "tabular attachments feed the data-analysis agent" and §7.1's processing statuses. `analysed` is now set only for files the plan selected.
- **Per-sample values are saved (owner).**
  - `analysis.py` is extended (an exception to "runs unchanged"): for each screened candidate (biomarker × drug), it returns the per-sample rows it already computes in `_screen_single_matrix`, which are currently discarded.
  - The rows are stored in a new `analysis_points` collection, one document per candidate:
    - `session_id`
    - `candidate_key` (biomarker + drug)
    - `metric` (e.g. `"os_months"`) and `unit`
    - `points` (list of `{sample_id, group: "altered" | "unaltered", value}`)
  - One document per candidate keeps each well under 16 MB (about 24k samples × a few fields).
  - **Linking to hypotheses:** a hypothesis's `data_evidence` carries the `candidate_key`. `/research` fills `dataPoints` from the matching `analysis_points` (label = `sample_id`) and `dataSummary` from the aggregates (`metric`, `unit`, and a one-line description).
  - **Patient-level data:** these rows contain sample identifiers from the researcher's own upload. They stay scoped to the session, and are only returned by that session's `/research` route.
