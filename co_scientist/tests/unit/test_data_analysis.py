"""Unit tests for DataAnalysisAgent and data-driven workflow."""

from __future__ import annotations

import csv
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from co_scientist import ids
from co_scientist.agents.base import AgentDeps
from co_scientist.agents.data_analysis import DataAnalysisAgent
from co_scientist.agents.generation import _render_hypothesis_md
from co_scientist.agents.supervisor import Supervisor, _detect_data_presence
from co_scientist.config import Config, StorageCfg
from co_scientist.models import ResearchPlan, Session, Task
from co_scientist.storage.datasets import tabular_files
from co_scientist.storage.repos import sessions as sess_repo


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


@pytest.fixture
def dataset_agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[DataAnalysisAgent, Task]:
    cfg = Config(storage=StorageCfg(data_dir=str(tmp_path)))
    session = Session(
        id=ids.session_id(),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        status="running",
        research_goal="Identify biomarkers for DRUG_A",
        research_plan=ResearchPlan(objective="Identify biomarkers for DRUG_A"),
        config_snapshot={},
        budget_tokens=1000,
        budget_usd=1.0,
    )
    # Session persistence is separate from reading the research tables.
    monkeypatch.setattr(sess_repo, "fetch", AsyncMock(return_value=session))
    agent = DataAnalysisAgent(AgentDeps(cfg=cfg, db=MagicMock(), llm=MagicMock(), tools=MagicMock()))
    task = Task(
        id=ids.task_id(), session_id=session.id, created_at=datetime.now(UTC),
        agent="data_analysis", action="ProfileDataset", payload={},
    )
    return agent, task


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

    result = await agent.execute(task)
    assert result.kind == "data_profiled"
    assert result.extra["sample_count"] == 30
    candidates = result.extra["candidates"]
    assert len(candidates) == 1
    top = candidates[0]
    assert top["biomarker"] == "GENE_X"
    assert top["alteration_type"] == alteration
    assert top["drug"] == "DRUG_A"
    assert top["delta_os_months"] == -30
    assert top["p_value"] < 0.05
    assert top["altered_samples"] == 15
    assert (agent.deps.cfg.data_dir / result.extra["artifact_path"]).is_file()
    audit_path = agent.deps.cfg.session_artifact_dir(task.session_id) / "data_analysis" / "statistical_tests.csv"
    assert audit_path.is_file()
    assert "u_statistic" in audit_path.read_text()
    assert result.extra["methods"]["alpha"] == 0.05
    assert "Statistical methods and significance" in result.extra["summary"]
    assert not agent.deps.cfg.db_path.exists()


@pytest.mark.parametrize("filename", ["cohort.csv", "cohort.CSV", "clinical.tsv", "patient_metadata.txt"])
def test_detect_flat_dataset(tmp_path: Path, filename: str) -> None:
    (tmp_path / filename).write_text("sample_id,drug,time\nS1,DRUG_A,12\n")
    assert _detect_data_presence("Explore cancer mechanisms", str(tmp_path))


def test_runtime_storage_is_not_a_dataset(tmp_path: Path) -> None:
    (tmp_path / "co_scientist.db").write_bytes(b"not an input table")
    (tmp_path / "index.meta.json").write_text("{}")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "generated.csv").write_text("sample_id,drug,time\nS1,DRUG_A,12\n")
    assert tabular_files(tmp_path) == []
    assert not _detect_data_presence("Explore cancer mechanisms", str(tmp_path))


async def test_missing_dataset_directory_does_not_fall_back(
    tmp_path: Path, dataset_agent: tuple[DataAnalysisAgent, Task], monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, task = dataset_agent
    # A missing explicit path must not silently load unrelated ./data files.
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "metadata.csv").write_text("id,drug,time\nS1,DRUG_A,12\n")
    monkeypatch.chdir(tmp_path)
    task.payload["data_dir"] = str(tmp_path / "missing")
    with pytest.raises(NotADirectoryError, match="missing"):
        await agent.execute(task)


async def test_configured_relative_data_dir_is_independent_of_cwd(
    tmp_path: Path, dataset_agent: tuple[DataAnalysisAgent, Task], monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent, task = dataset_agent
    monkeypatch.setattr("co_scientist.config.PROJECT_ROOT", tmp_path)
    agent.deps.cfg.storage.data_dir = "./data"
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "cohort.csv").write_text("id,drug,time\nS1,DRUG_A,12\n")
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    result = await agent.execute(task)
    assert result.extra["sample_count"] == 1
    # The goal parser must also discover files via the resolved config path.
    agent.deps.llm.call = AsyncMock(return_value=MagicMock(raw=MagicMock(content=[])))
    session = await sess_repo.fetch(agent.deps.db, task.session_id)
    plan = await Supervisor(agent.deps.cfg)._parse_goal(
        agent.deps, session, "Explore cancer mechanisms", None,
    )
    assert plan.has_dataset


async def test_no_clinical_metadata_reports_expected_format(
    tmp_path: Path, dataset_agent: tuple[DataAnalysisAgent, Task],
) -> None:
    agent, task = dataset_agent
    (tmp_path / "mutations.csv").write_text("sample_id,GENE_X\nS1,1\n")
    result = await agent.execute(task)
    assert result.extra["candidates"] == []
    assert "No clinical metadata table" in result.extra["summary"]
    assert "CSV" in result.extra["summary"]

