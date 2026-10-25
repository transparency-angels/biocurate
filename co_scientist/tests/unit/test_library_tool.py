from __future__ import annotations

from co_scientist.config import Config, StorageCfg
from co_scientist.tools.base import ToolCtx
from co_scientist.tools.builtins.library import SearchLibraryTool
from co_scientist.tools.registry import AGENT_TOOLS, ToolRegistry


async def test_search_library_tool_errors_on_sqlite(conn, tmp_cfg) -> None:
    res = await SearchLibraryTool().call({"query": "x"}, ToolCtx(cfg=tmp_cfg, db=conn))
    assert res.is_error and "atlas" in res.error_message.lower()


async def test_search_library_tool_rejects_empty_query(tmp_cfg) -> None:
    res = await SearchLibraryTool().call({"query": " "}, ToolCtx(cfg=tmp_cfg, db=None))
    assert res.is_error


def test_registry_registers_search_library_only_on_atlas(tmp_cfg) -> None:
    assert "search_library" not in ToolRegistry(tmp_cfg).discover()
    cfg = Config(storage=StorageCfg(backend="atlas"))
    assert "search_library" in ToolRegistry(cfg).discover()
    for agent in ("generation", "reflection", "evolution"):
        assert "search_library" in AGENT_TOOLS[agent]
    assert "search_library" not in AGENT_TOOLS["ranking"]


def _atlas_ctx(cfg):
    from co_scientist.storage import AtlasConn

    return ToolCtx(cfg=cfg, db=AtlasConn(client=None, db=None))  # type: ignore[arg-type]


def _patch_store(monkeypatch, n: int = 5):
    from co_scientist.storage.atlas import library as lib_store

    async def _count(conn):
        return n

    monkeypatch.setattr(lib_store, "count", _count)


async def test_search_library_tool_returns_error_on_pymongo_failure(monkeypatch) -> None:
    from pymongo.errors import ServerSelectionTimeoutError

    from co_scientist.library import search

    _patch_store(monkeypatch)

    async def boom(*a, **kw):
        raise ServerSelectionTimeoutError("cluster0-shard-00.secret.mongodb.net timed out")

    monkeypatch.setattr(search, "hybrid_search", boom)
    res = await SearchLibraryTool().call({"query": "x"}, _atlas_ctx(Config()))
    assert res.is_error
    assert "ServerSelectionTimeoutError" in res.error_message
    assert "secret" not in res.error_message


async def test_search_library_tool_reports_index_not_ready(monkeypatch) -> None:
    from pymongo.errors import OperationFailure

    from co_scientist.library import search

    _patch_store(monkeypatch)
    msg = (
        "cannot query search index 6adc (index library_text collection c (uuid) in database "
        "biocurate) while in state INITIAL_SYNC, full error: {}"
    )

    async def boom(*a, **kw):
        raise OperationFailure(msg, code=8, details={"codeName": "UnknownError"})

    monkeypatch.setattr(search, "hybrid_search", boom)
    res = await SearchLibraryTool().call({"query": "x"}, _atlas_ctx(Config()))
    assert res.error_message == "library index 'library_text' is not ready yet; retry shortly"


async def test_search_library_tool_other_operation_failure_is_generic(monkeypatch) -> None:
    from pymongo.errors import OperationFailure

    from co_scientist.library import search

    _patch_store(monkeypatch)

    async def boom(*a, **kw):
        raise OperationFailure("bad pipeline mentioning index library_text", code=40324)

    monkeypatch.setattr(search, "hybrid_search", boom)
    res = await SearchLibraryTool().call({"query": "x"}, _atlas_ctx(Config()))
    assert res.is_error and "OperationFailure" in res.error_message
    assert "not ready" not in res.error_message


async def test_search_library_tool_empty_hits_with_unready_index(monkeypatch) -> None:
    from co_scientist.library import search
    from co_scientist.tools.builtins import library as tool_mod

    _patch_store(monkeypatch)

    async def none(*a, **kw):
        return []

    async def unready(db, names):
        return names[1]

    monkeypatch.setattr(search, "hybrid_search", none)
    monkeypatch.setattr(tool_mod, "_unready_index", unready)
    res = await SearchLibraryTool().call({"query": "x"}, _atlas_ctx(Config()))
    assert "'library_vec' is not ready" in res.error_message


async def test_search_library_tool_truncates_text_to_800(monkeypatch) -> None:
    from co_scientist.library import search
    from co_scientist.library.search import LibraryHit

    _patch_store(monkeypatch)
    hit = LibraryHit("PMC1#p1", "PMC1", "T", "S", "paragraph", None, "z" * 2000, "u", 0.1, 0.9)

    async def ok(*a, **kw):
        return [hit]

    monkeypatch.setattr(search, "hybrid_search", ok)
    res = await SearchLibraryTool().call({"query": "x"}, _atlas_ctx(Config()))
    assert len(res.content["hits"][0]["text"]) == 800
    assert len(hit.text) == 2000


async def test_search_library_tool_rejects_non_numeric_k(monkeypatch) -> None:
    _patch_store(monkeypatch)
    res = await SearchLibraryTool().call({"query": "x", "k": "lots"}, _atlas_ctx(Config()))
    assert res.is_error and "k must be" in res.error_message


async def test_search_library_tool_rejects_unknown_kind(monkeypatch) -> None:
    _patch_store(monkeypatch)
    res = await SearchLibraryTool().call({"query": "x", "kind": "poster"}, _atlas_ctx(Config()))
    assert res.is_error
    assert "kind must be one of" in res.error_message and "abstract" in res.error_message


async def test_search_library_tool_accepts_every_schema_kind(monkeypatch) -> None:
    from co_scientist.library import search

    _patch_store(monkeypatch)
    seen: list[str] = []

    async def hits(db, cfg, query, *, k, kind, session_id=None):
        seen.append(kind)
        return []

    monkeypatch.setattr(search, "hybrid_search", hits)
    from co_scientist.tools.builtins import library as tool_mod

    async def ready(db, names):
        return None

    monkeypatch.setattr(tool_mod, "_unready_index", ready)
    kinds = SearchLibraryTool.input_schema["properties"]["kind"]["enum"]
    for kind in kinds:
        await SearchLibraryTool().call({"query": "x", "kind": kind}, _atlas_ctx(Config()))
    assert seen == kinds


async def test_search_library_tool_passes_session_id(monkeypatch) -> None:
    from co_scientist.library import search

    _patch_store(monkeypatch)
    seen: list = []

    async def hits(db, cfg, query, *, k, kind, session_id):
        seen.append(session_id)
        return []

    monkeypatch.setattr(search, "hybrid_search", hits)
    from co_scientist.tools.builtins import library as tool_mod

    async def ready(db, names):
        return None

    monkeypatch.setattr(tool_mod, "_unready_index", ready)
    ctx = _atlas_ctx(Config())
    ctx.session_id = "S9"
    await SearchLibraryTool().call({"query": "x"}, ctx)
    assert seen == ["S9"]
