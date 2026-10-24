"""Data analysis agent: profiles uploaded attachments and stores results in the database."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from .. import timeline
from ..analysis import DatasetNotFoundError, profile_dataset
from ..logging import get_logger
from ..models import Task, TaskResult
from ..storage.repos import analysis as analysis_repo
from ..storage.repos import attachments as att_repo
from ..storage.repos import blobs
from ..storage.repos import sessions as sess_repo
from ..survival_plots import survival_plot_images
from .base import BaseAgent

log = get_logger("data_analysis")

FAILED_TEXT = "could not be analysed as a clinical dataset"
# The full test list is stored whole unless it could crowd a 16 MB document.
MAX_TESTS_BYTES = 8 * 1024 * 1024
TOP_TESTS_KEPT = 500


def _bounded_tests(
    tests: list[dict[str, Any]], keep: set[str],
) -> tuple[list[dict[str, Any]], bool]:
    """Return the tests to store: all of them, or candidates plus the top 500 by p-value."""
    if len(json.dumps(tests)) <= MAX_TESTS_BYTES:
        return tests, False
    by_p = sorted(tests, key=lambda t: (t["p_value"] is None, t["p_value"] or 0.0))
    top = {id(t) for t in by_p[:TOP_TESTS_KEPT]}
    kept = [t for t in tests if id(t) in top or t.get("candidate_key") in keep]
    return kept, True


class DataAnalysisAgent(BaseAgent):
    name = "data_analysis"

    async def execute(self, task: Task) -> TaskResult:
        if task.action != "ProfileDataset":
            raise ValueError(f"DataAnalysisAgent does not handle action {task.action!r}")
        session = await sess_repo.fetch(self.deps.db, task.session_id)
        if session is None:
            raise RuntimeError(f"session {task.session_id} missing")
        target_drug = task.payload.get("target_drug")
        drugs = [target_drug] if target_drug else None
        attachment_ids = [str(a) for a in task.payload.get("attachment_ids", [])]
        log.info(
            "profiling_dataset_started", session_id=session.id, attachments=len(attachment_ids),
        )
        with tempfile.TemporaryDirectory() as tmp:
            selected = await self._materialise(session.id, attachment_ids, Path(tmp))
            attachment_ids = [a for a in attachment_ids if a in selected]
            report = await self._profile(session, Path(tmp), drugs, attachment_ids)
        if isinstance(report, TaskResult):
            return report
        return await self._store(session.id, report, attachment_ids)

    async def _materialise(
        self, session_id: str, attachment_ids: list[str], root: Path,
    ) -> set[str]:
        """Write the session's selected attachments under their original filenames."""
        written: set[str] = set()
        used: set[str] = set()
        for att_id in attachment_ids:
            meta = await att_repo.fetch(self.deps.db, att_id)
            if meta is None or meta.session_id != session_id:
                continue
            name = Path(meta.filename).name
            if name in used:
                name = f"{len(used)}_{name}"
            used.add(name)
            (root / name).write_bytes(await blobs.get(self.deps.db, "attachments", meta.blob_id))
            written.add(att_id)
        return written

    async def _profile(
        self, session, data_dir: Path, drugs: list[str] | None, attachment_ids: list[str],
    ) -> dict[str, Any] | TaskResult:
        try:
            return profile_dataset(data_dir, goal=session.research_goal, target_drugs=drugs)
        except DatasetNotFoundError as exc:
            # A requested dataset may not contain a compatible clinical table.
            for att_id in attachment_ids:
                await att_repo.set_status(self.deps.db, att_id, "failed", FAILED_TEXT)
            await timeline.post(
                self.deps.db, session.id, kind="dataset_unusable",
                title="Dataset could not be analysed",
                body="No compatible clinical table was found in the selected files.",
                agent=self.name,
            )
            return TaskResult(kind="data_profiled", extra={"candidates": [], "summary": str(exc)})
        except Exception:
            for att_id in attachment_ids:
                await att_repo.set_status(self.deps.db, att_id, "failed", FAILED_TEXT)
            raise

    async def _store(
        self, session_id: str, report: dict[str, Any], attachment_ids: list[str],
    ) -> TaskResult:
        db = self.deps.db
        summary_md = report.pop("summary")
        tests = report.pop("tests")
        points = report.pop("points")
        keys = {c["candidate_key"] for c in report["candidates"]}
        key_by_path = {
            c["path"]: c["association"]["candidate_key"] for c in report["survival_curves"]
        }
        plots = []
        for relative_path, body in survival_plot_images(report).items():
            key = key_by_path.get(relative_path)
            blob_id = await blobs.put(
                db, "plots", Path(relative_path).name, body,
                {"session_id": session_id, "candidate_key": key},
            )
            plots.append({
                "name": Path(relative_path).stem, "blob_id": blob_id, "content_type": "image/png",
            })
        stored_tests, truncated = _bounded_tests(tests, keys)
        report["tests"] = stored_tests
        if truncated:
            report["tests_truncated"] = True
            report["tests_total"] = len(tests)
        report["summary_markdown"] = summary_md
        report["plots"] = plots
        await analysis_repo.save_report(db, session_id, report)
        for key, pts in points.items():
            await analysis_repo.save_points(
                db, session_id, key, metric="os_months", unit="months", points=pts,
            )
        for att_id in attachment_ids:
            await att_repo.set_status(db, att_id, "analysed")
        await timeline.post(
            db, session_id, kind="dataset_profiled", title="Dataset profiled",
            body=(
                f"{report['sample_count']} samples · drugs: {', '.join(report['drugs'])}"
                f" · {len(report['candidates'])} candidate biomarkers"
            ),
            agent=self.name,
        )
        log.info(
            "profiling_dataset_complete", session_id=session_id,
            samples=report["sample_count"], drugs=report["drugs"],
            candidates_found=len(report["candidates"]), tests=len(tests),
        )
        return TaskResult(kind="data_profiled", extra={
            "candidates": report["candidates"], "summary": summary_md,
            "artifact_path": None, "target_drugs": report["drugs"],
            "sample_count": report["sample_count"], "methods": report["methods"],
            "selection": report["selection"],
        })
