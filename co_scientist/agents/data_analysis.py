"""Data analysis agent — schedule-independent profiling with session artifacts."""

from __future__ import annotations

from pathlib import Path

from ..analysis import DatasetNotFoundError, profile_dataset, tests_csv
from ..logging import get_logger
from ..models import Task, TaskResult
from ..storage.artifacts import write_json, write_text
from ..storage.repos import sessions as sess_repo
from .base import BaseAgent

log = get_logger("data_analysis")


class DataAnalysisAgent(BaseAgent):
    name = "data_analysis"

    async def execute(self, task: Task) -> TaskResult:
        if task.action != "ProfileDataset":
            raise ValueError(f"DataAnalysisAgent does not handle action {task.action!r}")
        session = await sess_repo.fetch(self.deps.db, task.session_id)
        if session is None:
            raise RuntimeError(f"session {task.session_id} missing")
        data_dir = Path(task.payload.get("data_dir") or self.deps.cfg.data_dir)
        target_drug = task.payload.get("target_drug")
        log.info("profiling_dataset_started", session_id=session.id, data_dir=str(data_dir))
        try:
            report = profile_dataset(
                data_dir, goal=session.research_goal,
                target_drugs=[target_drug] if target_drug else None,
            )
        except DatasetNotFoundError as exc:
            # A requested dataset may not contain a compatible clinical table.
            return TaskResult(kind="data_profiled", extra={"candidates": [], "summary": str(exc)})
        summary_md = report.pop("summary")
        tests = report.pop("tests")
        artifact_path = await write_json(
            self.deps.cfg, session.id, "data_analysis", "biomarker_candidates", report,
        )
        await write_text(self.deps.cfg, session.id, "data_analysis", "statistical_tests", ".csv", tests_csv(tests))
        await write_text(self.deps.cfg, session.id, "data_analysis", "summary", ".md", summary_md)
        log.info(
            "profiling_dataset_complete", session_id=session.id,
            samples=report["sample_count"], drugs=report["drugs"],
            candidates_found=len(report["candidates"]), tests=len(tests),
        )
        return TaskResult(kind="data_profiled", extra={
            "candidates": report["candidates"], "summary": summary_md,
            "artifact_path": artifact_path, "target_drugs": report["drugs"],
            "sample_count": report["sample_count"], "methods": report["methods"],
            "selection": report["selection"],
        })
