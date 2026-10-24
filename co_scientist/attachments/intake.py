"""Validate researcher uploads and unzip archives safely (pure, no I/O)."""

from __future__ import annotations

import io
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Literal

from co_scientist.config import AttachmentsCfg

_MB = 1024 * 1024

_TYPES: dict[str, tuple[str, Literal["tabular", "document"]]] = {
    ".pdf": ("application/pdf", "document"),
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "document",
    ),
    ".txt": ("text/plain", "tabular"),
    ".csv": ("text/csv", "tabular"),
}


class IntakeError(ValueError):
    """Upload rejected. `status_code` is 400 (bad request) or 413 (too large)."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class IncomingFile:
    filename: str
    data: bytes
    content_type: str
    kind: Literal["tabular", "document"]


@dataclass
class IntakeResult:
    files: list[IncomingFile] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _ext(name: str) -> str:
    return PurePosixPath(name).suffix.lower()


def _make(name: str, data: bytes) -> IncomingFile:
    ctype, kind = _TYPES[_ext(name)]
    return IncomingFile(filename=name, data=data, content_type=ctype, kind=kind)


def _dedupe(name: str, seen: set[str]) -> str:
    if name not in seen:
        return name
    p = PurePosixPath(name)
    n = 2
    while f"{p.stem} ({n}){p.suffix}" in seen:
        n += 1
    return f"{p.stem} ({n}){p.suffix}"


def _unzip(zname: str, data: bytes, cfg: AttachmentsCfg, out: IntakeResult) -> None:
    limit = cfg.max_unzipped_mb * _MB
    total = 0
    accepted = 0
    seen: set[str] = set()
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError, NotImplementedError) as exc:
        raise IntakeError(f"{zname} could not be read as a zip archive", 400) from exc
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = PurePosixPath(info.filename.replace("\\", "/")).name
            if not name or name.startswith(".") or info.filename.startswith("__MACOSX"):
                continue
            ext = _ext(name)
            if ext == ".zip":
                out.skipped.append(f"{name}: nested zip files are not supported")
                continue
            if ext not in _TYPES:
                out.skipped.append(f"{name}: unsupported file type")
                continue
            if info.flag_bits & 0x1:
                out.skipped.append(f"{name}: encrypted")
                continue
            accepted += 1
            if accepted > cfg.max_zip_members:
                raise IntakeError(f"{zname} holds more than {cfg.max_zip_members} files", 413)
            chunks: list[bytes] = []
            try:
                with zf.open(info) as fh:
                    while chunk := fh.read(_MB):
                        total += len(chunk)
                        if total > limit:
                            raise IntakeError(f"{zname} expands past {cfg.max_unzipped_mb} MB", 413)
                        chunks.append(chunk)
            except (zipfile.BadZipFile, zlib.error, RuntimeError, NotImplementedError) as exc:
                raise IntakeError(f"{zname} could not be read as a zip archive", 400) from exc
            final = _dedupe(name, seen)
            seen.add(final)
            out.files.append(_make(final, b"".join(chunks)))


def accept_uploads(uploads: list[tuple[str, bytes, str]], cfg: AttachmentsCfg) -> IntakeResult:
    """Validate uploads (name, bytes, client content-type) and expand zips."""
    if len(uploads) > cfg.max_files:
        raise IntakeError(f"at most {cfg.max_files} files may be attached", 400)
    out = IntakeResult()
    for raw_name, data, _client_type in uploads:
        name = PurePosixPath(raw_name.replace("\\", "/")).name
        if len(data) > cfg.max_file_mb * _MB:
            raise IntakeError(f"{name} is larger than {cfg.max_file_mb} MB", 400)
        ext = _ext(name)
        if ext == ".zip":
            _unzip(name, data, cfg, out)
        elif ext in _TYPES:
            out.files.append(_make(name, data))
        else:
            raise IntakeError(f"{name}: unsupported file type", 400)
    return out
