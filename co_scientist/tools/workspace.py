"""Workspace file tools — read and write one folder on disk.

Registered only when `[workspace] root` is set. They are ordinary registry
tools, so they reach the agents by the same three paths everything else does:
the Anthropic/OpenAI tool loop under an API backend, and the bundled MCP
server under `claude_cli` / `codex_cli`. That also means every call lands in
`tools.jsonl` and the per-agent allowlist in `registry.AGENT_TOOLS` decides who
gets them.

Containment is the whole security story here. `resolve_in_root` resolves the
candidate path *and* the root, then checks ancestry on the resolved pair — so
`..`, an absolute path, and a symlink pointing outside all fail the same way.
Resolving before comparing is what makes the symlink case work; comparing the
unresolved strings would let `root/link-to-etc/passwd` through.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from ..config import Config
from .base import ToolCtx, ToolResult

# Read as text, but skip the obvious binaries rather than handing the model a
# screenful of replacement characters. PDFs are the exception worth decoding:
# a research folder is mostly papers, and pypdf is already a dependency.
_PDF_SUFFIXES = {".pdf"}
_SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".ico",
    ".zip", ".gz", ".bz2", ".xz", ".tar", ".7z", ".rar",
    ".so", ".dylib", ".dll", ".exe", ".bin", ".o", ".a",
    ".mp3", ".mp4", ".wav", ".mov", ".avi", ".mkv",
    ".pyc", ".pyo", ".faiss", ".npy", ".npz",
}


class WorkspaceError(Exception):
    """Path fell outside the workspace root, or the root is unusable."""


def workspace_root(cfg: Config) -> Path | None:
    """The configured root, resolved. None when the workspace is off."""
    raw = (cfg.workspace.root or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def resolve_in_root(root: Path, candidate: str, *, must_exist: bool) -> Path:
    """Resolve `candidate` relative to `root`, refusing anything outside it.

    `strict=False` so a not-yet-created file still resolves — its parents are
    resolved, which is what matters for the symlink check.
    """
    text = (candidate or "").strip()
    if not text:
        raise WorkspaceError("path is required")

    target = (root / text).resolve() if not Path(text).is_absolute() else Path(text).resolve()

    if target != root and root not in target.parents:
        raise WorkspaceError(
            f"path escapes the workspace root: {candidate!r} is not under {root}"
        )
    if must_exist and not target.exists():
        raise WorkspaceError(f"no such file: {candidate}")
    return target


def _rel(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:                                   # pragma: no cover
        return str(path)


class _WorkspaceTool:
    """Shared root resolution and error envelope."""

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg

    def _root(self) -> Path:
        root = workspace_root(self._cfg)
        if root is None:
            raise WorkspaceError("no workspace configured; set [workspace] root")
        if not root.is_dir():
            raise WorkspaceError(f"workspace root is not a directory: {root}")
        return root

    async def call(self, args: dict[str, Any], ctx: ToolCtx) -> ToolResult:
        t0 = time.monotonic()
        try:
            content = await asyncio.to_thread(self._run, self._root(), args)
        except WorkspaceError as e:
            return ToolResult(is_error=True, error_message=str(e))
        except OSError as e:
            return ToolResult(is_error=True, error_message=f"{type(e).__name__}: {e}")
        return ToolResult(
            content=content,
            duration_ms=int((time.monotonic() - t0) * 1000),
            result_bytes=len(str(content)),
        )

    def _run(self, root: Path, args: dict[str, Any]) -> Any:   # pragma: no cover
        raise NotImplementedError


class FileListTool(_WorkspaceTool):
    name = "file_list"
    description = (
        "List files in the research workspace folder. Returns {root, path, entries:[{path, "
        "kind, bytes}], truncated}. Paths are relative to the workspace root and are what "
        "file_read and file_write expect. Start here to see what source material you have."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Subdirectory relative to the workspace root. Omit for the root.",
            },
            "recursive": {
                "type": "boolean",
                "description": "Descend into subdirectories (default true).",
            },
            "glob": {
                "type": "string",
                "description": "Optional filename filter, e.g. '*.pdf' or '*.csv'.",
            },
        },
    }

    def _run(self, root: Path, args: dict[str, Any]) -> Any:
        base = resolve_in_root(root, args.get("path") or ".", must_exist=True)
        if not base.is_dir():
            raise WorkspaceError(f"not a directory: {args.get('path')}")

        recursive = args.get("recursive")
        recursive = True if recursive is None else bool(recursive)
        pattern = (args.get("glob") or "*").strip() or "*"
        limit = self._cfg.workspace.max_list_entries

        walker = base.rglob(pattern) if recursive else base.glob(pattern)
        entries: list[dict[str, Any]] = []
        truncated = False
        for p in sorted(walker):
            if p.name.startswith(".") or any(part.startswith(".") for part in p.parts):
                continue                       # dotfiles and .git/.venv noise
            if len(entries) >= limit:
                truncated = True
                break
            is_dir = p.is_dir()
            entries.append({
                "path": _rel(root, p),
                "kind": "dir" if is_dir else "file",
                "bytes": None if is_dir else p.stat().st_size,
            })
        return {
            "root": str(root),
            "path": _rel(root, base),
            "entries": entries,
            "truncated": truncated,
        }


class FileReadTool(_WorkspaceTool):
    name = "file_read"
    description = (
        "Read a text file (or extract text from a PDF) from the research workspace folder. "
        "Returns {path, text, chars, truncated}. Use file_list first to find paths. "
        "Cite what you read here by its path, the same way you would cite a URL."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to the workspace root.",
            },
            "max_chars": {
                "type": "integer",
                "minimum": 200,
                "maximum": 400_000,
                "description": "Truncate to this many characters (default from config).",
            },
        },
        "required": ["path"],
    }

    def _run(self, root: Path, args: dict[str, Any]) -> Any:
        target = resolve_in_root(root, args.get("path", ""), must_exist=True)
        if target.is_dir():
            raise WorkspaceError(f"{args['path']} is a directory; use file_list")

        suffix = target.suffix.lower()
        if suffix in _SKIP_SUFFIXES:
            raise WorkspaceError(f"binary file not readable as text: {suffix}")

        limit = int(args.get("max_chars") or self._cfg.workspace.max_read_chars)
        if suffix in _PDF_SUFFIXES:
            text = _extract_pdf(target)
        else:
            text = target.read_text(encoding="utf-8", errors="replace")

        truncated = len(text) > limit
        return {
            "path": _rel(root, target),
            "text": text[:limit],
            "chars": len(text),
            "truncated": truncated,
        }


class FileWriteTool(_WorkspaceTool):
    name = "file_write"
    description = (
        "Write a text file into the research workspace folder, creating parent directories "
        "as needed. Returns {path, bytes, mode}. Use for notes, extracted tables, analysis "
        "you want to keep, or a draft you want the next agent to build on."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path relative to the workspace root.",
            },
            "content": {"type": "string", "description": "Full text to write."},
            "mode": {
                "type": "string",
                "enum": ["overwrite", "append"],
                "description": "Default 'overwrite'.",
            },
        },
        "required": ["path", "content"],
    }

    def _run(self, root: Path, args: dict[str, Any]) -> Any:
        if not self._cfg.workspace.allow_write:
            raise WorkspaceError("workspace is read-only ([workspace] allow_write = false)")

        target = resolve_in_root(root, args.get("path", ""), must_exist=False)
        if target.is_dir():
            raise WorkspaceError(f"{args['path']} is a directory")

        content = args.get("content")
        if not isinstance(content, str):
            raise WorkspaceError("content must be a string")
        data = content.encode("utf-8")
        cap = self._cfg.workspace.max_write_bytes
        if len(data) > cap:
            raise WorkspaceError(f"content is {len(data)} bytes; cap is {cap}")

        mode = (args.get("mode") or "overwrite").strip().lower()
        if mode not in ("overwrite", "append"):
            raise WorkspaceError(f"unknown mode: {mode}")

        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a" if mode == "append" else "w", encoding="utf-8") as f:
            f.write(content)
        return {"path": _rel(root, target), "bytes": len(data), "mode": mode}


def _extract_pdf(path: Path) -> str:
    import pypdf

    reader = pypdf.PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


__all__ = [
    "FileListTool",
    "FileReadTool",
    "FileWriteTool",
    "WorkspaceError",
    "resolve_in_root",
    "workspace_root",
]
