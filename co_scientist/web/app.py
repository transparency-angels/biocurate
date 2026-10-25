"""FastAPI web UI for the co-scientist.

One process per host: launching `co-scientist serve` runs both the API + UI
and the worker pool — the queue is DB-backed so CLI `co-scientist run` in a
separate terminal feeds tasks to whatever Supervisor is currently active.

The UI is server-side Jinja2 + SSE for live events, in a sidebar / main / rail
shell. No JS build step, and no CDN either: the stylesheet and the ~120 lines
of JS are served from `static/`, so the console renders with the network
unplugged — same local-first posture as the rest of the tool.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging as stdlib_logging
import math
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pymongo.errors import PyMongoError
from sse_starlette.sse import EventSourceResponse

from .. import ids
from ..attachments.intake import IntakeError, accept_uploads
from ..attachments.store import AttachmentQuotaError
from ..config import Config, load_config
from ..logging import get_logger
from ..models import SystemFeedback
from ..orchestrator.events import GLOBAL_BUS
from ..overview import DB_PREFIX, load_overview_markdown
from ..storage import db as db_mod
from ..storage.atlas.client import AtlasConn
from ..storage.repos import analysis as analysis_repo
from ..storage.repos import attachments as att_repo
from ..storage.repos import blobs as blobs_repo
from ..storage.repos import events as events_repo
from ..storage.repos import feedback as fb_repo
from ..storage.repos import hypotheses as hyp_repo
from ..storage.repos import reviews as rev_repo
from ..storage.repos import sessions as sess_repo
from ..storage.repos import syntheses as syntheses_repo
from ..storage.repos import timeline as timeline_repo
from ..storage.repos import tournaments as tourney_repo
from ..storage.repos import transcripts as tx_repo
from ..timeline import to_payload
from . import research_view
from .sanitize import render_markdown

log = get_logger("web")
HERE = Path(__file__).parent
TEMPLATES = Jinja2Templates(directory=HERE / "templates")
# ids.session_id(): "ses_" + a 26-character Crockford base32 ULID.
SESSION_ID_RE = re.compile(r"^ses_[0-9A-Z]{26}$")
DB_UNAVAILABLE = "database unavailable"


async def valid_session_id(session_id: str) -> str:
    """Reject anything that is not a real session id before it reaches a query or a path."""
    if not SESSION_ID_RE.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="invalid session id")
    return session_id


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or load_config()
    app = FastAPI(title="AI Co-Scientist")
    app.state.cfg = cfg
    app.state.background_runs: dict[str, asyncio.Task] = {}
    api = APIRouter(
        prefix="/api/sessions/{session_id}", dependencies=[Depends(valid_session_id)]
    )

    @app.exception_handler(PyMongoError)
    async def _db_unavailable(request: Request, exc: PyMongoError) -> JSONResponse:
        # Never echo the PyMongo message: it can carry hosts, queries and credentials.
        log.warning("db_error", path=request.url.path, err_type=type(exc).__name__)
        return JSONResponse({"detail": DB_UNAVAILABLE}, status_code=503)

    # Static
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    async def shell(
        extra: dict[str, Any],
        *,
        nav: str = "",
        session_id: str = "",
    ) -> dict[str, Any]:
        """Merge in what the sidebar and footer need on every page.

        The recents list is its own small query rather than something each
        route threads through, so adding a page never means remembering to
        populate the sidebar.
        """
        return {
            **extra,
            "nav_sessions": await _list_sessions(cfg, limit=12),
            "active_nav": nav,
            "active_session_id": session_id,
            "env": _env_row(cfg),
        }

    # ----------------------------- pages ----------------------------- #

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        rows = await _list_sessions(cfg)
        return TEMPLATES.TemplateResponse(
            request, "index.html", await shell({"sessions": rows}, nav="sessions")
        )

    @app.get("/sessions/new", response_class=HTMLResponse)
    async def new_session_form(request: Request) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request,
            "new_session.html",
            await shell({"default_budget": cfg.run.budget_usd}, nav="new"),
        )

    @app.post("/sessions/new")
    async def create_session(
        request: Request,
        background_tasks: BackgroundTasks,
        goal: str = Form(...),
        preferences: str = Form(""),
        budget_usd: float = Form(cfg.run.budget_usd),
        n_initial: int = Form(3),
        wall_clock_seconds: int = Form(cfg.run.wall_clock_seconds),
    ) -> RedirectResponse:
        from ..agents.supervisor import Supervisor

        # Hand the Supervisor a fresh Config copy so per-session knobs don't leak.
        sup_cfg = cfg.model_copy(deep=True)
        sup_cfg.run.budget_usd = budget_usd
        sup_cfg.run.wall_clock_seconds = wall_clock_seconds
        sup = Supervisor(sup_cfg)

        async def _run() -> None:
            try:
                await sup.run_session(
                    goal=goal, preferences_text=preferences or None,
                    n_initial=n_initial, wall_clock_seconds=wall_clock_seconds,
                )
            except Exception:
                log.exception("background_run_failed")

        task = asyncio.create_task(_run())
        # No durable session id at this point — give the run a chance to insert
        # the row, then redirect to /. The user can find it in the listing.
        _ = task
        return RedirectResponse(url="/", status_code=303)

    @app.get("/sessions/{session_id}", response_class=HTMLResponse)
    async def session_detail(request: Request, session_id: str) -> HTMLResponse:
        conn = await db_mod.connect(cfg)
        try:
            session = await sess_repo.fetch(conn, session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="session not found")
            hyps = await hyp_repo.list_for_session(conn, session_id)
            recent_matches = await _recent_matches(conn, session_id, limit=20)
            usage = await tx_repo.usage_summary(conn, session_id)
            return TEMPLATES.TemplateResponse(
                request,
                "session_detail.html",
                await shell(
                    {
                        "session": session,
                        "hypotheses": sorted(hyps, key=lambda h: -(h.elo or 0)),
                        "recent_matches": recent_matches,
                        "usage": usage,
                        "stages": _stages(session, hyps),
                    },
                    session_id=session_id,
                ),
            )
        finally:
            await conn.close()

    @app.get("/sessions/{session_id}/hypotheses/{hid}", response_class=HTMLResponse)
    async def hypothesis_detail(request: Request, session_id: str, hid: str) -> HTMLResponse:
        conn = await db_mod.connect(cfg)
        try:
            h = await hyp_repo.fetch(conn, hid)
            session = await sess_repo.fetch(conn, session_id)
            if h is None or session is None:
                raise HTTPException(status_code=404, detail="not found")
            reviews = await rev_repo.list_for_hypothesis(conn, hid)
            return TEMPLATES.TemplateResponse(
                request,
                "hypothesis_detail.html",
                await shell(
                    {
                        "session": session,
                        "h": h,
                        "reviews": reviews,
                        "full_text_html": render_markdown(h.full_text or ""),
                    },
                    session_id=session_id,
                ),
            )
        finally:
            await conn.close()

    @app.get("/sessions/{session_id}/overview", response_class=HTMLResponse)
    async def session_overview(request: Request, session_id: str) -> HTMLResponse:
        conn = await db_mod.connect(cfg)
        try:
            session = await sess_repo.fetch(conn, session_id)
            if session is None or not session.final_overview:
                raise HTTPException(
                    status_code=404, detail="no final overview yet for this session"
                )
            if not session.final_overview.startswith(DB_PREFIX):
                # Legacy file: resolve and confirm the path is still inside
                # `data_dir` so a tampered row can't read arbitrary files.
                base = cfg.data_dir.resolve()
                try:
                    (cfg.data_dir / session.final_overview).resolve().relative_to(base)
                except (ValueError, OSError) as e:
                    log.error("overview_path_escape", session=session_id, err=str(e))
                    raise HTTPException(status_code=404, detail="overview unavailable") from e
            overview_md = await load_overview_markdown(conn, cfg, session)
            if overview_md is None:
                raise HTTPException(status_code=404, detail="overview missing on disk")
            return TEMPLATES.TemplateResponse(
                request,
                "overview.html",
                await shell(
                    {
                        "session": session,
                        "overview_html": render_markdown(overview_md),
                        "overview_md": overview_md,
                    },
                    session_id=session_id,
                ),
            )
        finally:
            await conn.close()

    # ----------------------------- API + SSE ----------------------------- #

    @api.get("/metrics")
    async def api_metrics(session_id: str) -> JSONResponse:
        from ..obs.metrics import session_metrics_cached, to_dict

        conn = await db_mod.connect(cfg)
        try:
            m = await session_metrics_cached(conn, session_id)
            return JSONResponse(to_dict(m))
        finally:
            await conn.close()

    @api.get("")
    async def api_session(session_id: str) -> JSONResponse:
        conn = await db_mod.connect(cfg)
        try:
            s = await sess_repo.fetch(conn, session_id)
            if s is None:
                raise HTTPException(status_code=404)
            return JSONResponse(s.model_dump(mode="json"))
        finally:
            await conn.close()

    async def _synthesis_doc(session_id: str) -> dict[str, Any] | None:
        conn = await db_mod.connect(cfg)
        try:
            doc = await syntheses_repo.fetch(conn, session_id)
        finally:
            await conn.close()
        return doc if doc is not None else _legacy_synthesis(cfg, session_id)

    @api.get("/overview")
    async def api_overview(session_id: str) -> JSONResponse:
        doc = await _synthesis_doc(session_id)
        if doc is None:
            legacy = _legacy_json(cfg, session_id, "overview.json")
            if legacy is None:
                raise HTTPException(status_code=404, detail="overview not found")
            return JSONResponse(legacy)
        return JSONResponse(doc.get("overview", doc))

    @api.get("/synthesis")
    async def api_synthesis(session_id: str) -> JSONResponse:
        doc = await _synthesis_doc(session_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="synthesis not found")
        return JSONResponse(doc)

    @api.get("/sources")
    async def api_sources(session_id: str) -> JSONResponse:
        doc = await _synthesis_doc(session_id)
        if doc is None:
            legacy = _legacy_json(cfg, session_id, "sources.json")
            if legacy is None:
                raise HTTPException(status_code=404, detail="sources not found")
            return JSONResponse(legacy)
        return JSONResponse(doc.get("sources", doc))

    @api.get("/timeline")
    async def api_timeline(session_id: str, after_seq: int = Query(0, ge=0)) -> JSONResponse:
        conn = await db_mod.connect(cfg)
        try:
            msgs = await timeline_repo.list_for_session(conn, session_id, after_seq=after_seq)
        finally:
            await conn.close()
        return JSONResponse({"messages": [to_payload(m) for m in msgs]})

    @api.get("/research")
    async def api_research(session_id: str) -> JSONResponse:
        conn = await db_mod.connect(cfg)
        try:
            if await sess_repo.fetch(conn, session_id) is None:
                raise HTTPException(status_code=404, detail="session not found")
            shown = research_view.select_hypotheses(
                await hyp_repo.list_for_session(conn, session_id)
            )
            keys = research_view.linked_candidate_keys(shown)
            points = await analysis_repo.fetch_points(conn, session_id, keys) if keys else {}
            report = await analysis_repo.fetch_report(conn, session_id) if keys else None
            atts = {
                a.id: (a.filename, a.kind)
                for a in await att_repo.list_for_session(conn, session_id)
            }
            journals = await _library_journals(conn, shown)
        finally:
            await conn.close()
        return JSONResponse(research_view.to_research_session(
            session_id, shown, report, points, journals=journals, attachments=atts,
        ))

    @api.get("/analysis")
    async def api_analysis(session_id: str) -> JSONResponse:
        conn = await db_mod.connect(cfg)
        try:
            report = await analysis_repo.fetch_report(conn, session_id)
        finally:
            await conn.close()
        if report is None:
            raise HTTPException(status_code=404, detail="analysis not found")
        report["plots"] = [
            {
                **{k: v for k, v in p.items() if k != "blob_id"},
                "url": f"/api/sessions/{session_id}/plots/{p.get('name', '')}",
            }
            for p in report.get("plots", [])
        ]
        return JSONResponse(jsonable_encoder(report))

    @api.get("/plots/{name}")
    async def api_plot(session_id: str, name: str) -> Response:
        conn = await db_mod.connect(cfg)
        try:
            report = await analysis_repo.fetch_report(conn, session_id)
            plot = next(
                (p for p in (report or {}).get("plots", []) if p.get("name") == name), None
            )
            if plot is None or not plot.get("blob_id"):
                raise HTTPException(status_code=404, detail="plot not found")
            try:
                data = await blobs_repo.get(conn, "plots", plot["blob_id"])
            except KeyError as e:
                raise HTTPException(status_code=404, detail="plot not found") from e
        finally:
            await conn.close()
        return Response(content=data, media_type="image/png")

    @api.get("/attachments")
    async def api_attachments(session_id: str) -> JSONResponse:
        conn = await db_mod.connect(cfg)
        try:
            if await sess_repo.fetch(conn, session_id) is None:
                raise HTTPException(status_code=404, detail="session not found")
            metas = await att_repo.list_for_session(conn, session_id)
        finally:
            await conn.close()
        return JSONResponse({"attachments": [
            {"id": a.id, "filename": a.filename, "kind": a.kind, "size": a.size,
             "status": a.status}
            for a in metas
        ]})

    @api.get("/events")
    async def api_events(session_id: str) -> EventSourceResponse:
        async def _stream() -> AsyncIterator[dict[str, Any]]:
            # Replay last 25 events from DB so refreshes don't go blank.
            conn = await db_mod.connect(cfg)
            try:
                history = await events_repo.recent(conn, session_id, limit=25)
            finally:
                await conn.close()
            for ev in reversed(history):
                yield {
                    "event": ev["event"],
                    "data": json.dumps({"payload": ev["payload"], "ts": ev["ts"]}),
                }
            async with contextlib.aclosing(GLOBAL_BUS.subscribe(session_id)) as gen:
                async for ev in gen:
                    yield {
                        "event": ev.name,
                        "data": ev.to_json(),
                    }

        return EventSourceResponse(_stream())

    @api.post("/pause")
    async def api_pause(session_id: str) -> JSONResponse:
        conn = await db_mod.connect(cfg)
        try:
            await sess_repo.set_status(conn, session_id, "paused")
            await GLOBAL_BUS.publish(session_id, "session_paused", {})
            return JSONResponse({"ok": True})
        finally:
            await conn.close()

    @api.post("/resume")
    async def api_resume(session_id: str) -> JSONResponse:
        conn = await db_mod.connect(cfg)
        try:
            await sess_repo.set_status(conn, session_id, "running")
            await GLOBAL_BUS.publish(session_id, "session_resumed", {})
            return JSONResponse({"ok": True})
        finally:
            await conn.close()

    @api.post("/abort")
    async def api_abort(session_id: str) -> JSONResponse:
        conn = await db_mod.connect(cfg)
        try:
            await sess_repo.set_status(conn, session_id, "aborted")
            await GLOBAL_BUS.publish(session_id, "session_aborted", {})
            return JSONResponse({"ok": True})
        finally:
            await conn.close()

    @api.post("/feedback")
    async def api_feedback(
        session_id: str,
        text: str = Form(...),
        kind: str = Form("directive"),
        target_id: str = Form(""),
    ) -> JSONResponse:
        conn = await db_mod.connect(cfg)
        try:
            fb = SystemFeedback(
                id=ids.feedback_id(), session_id=session_id,
                created_at=datetime.now(UTC),
                source="human", kind=kind,
                target_id=target_id or None, text=text, active=True,
            )
            await fb_repo.insert(conn, fb)
            if kind == "pin" and target_id:
                await hyp_repo.set_state(conn, target_id, "pinned")
            elif kind == "rejection" and target_id:
                await hyp_repo.set_state(conn, target_id, "rejected")
            await GLOBAL_BUS.publish(session_id, "human_feedback", {
                "kind": kind, "target_id": target_id or None, "text": text[:200],
            })
            return JSONResponse({"ok": True, "feedback_id": fb.id})
        finally:
            await conn.close()

    @app.post("/api/sessions", status_code=201)
    async def api_create_session(
        question: str = Form(...),
        files: Annotated[list[UploadFile] | None, File()] = None,
        budget_usd: float | None = Form(None),
    ) -> JSONResponse:
        from ..agents.supervisor import Supervisor

        goal = question.strip()
        if not goal:
            raise HTTPException(status_code=400, detail="question is required")
        if budget_usd is not None and not (math.isfinite(budget_usd) and budget_usd > 0):
            raise HTTPException(status_code=400, detail="budget_usd must be a positive number")
        limits = cfg.attachments
        uploads = list(files or [])
        if len(uploads) > limits.max_files:
            raise HTTPException(
                status_code=400, detail=f"at most {limits.max_files} files may be attached"
            )
        cap = limits.max_file_mb * 1024 * 1024
        # Read one byte past the cap so an oversize file is rejected without buffering it all.
        raw = [(u.filename or "", await u.read(cap + 1), u.content_type or "") for u in uploads]
        try:
            intake = accept_uploads(raw, limits)
        except IntakeError as e:
            raise HTTPException(status_code=e.status_code, detail=str(e)) from e

        # A fresh Config copy per session so per-session knobs don't leak.
        sup_cfg = cfg.model_copy(deep=True)
        if budget_usd is not None:
            sup_cfg.run.budget_usd = budget_usd
        sup = Supervisor(sup_cfg)
        conn = await db_mod.connect(sup_cfg)
        try:
            session = await sup.prepare_session(
                conn, goal, attachments=intake.files, skipped=intake.skipped,
            )
        except AttachmentQuotaError as e:
            raise HTTPException(status_code=413, detail=str(e)) from e
        finally:
            await conn.close()

        async def _run() -> None:
            try:
                await sup.run_session(goal=goal, session_id=session.id)
            except Exception:
                log.exception("background_run_failed", session_id=session.id)
            finally:
                app.state.background_runs.pop(session.id, None)

        app.state.background_runs[session.id] = asyncio.create_task(_run())
        return JSONResponse({"session_id": session.id}, status_code=201)

    app.include_router(api)

    @app.get("/healthz")
    async def health() -> JSONResponse:
        return JSONResponse({"ok": True})

    # quiet uvicorn access spam during streaming
    stdlib_logging.getLogger("uvicorn.access").setLevel(stdlib_logging.WARNING)
    return app


# ----------------------------- helpers ----------------------------- #


def _legacy_json(cfg: Config, session_id: str, name: str) -> dict[str, Any] | None:
    """Read `<name>` from a pre-database session's artifact folder, if present.

    `session_id` is already validated against SESSION_ID_RE, so the path stays inside
    `data_dir/artifacts`.
    """
    root = cfg.data_dir / "artifacts" / session_id
    for candidate in (root / "final" / name, root / name):
        if candidate.is_file():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                log.warning("legacy_json_unreadable", session=session_id, err_type=type(e).__name__)
                raise HTTPException(status_code=500, detail="stored file is unreadable") from e
            return data if isinstance(data, dict) else {"data": data}
    return None


def _legacy_synthesis(cfg: Config, session_id: str) -> dict[str, Any] | None:
    return _legacy_json(cfg, session_id, "synthesis.json")


async def _library_journals(conn: Any, hypotheses: list[Any]) -> dict[str, str]:
    """Journal names for cited library papers. The library lives on Atlas only."""
    if not isinstance(conn, AtlasConn):
        return {}
    from ..storage.atlas import library as lib_store

    pmcids = {
        p for h in hypotheses for c in h.citations
        if (p := research_view.library_pmcid(c.url))
    }
    return await lib_store.journals_by_pmcid(conn, sorted(pmcids)) if pmcids else {}


async def _list_sessions(cfg: Config, *, limit: int = 50) -> list[dict[str, Any]]:
    conn = await db_mod.connect(cfg)
    try:
        return await sess_repo.list_with_stats(conn, limit=limit)
    finally:
        await conn.close()


def _env_row(cfg: Config) -> dict[str, Any]:
    """What the sidebar footer shows: which backend, model and folder are live.

    Answers "what is this actually running on" without a trip to `doctor`,
    which matters most when the workspace is on — you want to see the folder
    the agents can write to before you launch anything.
    """
    from ..llm.provider import CLI_BACKENDS
    from ..tools.workspace import workspace_root

    backend = (getattr(cfg.llm, "provider", "") or "").strip() or "openrouter"
    root = workspace_root(cfg)
    return {
        "backend": backend,
        "is_cli": backend in CLI_BACKENDS,
        "model": cfg.models.generation,
        "workspace": str(root) if root else "off",
        "workspace_on": root is not None,
    }


# Ordered pipeline stages, and the evidence that each one has happened. The
# session row alone can't say this — "has any hypothesis been reviewed" is a
# fact about the hypotheses table — so the caller passes what it already
# fetched rather than us re-querying.
def _stages(session: Any, hypotheses: list[Any]) -> list[dict[str, str]]:
    done_states = {"reviewed", "in_tournament", "pinned", "rejected", "retired"}
    reached = [
        ("Generation", bool(hypotheses)),
        ("Reflection", any(h.state in done_states for h in hypotheses)),
        ("Ranking", any((h.matches_played or 0) > 0 for h in hypotheses)),
        ("Evolution", any(h.parent_ids for h in hypotheses)),
        ("Meta-review", bool(session.final_overview)),
    ]
    out: list[dict[str, str]] = []
    active_marked = session.status not in ("running", "paused")
    for label, is_done in reached:
        if is_done:
            state = "done"
        elif not active_marked:
            state, active_marked = "active", True
        else:
            state = ""
        out.append({"label": label, "state": state})
    return out


async def _recent_matches(conn, session_id: str, *, limit: int) -> list[dict[str, Any]]:
    matches = await tourney_repo.list_for_session(conn, session_id, limit=limit)
    return [
        {
            "id": m.id, "hyp_a": m.hyp_a, "hyp_b": m.hyp_b, "mode": m.mode,
            "winner": m.winner, "elo_a_after": m.elo_a_after, "elo_b_after": m.elo_b_after,
            "created_at": m.created_at.isoformat(),
        }
        for m in matches
    ]
