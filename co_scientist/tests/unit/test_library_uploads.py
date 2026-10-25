"""Offline tests for parsing uploaded documents into library passages."""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
)

from co_scientist.config import Config
from co_scientist.library import uploads
from co_scientist.models.attachment import AttachmentMeta
from co_scientist.storage.atlas import library as lib_store

AID = "01HZXABCDEFGHJKMNPQRSTVWXY"


def _pdf(pages: list[str]) -> bytes:
    w = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = w._add_object(font)
    for text in pages:
        page = w.add_blank_page(width=612, height=792)
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 700 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = w._add_object(stream)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})}
        )
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _docx(paras: list[str]) -> bytes:
    d = Document()
    for p in paras:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_parse_pdf_and_docx_into_anchored_passages() -> None:
    meta, ps = uploads.parse_document("trial.pdf", _pdf(["Alpha kinase result", "Beta"]), AID)
    assert meta.pmcid == f"UPLOAD{AID[-12:]}" and meta.title == "trial.pdf"
    assert [p.anchor_id for p in ps] == [f"UPLOAD{AID[-12:]}#p1", f"UPLOAD{AID[-12:]}#p2"]
    assert all(p.kind == "paragraph" and p.pmcid == meta.pmcid for p in ps)
    assert "Alpha kinase" in ps[0].text and [p.ordinal for p in ps] == [0, 1]

    meta, ps = uploads.parse_document("notes.docx", _docx(["One.", "", "Two."]), AID)
    assert [p.text for p in ps] == ["One.", "Two."]
    assert ps[1].anchor_id.endswith("#p2")


def test_parse_splits_long_paragraphs() -> None:
    _, ps = uploads.parse_document("n.docx", _docx(["word " * 100]), AID, max_chars=120)
    assert len(ps) > 1 and all(len(p.text) <= 120 for p in ps)
    assert [p.anchor_id.rsplit("#p", 1)[1] for p in ps] == [str(i + 1) for i in range(len(ps))]


def test_parse_rejects_unreadable_and_unknown() -> None:
    with pytest.raises(ValueError):
        uploads.parse_document("x.pdf", b"not a pdf", AID)
    with pytest.raises(ValueError):
        uploads.parse_document("x.docx", b"not a docx", AID)
    with pytest.raises(ValueError):
        uploads.parse_document("x.txt", b"hello", AID)


def test_passage_url_for_uploads() -> None:
    url = lib_store.passage_url("UPLOADx", "UPLOADx#p3", attachment_id=AID)
    assert url == f"upload://{AID}#p3"
    assert lib_store.passage_url("PMC1", "PMC1#F2~2") == "https://europepmc.org/article/PMC/PMC1#F2"


def _meta(filename: str) -> AttachmentMeta:
    return AttachmentMeta(
        id=AID, session_id="S1", filename=filename, content_type="", size=1, sha256="h",
        kind="document", status="stored", blob_id="b1", uploaded_at=datetime.now(UTC),
    )


@pytest.fixture
def fakes(monkeypatch):
    calls: dict = {"status": [], "upsert": []}

    async def get(conn, bucket, blob_id):
        return calls["data"]

    async def set_status(conn, aid, status, error=None):
        calls["status"].append((aid, status, error))

    async def upsert(conn, meta, passages, **kw):
        calls["upsert"].append((meta, passages, kw))
        return len(passages)

    monkeypatch.setattr(uploads.blobs, "get", get)
    monkeypatch.setattr(uploads.attachments, "set_status", set_status)
    monkeypatch.setattr(uploads.lib_store, "upsert_passages", upsert)
    return calls


async def test_ingest_attachment_stores_scoped_passages(fakes) -> None:
    fakes["data"] = _docx(["Hello there.", "General Kenobi."])
    n = await uploads.ingest_attachment(object(), Config(), _meta("a.docx"))
    assert n == 2
    _, passages, kw = fakes["upsert"][0]
    assert len(passages) == 2
    assert kw["source"] == "upload" and kw["session_id"] == "S1" and kw["attachment_id"] == AID
    assert fakes["status"] == [(AID, "ingested", None)]


async def test_ingest_attachment_failure_uses_fixed_message(fakes) -> None:
    fakes["data"] = b"%PDF-1.4 secret-internal-detail garbage"
    n = await uploads.ingest_attachment(object(), Config(), _meta("a.pdf"))
    assert n == 0 and not fakes["upsert"]
    assert fakes["status"] == [(AID, "failed", "could not be read as a document")]


async def test_ingest_attachment_encrypted_pdf_fails(fakes) -> None:
    w = PdfWriter()
    w.add_blank_page(width=10, height=10)
    w.encrypt("pw")
    buf = io.BytesIO()
    w.write(buf)
    fakes["data"] = buf.getvalue()
    assert await uploads.ingest_attachment(object(), Config(), _meta("a.pdf")) == 0
    assert fakes["status"][0][1:] == ("failed", "could not be read as a document")


def test_anchor_prefix_distinct_for_ids_minted_back_to_back() -> None:
    from co_scientist import ids

    metas = [uploads.parse_document("a.docx", _docx(["x"]), ids.attachment_id())[0]
             for _ in range(50)]
    assert len({m.pmcid for m in metas}) == 50
