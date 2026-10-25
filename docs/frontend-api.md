# Frontend API guide

For the UI teammate: you know React and TypeScript, not this backend. This page
lists every JSON route the React app can call, what comes back, and how it fails.
The code is in `co_scientist/web/app.py` (routes) and
`co_scientist/web/research_view.py` (the `ResearchSession` mapping).

Start the server with `co-scientist serve` (default `http://127.0.0.1:7878`).
There is no authentication; it is a local tool.

All results (timeline, attachments, analysis report, plots, synthesis) come from
the database, so a page reload or a second browser tab shows the same data.

---

## 1. Conventions

- **Session ids** look like `ses_` plus 26 uppercase letters or digits, for
  example `ses_01JABCDEFGHJKMNPQRSTVWXYZ0`. Every `/api/sessions/{session_id}/...`
  route checks the id against `^ses_[0-9A-Z]{26}$` first.
- **Times** in the timeline are epoch milliseconds (numbers). Times inside the
  raw session row are ISO strings.
- **Errors** are JSON: `{"detail": "<text>"}`. Branch on the status code, not the text.

### Error status codes

| Status | When | `detail` |
|---|---|---|
| 400 | Malformed session id (does not match `^ses_[0-9A-Z]{26}$`) | `invalid session id` |
| 400 | `POST /api/sessions` intake problems (section 3) | see the table there |
| 404 | Unknown session, or the thing you asked for does not exist yet | route specific |
| 413 | Upload too large or over a storage quota (section 3) | explains which limit |
| 422 | A required form field is missing, or `GET /timeline` got an `after_seq` that is not a non-negative integer (`/events` treats a bad value as 0 instead) | FastAPI validation list |
| 500 | `/overview`, `/sources` or `/synthesis` of an old session whose result file on disk is unreadable | `stored file is unreadable` |
| 503 | The database is unavailable | always exactly `database unavailable` |

The 503 text is fixed on purpose: the real database error can contain host names
and credentials, so it is only written to the server log.

Because the session id is checked before anything else, a malformed id gives 400
even for a session that could never exist; a well-formed but unknown id gives 404
(on routes that look the session up).

---

## 2. Routes at a glance

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/sessions` | Start a research session, optionally with files |
| GET | `/api/sessions/{id}` | The raw session row |
| GET | `/api/sessions/{id}/research` | The ranked hypotheses in the `ResearchSession` shape |
| GET | `/api/sessions/{id}/timeline` | Progress messages |
| GET | `/api/sessions/{id}/events` | Live stream (SSE) |
| GET | `/api/sessions/{id}/overview` | The final overview |
| GET | `/api/sessions/{id}/sources` | The final overview's source list |
| GET | `/api/sessions/{id}/synthesis` | Overview and sources together |
| GET | `/api/sessions/{id}/analysis` | The data-analysis report |
| GET | `/api/sessions/{id}/plots/{name}` | One plot image (PNG) |
| GET | `/api/sessions/{id}/attachments` | Files attached to the session |
| GET | `/api/sessions/{id}/metrics` | Cost and progress counters |
| POST | `/api/sessions/{id}/pause`, `/resume`, `/abort` | Control a running session |
| POST | `/api/sessions/{id}/feedback` | Send researcher feedback |
| GET | `/healthz` | Liveness check, returns `{"ok": true}` |

---

## 3. `POST /api/sessions`: start a session

Starts a research session in the background and returns its id straight away.
Follow progress with the timeline and the event stream.

**Request:** `multipart/form-data`.

| Field | Required | Notes |
|---|---|---|
| `question` | yes | The research question. Whitespace is trimmed; blank is a 400 |
| `files` | no | Repeat the field once per file. `.pdf`, `.docx`, `.csv`, `.txt`, or a `.zip` of those |
| `budget_usd` | no | Positive number. Defaults to the server's budget |

```ts
const form = new FormData()
form.append('question', 'Which biomarkers predict response to FOLFOX?')
for (const f of files) form.append('files', f)   // same field name each time
form.append('budget_usd', '5')

const res = await fetch('/api/sessions', { method: 'POST', body: form })
// Do not set Content-Type yourself; the browser adds the multipart boundary.
```

Equivalent curl:

```bash
curl -X POST http://127.0.0.1:7878/api/sessions \
  -F 'question=Which biomarkers predict response to FOLFOX?' \
  -F 'files=@patient_metadata.csv' -F 'files=@mutations.csv' \
  -F 'budget_usd=5'
```

**Response: 201**

```json
{ "session_id": "ses_01JABCDEFGHJKMNPQRSTVWXYZ0" }
```

Files are stored and the session row exists before this returns. The agents run
afterwards, in the background.

**What the server does with files**

- `.pdf` and `.docx` are "documents": their text is indexed so agents can search
  and cite it.
- `.csv` and `.txt` are "tabular": the analysis agent profiles them.
- A `.zip` is opened and its supported members are treated as separate files. Members
  that cannot be used (nested zip, hidden or unsafe name, unsupported type,
  encrypted, unsupported compression) are skipped, not fatal; the skipped list
  appears in a timeline message of kind `attachments_received`.
- Two files with the same name get ` (2)`, ` (3)`... added.

**Errors**

| Status | Cause |
|---|---|
| 400 | `question is required` (blank question) |
| 400 | `budget_usd must be a positive number` (zero, negative, NaN, infinity) |
| 400 | `at most N files may be attached` (more than `max_files`, default 5) |
| 400 | `an upload has an invalid file name` |
| 400 | `<name> is larger than N MB` (one file over `max_file_mb`, default 25) |
| 400 | `<name>: unsupported file type` (only pdf, docx, csv, txt, zip) |
| 400 | `<zip> could not be read as a zip archive` (corrupt or unreadable zip) |
| 413 | `<zip> has too many entries` (over 1000 entries) |
| 413 | `<zip> exceeds N files in total` (over `max_zip_members`, default 50) |
| 413 | `... pushes the upload past N MB` (total unpacked size over `max_unzipped_mb`, default 512) |
| 413 | `attachments exceed the N MB per-session limit` (`max_session_mb`, default 512) |
| 413 | `attachments exceed the N MB storage limit` (`max_total_mb`, default 2048) |
| 422 | `question` field missing |
| 503 | `database unavailable` |

The limits live in the server config under `[attachments]` (`max_files`,
`max_file_mb`, `max_unzipped_mb`, `max_zip_members`, `max_session_mb`,
`max_total_mb`). The API has no endpoint that reports them, so do not hard-code
the numbers in the UI beyond a friendly hint; rely on the error text.

---

## 4. Reading a session

### `GET /api/sessions/{id}`

The stored session row: `id`, `status`, `research_goal`, `research_plan`,
budget fields, `final_overview`, timestamps and so on. `status` is one of
`running`, `paused`, `done`, `failed`, `aborted`.

Errors: 404 if the session does not exist (`detail` is FastAPI's default `Not Found`).

### `GET /api/sessions/{id}/research`

The ranked hypotheses, already in the `ResearchSession` shape from
`frontend/src/types/research.ts`. Replaces the mock data in the results page.

```json
{
  "id": "ses_01JABCDEFGHJKMNPQRSTVWXYZ0",
  "isDemo": false,
  "hypotheses": [
    {
      "id": "hyp_...",
      "rank": 1,
      "title": "KRAS mutation predicts poorer response to FOLFOX",
      "summary": "One-line summary",
      "abstract": "First paragraph of the full text",
      "explanation": "The remaining paragraphs",
      "dataSummary": {
        "description": "KRAS mutation and survival on FLUOROURACIL (Δ median OS -4.2 months, p = 0.003, n = 412)",
        "metric": "os_months",
        "unit": "months"
      },
      "dataPoints": [
        { "id": "S1", "label": "S1", "group": "altered", "value": 12.4 }
      ],
      "sources": [
        {
          "id": "hyp_...-s1",
          "title": "Paper title",
          "publication": "Nature Medicine",
          "year": 2021,
          "evidenceType": "Clinical study",
          "description": "Excerpt the agent quoted",
          "url": "https://europepmc.org/article/PMC/PMC1234567#s3.p5"
        }
      ]
    }
  ]
}
```

Notes:

- Hypotheses shown: those in the tournament or pinned, best Elo first (`rank`
  counts from 1). Before any tournament exists, reviewed hypotheses are shown too.
- `dataSummary` is empty strings and `dataPoints` is `[]` for a hypothesis with no
  linked dataset result.
- A source cited from an uploaded file has `url: null`, `publication` set to the
  file name, and `evidenceType: "Dataset"` when the file was tabular.
- `url` is `null` whenever the stored link is not a real `http(s)` URL.
- `isDemo` is always `false` here.

Errors: 404 `session not found`.

### `GET /api/sessions/{id}/timeline?after_seq=N`

The progress messages, oldest first. `after_seq` (default 0) returns only messages
with `seq` greater than `N`.

```json
{
  "messages": [
    {
      "seq": 1,
      "ts": 1761300000000,
      "role": "system",
      "agent": null,
      "kind": "attachments_received",
      "title": "Attachments received",
      "body_markdown": "patient_metadata.csv · tabular · 20480",
      "refs": []
    }
  ]
}
```

Fields: `seq` (integer, starts at 1, unique per session), `ts` (epoch ms), `role`
(`"system"`, `"user"` or `"assistant"`), `agent` (string or `null`), `kind` (a
short machine label; treat it as an open string, new kinds appear as features are
added), `title`, `body_markdown`, `refs` (list of strings).

An unknown session returns `{"messages": []}`, not a 404.

### `GET /api/sessions/{id}/overview`, `/sources`, `/synthesis`

`/synthesis` is the whole stored document; `/overview` and `/sources` return its
`overview` and `sources` parts. For sessions that finished before results moved
into the database, the server falls back to the old JSON files on disk.

```json
{
  "session_id": "ses_...",
  "generated_at": "2026-10-24T18:03:11+00:00",
  "overview": { "...": "parsed overview sections" },
  "sources": { "sources": [ { "...": "one entry per cited source" } ] },
  "sources_list": [ { "...": "same entries as sources.sources" } ]
}
```

The exact inner shape of `overview` and `sources` is produced by the meta-review
agent. Check a real response before you type it.

Errors: 404 `overview not found`, `sources not found` or `synthesis not found`.
There is no overview until the session finishes meta-review.

### `GET /api/sessions/{id}/analysis`

The data-analysis report (Kaplan-Meier and log-rank biomarker screen). It exists
only when the session had a usable tabular attachment.

```json
{
  "candidates": [
    {
      "candidate_key": "KRAS|mutation|FLUOROURACIL",
      "biomarker": "KRAS",
      "alteration_type": "mutation",
      "drug": "FLUOROURACIL",
      "p_value": 0.003
    }
  ],
  "drugs": ["FLUOROURACIL"],
  "sample_count": 412,
  "generated_at": "2026-10-24T18:01:02+00:00",
  "created_at": "2026-10-24T18:01:03+00:00",
  "endpoint": { "...": "which duration and event columns were used" },
  "survival_curves": [ { "...": "per-plot curve data" } ],
  "tests": [ { "...": "one row per tested comparison" } ],
  "tests_truncated": true,
  "tests_total": 5400,
  "summary_markdown": "# Dataset analysis\n...",
  "plots": [
    {
      "name": "kaplan_meier_1",
      "content_type": "image/png",
      "url": "/api/sessions/ses_.../plots/kaplan_meier_1"
    }
  ]
}
```

The candidate entries carry more statistics than shown (medians, counts and so
on); the example lists only the fields the rest of the API relies on. `tests` is
capped to keep the document small; when it was cut, `tests_truncated` is `true`
and `tests_total` is the full count (both fields are absent otherwise).

Each plot gets a ready-made `url`. Use it directly as an image source.

Errors: 404 `analysis not found`.

### `GET /api/sessions/{id}/plots/{name}`

The PNG bytes of one plot (`Content-Type: image/png`). `name` comes from the
`plots[].name` in the analysis response; use the `url` given there, which is
already URL-encoded.

```tsx
<img src={plot.url} alt={plot.name} />
```

Errors: 404 `plot not found`.

### `GET /api/sessions/{id}/attachments`

```json
{
  "attachments": [
    {
      "id": "att_...",
      "filename": "patient_metadata.csv",
      "kind": "tabular",
      "size": 20480,
      "status": "analysed"
    }
  ]
}
```

`kind` is `tabular` or `document`. `status` is `stored`, `ingested` (document
text indexed), `analysed` (dataset profiled) or `failed`. There is no download
route for the original file.

Errors: 404 `session not found`.

### `GET /api/sessions/{id}/metrics`

Counters for cost and progress (tokens, spend, hypothesis and task counts). The
keys come straight from the backend's metrics object; inspect a response before
typing it.

---

## 5. Controlling a session

All four return `{"ok": true}` (feedback also returns `feedback_id`). They do not
check that the session exists.

- `POST /api/sessions/{id}/pause`
- `POST /api/sessions/{id}/resume`
- `POST /api/sessions/{id}/abort`
- `POST /api/sessions/{id}/feedback`: form fields `text` (required), `kind`
  (default `directive`; `pin` and `rejection` also change the target hypothesis'
  state), `target_id` (a hypothesis id, optional).

```ts
const body = new FormData()
body.append('text', 'Focus on metabolic pathways')
await fetch(`/api/sessions/${id}/feedback`, { method: 'POST', body })
```

Pause, resume and abort also publish `session_paused`, `session_resumed` and
`session_aborted` on the event stream.

---

## 6. Live updates: `GET /api/sessions/{id}/events` (SSE)

Open it with `EventSource`. It sends two kinds of events.

### Bus events (the ones you already handle)

`session_started`, `task_started`, `task_completed`, `task_failed`,
`session_paused`, `session_resumed`, `session_aborted`, `session_done`,
`human_feedback`. On connect, the last 25 stored events are replayed (shape
`ReplayEventData`), then live events follow (shape `LiveEventData`, the bus
envelope). This is the behaviour `frontend/src/types/researchEvents.ts` already
describes.

### `timeline_message` events (new, different shape)

```
id: 7
event: timeline_message
data: {"seq":7,"ts":1761300000000,"role":"system","agent":"data_analysis","kind":"dataset_profiled","title":"...","body_markdown":"...","refs":[]}
```

- The SSE `id:` is the message's `seq`.
- `data` is the flat `TimelineMessage`, exactly one element of the `messages`
  array from `GET /timeline`.
- It is **not** the bus envelope. The `LiveEventData` comment in
  `researchEvents.ts` (`name`, `session_id`, `payload`, `ts_ms`) does **not**
  apply to `timeline_message`; do not look for `payload` in it. Parse it as a
  `TimelineMessage`.
- Timeline messages are never replayed through the 25-event history. The server
  sends the timeline backlog itself (see the start point below).

### Where the timeline stream starts

The stream resumes after the **larger** of two numbers:

1. the `?after_seq=N` query parameter, and
2. the `Last-Event-ID` header (which the browser sends by itself when an
   `EventSource` reconnects).

A missing, non-numeric or negative value counts as 0. Only messages with `seq`
greater than that start point are sent. An `EventSource` keeps its original URL
when it reconnects, so without the header rule it would resend everything from
the first page load.

### Ordering and repeats: the client must dedupe and sort

- Messages **can arrive out of `seq` order**: two messages written at nearly the
  same moment can reach the stream in either order.
- Messages **can repeat across reconnects** (and a reconnect can replay messages
  you already showed).
- Therefore: **keep a map keyed by `seq` to drop duplicates, and render the list
  sorted by `seq`.** Do not treat "highest seq seen so far" as a cursor for
  dropping messages, or you will lose a late-arriving lower one.

### Suggested pattern

1. `GET /api/sessions/{id}/timeline` and store the messages by `seq`.
2. Compute `maxSeq` (0 if empty).
3. Open `new EventSource(`/api/sessions/${id}/events?after_seq=${maxSeq}`)`.
4. On each `timeline_message`, parse the data, insert into the map by `seq`
   (ignore if present), and render sorted by `seq`.

```ts
const bySeq = new Map<number, TimelineMessage>()
const { messages } = await (await fetch(`/api/sessions/${id}/timeline`)).json()
for (const m of messages) bySeq.set(m.seq, m)
const maxSeq = Math.max(0, ...bySeq.keys())

const es = new EventSource(`/api/sessions/${id}/events?after_seq=${maxSeq}`)
es.addEventListener('timeline_message', (e) => {
  const m = JSON.parse((e as MessageEvent).data) as TimelineMessage
  if (bySeq.has(m.seq)) return
  bySeq.set(m.seq, m)
  setTimeline([...bySeq.values()].sort((a, b) => a.seq - b.seq))
})
```

`EventSource` only delivers events you register a listener for by name, so
`timeline_message` must be listened for explicitly (see section 8).

If the database watcher fails, the server logs it and the timeline part of the
stream ends; the bus events keep flowing. After a dropped connection, fall back
to `GET /timeline?after_seq=<maxSeq>`.

---

## 7. TypeScript types to add

These do not exist in `frontend/src/types` yet. Suggested home:
`frontend/src/types/research.ts` (or a new `timeline.ts`).

```ts
/** One timeline message. Same shape from GET /timeline and from the timeline_message SSE event. */
export interface TimelineMessage {
  /** Per-session counter starting at 1. Unique; use it as the key. */
  seq: number
  /** Epoch milliseconds */
  ts: number
  role: 'system' | 'user' | 'assistant'
  /** Which agent posted it, if any */
  agent: string | null
  /** Open set of machine labels, e.g. 'attachments_received', 'dataset_profiled', 'overview_ready' */
  kind: string
  title: string
  body_markdown: string
  refs: string[]
}

export interface AttachmentInfo {
  id: string
  filename: string
  kind: 'tabular' | 'document'
  /** Bytes */
  size: number
  status: 'stored' | 'ingested' | 'analysed' | 'failed'
}

export interface AnalysisPlot {
  name: string
  content_type: string
  /** Ready to use as an <img src> */
  url: string
}

export interface AnalysisCandidate {
  candidate_key: string
  biomarker: string
  alteration_type: string
  drug: string
  /** null when the test statistic was not finite */
  p_value: number | null
  [stat: string]: unknown
}

export interface AnalysisReport {
  candidates: AnalysisCandidate[]
  drugs: string[]
  sample_count: number
  generated_at: string
  /** When the report was stored (ISO 8601) */
  created_at: string
  endpoint: Record<string, unknown>
  survival_curves: Record<string, unknown>[]
  tests: Record<string, unknown>[]
  /** Present only when `tests` was cut down */
  tests_truncated?: boolean
  tests_total?: number
  summary_markdown: string
  plots: AnalysisPlot[]
}
```

---

## 8. The one-line change in `researchEvents.ts`

Add `'timeline_message'` to `KNOWN_EVENT_NAMES` in
`frontend/src/types/researchEvents.ts` (the array around line 117) so the app
registers a listener for it. `KNOWN_EVENT_NAMES` is typed
`as const satisfies readonly KnownEventName[]`, so you must also add a
`timeline_message` entry to `EventPayloads` (its type is `TimelineMessage`, not a
bus payload), or the `satisfies` check fails. Also update the `LiveEventData`
comment to say timeline messages are not wrapped in it.

---

## 9. Mock data must be committed

`frontend/src/data/mock*.ts` (for example `mockHypotheses.ts` and
`mockResearchOverview.ts`, imported from `@/data/...` by the pages) was matched by
the old `.gitignore` rule `data/`, which ignored any folder named `data`. The
rule is now anchored to the repo root (`/data/`), which is the runtime data
folder only. Commit `frontend/src/data/mock*.ts` now; a fresh clone will not
build without them.
