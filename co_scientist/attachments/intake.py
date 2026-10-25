"""Validate researcher uploads and unzip archives safely (pure, no I/O)."""

from __future__ import annotations

import io
import re
import zipfile
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


_MAX_ENTRIES = 1000
_MAX_SKIPPED = 50
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_DRIVE = re.compile(r"^[A-Za-z]:")


def _ext(name: str) -> str:
    return PurePosixPath(name).suffix.lower()


def _safe_name(raw: str) -> str | None:
    """Reduce an untrusted name to a bare, safe filename, or None."""
    name = raw.replace("\\", "/").split("/")[-1]
    name = _DRIVE.sub("", name).replace(":", "")
    name = _CTRL.sub("", name).strip()
    if not name or name in (".", "..") or name.startswith("."):
        return None
    return name


def _make(name: str, data: bytes) -> IncomingFile:
    ctype, kind = _TYPES[_ext(name)]
    return IncomingFile(filename=name, data=data, content_type=ctype, kind=kind)


@dataclass
class _Request:
    """Per-request state: byte budget, member cap, used names, skip reasons."""

    cfg: AttachmentsCfg
    remaining: int
    members: int = 0
    seen: set[str] = field(default_factory=set)
    skipped: list[str] = field(default_factory=list)
    skipped_extra: int = 0

    def skip(self, name: str, reason: str) -> None:
        if len(self.skipped) < _MAX_SKIPPED:
            self.skipped.append(f"{name}: {reason}")
        else:
            self.skipped_extra += 1

    def charge(self, n: int, what: str) -> None:
        self.remaining -= n
        if self.remaining < 0:
            raise IntakeError(f"{what} pushes the upload past {self.cfg.max_unzipped_mb} MB", 413)

    def unique(self, name: str) -> str:
        final = name
        if final in self.seen:
            p = PurePosixPath(name)
            n = 2
            while f"{p.stem} ({n}){p.suffix}" in self.seen:
                n += 1
            final = f"{p.stem} ({n}){p.suffix}"
        self.seen.add(final)
        return final


def _read_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, zname: str, req: _Request) -> bytes:
    buf = bytearray()
    try:
        with zf.open(info) as fh:
            while chunk := fh.read(_MB):
                req.charge(len(chunk), zname)
                buf += chunk
    except IntakeError:
        raise
    except Exception as exc:  # corrupt data: BadZipFile, OSError, LZMAError, EOFError, ...
        raise IntakeError(f"{zname} could not be read as a zip archive", 400) from exc
    return bytes(buf)


def _unzip(zname: str, data: bytes, req: _Request, out: IntakeResult) -> None:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except Exception as exc:
        raise IntakeError(f"{zname} could not be read as a zip archive", 400) from exc
    with zf:
        infos = zf.infolist()
        if len(infos) > _MAX_ENTRIES:
            raise IntakeError(f"{zname} has too many entries", 413)
        for info in infos:
            if info.is_dir():
                continue
            norm = info.filename.replace("\\", "/")
            if "__MACOSX" in norm.split("/"):
                continue
            name = _safe_name(norm)
            if name is None:
                if norm.rstrip("/").split("/")[-1]:
                    req.skip(norm.split("/")[-1], "unsafe or hidden file name")
                continue
            ext = _ext(name)
            if ext == ".zip":
                req.skip(name, "nested zip files are not supported")
            elif ext not in _TYPES:
                req.skip(name, "unsupported file type")
            elif info.flag_bits & 0x1:
                req.skip(name, "encrypted")
            elif info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                req.skip(name, "unsupported compression")
            else:
                req.members += 1
                if req.members > req.cfg.max_zip_members:
                    raise IntakeError(
                        f"{zname} exceeds {req.cfg.max_zip_members} files in total", 413
                    )
                body = _read_member(zf, info, zname, req)
                out.files.append(_make(req.unique(name), body))


def accept_uploads(uploads: list[tuple[str, bytes, str]], cfg: AttachmentsCfg) -> IntakeResult:
    """Validate uploads (name, bytes, client content-type) and expand zips."""
    if len(uploads) > cfg.max_files:
        raise IntakeError(f"at most {cfg.max_files} files may be attached", 400)
    out = IntakeResult()
    req = _Request(cfg=cfg, remaining=cfg.max_unzipped_mb * _MB)
    for raw_name, data, _client_type in uploads:
        name = _safe_name(raw_name)
        if name is None:
            raise IntakeError("an upload has an invalid file name", 400)
        if len(data) > cfg.max_file_mb * _MB:
            raise IntakeError(f"{name} is larger than {cfg.max_file_mb} MB", 400)
        ext = _ext(name)
        if ext == ".zip":
            _unzip(name, data, req, out)
        elif ext in _TYPES:
            req.charge(len(data), name)
            out.files.append(_make(req.unique(name), data))
        else:
            raise IntakeError(f"{name}: unsupported file type", 400)
    out.skipped = req.skipped
    if req.skipped_extra:
        out.skipped.append(f"...and {req.skipped_extra} more")
    return out
