"""Data analysis agent: profiles uploaded attachments and stores results in the database."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from .. import timeline
from ..analysis import DatasetNotFoundError, profile_dataset, tests_csv
from ..generic_analysis import profile_generic_dataset
from ..logging import get_logger
from ..models import Task, TaskResult
from ..storage.artifacts import write_bytes, write_json, write_text
from ..storage.repos import analysis as analysis_repo
from ..storage.repos import attachments as att_repo
from ..storage.repos import blobs
from ..storage.repos import sessions as sess_repo
from ..survival_plots import survival_plot_images
from .base import BaseAgent

log = get_logger("data_analysis")

FAILED_TEXT = "could not be analysed; inspect the table format and processing logs"
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
        session = None
        if self.deps.db is not None:
            try:
                session = await sess_repo.fetch(self.deps.db, task.session_id)
            except Exception as exc:
                log.warning("session_fetch_failed", session_id=task.session_id, error=type(exc).__name__)
        if session is None and "data_dir" not in task.payload:
            raise RuntimeError(f"session {task.session_id} missing")
        target_drug = task.payload.get("target_drug")
        drugs = [target_drug] if target_drug else None
        attachment_ids = [str(a) for a in task.payload.get("attachment_ids", [])]
        session_id = session.id if session else task.session_id
        log.info(
            "profiling_dataset_started", session_id=session_id, attachments=len(attachment_ids),
        )
        if "data_dir" in task.payload:
            data_dir = Path(task.payload["data_dir"])
            report = await self._profile(session, data_dir, drugs, attachment_ids, goal=str(task.payload.get("research_goal") or ""))
        else:
            with tempfile.TemporaryDirectory() as tmp:
                selected = await self._materialise(session_id, attachment_ids, Path(tmp))
                attachment_ids = [a for a in attachment_ids if a in selected]
                report = await self._profile(session, Path(tmp), drugs, attachment_ids)
        if isinstance(report, TaskResult):
            return report
        return await self._store(session_id, report, attachment_ids)

    async def _materialise(
        self, session_id: str, attachment_ids: list[str], root: Path,
    ) -> set[str]:
        """Write the session's selected attachments under their original filenames."""
        written: set[str] = set()
        used: set[str] = set()
        if self.deps.db is None:
            return written
        for att_id in attachment_ids:
            try:
                meta = await att_repo.fetch(self.deps.db, att_id)
                if meta is None or meta.session_id != session_id:
                    continue
                name = Path(meta.filename).name
                if name in used:
                    name = f"{len(used)}_{name}"
                used.add(name)
                (root / name).write_bytes(await blobs.get(self.deps.db, "attachments", meta.blob_id))
                written.add(att_id)
            except Exception as exc:
                log.warning("materialise_attachment_failed", att_id=att_id, error=type(exc).__name__)
        return written

    async def _profile(
        self, session, data_dir: Path, drugs: list[str] | None, attachment_ids: list[str],
        *, goal: str = "",
    ) -> dict[str, Any] | TaskResult:
        research_goal = session.research_goal if session is not None else goal
        try:
            return profile_dataset(data_dir, goal=research_goal, target_drugs=drugs)
        except (DatasetNotFoundError, ValueError) as exc:
            # Survival profiling is schema-specific. For other delimited uploads,
            # provide general descriptive statistics, group comparisons and
            # correlations instead of silently returning no report.
            log.info("using_generic_dataset_profile", session_id=session.id if session else "unknown", reason=str(exc))
            try:
                return profile_generic_dataset(data_dir)
            except Exception as generic_exc:
                if self.deps.db is not None:
                    for att_id in attachment_ids:
                        try:
                            await att_repo.set_status(self.deps.db, att_id, "failed", FAILED_TEXT)
                        except Exception:
                            pass
                    try:
                        await timeline.post(
                            self.deps.db, session.id if session else "unknown", kind="dataset_unusable",
                            title="Dataset could not be analysed",
                            body="No compatible clinical or tabular data was found in the selected files.",
                            agent=self.name,
                        )
                    except Exception:
                        pass
                return TaskResult(kind="data_profiled", extra={"candidates": [], "summary": f"{exc}; {generic_exc}"})
        except Exception:
            if self.deps.db is not None:
                for att_id in attachment_ids:
                    try:
                        await att_repo.set_status(self.deps.db, att_id, "failed", FAILED_TEXT)
                    except Exception:
                        pass
            raise

    async def _store(
        self, session_id: str, report: dict[str, Any], attachment_ids: list[str],
    ) -> TaskResult:
        db = self.deps.db
        summary_md = report.pop("summary")
        tests = report.pop("tests")
        points = report.pop("points")
        keys = {c["candidate_key"] for c in report["candidates"]}
        survival_curves = report.get("survival_curves", [])
        key_by_path = {
            c["path"]: c["association"]["candidate_key"] for c in survival_curves
        }
        plot_images = survival_plot_images(report)
        stored_tests, truncated = _bounded_tests(tests, keys)
        report["tests"] = stored_tests
        if truncated:
            report["tests_truncated"] = True
            report["tests_total"] = len(tests)
        report["summary_markdown"] = summary_md

        artifact_path: str | None = None
        db_persisted = False

        if db is not None:
            try:
                plots = []
                for relative_path, body in plot_images.items():
                    key = key_by_path.get(relative_path)
                    blob_id = await blobs.put(
                        db, "plots", Path(relative_path).name, body,
                        {"session_id": session_id, "candidate_key": key},
                    )
                    plots.append({
                        "name": Path(relative_path).stem, "blob_id": blob_id, "content_type": "image/png",
                    })
                report["plots"] = plots
                await analysis_repo.save_report(db, session_id, report)
                for key, pts in points.items():
                    await analysis_repo.save_points(
                        db, session_id, key, metric="os_months", unit="months", points=pts,
                    )
                for curve in survival_curves:
                    candidate = curve.get("association", {})
                    cand_key = candidate.get("candidate_key")
                    if not cand_key:
                        continue
                    km_points = []
                    for group in ("altered", "unaltered"):
                        estimate = curve.get(group, {})
                        times = estimate.get("timeline", [])
                        survival_prob = estimate.get("survival_probability", [])
                        ci_lower = estimate.get("ci_lower", [])
                        ci_upper = estimate.get("ci_upper", [])
                        at_risk = estimate.get("at_risk", [])
                        for i in range(len(times)):
                            km_points.append({
                                "time": float(times[i]),
                                "survival_probability": float(survival_prob[i]),
                                "ci_lower": float(ci_lower[i]) if i < len(ci_lower) and ci_lower[i] is not None else None,
                                "ci_upper": float(ci_upper[i]) if i < len(ci_upper) and ci_upper[i] is not None else None,
                                "at_risk": int(at_risk[i]) if i < len(at_risk) and at_risk[i] is not None else 0,
                                "group": group,
                            })
                    await analysis_repo.save_points(
                        db, session_id, f"{cand_key}|km", metric="kaplan_meier", unit="months", points=km_points,
                    )
                for att_id in attachment_ids:
                    await att_repo.set_status(db, att_id, "analysed")
                await timeline.post(
                    db, session_id, kind="dataset_profiled", title="Dataset profiled",
                    body=(f"Exploratory profile · {report['sample_count']} rows · "
                          f"{len(report.get('tables', []))} tables · "
                          f"{report.get('group_comparisons_total', len(report.get('group_comparisons', [])))} group comparisons"
                          if report.get("profile_type") == "exploratory_tabular" else
                          f"{report['sample_count']} samples · drugs: {', '.join(report['drugs'])}"
                          f" · {len(report['candidates'])} candidate biomarkers"),
                    agent=self.name,
                )
                db_persisted = True
            except Exception as exc:
                log.warning(
                    "analysis_db_persistence_failed",
                    session_id=session_id,
                    error=type(exc).__name__,
                )

        if not db_persisted:
            try:
                for relative_path, body in plot_images.items():
                    path = Path(relative_path)
                    await write_bytes(
                        self.deps.cfg, session_id, f"data_analysis/{path.parent}", path.stem, path.suffix, body,
                    )
                artifact_path = await write_json(
                    self.deps.cfg, session_id, "data_analysis", "biomarker_candidates", report,
                )
                await write_text(
                    self.deps.cfg, session_id, "data_analysis", "statistical_tests", ".csv", tests_csv(tests),
                )
                await write_text(
                    self.deps.cfg, session_id, "data_analysis", "summary", ".md", summary_md,
                )
            except Exception as exc:
                log.warning(
                    "analysis_disk_fallback_failed",
                    session_id=session_id,
                    error=type(exc).__name__,
                )
        log.info(
            "profiling_dataset_complete", session_id=session_id,
            samples=report["sample_count"], drugs=report["drugs"],
            candidates_found=len(report["candidates"]), tests=len(tests),
        )
        return TaskResult(kind="data_profiled", extra={
            "candidates": report["candidates"], "summary": summary_md,
            "artifact_path": artifact_path, "target_drugs": report["drugs"],
            "sample_count": report["sample_count"], "methods": report["methods"],
            "selection": report["selection"],
        })
