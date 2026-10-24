"""Rerun biomarker statistics without a session, database, API key, or LLM.

Example:
    python scripts/validate_data_analysis.py --data-dir ./data \
        --reference data/artifacts/<session_id>/data_analysis/biomarker_candidates.json \
        --output-dir ./data/validation

An optional reference fixes the treatment arms to the stored selection and checks
every stored candidate field, the candidate ordering, and the loaded sample count.
Exit status: 0 for success/match, 1 for a mismatch, 2 for invalid inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shlex
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from co_scientist.analysis import profile_dataset, tests_csv  # noqa: E402
from co_scientist.survival_plots import survival_plot_images  # noqa: E402


def compare_reference(report: dict[str, Any], reference: dict[str, Any]) -> dict[str, Any]:
    """Compare stored values with strict relative tolerances for tiny p-values."""
    differences = []
    checks = 0

    def check(label: str, expected: Any, actual: Any) -> None:
        nonlocal checks
        checks += 1
        if isinstance(expected, (float, int)) and not isinstance(expected, bool):
            matched = isinstance(actual, (float, int)) and math.isclose(
                expected, actual, rel_tol=1e-10, abs_tol=0.0,
            )
        else:
            matched = expected == actual
        if not matched:
            differences.append({"field": label, "expected": expected, "actual": actual})

    key_fields = ("biomarker", "alteration_type", "drug")

    def key(candidate: dict[str, Any]) -> tuple[str, ...]:
        return tuple(candidate[field] for field in key_fields)

    expected_candidates = reference["candidates"]
    # Changed analysis methods are expected to produce different numbers.
    reference_method = reference.get("methods", {}).get("primary_test", "legacy (method not recorded)")
    report_method = report["methods"]["primary_test"]
    check("primary_test", reference_method, report_method)
    check("candidate_order", [key(c) for c in expected_candidates], [key(c) for c in report["candidates"]])
    for field in ("sample_count", "drugs"):
        check(field, reference[field], report[field])
    actual_by_key = {key(candidate): candidate for candidate in report["tests"]}
    for expected in expected_candidates:
        actual = actual_by_key.get(key(expected), {})
        for field, value in expected.items():
            check(f"{'/'.join(key(expected))}/{field}", value, actual.get(field))
    return {
        "all_matched": not differences,
        "reference_candidates": len(expected_candidates),
        "checks": checks,
        "numeric_tolerance": {"relative": 1e-10, "absolute": 0.0},
        "differences": differences,
        "method_changed": reference_method != report_method,
        "scope": "Recompute against current source files; original input snapshots and software versions are not inferred.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=REPO_ROOT / "data")
    parser.add_argument("--goal", default="", help="Optional goal used for automatic treatment selection.")
    parser.add_argument("--drug", action="append", help="Treatment to screen; repeat for multiple treatments.")
    parser.add_argument("--reference", type=Path, help="Previously generated biomarker_candidates.json to validate.")
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT / "data" / "validation")
    args = parser.parse_args(argv)
    output_dir = args.output_dir.expanduser().resolve()
    try:
        reference = None
        if args.reference:
            reference_path = args.reference.expanduser().resolve()
            if reference_path == output_dir / "biomarker_candidates.json":
                parser.error("Choose a separate output directory to preserve the reference artifact.")
            reference = json.loads(reference_path.read_text(encoding="utf-8"))
        drugs = args.drug if args.drug is not None else (reference["drugs"] if reference is not None else None)
        report = profile_dataset(args.data_dir, goal=args.goal, target_drugs=drugs)
        validation = compare_reference(report, reference) if reference is not None else None
        if validation is not None:
            validation["reference_path"] = str(reference_path)
            validation["reference_sha256"] = hashlib.sha256(reference_path.read_bytes()).hexdigest()
        summary = report.pop("summary")
        tests = report.pop("tests")
        command = shlex.join([sys.executable, str(Path(__file__).resolve()), *(sys.argv[1:] if argv is None else argv)])
        summary += f"\nRerun command:\n\n```bash\n{command}\n```\n"
        if validation is not None:
            status = "MATCH" if validation["all_matched"] else "MISMATCH"
            summary += (
                f"\n## Comparison with stored artifact\n\n"
                f"- Result: **{status}** across {validation['reference_candidates']} candidates and {validation['checks']} checks.\n"
                f"- Reference: `{reference_path}`. Full differences: `validation.json`.\n"
                "- Numeric comparisons use relative tolerance 1e-10 and zero absolute tolerance, including very small p-values.\n"
                "- This validates the current source tables against stored numbers; the original run did not necessarily record input hashes or package versions.\n"
            )
            if validation["method_changed"]:
                summary += "- **Analysis method changed**: differences from the older method are expected. Use a Kaplan-Meier/log-rank artifact as the reference to validate the new calculation.\n"
        output_dir.mkdir(parents=True, exist_ok=True)
        for relative_path, body in survival_plot_images(report).items():
            path = output_dir / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        (output_dir / "summary.md").write_text(summary, encoding="utf-8")
        (output_dir / "biomarker_candidates.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        (output_dir / "statistical_tests.csv").write_text(tests_csv(tests), encoding="utf-8")
        if validation is not None:
            (output_dir / "validation.json").write_text(json.dumps(validation, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(f"Tested {report['selection']['eligible_tests']} comparisons; {report['selection']['nominally_significant_tests']} nominally significant; {len(report['candidates'])} candidates reported.")
    print(f"Summary: {output_dir / 'summary.md'}")
    if validation is not None:
        print(f"Reference validation: {'MATCH' if validation['all_matched'] else 'MISMATCH'} ({len(validation['differences'])} differences)")
    return 1 if validation is not None and not validation["all_matched"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
