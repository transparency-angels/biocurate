"""Data analysis agent — screens datasets and metadata for empirical biomarker signals.

Ingests clinical metadata and genomic matrices (mutations, copy number alterations),
computes statistical associations between alterations and treatment response/survival,
and outputs candidate biomarkers to seed downstream mechanistic hypothesis generation.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

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

        data_dir_raw = task.payload.get("data_dir") or self.deps.cfg.storage.data_dir
        data_dir = Path(data_dir_raw).resolve()
        if not data_dir.exists():
            data_dir = Path("./data").resolve()

        log.info("profiling_dataset_started", session_id=session.id, data_dir=str(data_dir))

        # 1. Load and parse clinical / study metadata
        metadata_file = self._find_metadata_file(data_dir)
        if metadata_file is None:
            log.warning("no_metadata_file_found", data_dir=str(data_dir))
            return TaskResult(
                kind="data_profiled",
                extra={"candidates": [], "summary": "No tabular dataset found to profile."},
            )

        samples, drugs = self._load_patient_metadata(metadata_file)
        if not samples:
            return TaskResult(
                kind="data_profiled",
                extra={"candidates": [], "summary": f"No valid sample records found in {metadata_file.name}."},
            )

        # 2. Determine target drugs to analyze
        target_drugs = self._select_target_drugs(session.research_goal, drugs, task.payload.get("target_drug"))

        # 3. Screen genomic alteration matrices against treatment response/survival
        candidates = self._screen_alterations(data_dir, samples, target_drugs)

        # 4. Generate summary markdown and save artifacts
        summary_md = self._render_summary(samples, target_drugs, candidates)
        artifact_path = await write_json(
            self.deps.cfg,
            session.id,
            "data_analysis",
            "biomarker_candidates",
            {"candidates": candidates, "drugs": target_drugs, "sample_count": len(samples)},
        )
        await write_text(self.deps.cfg, session.id, "data_analysis", "summary", ".md", summary_md)

        log.info(
            "profiling_dataset_complete",
            session_id=session.id,
            samples=len(samples),
            drugs=target_drugs,
            candidates_found=len(candidates),
        )

        return TaskResult(
            kind="data_profiled",
            extra={
                "candidates": candidates,
                "summary": summary_md,
                "artifact_path": artifact_path,
                "target_drugs": target_drugs,
                "sample_count": len(samples),
            },
        )

    # ----------------------------- data loading ----------------------------- #

    def _find_metadata_file(self, data_dir: Path) -> Path | None:
        preferred = ["patient_metadata.txt", "pfs_months.txt", "OS_time_adjusted.txt", "metadata.tsv", "metadata.csv"]
        for name in preferred:
            p = data_dir / name
            if p.is_file():
                return p
        # Fallback to any txt/csv/tsv file in data_dir
        for p in data_dir.glob("*.txt"):
            if "mutation" not in p.name.lower() and "amplification" not in p.name.lower() and "deletion" not in p.name.lower():
                return p
        return None

    def _load_patient_metadata(self, metadata_path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
        samples: dict[str, dict[str, Any]] = {}
        drugs: dict[str, list[str]] = defaultdict(list)

        delimiter = "\t" if metadata_path.suffix in (".tsv", ".txt") else ","
        with open(metadata_path, encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for row in reader:
                sid = row.get("SAMPLE_ID") or row.get("PATIENT_ID") or row.get("sample") or row.get("id")
                if not sid:
                    continue
                drug = (row.get("DRUG") or row.get("drug") or row.get("TREATMENT") or "").strip().upper()
                
                # Parse overall survival
                os_val = None
                for os_col in ("OS_MONTHS", "PFS_MONTHS", "survival_months", "time"):
                    if row.get(os_col):
                        try:
                            os_val = float(row[os_col])
                            break
                        except ValueError:
                            pass
                if os_val is None:
                    os_val = 0.0

                # Parse status (1 = deceased/event, 0 = living/censored)
                status = 0
                for st_col in ("OS_STATUS", "PFS_STATUS", "vital_status", "status", "event"):
                    if row.get(st_col):
                        raw_st = str(row[st_col]).upper()
                        if "DECEASED" in raw_st or "PROGRESSION" in raw_st or "1:" in raw_st or raw_st == "1":
                            status = 1
                        break

                if sid not in samples:
                    samples[sid] = {"os_months": os_val, "status": status, "drugs": set()}
                if drug:
                    samples[sid]["drugs"].add(drug)
                    drugs[drug].append(sid)

        return samples, drugs

    def _select_target_drugs(
        self, goal: str, available_drugs: dict[str, list[str]], override: str | None = None
    ) -> list[str]:
        if override and override.upper() in available_drugs:
            return [override.upper()]

        # Check goal for drug mentions
        goal_upper = goal.upper()
        mentioned = [d for d in available_drugs if d in goal_upper and len(available_drugs[d]) >= 10]
        if mentioned:
            return sorted(mentioned, key=lambda d: len(available_drugs[d]), reverse=True)[:3]

        # Top drugs by cohort size
        sorted_drugs = sorted(available_drugs.items(), key=lambda kv: len(kv[1]), reverse=True)
        return [d for d, sids in sorted_drugs[:4] if len(sids) >= 30]

    # ----------------------------- screening ----------------------------- #

    def _screen_alterations(
        self, data_dir: Path, samples: dict[str, dict[str, Any]], target_drugs: list[str]
    ) -> list[dict[str, Any]]:
        alteration_specs = [
            ("mutation", self._find_matrix_file(data_dir, ["cell2mutation_labeled.txt", "*mutation*.txt", "*mut*.tsv"])),
            ("amplification", self._find_matrix_file(data_dir, ["cell2cnamplification_labeled.txt", "*amplification*.txt"])),
            ("deletion", self._find_matrix_file(data_dir, ["cell2cndeletion_labeled.txt", "*deletion*.txt"])),
        ]

        all_candidates: list[dict[str, Any]] = []

        for alt_type, matrix_path in alteration_specs:
            if not matrix_path or not matrix_path.is_file():
                continue
            for drug in target_drugs:
                drug_candidates = self._screen_single_matrix(matrix_path, alt_type, drug, samples)
                all_candidates.extend(drug_candidates)

        # Sort all candidates by p_value ascending
        all_candidates.sort(key=lambda c: c["p_value"])
        # Dedup to keep strongest alteration/drug pair per gene
        seen: set[tuple[str, str]] = set()
        unique_candidates: list[dict[str, Any]] = []
        for c in all_candidates:
            key = (c["biomarker"], c["drug"])
            if key not in seen:
                seen.add(key)
                unique_candidates.append(c)

        return unique_candidates[:12]

    def _find_matrix_file(self, data_dir: Path, patterns: list[str]) -> Path | None:
        for pat in patterns:
            if "*" in pat:
                for match in data_dir.glob(pat):
                    if match.is_file():
                        return match
            else:
                p = data_dir / pat
                if p.is_file():
                    return p
        return None

    def _screen_single_matrix(
        self, matrix_path: Path, alt_type: str, drug: str, samples: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        target_sids = {sid: info for sid, info in samples.items() if drug in info["drugs"]}
        if len(target_sids) < 20:
            return []

        delimiter = "\t" if matrix_path.suffix in (".tsv", ".txt") else ","
        candidates: list[dict[str, Any]] = []

        try:
            with open(matrix_path, encoding="utf-8", errors="replace") as f:
                header_line = f.readline().strip()
                if not header_line:
                    return []
                headers = header_line.split(delimiter)
                # First column is sample index/header
                genes = headers[1:] if headers[0] == "" or "sample" in headers[0].lower() else headers

                mut_os: dict[int, list[float]] = {i: [] for i in range(len(genes))}
                wt_os: dict[int, list[float]] = {i: [] for i in range(len(genes))}
                mut_status: dict[int, list[int]] = {i: [] for i in range(len(genes))}
                wt_status: dict[int, list[int]] = {i: [] for i in range(len(genes))}

                for line in f:
                    parts = line.strip().split(delimiter)
                    if not parts or len(parts) < 2:
                        continue
                    sid = parts[0]
                    if sid not in target_sids:
                        continue
                    s_info = target_sids[sid]
                    vals = parts[1:]
                    for i, val in enumerate(vals):
                        if i >= len(genes):
                            break
                        if val in ("1", "1.0", "TRUE", "true"):
                            mut_os[i].append(s_info["os_months"])
                            mut_status[i].append(s_info["status"])
                        else:
                            wt_os[i].append(s_info["os_months"])
                            wt_status[i].append(s_info["status"])

            for i, gene in enumerate(genes):
                n_alt = len(mut_os[i])
                n_wt = len(wt_os[i])
                if n_alt < 10 or n_wt < 10:
                    continue

                try:
                    _u_stat, p_val = stats.mannwhitneyu(mut_os[i], wt_os[i], alternative="two-sided")
                except Exception:
                    continue

                if np.isnan(p_val) or p_val > 0.05:
                    continue

                med_alt = float(np.median(mut_os[i]))
                med_wt = float(np.median(wt_os[i]))
                delta_os = round(med_alt - med_wt, 2)

                # Fisher exact test for mortality difference
                alt_dec = sum(mut_status[i])
                alt_liv = n_alt - alt_dec
                wt_dec = sum(wt_status[i])
                wt_liv = n_wt - wt_dec
                odds_ratio, f_pval = stats.fisher_exact([[alt_dec, alt_liv], [wt_dec, wt_liv]])
                or_val = round(float(odds_ratio), 2) if not np.isnan(odds_ratio) and not np.isinf(odds_ratio) else 1.0

                relationship = "reduced_response_or_poor_prognosis" if delta_os < 0 else "favorable_response_or_prognosis"

                candidates.append({
                    "biomarker": gene,
                    "alteration_type": alt_type,
                    "drug": drug,
                    "relationship": relationship,
                    "delta_os_months": delta_os,
                    "median_os_altered": round(med_alt, 2),
                    "median_os_wt": round(med_wt, 2),
                    "p_value": float(p_val),
                    "odds_ratio": or_val,
                    "fisher_p_value": float(f_pval),
                    "sample_size": n_alt + n_wt,
                    "altered_samples": n_alt,
                    "cohort": f"Clinical cohort ({drug})",
                })
        except Exception as e:
            log.warning("screen_single_matrix_failed", path=str(matrix_path), err=str(e))

        return candidates

    # ----------------------------- rendering ----------------------------- #

    def _render_summary(
        self, samples: dict[str, dict[str, Any]], target_drugs: list[str], candidates: list[dict[str, Any]]
    ) -> str:
        parts: list[str] = [
            "# Dataset & Biomarker Profiling Summary",
            f"- Total patient samples analyzed: **{len(samples)}**",
            f"- Targeted treatment arms screened: **{', '.join(target_drugs)}**",
            f"- Statistically significant candidate associations identified: **{len(candidates)}**",
            "",
            "## Top Candidate Biomarkers Associated With Treatment Response",
        ]
        if not candidates:
            parts.append("*(No candidate alterations reached nominal statistical significance p < 0.05.)*")
        else:
            parts.append("| Gene | Alteration | Drug | Effect (Δ OS Months) | p-value | Altered N | Association Direction |")
            parts.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
            for c in candidates:
                parts.append(
                    f"| **{c['biomarker']}** | {c['alteration_type']} | {c['drug']} | "
                    f"{c['delta_os_months']:+.2f} mo | {c['p_value']:.4e} | {c['altered_samples']} | "
                    f"`{c['relationship']}` |"
                )
        return "\n".join(parts)
