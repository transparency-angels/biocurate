"""Workspace file tools — registration, containment, and read/write behaviour.

The containment tests are the important ones: a path in a tool call can come
from a source document the agent just read, so `..`, an absolute path and a
symlink out of the root all have to fail rather than resolve.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from co_scientist.tools.base import ToolCtx
from co_scientist.tools.registry import ToolRegistry
from co_scientist.tools.workspace import (
    FileListTool,
    FileReadTool,
    FileWriteTool,
    WorkspaceError,
    resolve_in_root,
    workspace_root,
)


@pytest.fixture
def ws(tmp_cfg, tmp_path: Path) -> Path:
    root = tmp_path / "research"
    (root / "papers").mkdir(parents=True)
    (root / "notes.md").write_text("# prior notes\nIL-10 knockouts.\n", encoding="utf-8")
    (root / "papers" / "trial.txt").write_text("randomised, n=240", encoding="utf-8")
    tmp_cfg.workspace.root = str(root)
    return root


def ctx_for(cfg) -> ToolCtx:
    return ToolCtx(cfg=cfg)


# ------------------------------- registration ------------------------------ #


def test_workspace_tools_absent_by_default(tmp_cfg) -> None:
    """No root configured means no file tools, so agents never see a folder
    that isn't there."""
    names = {t.name for t in ToolRegistry(tmp_cfg).discover().all()}
    assert not {"file_list", "file_read", "file_write"} & names


def test_workspace_tools_registered_when_root_set(tmp_cfg, ws) -> None:
    names = {t.name for t in ToolRegistry(tmp_cfg).discover().all()}
    assert {"file_list", "file_read", "file_write"} <= names


def test_read_only_workspace_omits_writer(tmp_cfg, ws) -> None:
    tmp_cfg.workspace.allow_write = False
    names = {t.name for t in ToolRegistry(tmp_cfg).discover().all()}
    assert {"file_list", "file_read"} <= names
    assert "file_write" not in names


def test_allowlist_gives_file_tools_to_research_agents(tmp_cfg, ws) -> None:
    reg = ToolRegistry(tmp_cfg).discover()
    for agent in ("generation", "reflection", "evolution"):
        assert {"file_list", "file_read", "file_write"} <= {
            t.name for t in reg.tools_for(agent)
        }
    # Ranking debates and Proximity stay tool-free.
    for agent in ("ranking", "proximity"):
        assert reg.tools_for(agent) == []


def test_workspace_root_expands_user(tmp_cfg) -> None:
    tmp_cfg.workspace.root = "~/somewhere"
    root = workspace_root(tmp_cfg)
    assert root is not None and "~" not in str(root)


# -------------------------------- containment ------------------------------ #


def test_parent_traversal_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(WorkspaceError, match="escapes"):
        resolve_in_root(root, "../secrets.txt", must_exist=False)


def test_absolute_path_outside_root_rejected(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(WorkspaceError, match="escapes"):
        resolve_in_root(root, "/etc/passwd", must_exist=False)


def test_symlink_escaping_root_rejected(tmp_path: Path) -> None:
    """Resolving before the ancestry check is what catches this — comparing
    the unresolved strings would let root/link/... through."""
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("x", encoding="utf-8")
    (root / "link").symlink_to(outside)

    with pytest.raises(WorkspaceError, match="escapes"):
        resolve_in_root(root, "link/secret.txt", must_exist=False)


def test_absolute_path_inside_root_allowed(tmp_path: Path) -> None:
    root = (tmp_path / "root").resolve()
    root.mkdir()
    (root / "a.txt").write_text("hi", encoding="utf-8")
    assert resolve_in_root(root, str(root / "a.txt"), must_exist=True).name == "a.txt"


async def test_read_outside_root_is_an_error_not_a_crash(tmp_cfg, ws) -> None:
    result = await FileReadTool(tmp_cfg).call({"path": "../../etc/passwd"}, ctx_for(tmp_cfg))
    assert result.is_error
    assert "escapes" in (result.error_message or "")


# ----------------------------------- read ---------------------------------- #


async def test_file_list_returns_relative_paths(tmp_cfg, ws) -> None:
    result = await FileListTool(tmp_cfg).call({}, ctx_for(tmp_cfg))
    assert not result.is_error
    paths = {e["path"] for e in result.content["entries"]}
    assert {"notes.md", "papers", "papers/trial.txt"} <= paths


async def test_file_list_glob_filter(tmp_cfg, ws) -> None:
    result = await FileListTool(tmp_cfg).call({"glob": "*.md"}, ctx_for(tmp_cfg))
    assert {e["path"] for e in result.content["entries"]} == {"notes.md"}


async def test_file_list_non_recursive(tmp_cfg, ws) -> None:
    result = await FileListTool(tmp_cfg).call({"recursive": False}, ctx_for(tmp_cfg))
    paths = {e["path"] for e in result.content["entries"]}
    assert "notes.md" in paths
    assert "papers/trial.txt" not in paths


async def test_file_list_truncates_at_cap(tmp_cfg, ws) -> None:
    for i in range(10):
        (ws / f"f{i}.txt").write_text("x", encoding="utf-8")
    tmp_cfg.workspace.max_list_entries = 5
    result = await FileListTool(tmp_cfg).call({}, ctx_for(tmp_cfg))
    assert result.content["truncated"] is True
    assert len(result.content["entries"]) == 5


async def test_file_read_returns_text(tmp_cfg, ws) -> None:
    result = await FileReadTool(tmp_cfg).call({"path": "notes.md"}, ctx_for(tmp_cfg))
    assert not result.is_error
    assert "IL-10 knockouts" in result.content["text"]
    assert result.content["truncated"] is False


async def test_file_read_truncates(tmp_cfg, ws) -> None:
    (ws / "big.txt").write_text("y" * 5000, encoding="utf-8")
    result = await FileReadTool(tmp_cfg).call(
        {"path": "big.txt", "max_chars": 200}, ctx_for(tmp_cfg)
    )
    assert result.content["chars"] == 5000
    assert len(result.content["text"]) == 200
    assert result.content["truncated"] is True


async def test_file_read_rejects_binary(tmp_cfg, ws) -> None:
    (ws / "figure.png").write_bytes(b"\x89PNG\r\n")
    result = await FileReadTool(tmp_cfg).call({"path": "figure.png"}, ctx_for(tmp_cfg))
    assert result.is_error
    assert "binary" in (result.error_message or "")


async def test_file_read_missing_file(tmp_cfg, ws) -> None:
    result = await FileReadTool(tmp_cfg).call({"path": "nope.txt"}, ctx_for(tmp_cfg))
    assert result.is_error
    assert "no such file" in (result.error_message or "")


async def test_file_read_on_directory_points_at_file_list(tmp_cfg, ws) -> None:
    result = await FileReadTool(tmp_cfg).call({"path": "papers"}, ctx_for(tmp_cfg))
    assert result.is_error
    assert "file_list" in (result.error_message or "")


# ----------------------------------- write --------------------------------- #


async def test_file_write_creates_parents(tmp_cfg, ws) -> None:
    result = await FileWriteTool(tmp_cfg).call(
        {"path": "out/analysis/summary.md", "content": "# findings\n"}, ctx_for(tmp_cfg)
    )
    assert not result.is_error
    assert (ws / "out" / "analysis" / "summary.md").read_text() == "# findings\n"


async def test_file_write_append(tmp_cfg, ws) -> None:
    tool = FileWriteTool(tmp_cfg)
    await tool.call({"path": "log.md", "content": "one\n"}, ctx_for(tmp_cfg))
    await tool.call(
        {"path": "log.md", "content": "two\n", "mode": "append"}, ctx_for(tmp_cfg)
    )
    assert (ws / "log.md").read_text() == "one\ntwo\n"


async def test_file_write_overwrites(tmp_cfg, ws) -> None:
    tool = FileWriteTool(tmp_cfg)
    await tool.call({"path": "log.md", "content": "one\n"}, ctx_for(tmp_cfg))
    await tool.call({"path": "log.md", "content": "two\n"}, ctx_for(tmp_cfg))
    assert (ws / "log.md").read_text() == "two\n"


async def test_file_write_outside_root_rejected(tmp_cfg, ws) -> None:
    result = await FileWriteTool(tmp_cfg).call(
        {"path": "../escaped.txt", "content": "x"}, ctx_for(tmp_cfg)
    )
    assert result.is_error
    assert not (ws.parent / "escaped.txt").exists()


async def test_file_write_blocked_when_read_only(tmp_cfg, ws) -> None:
    tmp_cfg.workspace.allow_write = False
    result = await FileWriteTool(tmp_cfg).call(
        {"path": "x.md", "content": "x"}, ctx_for(tmp_cfg)
    )
    assert result.is_error
    assert "read-only" in (result.error_message or "")


async def test_file_write_respects_size_cap(tmp_cfg, ws) -> None:
    tmp_cfg.workspace.max_write_bytes = 10
    result = await FileWriteTool(tmp_cfg).call(
        {"path": "x.md", "content": "z" * 100}, ctx_for(tmp_cfg)
    )
    assert result.is_error
    assert "cap is 10" in (result.error_message or "")


async def test_tools_error_cleanly_when_root_missing(tmp_cfg, tmp_path: Path) -> None:
    tmp_cfg.workspace.root = str(tmp_path / "does-not-exist")
    result = await FileListTool(tmp_cfg).call({}, ctx_for(tmp_cfg))
    assert result.is_error
    assert "not a directory" in (result.error_message or "")
