"""One-off tidy-up: set `source="europepmc"` on library passages that have no `source`.

Search does not need this (passages without `source` are treated as Europe PMC), so it is
optional. Idempotent: only documents missing the field are touched, and re-running is a no-op.

    uv run python scripts/backfill_library_source.py -c atlas.toml --dry-run
    uv run python scripts/backfill_library_source.py -c atlas.toml

`atlas.toml` is a config overlay containing `[storage]` with `backend = "atlas"`.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from co_scientist.config import load_config
from co_scientist.storage.atlas.client import connect_atlas

_MISSING = {"source": {"$exists": False}}


async def backfill(config: Path | None, dry_run: bool) -> int:
    cfg = load_config(config)
    if cfg.storage.backend != "atlas":
        raise SystemExit("needs the Atlas backend: pass -c with [storage] backend = 'atlas'")
    conn = await connect_atlas(cfg)
    coll = conn.coll("library")
    n = await coll.count_documents(_MISSING)
    if dry_run:
        print(f"[dry-run] {n} passage(s) in {coll.full_name} lack `source`; nothing changed")
        return n
    res = await coll.update_many(_MISSING, {"$set": {"source": "europepmc"}})
    print(f"set source=europepmc on {res.modified_count} passage(s) in {coll.full_name}")
    return res.modified_count


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-c", "--config", type=Path, help="extra TOML config overlay")
    ap.add_argument("--dry-run", action="store_true", help="count only; write nothing")
    args = ap.parse_args()
    asyncio.run(backfill(args.config, args.dry_run))


if __name__ == "__main__":
    main()
