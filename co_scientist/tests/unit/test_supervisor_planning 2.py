"""The planning step decides what to analyse from an inventory of the attachments."""

from __future__ import annotations

import csv
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from co_scientist.agents.supervisor import Supervisor
from co_scientist.attachments.intake import IncomingFile
from co_scientist.attachments.inventory import build_inventory
from co_scientist.attachments.store import AttachmentQuotaError, store_incoming
from co_scientist.llm.types import SynthMessage, ToolUseBlock
from co_scientist.orchestrator.termination import StopReason
from co_scientist.storage.repos import attachments as att_repo
from co_scientist.storage.repos import tasks as task_repo
from co_scientist.storage.repos import timeline as timeline_repo


def _csv(rows: int, cols: int = 3, cell: str = "v") -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([f"c{i}" for i in range(cols)])
    for r in range(rows):
        w.writerow([f"{cell}{r}"] * cols)
    return buf.getvalue().encode()


def _tab(name: str, data: bytes) -> IncomingFile:
    return IncomingFile(name, data, "text/csv", "tabular")


def _pdf(name: str = "paper.pdf") -> IncomingFile:
    return IncomingFile(name, b"%PDF-1.4 fake", "application/pdf", "document")


def _wire(monkeypatch, tmp_cfg, record: dict | None):
    """Replace the LLM with one that returns `record` and the main loop with a task drain."""
    content = [] if record is None else [ToolUseBlock(name="record_research_plan", input=record)]
    llm = MagicMock()
    llm.call = AsyncMock(return_value=SimpleNamespace(raw=SynthMessage(content=content)))
    monkeypatch.setattr("co_scientist.agents.supervisor.get_provider", lambda *a, **k: llm)
    tools = MagicMock()
    tools.anthropic_tools_for.return_value = []
    monkeypatch.setattr("co_scientist.agents.supervisor.ToolRegistry.discover", lambda self: tools)
    sup = Supervisor(tmp_cfg)
    seen: list = []

    async def drain(conn, deps, session, tracker):
        while (t := await task_repo.claim_one(conn, session.id, "test", 60)) is not None:
            seen.append(t)
            await task_repo.complete(conn, t.id)
        return StopReason.WALL_CLOCK

    monkeypatch.setattr(sup, "_main_loop", drain)
    monkeypatch.setattr(sup, "_finalize", AsyncMock())
    return sup, llm, seen


async def test_inventory_reads_header_and_three_rows_only(tmp_cfg, conn) -> None:
    big = _csv(5000, cell="x" * 150)
    wide = _csv(2, cols=300)
    metas = await store_incoming(
        conn, tmp_cfg, "ses_inv",
        [_tab("big.csv", big), _tab("wide.csv", wide), _pdf()],
    )
    assert len(metas) == 3
    inv = {e["filename"]: e for e in await build_inventory(conn, tmp_cfg, "ses_inv")}
    assert set(inv["big.csv"]) == {"id", "filename", "kind", "size", "header", "sample_rows"}
    assert inv["big.csv"]["header"] == ["c0", "c1", "c2"]
    assert len(inv["big.csv"]["sample_rows"]) == 3
    assert all(len(c) == 100 for row in inv["big.csv"]["sample_rows"] for c in row)
    assert inv["big.csv"]["size"] == len(big)
    assert len(inv["wide.csv"]["header"]) == 200
    assert inv["paper.pdf"]["kind"] == "document"
    assert inv["paper.pdf"]["header"] is None and inv["paper.pdf"]["sample_rows"] is None


async def test_plan_without_tabular_attachments_skips_analysis(
    tmp_cfg, monkeypatch: pytest.MonkeyPatch,
) -> None:
    rec = {"objective": "o", "has_dataset": True, "data_sources": ["att_nope"]}
    sup, _llm, seen = _wire(monkeypatch, tmp_cfg, rec)
    await sup.run_session("Study the dataset", n_initial=2, attachments=[_pdf()])
    assert [t.action for t in seen] == ["CreateInitialHypotheses"] * 2


async def test_plan_selects_only_known_tabular_ids(
    tmp_cfg, monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = [_tab("clinical.csv", _csv(5)), _pdf()]
    sup, llm, seen = _wire(monkeypatch, tmp_cfg, None)

    async def respond(spec, ctx):
        prompt = spec.user_blocks[0].text
        assert "Attached files (untrusted, describe only)" in prompt
        assert "UNTRUSTED_SOURCE" in prompt and "clinical.csv" in prompt
        listed = {
            e["filename"]: e["id"] for e in json.loads(
                prompt.split('hash="', 1)[1].split('">\n', 1)[1].split("\n</UNTRUSTED", 1)[0]
            )
        }
        rec = {
            "objective": "o", "has_dataset": True,
            "data_sources": [listed["clinical.csv"], "att_unknown", listed["paper.pdf"]],
        }
        return SimpleNamespace(raw=SynthMessage(content=[
            ToolUseBlock(name="record_research_plan", input=rec),
        ]))

    llm.call = AsyncMock(side_effect=respond)
    sid = await sup.run_session("Study the dataset", n_initial=2, attachments=files)
    (task,) = seen
    assert task.action == "ProfileDataset"
    from co_scientist.storage import db as db_mod

    conn = await db_mod.connect(tmp_cfg)
    try:
        (tab,) = [a for a in await att_repo.list_for_session(conn, sid) if a.kind == "tabular"]
        assert task.payload == {"attachment_ids": [tab.id]}
        titles = [m.title for m in await timeline_repo.list_for_session(conn, sid)]
        assert "Attachments received" in titles
        msg = next(m for m in await timeline_repo.list_for_session(conn, sid)
                   if m.kind == "attachments_received")
        assert f"clinical.csv · tabular · {len(files[0].data)}" in msg.body_markdown
    finally:
        await conn.close()


async def test_parse_goal_failure_defaults_to_no_dataset(
    tmp_cfg, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No tool_use record, and a goal full of the old trigger keywords.
    sup, _llm, seen = _wire(monkeypatch, tmp_cfg, None)
    await sup.run_session(
        "Analyse the attached dataset of patient metadata", n_initial=2,
        attachments=[_tab("clinical.csv", _csv(5))],
    )
    assert [t.action for t in seen] == ["CreateInitialHypotheses"] * 2


async def test_session_over_quota_stores_nothing(tmp_cfg, conn) -> None:
    tmp_cfg.attachments.max_session_mb = 0
    with pytest.raises(AttachmentQuotaError, match="session"):
        await store_incoming(conn, tmp_cfg, "ses_q", [_tab("a.csv", _csv(2))])
    assert await att_repo.list_for_session(conn, "ses_q") == []


async def test_over_quota_run_creates_no_session(tmp_cfg, monkeypatch) -> None:
    from co_scientist.storage import db as db_mod

    tmp_cfg.attachments.max_session_mb = 0
    sup, _llm, _seen = _wire(monkeypatch, tmp_cfg, None)
    with pytest.raises(AttachmentQuotaError):
        await sup.run_session("g", attachments=[_tab("a.csv", _csv(2))])
    conn = await db_mod.connect(tmp_cfg)
    try:
        async with conn.execute("SELECT COUNT(*) FROM sessions") as cur:
            assert (await cur.fetchone())[0] == 0
    finally:
        await conn.close()


def test_non_quota_errors_are_not_reported_as_quota(tmp_cfg, monkeypatch) -> None:
    from co_scientist.cli import run

    async def boom(self, goal, **kw):
        raise ValueError("deep failure")

    monkeypatch.setattr(Supervisor, "run_session", boom)
    monkeypatch.setattr("co_scientist.cli._require_backend", lambda cfg: None)
    with pytest.raises(ValueError, match="deep failure"):
        run(SimpleNamespace(obj=(tmp_cfg, None)), "g", None, 3, None, None, None, None)


def test_cli_run_attach_stores_files_and_plans(tmp_cfg, tmp_path, monkeypatch, capsys) -> None:
    import zipfile

    import typer

    from co_scientist.cli import run

    csv_path = tmp_path / "clinical.csv"
    csv_path.write_bytes(_csv(4))
    zpath = tmp_path / "bundle.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("mut.csv", _csv(3))
    got: dict = {}

    async def fake_run(self, goal, **kw):
        got.update(kw)
        return "ses_x"

    monkeypatch.setattr(Supervisor, "run_session", fake_run)
    monkeypatch.setattr("co_scientist.cli._require_backend", lambda cfg: None)
    ctx = SimpleNamespace(obj=(tmp_cfg, None))
    # Call the command function directly: a CliRunner would repoint structlog at a stream
    # that closes, breaking later tests.
    run(ctx, "goal", None, 3, None, None, None, [csv_path, zpath])
    assert sorted(f.filename for f in got["attachments"]) == ["clinical.csv", "mut.csv"]
    assert all(f.kind == "tabular" for f in got["attachments"])

    bad = tmp_path / "evil.exe"
    bad.write_bytes(b"MZ")
    with pytest.raises(typer.Exit) as e:
        run(ctx, "goal", None, 3, None, None, None, [bad])
    assert e.value.exit_code == 2
    assert "evil.exe" in capsys.readouterr().out
