"""Unit tests for DataAnalysisAgent and data-driven workflow."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from co_scientist import ids
from co_scientist.agents.base import AgentDeps
from co_scientist.agents.data_analysis import DataAnalysisAgent
from co_scientist.agents.generation import _render_hypothesis_md
from co_scientist.config import load_config
from co_scientist.models import ResearchPlan, Session, Task


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


@pytest.mark.asyncio
async def test_data_analysis_screening() -> None:
    cfg = load_config()
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # Create dummy patient_metadata.txt
        metadata_lines = [
            "SAMPLE_ID\tPATIENT_ID\tDRUG\tOS_MONTHS\tOS_STATUS",
        ]
        # 30 samples for DRUG_A: 15 with short survival, 15 with long
        for i in range(15):
            metadata_lines.append(f"S{i:02d}\tP{i:02d}\tDRUG_A\t10.0\t1:DECEASED")
        for i in range(15, 30):
            metadata_lines.append(f"S{i:02d}\tP{i:02d}\tDRUG_A\t40.0\t0:LIVING")
        (tmp_path / "patient_metadata.txt").write_text("\n".join(metadata_lines))

        # Create dummy cell2mutation_labeled.txt: GENE_X mutated in short-survival samples (0-14)
        mut_lines = ["\tGENE_X\tGENE_Y"]
        for i in range(15):
            mut_lines.append(f"S{i:02d}\t1\t0")
        for i in range(15, 30):
            mut_lines.append(f"S{i:02d}\t0\t0")
        (tmp_path / "cell2mutation_labeled.txt").write_text("\n".join(mut_lines))

        # Mock DB & Session
        mock_db = MagicMock()
        mock_session = Session(
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

        deps = AgentDeps(cfg=cfg, db=mock_db, llm=MagicMock(), tools=MagicMock())
        agent = DataAnalysisAgent(deps)

        import co_scientist.storage.repos.sessions as sess_repo
        sess_repo.fetch = AsyncMock(return_value=mock_session)

        task = Task(
            id=ids.task_id(),
            session_id=mock_session.id,
            created_at=datetime.now(UTC),
            agent="data_analysis",
            action="ProfileDataset",
            payload={"data_dir": str(tmp_path)},
        )

        result = await agent.execute(task)
        assert result.kind == "data_profiled"
        candidates = result.extra.get("candidates", [])
        assert len(candidates) > 0
        top = candidates[0]
        assert top["biomarker"] == "GENE_X"
        assert top["drug"] == "DRUG_A"
        assert top["delta_os_months"] < 0
        assert top["p_value"] < 0.05
        assert top["altered_samples"] == 15

