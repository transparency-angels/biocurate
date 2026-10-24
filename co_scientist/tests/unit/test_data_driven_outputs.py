"""Data-driven research keeps separate empirical and literature reports."""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from co_scientist.agents.base import AgentDeps
from co_scientist.agents.data_analysis import DataAnalysisAgent
from co_scientist.agents.generation import GenerationAgent
from co_scientist.agents.supervisor import Supervisor
from co_scientist.llm.types import SynthMessage, TextBlock, ToolUseBlock
from co_scientist.models import Hypothesis, ResearchPlan, Session
from co_scientist.orchestrator.termination import StopReason
from co_scientist.storage import db as db_mod
from co_scientist.storage.artifacts import write_text
from co_scientist.storage.repos import analysis as analysis_repo
from co_scientist.storage.repos import blobs
from co_scientist.storage.repos import hypotheses as hyp_repo
from co_scientist.storage.repos import sessions as sess_repo
from co_scientist.storage.repos import tasks as task_repo


async def test_data_driven_session_writes_both_reports(tmp_cfg, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise real profiling, generation persistence, and finalization.

    Only model responses, embeddings, and the worker-loop timing are replaced;
    task payloads, source hydration, database updates, and files are real.
    """
    with (tmp_cfg.data_dir / "clinical.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sample_id", "drug", "os_months", "event"])
        for i in range(30):
            writer.writerow([f"S{i}", "DRUG_A", 10 if i < 15 else 40, int(i < 15)])
    with (tmp_cfg.data_dir / "mutations.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sample_id", "GENE_X"])
        for i in range(30):
            writer.writerow([f"S{i}", int(i < 15)])

    paper = "https://paper.example/mechanism"
    literature_overview = (
        "# Executive summary\n\nGENE_X is a candidate for further mechanistic study [S1].\n\n"
        f"# Sources\n\n[S1] Mechanistic paper: {paper}\n"
    )
    llm = MagicMock()
    llm.call = AsyncMock(return_value=SimpleNamespace(raw=SynthMessage(content=[TextBlock(literature_overview)])))
    monkeypatch.setattr("co_scientist.agents.supervisor.get_provider", lambda *args, **kwargs: llm)
    tools = MagicMock()
    tools.anthropic_tools_for.return_value = []
    monkeypatch.setattr("co_scientist.agents.supervisor.ToolRegistry.discover", lambda self: tools)
    monkeypatch.setattr(GenerationAgent, "_dedup_query", AsyncMock(return_value=(None, None)))
    record = {
        "title": "GENE_X and treatment response",
        "statement": "GENE_X could influence treatment response through altered DNA repair.",
        "mechanism": "A DNA repair mechanism to test experimentally.",
        "citations": [{"title": "Mechanistic paper", "url": paper}],
    }
    generation_loop = AsyncMock(return_value=SimpleNamespace(
        response=SimpleNamespace(raw=SynthMessage(content=[ToolUseBlock(name="record_hypothesis", input=record)])),
        seen_urls={paper}, tool_calls=[], iterations=1,
    ))
    monkeypatch.setattr("co_scientist.agents.generation.run_tool_loop", generation_loop)

    supervisor = Supervisor(tmp_cfg)
    monkeypatch.setattr(supervisor, "_parse_goal", AsyncMock(return_value=ResearchPlan(
        objective="Find biomarkers with mechanistic literature support", has_dataset=True,
    )))
    captured = {}

    async def profile_and_generate(conn, deps, session, tracker):
        profile_task = await task_repo.claim_one(conn, session.id, "test", 60)
        assert profile_task.agent == "data_analysis"
        result = await DataAnalysisAgent(deps).execute(profile_task)
        assert result.extra["methods"]["primary_test"] == "lifelines.statistics.logrank_test"
        assert result.extra["artifact_path"] is None
        stored = await analysis_repo.fetch_report(conn, session.id)
        captured["summary"] = stored["summary_markdown"]
        await supervisor._apply_follow_ups(conn, session, profile_task, result)
        await task_repo.complete(conn, profile_task.id)

        generation_task = await task_repo.claim_one(conn, session.id, "test", 60)
        assert generation_task.payload["strategy"] == "data_driven"
        assert generation_task.payload["candidate"]["biomarker"] == "GENE_X"
        assert generation_task.payload["dataset_summary"] == result.extra["summary"]
        generated = await GenerationAgent(deps).execute(generation_task)
        assert generated.hypothesis_ids
        await supervisor._apply_follow_ups(conn, session, generation_task, generated)
        await task_repo.complete(conn, generation_task.id)
        # End the scheduled work here; run_session must still finalize normally.
        return StopReason.WALL_CLOCK

    monkeypatch.setattr(supervisor, "_main_loop", profile_and_generate)
    session_id = await supervisor.run_session("Find biomarkers in the dataset")
    root = tmp_cfg.session_artifact_dir(session_id)
    assert not (root / "data_analysis").exists()
    # The meta-review writes its overview into final/synthesis.json (cite-lines);
    # the simple fallback overview below is still final/overview.md.
    synthesis = json.loads((root / "final" / "synthesis.json").read_text())
    overview = synthesis["overview"]["markdown"]
    # "# Sources" is split out of the overview into the structured sources.
    assert "GENE_X is a candidate for further mechanistic study [S1]." in overview
    assert "# Sources" not in overview
    assert "[dataset analysis summary](../data_analysis/summary.md)" in overview
    assert paper in json.dumps(synthesis["sources"])
    llm.call.assert_awaited_once()
    spec, context = llm.call.call_args.args
    assert context.action == "GenerateFinalResearchOverview"
    prompt = spec.user_blocks[0].text
    assert paper in prompt  # Hydrated from the persisted generation artifact.
    assert "Kaplan-Meier" in prompt
    assert "Write the literature and mechanistic research overview as a separate report" in prompt
    generation_loop.assert_awaited_once()

    conn = await db_mod.connect(tmp_cfg)
    try:
        report = await analysis_repo.fetch_report(conn, session_id)
        assert report["summary_markdown"] == captured["summary"]
        (plot,) = report["plots"]
        assert (await blobs.get(conn, "plots", plot["blob_id"])).startswith(b"\x89PNG")
        session = await sess_repo.fetch(conn, session_id)
        assert session.status == "done"
        assert tmp_cfg.data_dir / session.final_overview == root / "final" / "synthesis.json"
        assert (await hyp_repo.list_for_session(conn, session_id))[0].strategy == "data_driven"
    finally:
        await conn.close()


@pytest.mark.parametrize("failure", ["no_hypotheses", "llm_error"])
async def test_finalization_keeps_dataset_report_when_meta_review_cannot_write(
    tmp_cfg, conn, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    now = datetime.now(UTC)
    session = Session(
        id="ses_data_outputs", created_at=now, updated_at=now, status="running",
        research_goal="Study biomarkers", research_plan=ResearchPlan(objective="Study biomarkers", has_dataset=True),
        config_snapshot={}, budget_tokens=1000, budget_usd=1,
    )
    await sess_repo.insert(conn, session)
    summary = "# Dataset analysis\n\nKaplan-Meier results and plots.\n"
    await write_text(tmp_cfg, session.id, "data_analysis", "summary", ".md", summary)
    if failure == "llm_error":
        await hyp_repo.insert(conn, Hypothesis(
            id="hyp_data_outputs", session_id=session.id, created_at=now, created_by="generation",
            strategy="data_driven", title="A mechanistic hypothesis", summary="A short claim",
            full_text="Mechanistic discussion with a recorded source: https://paper.example/mechanism",
            artifact_path="artifacts/ses_data_outputs/hypotheses/hyp_data_outputs.json",
        ))
    llm = MagicMock()
    llm.call = AsyncMock(side_effect=RuntimeError("model unavailable"))
    deps = AgentDeps(cfg=tmp_cfg, db=conn, llm=llm, tools=MagicMock())
    await Supervisor(tmp_cfg)._finalize(conn, deps, session, StopReason.IDLE)

    saved = await sess_repo.fetch(conn, session.id)
    root = tmp_cfg.session_artifact_dir(session.id)
    assert saved.status == "done"
    assert tmp_cfg.data_dir / saved.final_overview == root / "final" / "overview.md"
    assert (root / "data_analysis" / "summary.md").read_text() == summary
    overview = (root / "final" / "overview.md").read_text()
    assert "[dataset analysis summary](../data_analysis/summary.md)" in overview
    if failure == "no_hypotheses":
        assert "No hypotheses were generated" in overview
        llm.call.assert_not_awaited()
    else:
        assert "Mechanistic discussion" in overview
        assert "https://paper.example/mechanism" in overview

