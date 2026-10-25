"""Every SQLite repo function needs an Atlas twin and a dispatcher."""

from __future__ import annotations

import importlib
import inspect

import pytest

MODULES = [
    "analysis", "attachments", "blobs", "embeddings", "events", "feedback", "hypotheses",
    "reviews",
    "sessions", "spans", "syntheses", "tasks", "timeline", "tournaments", "transcripts",
]


def _public_async(mod) -> set[str]:
    return {
        n for n, f in vars(mod).items()
        if inspect.iscoroutinefunction(f) and not n.startswith("_")
    }


def _is_dual(repo_fn, sql_fn) -> bool:
    """`dual` uses functools.wraps, so the repo attribute wraps the SQLite function."""
    return getattr(repo_fn, "__wrapped__", None) is sql_fn


def test_is_dual_flags_a_plain_alias_and_a_local_function():
    from co_scientist.storage.repos._dispatch import dual

    async def f(conn):
        return 1

    async def g(conn):
        return 2

    assert _is_dual(dual(f, g), f)
    assert not _is_dual(f, f)  # `foo = _sql.foo` with no dispatch
    assert not _is_dual(g, f)  # a function written directly in repos/


def test_public_async_sees_a_function_added_to_a_repo_module():
    import types

    mod = types.ModuleType("m")

    async def sneaky(conn):
        return 1

    mod.sneaky = sneaky
    assert _public_async(mod) == {"sneaky"}


def test_spans_span_is_the_only_allowed_non_dual_public_helper():
    from co_scientist.storage.repos import spans

    assert not inspect.iscoroutinefunction(spans.span)  # asynccontextmanager, not a coroutine
    assert "span" not in _public_async(spans)


@pytest.mark.parametrize("name", MODULES)
def test_every_sqlite_repo_function_has_atlas_twin(name):
    sql = importlib.import_module(f"co_scientist.storage.sqlite.{name}")
    atlas = importlib.import_module(f"co_scientist.storage.atlas.{name}")
    repo = importlib.import_module(f"co_scientist.storage.repos.{name}")
    names = _public_async(sql)
    assert names, f"{name}: no public functions found"
    assert names == _public_async(atlas)
    assert names == _public_async(repo), (
        f"repos.{name} public coroutines differ from storage/sqlite/{name}.py: "
        f"{names ^ _public_async(repo)} (write functions in sqlite/ + atlas/, wire with dual)"
    )
    for fn in names:
        assert hasattr(repo, fn), f"repos.{name}.{fn} missing"
        assert _is_dual(getattr(repo, fn), getattr(sql, fn)), (
            f"repos.{name}.{fn} must be `dual(_sql.{fn}, _atlas.{fn})`"
        )
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
