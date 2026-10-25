"""Turn uploaded PDF and DOCX files into library passages scoped to their session."""

from __future__ import annotations

import asyncio
import io
import re
from typing import TYPE_CHECKING

from ..logging import get_logger
from ..models.attachment import AttachmentMeta
from ..storage.atlas import library as lib_store
from ..storage.repos import attachments, blobs
from .jats import PaperMeta, Passage, _split_text

if TYPE_CHECKING:
    from ..config import Config
    from ..storage.atlas.client import AtlasConn

log = get_logger(__name__)

UNREADABLE = "could not be read as a document"
_BLANK_LINES = re.compile(r"\n\s*\n")
_WS = re.compile(r"\s+")


def _pdf_blocks(data: bytes) -> list[tuple[str, str]]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise ValueError("encrypted PDF")
    blocks: list[tuple[str, str]] = []
    for n, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        blocks.extend((f"Page {n}", para) for para in _BLANK_LINES.split(text))
    return blocks


def _docx_blocks(data: bytes) -> list[tuple[str, str]]:
    from docx import Document

    section = "Document"
    blocks: list[tuple[str, str]] = []
    for para in Document(io.BytesIO(data)).paragraphs:
        style = para.style.name if para.style is not None and para.style.name else ""
        if style.startswith(("Heading", "Title")) and para.text.strip():
            section = _WS.sub(" ", para.text).strip()
        blocks.append((section, para.text))
    return blocks


def parse_document(
    filename: str, data: bytes, attachment_id: str, *, max_chars: int = 2000
) -> tuple[PaperMeta, list[Passage]]:
    """Split a PDF or DOCX into anchored paragraph passages.

    Raises `ValueError` for an unsupported, encrypted or corrupt file.
    """
    name = filename.lower()
    try:
        if name.endswith(".pdf"):
            blocks = _pdf_blocks(data)
        elif name.endswith(".docx"):
            blocks = _docx_blocks(data)
        else:
            raise ValueError("unsupported document type")
    except ValueError:
        raise
    except Exception as e:  # pypdf / python-docx / zipfile raise assorted types
        raise ValueError(UNREADABLE) from e
    pmcid = f"UPLOAD{attachment_id[-12:]}"
    passages: list[Passage] = []
    for section, raw in blocks:
        text = _WS.sub(" ", raw).strip()
        if not text:
            continue
        for chunk in _split_text(text, max_chars):
            n = len(passages)
            passages.append(
                Passage(
                    anchor_id=f"{pmcid}#p{n + 1}", pmcid=pmcid, kind="paragraph",
                    section=section, label=None, text=chunk, ordinal=n,
                )
            )
    return PaperMeta(pmcid=pmcid, title=filename, doi=None, year=None, journal=None), passages


async def ingest_attachment(conn: AtlasConn, cfg: Config, meta: AttachmentMeta) -> int:
    """Index one document attachment in the library, scoped to its session.

    Marks the attachment `ingested`, or `failed` with a fixed message (never the exception
    text). Returns the number of passages stored.
    """
    try:
        data = await blobs.get(conn, "attachments", meta.blob_id)
        parsed, passages = await asyncio.to_thread(
            parse_document, meta.filename, data, meta.id, max_chars=cfg.library.max_passage_chars
        )
        if not passages:
            raise ValueError("no text")
        embeddings = None
        if cfg.library.embedding == "client":
            from ..vectors.embedder import make_embedder

            vecs = await make_embedder(cfg).embed([p.text for p in passages])
            embeddings = [[float(x) for x in v] for v in vecs]
        n = await lib_store.upsert_passages(
            conn, parsed, passages, embeddings=embeddings, source="upload",
            session_id=meta.session_id, attachment_id=meta.id,
        )
    except Exception as e:
        log.warning("upload_ingest_failed", attachment_id=meta.id, error=type(e).__name__)
        await attachments.set_status(conn, meta.id, "failed", UNREADABLE)
        return 0
    await attachments.set_status(conn, meta.id, "ingested")
    return n
