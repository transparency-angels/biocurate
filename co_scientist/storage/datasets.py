"""Discovery helpers for flat research tables, independent of session storage."""

from __future__ import annotations

from pathlib import Path

TABULAR_SUFFIXES = (".csv", ".tsv", ".txt")


def tabular_files(data_dir: Path) -> list[Path]:
    """List input tables directly in a directory, preferring CSV files.

    Runtime databases and artifacts are never dataset inputs. Subdirectories
    are deliberately excluded so generated session artifacts are not reloaded.
    """
    if not data_dir.is_dir():
        return []
    return sorted(
        (
            path for path in data_dir.iterdir()
            if path.is_file() and path.suffix.lower() in TABULAR_SUFFIXES
        ),
        key=lambda path: (TABULAR_SUFFIXES.index(path.suffix.lower()), path.name.casefold()),
    )


def table_delimiter(path: Path) -> str:
    """CSV uses commas; legacy TSV and TXT tables use tabs."""
    return "," if path.suffix.lower() == ".csv" else "\t"
