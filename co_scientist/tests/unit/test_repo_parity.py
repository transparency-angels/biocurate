"""Every SQLite repo function needs an Atlas twin and a dispatcher."""

from __future__ import annotations

import importlib
import inspect

import pytest

MODULES = [
    "embeddings", "events", "feedback", "hypotheses", "reviews",
    "sessions", "spans", "tasks", "tournaments", "transcripts",
]


def _public_async(mod) -> set[str]:
    return {
        n for n, f in vars(mod).items()
        if inspect.iscoroutinefunction(f) and not n.startswith("_")
    }


@pytest.mark.parametrize("name", MODULES)
def test_every_sqlite_repo_function_has_atlas_twin(name):
    sql = importlib.import_module(f"co_scientist.storage.sqlite.{name}")
    atlas = importlib.import_module(f"co_scientist.storage.atlas.{name}")
    repo = importlib.import_module(f"co_scientist.storage.repos.{name}")
    names = _public_async(sql)
    assert names, f"{name}: no public functions found"
    assert names == _public_async(atlas)
    for fn in names:
        assert hasattr(repo, fn), f"repos.{name}.{fn} missing"
        assert list(inspect.signature(getattr(atlas, fn)).parameters)[1:] == list(
            inspect.signature(getattr(sql, fn)).parameters
        )[1:], f"{name}.{fn}: signature differs"


async def test_dual_routes_by_connection_type():
    from co_scientist.storage.atlas.client import AtlasConn
    from co_scientist.storage.repos._dispatch import dual

    async def sql_fn(conn, x):
        return ("sql", x)

    async def atlas_fn(conn, x):
        return ("atlas", x)

    f = dual(sql_fn, atlas_fn)
    assert f.__name__ == "sql_fn"
    assert await f(object(), 1) == ("sql", 1)
    assert await f(AtlasConn(client=None, db=None), 2) == ("atlas", 2)
