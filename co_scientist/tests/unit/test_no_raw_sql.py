"""Guard: SQL against core tables lives in storage/repos, nowhere else."""

from __future__ import annotations

import re
from pathlib import Path

import co_scientist

_SQL_VERB = r"(?:SELECT|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|PRAGMA|REPLACE|WITH)"
# Receivers that are DB handles (conn, self._conn, db, cur, cursor, ...). The variable-SQL rule
# is limited to these so `agent.execute(task)` and `tool.execute(args)` are not flagged.
_DB_RECEIVER = r"(?:\w*conn\w*|db|con|cur|cursor)"
_RULES = {
    # literal or f-string/raw-string SQL passed straight to execute
    "literal-sql": re.compile(
        rf"""\.execute(?:many)?\(\s*[rRfF]{{0,2}}["']{{1,3}}\s*{_SQL_VERB}""", re.I
    ),
    "executescript": re.compile(r"executescript\("),
    "count-helper": re.compile(r"_count_by\("),
    # SQL built elsewhere and passed by name to a DB handle
    "variable-sql": re.compile(rf"\b{_DB_RECEIVER}\.execute(?:many)?\(\s*[A-Za-z_]\w*\s*[,)]"),
    "direct-connect": re.compile(r"\baiosqlite\.connect\("),
}
_EXCLUDED = {"storage", "bench", "tests"}
# bench is SQLite-only by design and opens its own DB, so it is excluded like storage/.


def scan(text: str) -> list[str]:
    """Names of the rules `text` violates."""
    return [name for name, rx in _RULES.items() if rx.search(text)]


def test_no_raw_sql_outside_storage() -> None:
    root = Path(co_scientist.__file__).parent
    offenders = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if rel.parts[0] in _EXCLUDED:
            continue
        if hits := scan(path.read_text(encoding="utf-8")):
            offenders.append(f"{rel}: {hits}")
    assert not offenders, f"raw SQL outside storage/: {offenders}"


def test_checker_flags_each_pattern() -> None:
    flagged = {
        'await conn.execute("SELECT 1")': "literal-sql",
        "await conn.execute(f'DELETE FROM t WHERE id={x}')": "literal-sql",
        'await db.execute(rf"""update t set a=1""")': "literal-sql",
        "await conn.executemany('INSERT INTO t VALUES (?)', rows)": "literal-sql",
        "await conn.executescript(ddl)": "executescript",
        "n = _count_by(conn, 't')": "count-helper",
        "await conn.execute(sql, (a,))": "variable-sql",
        "cur = await self._conn.execute(query)": "variable-sql",
        "db = await aiosqlite.connect(path)": "direct-connect",
    }
    for snippet, rule in flagged.items():
        assert rule in scan(snippet), snippet


def test_checker_ignores_non_db_execute() -> None:
    for ok in (
        "result = await agent.execute(task)",
        "await GenerationAgent(deps).execute(task)",
        "out = await tool.execute(args)",
        "await conn.close()",
        "from . import aiosqlite_compat",
    ):
        assert scan(ok) == [], ok
