"""Unit tests for DataAnalysisAgent and data-driven workflow."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from co_scientist import ids
from co_scientist.agents.base import AgentDeps
from co_scientist.agents.data_analysis import DataAnalysisAgent
from co_scientist.agents.generation import _render_hypothesis_md
from co_scientist.config import Config
from co_scientist.models import ResearchPlan, Session, Task
from co_scientist.models.attachment import AttachmentMeta
from co_scientist.storage.datasets import tabular_files
from co_scientist.storage.repos import analysis as analysis_repo
from co_scientist.storage.repos import attachments as att_repo
from co_scientist.storage.repos import blobs
from co_scientist.storage.repos import sessions as sess_repo
from co_scientist.storage.repos import timeline as timeline_repo


def test_render_hypothesis_md_with_data_evidence() -> None:
    record = {
        "title": "KEAP1 Mutation and Cisplatin Resistance",
        "statement": "KEAP1 loss-of-function causes cisplatin resistance.",
        "mechanism": "Constitutive NRF2 activation enhances glutathione synthesis.",
        "entities": ["KEAP1", "NRF2", "Cisplatin"],
        "anticipated_outcomes": "Reduced DNA adduct persistence.",
        "novelty_argument": "Novel pathway link.",
        "citations": [{"title": "Study 1", "url": "https://pubmed.ncbi.nlm.nih.gov/12345", "year": 2023}],
        "data_evidence": {
            "biomarker": "KEAP1",
            "alteration_type": "mutation",
            "drug": "CISPLATIN",
            "relationship": "reduced_response_or_poor_prognosis",
            "delta_os_months": -11.55,
            "p_value": 0.00019,
            "altered_samples": 120,
            "sample_size": 1622,
        },
    }
    md = _render_hypothesis_md(record)
    assert "## Empirical Data Evidence" in md
    assert "KEAP1" in md
    assert "CISPLATIN" in md
    assert "-11.55" in md
    assert "0.00019" in md
    assert "120 altered / 1622 total" in md


def _session(goal: str = "Identify biomarkers for DRUG_A") -> Session:
    return Session(
        id=ids.session_id(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        status="running",
        research_goal=goal,
        research_plan=ResearchPlan(objective=goal),
        config_snapshot={},
        budget_tokens=1000,
        budget_usd=1.0,
    )


def _task(session: Session, payload: dict) -> Task:
    return Task(
        id=ids.task_id(), session_id=session.id, created_at=datetime.now(UTC),
        agent="data_analysis", action="ProfileDataset", payload=payload,
    )


@pytest.fixture
async def dataset_agent(tmp_cfg: Config, conn) -> tuple[DataAnalysisAgent, Task]:
    session = _session()
    await sess_repo.insert(conn, session)
    agent = DataAnalysisAgent(AgentDeps(cfg=tmp_cfg, db=conn, llm=MagicMock(), tools=MagicMock()))
    return agent, _task(session, {})


def _write_cohort(root: Path, n: int = 30) -> None:
    with (root / "clinical.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sample_id", "drug", "os_months", "event"])
        for i in range(n):
            writer.writerow([f"S{i}", "DRUG_A", 10 if i < n // 2 else 40, int(i < n // 2)])
    with (root / "mutations.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sample_id", "GENE_X", "GENE_Y"])
        for i in range(n):
            writer.writerow([f"S{i}", int(i < n // 2), 0])


async def _attach(conn, session_id: str, files: dict[str, bytes]) -> list[str]:
    out = []
    for name, data in files.items():
        blob_id = await blobs.put(conn, "attachments", name, data, {"session_id": session_id})
        meta = AttachmentMeta(
            id=f"att_{ids.blob_id()}",
            session_id=session_id, filename=name, content_type="text/csv", size=len(data),
            sha256=f"sha_{name}", kind="tabular", status="stored", blob_id=blob_id,
            uploaded_at=datetime.now(UTC),
        )
        assert await att_repo.insert(conn, meta)
        out.append(meta.id)
    return out


async def test_profile_from_attachments_stores_report_points_and_plots(
    tmp_path: Path, tmp_cfg: Config, any_conn,
) -> None:
    conn = any_conn
    session = _session()
    await sess_repo.insert(conn, session)
    src = tmp_path / "src"
    src.mkdir()
    _write_cohort(src)
    att_ids = await _attach(conn, session.id, {p.name: p.read_bytes() for p in src.iterdir()})
    unrelated = await _attach(conn, session.id, {"notes.csv": b"a,b\n1,2\n"})
    agent = DataAnalysisAgent(AgentDeps(cfg=tmp_cfg, db=conn, llm=MagicMock(), tools=MagicMock()))

    result = await agent.execute(_task(session, {"attachment_ids": att_ids}))

    assert result.kind == "data_profiled"
    assert result.extra["artifact_path"] is None
    assert result.extra["sample_count"] == 30
    assert [c["biomarker"] for c in result.extra["candidates"]] == ["GENE_X"]
    report = await analysis_repo.fetch_report(conn, session.id)
    assert report["summary_markdown"] == result.extra["summary"]
    assert "points" not in report
    assert report["sample_count"] == 30 and report["drugs"] == ["DRUG_A"]
    assert report["candidates"][0]["candidate_key"] == "GENE_X|mutation|DRUG_A"
    assert [p["name"] for p in report["plots"]] == ["kaplan_meier_1"]
    plot = report["plots"][0]
    assert plot["content_type"] == "image/png"
    assert (await blobs.get(conn, "plots", plot["blob_id"])).startswith(b"\x89PNG")
    keys = [c["candidate_key"] for c in report["candidates"]]
    points = await analysis_repo.fetch_points(conn, session.id, keys)
    assert set(points) == set(keys)
    assert points[keys[0]]["metric"] == "os_months" and points[keys[0]]["unit"] == "months"
    assert len(points[keys[0]]["points"]) == 30
    assert not (tmp_cfg.session_artifact_dir(session.id) / "data_analysis").exists()
    statuses = {a.id: a.status for a in await att_repo.list_for_session(conn, session.id)}
    assert all(statuses[i] == "analysed" for i in att_ids)
    assert statuses[unrelated[0]] == "stored"
    msgs = await timeline_repo.list_for_session(conn, session.id)
    profiled = [m for m in msgs if m.kind == "dataset_profiled"]
    assert len(profiled) == 1
    assert profiled[0].title == "Dataset profiled"
    assert profiled[0].body_markdown == (
        "30 samples \u00b7 drugs: DRUG_A \u00b7 1 candidate biomarkers"
    )


async def test_unusable_attachments_mark_failed_and_post_timeline(
    tmp_cfg: Config, any_conn,
) -> None:
    conn = any_conn
    session = _session()
    await sess_repo.insert(conn, session)
    att_ids = await _attach(conn, session.id, {"mutations.csv": b"sample_id,GENE_X\nS1,1\n"})
    agent = DataAnalysisAgent(AgentDeps(cfg=tmp_cfg, db=conn, llm=MagicMock(), tools=MagicMock()))

    result = await agent.execute(_task(session, {"attachment_ids": att_ids}))

    assert result.kind == "data_profiled"
    assert result.extra["candidates"] == []
    assert "No clinical metadata table" in result.extra["summary"]
    (att,) = await att_repo.list_for_session(conn, session.id)
    assert att.status == "failed"
    assert att.error == "could not be analysed as a clinical dataset"
    assert await analysis_repo.fetch_report(conn, session.id) is None
    msgs = await timeline_repo.list_for_session(conn, session.id)
    unusable = [m for m in msgs if m.kind == "dataset_unusable"]
    assert len(unusable) == 1
    assert unusable[0].title == "Dataset could not be analysed"
    assert unusable[0].body_markdown == (
        "No compatible clinical table was found in the selected files."
    )


async def test_saved_report_stays_well_under_bson_limit(
    tmp_path: Path, tmp_cfg: Config, any_conn,
) -> None:
    conn = any_conn
    session = _session()
    await sess_repo.insert(conn, session)
    src = tmp_path / "src"
    src.mkdir()
    _write_cohort(src, n=200)
    att_ids = await _attach(conn, session.id, {p.name: p.read_bytes() for p in src.iterdir()})
    agent = DataAnalysisAgent(AgentDeps(cfg=tmp_cfg, db=conn, llm=MagicMock(), tools=MagicMock()))
    await agent.execute(_task(session, {"attachment_ids": att_ids}))
    report = await analysis_repo.fetch_report(conn, session.id)
    assert "tests_truncated" not in report  # small cohorts keep every test row
    assert len(report["tests"]) == report["selection"]["eligible_tests"]
    from bson import encode  # pymongo ships bson

    size = len(encode({k: v for k, v in report.items() if k != "created_at"}))
    print(f"BSON size of saved report: {size}")
    assert size < 1024 * 1024


def test_tests_are_truncated_only_when_large() -> None:
    from co_scientist.agents.data_analysis import _bounded_tests

    rows = [
        {"candidate_key": f"G{i}|mutation|D", "p_value": i / 10_000, "pad": "x" * 600}
        for i in range(20_000)
    ]
    keep = {"G19999|mutation|D", "G18000|mutation|D"}
    out, truncated = _bounded_tests(rows, keep)
    assert truncated
    assert len(out) == 500 + len(keep)
    assert keep <= {t["candidate_key"] for t in out}
    small, truncated = _bounded_tests(rows[:100], keep)
    assert not truncated and small == rows[:100]


@pytest.mark.parametrize(
    "suffix,delimiter,id_header",
    [(".txt", "\t", ""), (".tsv", "\t", "SAMPLE_ID"), (".csv", ",", "id"), (".CSV", ",", "")],
)
@pytest.mark.parametrize("alteration", ["mutation", "amplification", "deletion"])
async def test_data_analysis_screening(
    tmp_path: Path, dataset_agent: tuple[DataAnalysisAgent, Task],
    suffix: str, delimiter: str, id_header: str, alteration: str,
) -> None:
    agent, task = dataset_agent
    # Use an arbitrary metadata filename, mixed-case headers, and BOM/quotes
    # typical of spreadsheet CSV exports. Matrices sort before the metadata.
    with (tmp_path / f"z_clinical_cohort{suffix}").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=delimiter)
        writer.writerow([" sample_id ", "drug", "os_months", "os_status"])
        for i in range(30):
            writer.writerow([f"S,{i:02d}", "DRUG_A", 10.0 if i < 15 else 40.0,
                             "1:DECEASED" if i < 15 else "0:LIVING"])
    with (tmp_path / f"cohort_{alteration}{suffix}").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=delimiter)
        writer.writerow([id_header, "GENE_X", "GENE_Y"])
        for i in range(30):
            writer.writerow([f"S,{i:02d}", int(i < 15), 0])

    task.payload["attachment_ids"] = await _attach(
        agent.deps.db, task.session_id,
        {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()},
    )
    result = await agent.execute(task)
    assert result.kind == "data_profiled"
    assert result.extra["sample_count"] == 30
    candidates = result.extra["candidates"]
    assert len(candidates) == 1
    top = candidates[0]
    assert top["biomarker"] == "GENE_X"
    assert top["alteration_type"] == alteration
    assert top["drug"] == "DRUG_A"
    assert top["median_os_altered"] == 10
    assert top["median_os_wt"] is None  # The unaltered group is entirely censored.
    assert top["delta_os_months"] is None
    assert top["p_value"] < 0.05
    assert top["altered_samples"] == 15
    assert result.extra["artifact_path"] is None
    report = await analysis_repo.fetch_report(agent.deps.db, task.session_id)
    assert report["tests"] and "logrank_statistic" in report["tests"][0]
    assert result.extra["methods"]["alpha"] == 0.05
    assert "Statistical methods and significance" in result.extra["summary"]
    plot = report["plots"][0]
    png = await blobs.get(agent.deps.db, "plots", plot["blob_id"])
    assert plot["name"] == "kaplan_meier_1" and png.startswith(b"\x89PNG")
    assert "](plots/kaplan_meier_1.png)" in result.extra["summary"]
    assert not (agent.deps.cfg.session_artifact_dir(task.session_id) / "data_analysis").exists()


def test_runtime_storage_is_not_a_dataset(tmp_path: Path) -> None:
    (tmp_path / "co_scientist.db").write_bytes(b"not an input table")
    (tmp_path / "index.meta.json").write_text("{}")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "generated.csv").write_text("sample_id,drug,time\nS1,DRUG_A,12\n")
    assert tabular_files(tmp_path) == []


async def test_no_clinical_metadata_reports_expected_format(
    tmp_path: Path, dataset_agent: tuple[DataAnalysisAgent, Task],
) -> None:
    agent, task = dataset_agent
    task.payload["attachment_ids"] = await _attach(
        agent.deps.db, task.session_id, {"mutations.csv": b"sample_id,GENE_X\nS1,1\n"},
    )
    result = await agent.execute(task)
    assert result.extra["candidates"] == []
    assert "No clinical metadata table" in result.extra["summary"]
    assert "CSV" in result.extra["summary"]

