"""SQLite connection helpers and migration runner.

Single connection per process is fine for our workload (writes serialize on the WAL
anyway). We use aiosqlite for the async API and set PRAGMAs on each connect.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from ..config import Config

SCHEMA_PATH = Path(__file__).parent / "schema.sql"
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def is_network_filesystem(path: Path) -> bool:
    try:
        import subprocess

        out = subprocess.check_output(["df", "-T", str(path)], stderr=subprocess.DEVNULL, text=True)
        fstype = out.strip().splitlines()[-1].split()[1].lower()
        return any(net in fstype for net in ("nfs", "cifs", "smb", "lustre", "gpfs", "fuse"))
    except Exception:
        return False


async def _apply_pragmas(conn: aiosqlite.Connection, db_path: Path | None = None) -> None:
    # WAL mode requires POSIX shared-memory primitives (mmap / .shm locks).
    # On network filesystems like NFS, WAL mode leads to SQLITE_NOTADB ("file is not a database")
    # or concurrent locking errors. Use DELETE mode on NFS.
    use_wal = True
    if db_path is not None and is_network_filesystem(db_path):
        use_wal = False

    journal_mode = "WAL" if use_wal else "DELETE"
    await conn.execute(f"PRAGMA journal_mode={journal_mode};")
    await conn.execute("PRAGMA synchronous=NORMAL;")
    await conn.execute("PRAGMA foreign_keys=ON;")
    await conn.execute("PRAGMA busy_timeout=30000;")
    await conn.commit()


async def connect(cfg: Config) -> aiosqlite.Connection:
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(cfg.db_path)
    conn.row_factory = aiosqlite.Row
    await _apply_pragmas(conn, cfg.db_path)
    return conn


async def init_db(cfg: Config) -> None:
    """Create the DB if missing and apply pending migrations."""
    conn = await connect(cfg)
    try:
        await _ensure_migrations_table(conn)
        await _apply_pending(conn)
    finally:
        await conn.close()


async def _ensure_migrations_table(conn: aiosqlite.Connection) -> None:
    await conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
               version    INTEGER PRIMARY KEY,
               applied_at TEXT NOT NULL,
               name       TEXT NOT NULL
           )"""
    )
    await conn.commit()


async def _applied_versions(conn: aiosqlite.Connection) -> set[int]:
    async with conn.execute("SELECT version FROM schema_migrations") as cur:
        rows = await cur.fetchall()
    return {row["version"] for row in rows}


def _discover_migrations() -> list[tuple[int, str, Path]]:
    """Return [(version, name, path)] sorted by version."""
    out: list[tuple[int, str, Path]] = []
    for p in sorted(MIGRATIONS_DIR.glob("*.sql")):
        stem = p.stem  # e.g. 0001_initial
        version_str, _, name = stem.partition("_")
        out.append((int(version_str), name or "unnamed", p))
    return out


async def _apply_pending(conn: aiosqlite.Connection) -> None:
    applied = await _applied_versions(conn)
    for version, name, path in _discover_migrations():
        if version in applied:
            continue
        # v1 special-case: load the canonical schema.sql to avoid duplication.
        sql = SCHEMA_PATH.read_text() if version == 1 else path.read_text()
        try:
            await conn.executescript(sql)
        except aiosqlite.OperationalError as e:
            # When the canonical schema.sql is already ahead of an early
            # migration (e.g. fresh init creates v1 with `feasibility`, then
            # v2 tries to ALTER TABLE … ADD COLUMN feasibility), the ALTER
            # becomes a no-op. Mark it applied and move on.
            msg = str(e).lower()
            if "duplicate column name" in msg or (
                "already exists" in msg and "create" not in sql.lower()
            ):
                pass
            else:
                raise
        await conn.execute(
            "INSERT INTO schema_migrations(version, applied_at, name) VALUES (?, ?, ?)",
            (version, datetime.now(UTC).isoformat(), name),
        )
        await conn.commit()


async def table_names(conn: aiosqlite.Connection) -> list[str]:
    async with conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ) as cur:
        rows = await cur.fetchall()
    return [r["name"] for r in rows]
