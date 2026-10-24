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
