"""Offline tests for the Atlas connection layer. No network, no real cluster."""

from __future__ import annotations

import asyncio

import pytest
from pymongo import AsyncMongoClient
from pymongo.errors import CollectionInvalid, OperationFailure

from co_scientist.config import Config, Secrets, StorageCfg
from co_scientist.storage.atlas import client as client_mod
from co_scientist.storage.atlas import indexes as idx
from co_scientist.storage.atlas.client import (
    AtlasConn,
    connect_atlas,
    shutdown_clients,
)
from co_scientist.tests.atlas.conftest import drop_prefixed

URI = "mongodb://user:s3cret@localhost:1/"


def _atlas_cfg(uri: str = URI) -> Config:
    return Config(
        storage=StorageCfg(backend="atlas", atlas_db="dbx", atlas_prefix="t1_"),
        secrets=Secrets(MONGODB_URI=uri),
    )


def test_backend_defaults_to_sqlite():
    assert Config().storage.backend == "sqlite"
    assert Config().storage.atlas_db == "biocurate"
    assert Config().storage.atlas_prefix == ""


def test_library_defaults():
    lib = Config().library
    assert (lib.embedding, lib.embed_model, lib.rerank_model) == ("auto", "voyage-4", "rerank-2.5")
    assert (lib.search_index, lib.vector_index, lib.max_passage_chars) == (
        "library_text",
        "library_vec",
        2000,
    )


async def test_connect_atlas_requires_uri():
    with pytest.raises(RuntimeError, match="MONGODB_URI not set") as ei:
        await connect_atlas(_atlas_cfg(""))
    assert "mongodb" not in str(ei.value).replace("MONGODB_URI", "")


def test_atlas_conn_repr_hides_uri():
    c = AsyncMongoClient(URI, connect=False)
    conn = AtlasConn(client=c, db=c["dbx"], prefix="t1_")
    r = repr(conn)
    assert "s3cret" not in r and "localhost" not in r
    assert "dbx" in r and "t1_" in r


def test_coll_applies_prefix():
    c = AsyncMongoClient("mongodb://localhost", connect=False)
    conn = AtlasConn(client=c, db=c["dbx"], prefix="t1_")
    assert conn.coll("tasks").name == "t1_tasks"


async def test_client_cached_per_uri_and_loop_and_close_is_noop():
    a = await connect_atlas(_atlas_cfg())
    b = await connect_atlas(_atlas_cfg())
    assert a.client is b.client
    await a.close()  # shared client: must stay usable
    c = await connect_atlas(_atlas_cfg())
    assert c.client is a.client
    other = await connect_atlas(_atlas_cfg("mongodb://localhost:2/"))
    assert other.client is not a.client
    await shutdown_clients()
    assert client_mod._clients == {}
    d = await connect_atlas(_atlas_cfg())
    assert d.client is not a.client
    await shutdown_clients()


# --- teardown safety ---------------------------------------------------------


class _FakeDB:
    def __init__(self, names):
        self.names = list(names)
        self.dropped: list[str] = []

    async def list_collection_names(self):
        return list(self.names)

    async def drop_collection(self, name):
        self.dropped.append(name)


@pytest.mark.parametrize("bad", ["", "hypotheses", "t_"])
async def test_drop_prefixed_refuses_unsafe_prefix(bad):
    db = _FakeDB(["hypotheses", "t_x"])
    with pytest.raises(ValueError):
        await drop_prefixed(db, bad)
    assert db.dropped == []


async def test_drop_prefixed_only_drops_prefixed():
    p = "t01abcdefghij_"
    db = _FakeDB([p + "tasks", p + "library", "tasks", "t01abcdefghijX", "other_" + p])
    await drop_prefixed(db, p)
    assert sorted(db.dropped) == [p + "library", p + "tasks"]


# --- index bootstrap ---------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self):
        return self.rows


class _FakeColl:
    def __init__(self, name, existing=()):
        self.name = name
        self.existing = list(existing)
        self.created: list = []
        self.btree: list = []

    async def create_indexes(self, models):
        self.btree.extend(models)

    async def list_search_indexes(self, name=None):
        return _FakeCursor([{"name": n} for n in self.existing if name in (None, n)])

    async def create_search_index(self, model):
        self.created.append(model)


class _FakeConn:
    def __init__(self, existing=None):
        self.colls: dict[str, _FakeColl] = {}
        self.existing = existing or {}

    def coll(self, name):
        return self.colls.setdefault(name, _FakeColl(name, self.existing.get(name, ())))

    async def ensure_collection(self, name):  # mirrors AtlasConn
        return None


async def test_ensure_indexes_creates_only_missing_search_specs(monkeypatch):
    specs = [
        idx.SearchIndexSpec(
            "library", "have", "search", lambda cfg: {"mappings": {"dynamic": True}}
        ),
        idx.SearchIndexSpec(
            "library", "need", "vectorSearch", lambda cfg: {"fields": [{"type": "vector"}]}
        ),
    ]
    monkeypatch.setattr(idx, "SEARCH_INDEX_SPECS", specs)
    conn = _FakeConn(existing={"library": ["have"]})
    await idx.ensure_indexes(conn, Config())
    created = conn.colls["library"].created
    assert [m.document["name"] for m in created] == ["need"]
    assert created[0].document["type"] == "vectorSearch"
    # idempotent
    conn2 = _FakeConn(existing={"library": ["have", "need"]})
    await idx.ensure_indexes(conn2, Config())
    assert conn2.colls["library"].created == []


async def test_ensure_indexes_registers_btree_set():
    conn = _FakeConn()
    await idx.ensure_indexes(conn, Config())
    tasks = conn.colls["tasks"].btree
    idem = [m.document for m in tasks if m.document["key"].get("idempotency_key")]
    assert idem and idem[0]["unique"] is True
    assert idem[0]["partialFilterExpression"] == {"idempotency_key": {"$type": "string"}}
    assert "library" in conn.colls
    assert idx.SEARCH_INDEX_SPECS == []  # Tasks 7 and 9 register theirs


async def test_wait_for_search_index_times_out_false():
    coll = _FakeColl("c", existing=["x"])  # rows carry no queryable flag
    assert await idx.wait_for_search_index(coll, "x", timeout_s=0.05, poll_s=0.01) is False


async def test_wait_for_search_index_true_when_queryable():
    coll = _FakeColl("c")

    async def lsi(name=None):
        return _FakeCursor([{"name": name, "queryable": True}])

    coll.list_search_indexes = lsi
    assert await idx.wait_for_search_index(coll, "x", timeout_s=1, poll_s=0.01) is True


def test_client_cache_never_returns_client_from_closed_loop():
    seen: list = []

    async def one():
        before = set(map(id, (e[1] for e in client_mod._clients.values())))
        conn = await connect_atlas(_atlas_cfg())
        # created during this run, not left over from a dead loop
        assert id(conn.client) not in before
        assert len(client_mod._clients) == 1
        loop, cached = client_mod._clients[URI]
        assert loop is asyncio.get_running_loop() and cached is conn.client
        seen.append(conn.client)

    for _ in range(8):
        asyncio.run(one())
    assert len({id(c) for c in seen}) == 8  # holds refs, so ids cannot be reused


class _RacyDB:
    def __init__(self, exc):
        self.exc = exc

    name = "d"

    async def list_collection_names(self):
        return []

    async def create_collection(self, name):
        raise self.exc


@pytest.mark.parametrize(
    "exc", [CollectionInvalid("collection t_x already exists"), OperationFailure("x", code=48)]
)
async def test_ensure_collection_tolerates_lost_race(exc):
    c = AsyncMongoClient("mongodb://localhost", connect=False)
    conn = AtlasConn(client=c, db=_RacyDB(exc), prefix="t_")
    await conn.ensure_collection("x")


async def test_ensure_collection_reraises_other_errors():
    c = AsyncMongoClient("mongodb://localhost", connect=False)
    conn = AtlasConn(client=c, db=_RacyDB(OperationFailure("boom", code=13)), prefix="t_")
    with pytest.raises(OperationFailure):
        await conn.ensure_collection("x")
