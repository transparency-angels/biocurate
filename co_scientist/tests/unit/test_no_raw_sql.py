"""Guard: SQL against core tables lives in storage/repos, nowhere else."""

from __future__ import annotations

import re
from pathlib import Path

import co_scientist

_PATTERN = re.compile(
    r"""\.execute\(\s*["']{1,3}\s*(SELECT|INSERT|UPDATE|DELETE)|executescript\(|_count_by\(""",
    re.I,
)
_EXCLUDED = {"storage", "bench", "tests"}


def test_no_raw_sql_outside_storage() -> None:
    root = Path(co_scientist.__file__).parent
    offenders = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if rel.parts[0] in _EXCLUDED:
            continue
        if _PATTERN.search(path.read_text(encoding="utf-8")):
            offenders.append(str(rel))
    assert not offenders, f"raw SQL outside storage/: {offenders}"
