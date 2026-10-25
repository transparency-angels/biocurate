"""The co-scientist *session* MCP server: drive a research session from an agent.

Launched by an agent client (Claude Code, Codex CLI, or anything that speaks
MCP) and kept alive for the whole conversation:

    co-scientist mcp-server
    # or, without the console script on PATH:
    python -m co_scientist.mcp.session_server

This is a different server from `co_scientist.mcp.server`. That one is spawned
per LLM call by the CLI backends and never touches SQLite. This one is the
outward-facing surface: it owns session lifecycle, reads the ranked state, and
writes reviews and tournament matches back through the *same* repositories the
engine's own agents use.

That last point is the whole design. A review an agent writes by hand and a
review the Reflection agent writes land in the same table, through the same
model, and are counted the same way downstream. Elo stays coherent, provenance
stays intact, and the meta-review sees everything. Nothing here reimplements
Elo, dedup, scheduling, or termination: those live in the engine and stay there.

Configuration is by environment, same as the capture server:

    COSCI_CONFIG          optional path to an extra TOML config to overlay
    COSCI_ALLOW_START     "0" to refuse session_start / session_resume
                          (read-only mode for shared or untrusted setups)
    COSCI_START_TIMEOUT   seconds to wait for a spawned run to register its
                          session row (default 120)

Concurrency: every call opens its own SQLite connection and closes it again.
The engine runs with WAL and a busy timeout, so a write from here while a
session is running retries rather than failing.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import ids
from ..config import Config, load_config
from ..models import (
    CitedPaper,
    Hypothesis,
    Review,
    ReviewScores,
    SystemFeedback,
    TournamentMatch,
)
from ..orchestrator.elo import expected_score, k_factor
from ..overview import DB_PREFIX, load_overview_markdown
from ..storage import db as db_mod
from ..storage.artifacts import read_json, write_json
from ..storage.atlas import client as atlas_client
from ..storage.repos import feedback as fb_repo
from ..storage.repos import hypotheses as hyp_repo
from ..storage.repos import reviews as rev_repo
from ..storage.repos import sessions as sess_repo
from ..storage.repos import tasks as task_repo
from ..storage.repos import tournaments as tourney_repo
from .protocol import McpStdioServer, log, text_result

SERVER_NAME = "co-scientist"
SERVER_VERSION = "1.0.0"

# How long a spawned `co-scientist run` gets to write its session row before we
# give up waiting for the id. Import plus config load plus the pre-flight
# estimate is a few seconds; 120 leaves room on a cold cache.
DEFAULT_START_TIMEOUT = 120.0
_START_POLL_SECONDS = 0.5

REVIEW_KINDS = ("full", "verification", "observation", "simulation")
REVIEW_VERDICTS = (
    "already_explained", "other_more_likely", "missing_piece", "neutral", "disproved",
)
HYPOTHESIS_STRATEGIES = (
    "literature", "debate", "combine", "simplify", "out_of_box", "feasibility",
    "assumption", "feedback_driven",
)
FEEDBACK_KINDS = ("directive", "preference", "rejection", "pin")
MATCH_MODES = ("pairwise", "debate")


# --------------------------------------------------------------------------- #
# tool schemas


def _obj(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


_SESSION_ID = {"type": "string", "description": "Session id, e.g. ses_01J..."}
_HYP_ID = {"type": "string", "description": "Hypothesis id, e.g. hyp_9f2c..."}

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "session_start": {
        "description": (
            "Start a new research session from a natural-language goal. The engine "
            "runs the full Generation, Reflection, Elo tournament, Evolution and "
            "Meta-review loop in a detached process; this returns as soon as the "
            "session id exists. Poll session_status for progress. Costs money or "
            "subscription quota, so confirm the budget with the user first."
        ),
        "input_schema": _obj(
            {
                "goal": {
                    "type": "string",
                    "description": (
                        "The research goal. Write it as a scientist would: the system, "
                        "the phenomenon, and the kind of answer wanted."
                    ),
                },
                "preferences": {
                    "type": "string",
                    "description": "Optional extra constraints or preferences, free text.",
                },
                "n_initial": {
                    "type": "integer",
                    "description": "Parallel initial Generation calls. Default 3.",
                },
                "budget_usd": {"type": "number", "description": "Override the session USD budget."},
                "wall_clock_seconds": {"type": "integer", "description": "Override the wall-clock cap."},
                "concurrency": {"type": "integer", "description": "Override worker concurrency."},
            },
            ["goal"],
        ),
    },
    "session_resume": {
        "description": (
            "Resume a paused or interrupted session. The engine reclaims expired task "
            "leases and continues where it stopped. Returns immediately; poll session_status."
        ),
        "input_schema": _obj({"session_id": _SESSION_ID}, ["session_id"]),
    },
    "session_pause": {
        "description": "Pause a running session. Workers drain and the loop sleeps until resumed.",
        "input_schema": _obj({"session_id": _SESSION_ID}, ["session_id"]),
    },
    "session_abort": {
        "description": "Abort a session for good. The main loop exits at its next check.",
        "input_schema": _obj({"session_id": _SESSION_ID}, ["session_id"]),
    },
    "session_list": {
        "description": (
            "List sessions newest first, with status, hypothesis count, top Elo and "
            "budget spent. Use this to find a session id the user refers to by topic."
        ),
        "input_schema": _obj(
            {"limit": {"type": "integer", "description": "Max rows. Default 20."}}, []
        ),
    },
    "session_status": {
        "description": (
            "Progress for one session: status, task counts by state, hypothesis counts "
            "by state, matches played, Elo spread, budget spent, and whether the final "
            "overview exists yet. This is the polling tool."
        ),
        "input_schema": _obj({"session_id": _SESSION_ID}, ["session_id"]),
    },
    "hypotheses_list": {
        "description": (
            "List a session's hypotheses ranked by Elo, with title, summary, state, "
            "matches played and dedup cluster. Bodies are omitted; use hypothesis_get."
        ),
        "input_schema": _obj(
            {
                "session_id": _SESSION_ID,
                "limit": {"type": "integer", "description": "Max rows. Default 20."},
                "offset": {"type": "integer", "description": "Rows to skip. Default 0."},
                "state": {
                    "type": "string",
                    "description": (
                        "Filter by state: draft, reviewed, in_tournament, pinned, "
                        "rejected, quarantined, retired."
                    ),
                },
            },
            ["session_id"],
        ),
    },
    "hypothesis_get": {
        "description": (
            "One hypothesis in full: statement, detailed text, citations, Elo history, "
            "every review recorded against it, and its tournament matches. Read this "
            "before reviewing or ranking it."
        ),
        "input_schema": _obj(
            {
                "hypothesis_id": _HYP_ID,
                "include_matches": {
                    "type": "boolean",
                    "description": "Include the match list. Default true.",
                },
            },
            ["hypothesis_id"],
        ),
    },
    "hypothesis_record": {
        "description": (
            "Add a hypothesis to a session, in the same table Generation and Evolution "
            "write to. It enters as a draft, gets reviewed, and then competes in the "
            "tournament like any other. Set parent_ids when it derives from existing "
            "hypotheses, which is what makes it an Evolution result rather than a fresh "
            "idea. Recording is what makes a hypothesis real: an idea only described in "
            "chat is never reviewed, ranked, or seen by the meta-review."
        ),
        "input_schema": _obj(
            {
                "session_id": _SESSION_ID,
                "title": {"type": "string", "description": "One line naming the mechanism."},
                "summary": {
                    "type": "string",
                    "description": (
                        "About three sentences. This is the text that gets embedded for "
                        "dedup and clustering, so make it the mechanism, not a teaser."
                    ),
                },
                "full_text": {
                    "type": "string",
                    "description": (
                        "The hypothesis in full, markdown, written for a domain expert: "
                        "mechanism, predictions, and the experiment that would test it."
                    ),
                },
                "strategy": {
                    "type": "string",
                    "enum": list(HYPOTHESIS_STRATEGIES),
                    "description": (
                        "How it was produced. literature or debate for a fresh idea; "
                        "combine, simplify, feasibility or out_of_box for an evolution."
                    ),
                },
                "parent_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Hypotheses this derives from. Omit for a fresh idea.",
                },
                "citations": {
                    "type": "array",
                    "description": "Sources behind it. Cite only what you read.",
                    "items": _obj(
                        {
                            "title": {"type": "string"},
                            "url": {"type": "string"},
                            "excerpt": {"type": "string"},
                            "doi": {"type": "string"},
                            "year": {"type": "integer"},
                        },
                        ["title", "url"],
                    ),
                },
            },
            ["session_id", "title", "summary", "full_text", "strategy"],
        ),
    },
    "review_record": {
        "description": (
            "Record a review against a hypothesis, in the same table and format the "
            "Reflection agent writes. Every factual claim in `evidence` needs a url and "
            "an excerpt you actually read. A 'full' review on a draft hypothesis also "
            "promotes it to reviewed. Do not report a review to the user without "
            "recording it first, or the tournament and meta-review will never see it."
        ),
        "input_schema": _obj(
            {
                "hypothesis_id": _HYP_ID,
                "kind": {
                    "type": "string",
                    "enum": list(REVIEW_KINDS),
                    "description": (
                        "full = novelty, correctness, testability. verification = "
                        "assumption decomposition. observation = does it explain a "
                        "published observation. simulation = step-through of the mechanism."
                    ),
                },
                "body": {"type": "string", "description": "The review itself, markdown."},
                "verdict": {"type": "string", "enum": list(REVIEW_VERDICTS)},
                "scores": _obj(
                    {
                        "novelty": {"type": "number", "description": "0..1"},
                        "correctness": {"type": "number", "description": "0..1"},
                        "testability": {"type": "number", "description": "0..1"},
                        "feasibility": {"type": "number", "description": "0..1"},
                    },
                    [],
                ),
                "assumptions": {
                    "type": "array",
                    "description": "Deep-verification decomposition, one row per assumption.",
                    "items": _obj(
                        {
                            "assumption": {"type": "string"},
                            "plausibility": {
                                "type": "string",
                                "enum": ["plausible", "uncertain", "implausible"],
                            },
                            "rationale": {"type": "string"},
                        },
                        ["assumption", "plausibility", "rationale"],
                    ),
                },
                "evidence": {
                    "type": "array",
                    "description": "Sources backing the review. Cite only what you read.",
                    "items": _obj(
                        {
                            "claim": {"type": "string"},
                            "url": {"type": "string"},
                            "excerpt": {
                                "type": "string",
                                "description": "Text that actually appears at that url.",
                            },
                        },
                        ["claim", "url", "excerpt"],
                    ),
                },
                "iteration": {
                    "type": "integer",
                    "description": (
                        "Disambiguates repeat reviews of the same kind. Omit and the "
                        "server picks the next free slot."
                    ),
                },
            },
            ["hypothesis_id", "kind", "body"],
        ),
    },
    "match_record": {
        "description": (
            "Record the outcome of a head-to-head comparison between two hypotheses and "
            "apply the Elo update. Compare them on the paper's criteria (correctness, "
            "novelty, testability, and how well each survives its reviews) and give the "
            "rationale. Idempotent per (pair, round_id): recording the same pair twice "
            "under the same round moves no Elo."
        ),
        "input_schema": _obj(
            {
                "hyp_a": {"type": "string", "description": "First hypothesis id."},
                "hyp_b": {"type": "string", "description": "Second hypothesis id."},
                "winner": {
                    "type": "string",
                    "enum": ["a", "b"],
                    "description": "Which one wins. There are no draws.",
                },
                "rationale": {
                    "type": "string",
                    "description": "Why it won, in the terms the criteria are stated in.",
                },
                "mode": {
                    "type": "string",
                    "enum": list(MATCH_MODES),
                    "description": (
                        "pairwise = single comparison. debate = multi-turn scientific "
                        "debate. Default pairwise."
                    ),
                },
                "round_id": {
                    "type": "string",
                    "description": (
                        "Round label for idempotency. Default 'manual'. Change it to "
                        "rematch a pair deliberately."
                    ),
                },
            },
            ["hyp_a", "hyp_b", "winner", "rationale"],
        ),
    },
    "feedback_add": {
        "description": (
            "Inject researcher feedback into a session. A running session picks it up on "
            "its next planning step; a paused one picks it up on resume. kind='pin' or "
            "'rejection' with a target also moves that hypothesis's state."
        ),
        "input_schema": _obj(
            {
                "session_id": _SESSION_ID,
                "text": {"type": "string", "description": "The feedback, free text."},
                "kind": {"type": "string", "enum": list(FEEDBACK_KINDS)},
                "target": {"type": "string", "description": "Hypothesis id this is about."},
            },
            ["session_id", "text"],
        ),
    },
    "overview_get": {
        "description": (
            "The final research overview for a session: the meta-review synthesis of the "
            "ranked hypotheses. Only exists once the session has finalized."
        ),
        "input_schema": _obj({"session_id": _SESSION_ID}, ["session_id"]),
    },
    "estimate_cost": {
        "description": (
            "Pre-flight cost estimate for a session under the current config, with the "
            "per-agent breakdown. Run this before session_start and show the user."
        ),
        "input_schema": _obj({}, []),
    },
    "doctor": {
        "description": (
            "Check the install: which LLM backend is configured, whether its credentials "
            "resolve, whether embeddings are real or the hash fallback, and where the "
            "database lives. Run this first when anything fails."
        ),
        "input_schema": _obj({}, []),
    },
}


# --------------------------------------------------------------------------- #
# server


class SessionMcpServer:
    def __init__(self, cfg: Config | None = None) -> None:
        config_path = os.environ.get("COSCI_CONFIG")
        self.cfg = cfg or load_config(Path(config_path) if config_path else None)
        self.allow_start = os.environ.get("COSCI_ALLOW_START", "1") != "0"
        self.start_timeout = float(
            os.environ.get("COSCI_START_TIMEOUT", DEFAULT_START_TIMEOUT)
        )

    # ----------------------------- tool list ----------------------------- #

    def tool_list(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "description": schema["description"],
                "inputSchema": schema["input_schema"],
            }
            for name, schema in TOOL_SCHEMAS.items()
        ]

    # ----------------------------- dispatch ------------------------------ #

    async def handle(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_t_{name}", None)
        if handler is None:
            return text_result(
                {"error": f"unknown tool: {name}", "available": sorted(TOOL_SCHEMAS)},
                is_error=True,
            )
        try:
            return await handler(args)
        except _ToolError as e:
            return text_result({"error": str(e)}, is_error=True)
        except Exception as e:                                  # pragma: no cover
            log(f"[session-mcp] {name} failed: {e!r}")
            return text_result({"error": f"{name} failed: {e!r}"}, is_error=True)

    @contextlib.asynccontextmanager
    async def _db(self):
        conn = await db_mod.connect(self.cfg)
        try:
            yield conn
        finally:
            await conn.close()

    def _config_args(self) -> list[str]:
        """`-c <overlay>` so a spawned run uses the same config (and backend) as this server."""
        path = self.cfg._overlay_path
        if path is None and (env := os.environ.get("COSCI_CONFIG")):
            path = Path(env).resolve()
        return ["-c", str(path)] if path is not None else []

    # ----------------------------- lifecycle ----------------------------- #

    async def _t_session_start(self, args: dict[str, Any]) -> dict[str, Any]:
        if not self.allow_start:
            raise _ToolError(
                "session_start is disabled here (COSCI_ALLOW_START=0). "
                "This server is read-only; start sessions from the CLI."
            )
        goal = _require_str(args, "goal")
        ready, detail = _backend_ready(self.cfg)
        if not ready:
            raise _ToolError(f"LLM backend is not ready: {detail}. Call doctor for details.")

        argv = [sys.executable, "-m", "co_scientist.cli", *self._config_args(), "run", goal]
        if (n := args.get("n_initial")) is not None:
            argv += ["--n", str(int(n))]
        if (b := args.get("budget_usd")) is not None:
            argv += ["--budget-usd", str(float(b))]
        if (w := args.get("wall_clock_seconds")) is not None:
            argv += ["--wall-clock", str(int(w))]
        if (c := args.get("concurrency")) is not None:
            argv += ["--concurrency", str(int(c))]

        prefs_path: Path | None = None
        if prefs := args.get("preferences"):
            prefs_path = self.cfg.data_dir / "logs" / f"prefs-{int(time.time())}.txt"
            prefs_path.parent.mkdir(parents=True, exist_ok=True)
            prefs_path.write_text(str(prefs), encoding="utf-8")
            argv += ["--preferences-file", str(prefs_path)]

        known = await self._session_ids_since(_iso_now_floor())
        log_path = self.cfg.data_dir / "logs" / f"run-{int(time.time())}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        pid = _spawn_detached(argv, log_path)

        session_id = await self._await_new_session(goal, known)
        if session_id is None:
            raise _ToolError(
                f"the run started (pid {pid}) but no session row appeared within "
                f"{self.start_timeout:.0f}s. Check {log_path} for the reason."
            )
        return text_result({
            "session_id": session_id,
            "pid": pid,
            "log_path": str(log_path),
            "next": "poll session_status; the full loop takes minutes to hours",
        })

    async def _t_session_resume(self, args: dict[str, Any]) -> dict[str, Any]:
        if not self.allow_start:
            raise _ToolError("session_resume is disabled here (COSCI_ALLOW_START=0).")
        session_id = _require_str(args, "session_id")
        async with self._db() as conn:
            if await sess_repo.fetch(conn, session_id) is None:
                raise _ToolError(f"no such session: {session_id}")
        log_path = self.cfg.data_dir / "logs" / f"resume-{int(time.time())}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        pid = _spawn_detached(
            [sys.executable, "-m", "co_scientist.cli", *self._config_args(),
             "resume", session_id],
            log_path,
        )
        return text_result({"session_id": session_id, "pid": pid, "log_path": str(log_path)})

    async def _t_session_pause(self, args: dict[str, Any]) -> dict[str, Any]:
        return await self._set_status(_require_str(args, "session_id"), "paused")

    async def _t_session_abort(self, args: dict[str, Any]) -> dict[str, Any]:
        return await self._set_status(_require_str(args, "session_id"), "aborted")

    async def _set_status(self, session_id: str, status: str) -> dict[str, Any]:
        async with self._db() as conn:
            if await sess_repo.fetch(conn, session_id) is None:
                raise _ToolError(f"no such session: {session_id}")
            await sess_repo.set_status(conn, session_id, status)
        return text_result({"session_id": session_id, "status": status})

    # ------------------------------ reading ------------------------------ #

    async def _t_session_list(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = _clamp_int(args.get("limit"), default=20, low=1, high=200)
        async with self._db() as conn:
            stats = await sess_repo.list_with_stats(conn, limit=limit)
        rows = [
            {("n_hypotheses" if k == "n_hyps" else k): v for k, v in r.items()}
            for r in stats
        ]
        return text_result({"sessions": rows, "count": len(rows)})

    async def _t_session_status(self, args: dict[str, Any]) -> dict[str, Any]:
        session_id = _require_str(args, "session_id")
        async with self._db() as conn:
            out = await sess_repo.fetch_row(conn, session_id)
            if out is None:
                raise _ToolError(f"no such session: {session_id}")
            out["task_counts"] = await task_repo.count_by_status(conn, session_id)
            out["hypothesis_states"] = await hyp_repo.count_by_state(conn, session_id)
            out["matches_played"] = await tourney_repo.count_matches(conn, session_id)
            lo, hi, n_ranked = await hyp_repo.elo_range(conn, session_id)
            out["elo"] = {
                "min": lo,
                "max": hi,
                "spread": (hi - lo) if n_ranked else None,
                "ranked": n_ranked,
            }
            out["has_overview"] = bool(out.get("final_overview"))
        return text_result(out)

    async def _t_hypotheses_list(self, args: dict[str, Any]) -> dict[str, Any]:
        session_id = _require_str(args, "session_id")
        limit = _clamp_int(args.get("limit"), default=20, low=1, high=200)
        offset = _clamp_int(args.get("offset"), default=0, low=0, high=100_000)
        state = args.get("state") or None
        async with self._db() as conn:
            hyps = await hyp_repo.list_for_session(conn, session_id, state)
        window = hyps[offset : offset + limit]
        return text_result({
            "session_id": session_id,
            "total": len(hyps),
            "offset": offset,
            "hypotheses": [
                {
                    "id": h.id,
                    "title": h.title,
                    "summary": h.summary,
                    "elo": h.elo,
                    "matches_played": h.matches_played,
                    "state": h.state,
                    "strategy": h.strategy,
                    "created_by": h.created_by,
                    "parent_ids": h.parent_ids,
                    "dedup_cluster": h.dedup_cluster,
                    "n_citations": len(h.citations),
                }
                for h in window
            ],
        })

    async def _t_hypothesis_get(self, args: dict[str, Any]) -> dict[str, Any]:
        hypothesis_id = _require_str(args, "hypothesis_id")
        include_matches = args.get("include_matches", True)
        async with self._db() as conn:
            h = await hyp_repo.fetch(conn, hypothesis_id)
            if h is None:
                raise _ToolError(f"no such hypothesis: {hypothesis_id}")
            reviews = await rev_repo.list_for_hypothesis(conn, hypothesis_id)
            # Citations live in the artifact, not the hypotheses table. Surface
            # them here so a caller can check a source without knowing that.
            artifact: Any = None
            with contextlib.suppress(Exception):
                artifact = await read_json(self.cfg, h.artifact_path)
            matches: list[dict[str, Any]] = []
            if include_matches:
                matches = [
                    {
                        "id": m.id, "hyp_a": m.hyp_a, "hyp_b": m.hyp_b, "mode": m.mode,
                        "winner": m.winner,
                        "elo_a_before": m.elo_a_before, "elo_b_before": m.elo_b_before,
                        "elo_a_after": m.elo_a_after, "elo_b_after": m.elo_b_after,
                        "rationale": m.rationale, "created_at": m.created_at.isoformat(),
                    }
                    for m in await tourney_repo.list_for_hypothesis(conn, hypothesis_id)
                ]
        return text_result({
            "hypothesis": h.model_dump(mode="json"),
            "artifact": artifact,
            "reviews": [
                {
                    "id": r.id,
                    "kind": r.kind,
                    "verdict": r.verdict,
                    "scores": r.scores.model_dump(),
                    "body": r.body,
                    "created_at": r.created_at.isoformat(),
                }
                for r in reviews
            ],
            "matches": matches,
        })

    async def _t_overview_get(self, args: dict[str, Any]) -> dict[str, Any]:
        session_id = _require_str(args, "session_id")
        async with self._db() as conn:
            session = await sess_repo.fetch(conn, session_id)
            if session is None:
                raise _ToolError(f"no such session: {session_id}")
            if not session.final_overview:
                raise _ToolError(
                    f"session {session_id} has no final overview yet. "
                    "Check session_status; the overview is written when the session finalizes."
                )
            markdown = await load_overview_markdown(conn, self.cfg, session)
        if markdown is None:
            raise _ToolError(f"the overview for session {session_id} is missing")
        ref = session.final_overview
        return text_result({
            "session_id": session_id,
            "path": ref if ref.startswith(DB_PREFIX) else str(self.cfg.data_dir / ref),
            "overview_markdown": markdown,
        })

    # ------------------------------ writing ------------------------------ #

    async def _t_hypothesis_record(self, args: dict[str, Any]) -> dict[str, Any]:
        session_id = _require_str(args, "session_id")
        title = _require_str(args, "title")
        summary = _require_str(args, "summary")
        full_text = _require_str(args, "full_text")
        strategy = _require_enum(args, "strategy", HYPOTHESIS_STRATEGIES)
        parent_ids = args.get("parent_ids") or []
        if not isinstance(parent_ids, list) or not all(isinstance(p, str) for p in parent_ids):
            raise _ToolError("parent_ids must be an array of hypothesis ids")
        citations = args.get("citations") or []
        if not isinstance(citations, list):
            raise _ToolError("citations must be an array")

        # An evolved hypothesis is one with parents. The distinction drives how
        # the meta-review reports provenance, so it is derived, not asked for.
        created_by = "evolution" if parent_ids else "generation"

        async with self._db() as conn:
            if await sess_repo.fetch(conn, session_id) is None:
                raise _ToolError(f"no such session: {session_id}")
            for pid in parent_ids:
                if await hyp_repo.fetch(conn, pid) is None:
                    raise _ToolError(f"parent hypothesis does not exist: {pid}")

            hid = ids.hypothesis_id(session_id, created_by, summary)
            artifact_path = await write_json(
                self.cfg, session_id, "hypotheses", hid,
                {
                    "source": "agent", "strategy": strategy, "parent_ids": parent_ids,
                    "title": title, "summary": summary, "full_text": full_text,
                    "citations": citations,
                },
            )
            inserted = await hyp_repo.insert(conn, Hypothesis(
                id=hid, session_id=session_id, created_at=datetime.now(UTC),
                created_by=created_by,                      # type: ignore[arg-type]
                strategy=strategy,                          # type: ignore[arg-type]
                parent_ids=parent_ids, title=title, summary=summary,
                full_text=full_text,
                citations=[CitedPaper(**c) for c in citations],
                artifact_path=artifact_path, state="draft",
            ))
        return text_result({
            "hypothesis_id": hid,
            "session_id": session_id,
            "created_by": created_by,
            "state": "draft",
            "inserted": inserted,
            "artifact_path": artifact_path,
            "next": (
                "review it with review_record, then it can enter the tournament"
                if inserted else
                "a hypothesis with this summary already exists in the session; "
                "nothing was added"
            ),
        })

    async def _t_review_record(self, args: dict[str, Any]) -> dict[str, Any]:
        hypothesis_id = _require_str(args, "hypothesis_id")
        kind = _require_enum(args, "kind", REVIEW_KINDS)
        body = _require_str(args, "body")
        verdict = args.get("verdict")
        if verdict is not None and verdict not in REVIEW_VERDICTS:
            raise _ToolError(f"verdict must be one of {list(REVIEW_VERDICTS)}")
        scores = args.get("scores") or {}
        assumptions = args.get("assumptions") or []
        evidence = args.get("evidence") or []
        _check_evidence(evidence)

        async with self._db() as conn:
            h = await hyp_repo.fetch(conn, hypothesis_id)
            if h is None:
                raise _ToolError(f"no such hypothesis: {hypothesis_id}")

            iteration = args.get("iteration")
            if iteration is None:
                existing = await rev_repo.list_for_hypothesis(conn, hypothesis_id)
                iteration = sum(1 for r in existing if r.kind == kind)
            review_id = ids.review_id(hypothesis_id, kind, int(iteration))

            artifact_path = await write_json(
                self.cfg, h.session_id, "reviews", review_id,
                {
                    "hypothesis_id": hypothesis_id,
                    "source": "agent",
                    "record": {
                        "kind": kind, "verdict": verdict, **scores,
                        "assumptions": assumptions, "evidence": evidence,
                        "body": body,
                    },
                },
            )
            review = Review(
                id=review_id,
                hypothesis_id=hypothesis_id,
                session_id=h.session_id,
                created_at=datetime.now(UTC),
                kind=kind,                                  # type: ignore[arg-type]
                verdict=verdict,                            # type: ignore[arg-type]
                scores=ReviewScores(
                    novelty=scores.get("novelty"),
                    correctness=scores.get("correctness"),
                    testability=scores.get("testability"),
                    feasibility=scores.get("feasibility"),
                ),
                body=body,
                artifact_path=artifact_path,
            )
            inserted = await rev_repo.insert(conn, review)
            promoted = False
            if kind == "full":
                promoted = await hyp_repo.set_state_if(
                    conn, hypothesis_id, new_state="reviewed", expected_states=("draft",),
                )
        return text_result({
            "review_id": review_id,
            "hypothesis_id": hypothesis_id,
            "session_id": h.session_id,
            "inserted": inserted,
            "state_promoted_to_reviewed": promoted,
            "artifact_path": artifact_path,
            "note": (
                "already recorded under this id; pass a different `iteration` to add another"
                if not inserted else "recorded"
            ),
        })

    async def _t_match_record(self, args: dict[str, Any]) -> dict[str, Any]:
        hyp_a = _require_str(args, "hyp_a")
        hyp_b = _require_str(args, "hyp_b")
        winner = _require_enum(args, "winner", ("a", "b"))
        rationale = _require_str(args, "rationale")
        mode = args.get("mode") or "pairwise"
        if mode not in MATCH_MODES:
            raise _ToolError(f"mode must be one of {list(MATCH_MODES)}")
        if hyp_a == hyp_b:
            raise _ToolError("hyp_a and hyp_b must be different hypotheses")
        round_id = str(args.get("round_id") or "manual")

        initial_elo = float(self.cfg.ranking.elo_initial)
        async with self._db() as conn:
            a = await hyp_repo.fetch(conn, hyp_a)
            b = await hyp_repo.fetch(conn, hyp_b)
            if a is None:
                raise _ToolError(f"no such hypothesis: {hyp_a}")
            if b is None:
                raise _ToolError(f"no such hypothesis: {hyp_b}")
            if a.session_id != b.session_id:
                raise _ToolError(
                    "both hypotheses must belong to the same session "
                    f"({a.session_id} vs {b.session_id})"
                )

            # Entering the tournament is what gives a hypothesis its starting Elo.
            for h in (a, b):
                if h.elo is None:
                    await hyp_repo.init_tournament(conn, h.id, initial_elo)
            a = await hyp_repo.fetch(conn, hyp_a) or a
            b = await hyp_repo.fetch(conn, hyp_b) or b

            # Provisional pre-read ratings for the descriptive row; record_match_result
            # re-reads the stored ones inside its transaction and overwrites them.
            elo_a_pre = float(a.elo if a.elo is not None else initial_elo)
            elo_b_pre = float(b.elo if b.elo is not None else initial_elo)
            mid = ids.match_id(hyp_a, hyp_b, round_id)
            await tourney_repo.insert_match(conn, TournamentMatch(
                id=mid, session_id=a.session_id, created_at=datetime.now(UTC),
                hyp_a=hyp_a, hyp_b=hyp_b, mode=mode,          # type: ignore[arg-type]
                winner=winner,                                # type: ignore[arg-type]
                elo_a_before=elo_a_pre, elo_b_before=elo_b_pre,
                rationale=rationale,
            ))
            applied = await tourney_repo.record_match_result(
                conn,
                match_id=mid, hyp_a=hyp_a, hyp_b=hyp_b, winner=winner,
                k_new=self.cfg.ranking.k_factor_new,
                k_warm=self.cfg.ranking.k_factor_warm,
                initial_elo=initial_elo,
            )
            if applied is None:
                # Already recorded: report what that first run stored, if still readable.
                stored = next(
                    (m for m in await tourney_repo.list_for_hypothesis(conn, hyp_a)
                     if m.id == mid and m.elo_a_after is not None and m.elo_b_after is not None),
                    None,
                )
                if stored is not None:
                    elo_a_pre, elo_b_pre = stored.elo_a_before, stored.elo_b_before
                    elo_a_post, elo_b_post = stored.elo_a_after, stored.elo_b_after
                else:
                    elo_a_post, elo_b_post = elo_a_pre, elo_b_pre
                k, expected_a = k_factor(
                    min(a.matches_played, b.matches_played),
                    k_new=self.cfg.ranking.k_factor_new,
                    k_warm=self.cfg.ranking.k_factor_warm,
                ), expected_score(elo_a_pre, elo_b_pre)
            else:
                elo_a_pre, elo_b_pre = applied.elo_a_before, applied.elo_b_before
                elo_a_post, elo_b_post = applied.elo_a_after, applied.elo_b_after
                k, expected_a = applied.k, applied.expected_a
        return text_result({
            "match_id": mid,
            "session_id": a.session_id,
            "winner": winner,
            "elo_applied": applied is not None,
            "elo": {
                hyp_a: {"before": elo_a_pre, "after": elo_a_post},
                hyp_b: {"before": elo_b_pre, "after": elo_b_post},
            },
            "k_factor": k,
            "expected_a": expected_a,
            "note": (
                "recorded" if applied is not None else
                f"this pair already played round {round_id!r}; no Elo moved. "
                "Pass a different round_id to rematch deliberately."
            ),
        })

    async def _t_feedback_add(self, args: dict[str, Any]) -> dict[str, Any]:
        session_id = _require_str(args, "session_id")
        text = _require_str(args, "text")
        kind = args.get("kind") or "directive"
        if kind not in FEEDBACK_KINDS:
            raise _ToolError(f"kind must be one of {list(FEEDBACK_KINDS)}")
        target = args.get("target") or None
        if kind in ("pin", "rejection") and not target:
            raise _ToolError(f"kind={kind!r} needs a target hypothesis id")

        async with self._db() as conn:
            if await sess_repo.fetch(conn, session_id) is None:
                raise _ToolError(f"no such session: {session_id}")
            if target and await hyp_repo.fetch(conn, target) is None:
                raise _ToolError(f"no such hypothesis: {target}")
            fb_id = ids.feedback_id()
            await fb_repo.insert(conn, SystemFeedback(
                id=fb_id, session_id=session_id, created_at=datetime.now(UTC),
                source="human", kind=kind, target_id=target, text=text, active=True,
            ))
            if kind == "pin" and target:
                await hyp_repo.set_state(conn, target, "pinned")
            elif kind == "rejection" and target:
                await hyp_repo.set_state(conn, target, "rejected")
        return text_result({"feedback_id": fb_id, "session_id": session_id, "kind": kind})

    # ---------------------------- diagnostics ---------------------------- #

    async def _t_estimate_cost(self, args: dict[str, Any]) -> dict[str, Any]:
        from ..llm.estimator import estimate as _estimate

        est = _estimate(self.cfg).to_dict()
        return text_result({
            **est,
            "budget_usd": self.cfg.run.budget_usd,
            "max_ideas": self.cfg.run.max_ideas,
            "max_matches_per_idea": self.cfg.run.max_matches_per_idea,
        })

    async def _t_doctor(self, args: dict[str, Any]) -> dict[str, Any]:
        from ..config import has_embeddings_key
        from ..llm.provider import check_models

        ready, detail = _backend_ready(self.cfg)
        return text_result({
            "backend": self.cfg.llm.provider,
            "backend_ready": ready,
            "backend_detail": detail,
            "model_warnings": list(check_models(self.cfg)),
            "embeddings": (
                self.cfg.embeddings.model if has_embeddings_key(self.cfg)
                else "hash fallback (set VOYAGE_API_KEY or OPENAI_API_KEY for real dedup)"
            ),
            "data_dir": str(self.cfg.data_dir),
            "db_path": str(self.cfg.db_path),
            "db_exists": self.cfg.db_path.exists(),
            "session_start_allowed": self.allow_start,
        })

    # ------------------------------ helpers ------------------------------ #

    async def _session_ids_since(self, iso_ts: str) -> set[str]:
        async with self._db() as conn:
            return set(await sess_repo.ids_created_since(conn, iso_ts))

    async def _await_new_session(self, goal: str, known: set[str]) -> str | None:
        """Poll for the session row the spawned run is about to write.

        The run creates its session row before doing any LLM work, so this
        normally resolves within a few seconds of process start.
        """
        deadline = time.monotonic() + self.start_timeout
        while time.monotonic() < deadline:
            async with self._db() as conn:
                for sid in await sess_repo.ids_for_goal(conn, goal):
                    if sid not in known:
                        return str(sid)
            await asyncio.sleep(_START_POLL_SECONDS)
        return None


class _ToolError(Exception):
    """A problem the calling agent can fix. Reported as an MCP error result."""


# --------------------------------------------------------------------------- #
# small helpers


def _require_str(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise _ToolError(f"{key} is required and must be a non-empty string")
    return value


def _require_enum(args: dict[str, Any], key: str, allowed: tuple[str, ...]) -> str:
    value = args.get(key)
    if value not in allowed:
        raise _ToolError(f"{key} must be one of {list(allowed)}, got {value!r}")
    return str(value)


def _clamp_int(value: Any, *, default: int, low: int, high: int) -> int:
    if value is None:
        return default
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _check_evidence(evidence: Any) -> None:
    if not isinstance(evidence, list):
        raise _ToolError("evidence must be an array")
    for i, item in enumerate(evidence):
        if not isinstance(item, dict):
            raise _ToolError(f"evidence[{i}] must be an object")
        for key in ("claim", "url", "excerpt"):
            if not item.get(key):
                raise _ToolError(
                    f"evidence[{i}] is missing {key!r}. Cite only sources you read: "
                    "every entry needs the claim, the url, and an excerpt from that page."
                )


def _iso_now_floor() -> str:
    """UTC now, one second early, to survive clock granularity in created_at."""
    return datetime.fromtimestamp(time.time() - 1, tz=UTC).isoformat()


def _backend_ready(cfg: Config) -> tuple[bool, str]:
    from ..llm.provider import check_backend

    status = check_backend(cfg)
    return bool(status.ok), str(status.detail or "ok")


def _spawn_detached(argv: list[str], log_path: Path) -> int:
    """Start a run that outlives this tool call and this server.

    The engine's loop takes minutes to hours, far longer than any MCP call
    should block, so the process gets its own session and its output goes to a
    file the agent can read back when something fails.
    """
    handle = log_path.open("a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            argv,
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(Path.cwd()),
        )
    finally:
        handle.close()
    return proc.pid


# --------------------------------------------------------------------------- #
# entry point


async def serve(cfg: Config | None = None) -> None:
    """Serve the session tools on stdio until the client closes stdin."""
    server = SessionMcpServer(cfg)
    log(
        f"[session-mcp] db={server.cfg.db_path} "
        f"tools={len(TOOL_SCHEMAS)} start_allowed={server.allow_start}"
    )
    try:
        await McpStdioServer(
            name=SERVER_NAME,
            version=SERVER_VERSION,
            tools=server.tool_list(),
            handler=server.handle,
        ).serve()
    finally:
        await atlas_client.shutdown_clients()


def main(cfg: Config | None = None) -> None:
    try:
        asyncio.run(serve(cfg))
    except KeyboardInterrupt:                                   # pragma: no cover
        pass
    except BrokenPipeError:                                     # pragma: no cover
        sys.exit(0)


if __name__ == "__main__":
    main()
