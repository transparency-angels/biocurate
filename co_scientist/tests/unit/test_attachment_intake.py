import io
import struct
import zipfile

import pytest

from co_scientist.attachments.intake import IntakeError, accept_uploads
from co_scientist.config import AttachmentsCfg

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_accepts_plain_files_and_classifies_kind():
    cfg = AttachmentsCfg()
    res = accept_uploads(
        [
            ("a.CSV", b"x,y\n1,2\n", "application/octet-stream"),
            ("b.txt", b"hi", "x/y"),
            ("c.pdf", b"%PDF", ""),
            ("d.docx", b"PK", ""),
        ],
        cfg,
    )
    got = {f.filename: (f.kind, f.content_type) for f in res.files}
    assert got == {
        "a.CSV": ("tabular", "text/csv"),
        "b.txt": ("tabular", "text/plain"),
        "c.pdf": ("document", "application/pdf"),
        "d.docx": ("document", DOCX),
    }
    assert res.skipped == []


def test_rejects_too_many_and_too_large_and_bad_extension():
    cfg = AttachmentsCfg()
    with pytest.raises(IntakeError) as e:
        accept_uploads([(f"{i}.txt", b"x", "") for i in range(6)], cfg)
    assert e.value.status_code == 400
    with pytest.raises(IntakeError) as e:
        accept_uploads([("evil.exe", b"x", "")], cfg)
    assert e.value.status_code == 400
    assert "evil.exe" in str(e.value)
    cfg.max_file_mb = 1
    with pytest.raises(IntakeError) as e:
        accept_uploads([("big.txt", b"0" * (1024 * 1024 + 1), "")], cfg)
    assert e.value.status_code == 400
    with pytest.raises(IntakeError) as e:
        accept_uploads([("bad.zip", b"not a zip", "")], AttachmentsCfg())
    assert e.value.status_code == 400
    assert "could not be read as a zip archive" in str(e.value)


def test_unzip_flattens_paths_and_skips_junk():
    data = _zip(
        {
            "a/b/c.csv": b"1,2",
            "__MACOSX/x": b"junk",
            "a/.DS_Store": b"junk",
            "inner.zip": _zip({"z.csv": b"1"}),
            "notes.exe": b"x",
            "dir/": b"",
            "a/c.csv": b"3,4",
        }
    )
    res = accept_uploads([("up.zip", data, "")], AttachmentsCfg())
    assert [f.filename for f in res.files] == ["c.csv", "c (2).csv"]
    assert all(f.kind == "tabular" for f in res.files)
    assert any(s.startswith("inner.zip:") for s in res.skipped)
    assert any(s.startswith("notes.exe:") for s in res.skipped)
    assert not any("DS_Store" in f.filename for f in res.files)


def test_unzip_rejects_traversal_bomb_and_member_flood():
    res = accept_uploads([("t.zip", _zip({"../../etc/x.csv": b"1,2"}), "")], AttachmentsCfg())
    assert [f.filename for f in res.files] == ["x.csv"]

    cfg = AttachmentsCfg(max_unzipped_mb=1)
    bomb = _zip({"big.csv": b"\0" * (3 * 1024 * 1024)})
    with pytest.raises(IntakeError) as e:
        accept_uploads([("b.zip", bomb, "")], cfg)
    assert e.value.status_code == 413

    # declared size lies: small file_size recorded, large actual content
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("lie.csv", b"\0" * (3 * 1024 * 1024))
    raw = bytearray(buf.getvalue())
    # patch declared uncompressed size (local header + central dir) to 10
    for sig, off in ((b"PK\x03\x04", 22), (b"PK\x01\x02", 24)):
        i = raw.find(sig)
        raw[i + off : i + off + 4] = struct.pack("<I", 10)
    with pytest.raises(IntakeError) as e:
        accept_uploads([("l.zip", bytes(raw), "")], cfg)
    # zipfile stops at the declared size and then fails its CRC check, so a
    # lying header is rejected (never expanded past the limit) as unreadable.
    assert e.value.status_code == 400

    flood = _zip({f"f{i}.csv": b"1" for i in range(51)})
    with pytest.raises(IntakeError) as e:
        accept_uploads([("f.zip", flood, "")], AttachmentsCfg())
    assert e.value.status_code == 413


def _zip_with(name: str, data: bytes, comp: int) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", comp) as zf:
        zf.writestr(name, data)
    return buf.getvalue()


def _corrupt(raw: bytes, marker: bytes = b"PK\x03\x04") -> bytes:
    """Garble the compressed payload right after the first local header."""
    b = bytearray(raw)
    i = b.find(marker)
    n = struct.unpack("<H", b[i + 26 : i + 28])[0] + struct.unpack("<H", b[i + 28 : i + 30])[0]
    start = i + 30 + n
    for k in range(start, min(start + 40, len(b) - 100)):
        b[k] = 0xFF
    return bytes(b)


def test_encrypted_member_skipped_with_reason():
    raw = bytearray(_zip({"s.csv": b"1,2"}))
    for sig, off in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        i = raw.find(sig)
        raw[i + off] |= 0x1
    res = accept_uploads([("e.zip", bytes(raw), "")], AttachmentsCfg())
    assert res.files == []
    assert res.skipped == ["s.csv: encrypted"]


def test_corrupt_bzip2_lzma_and_eof_map_to_400():
    body = bytes(range(256)) * 400
    for comp in (zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA):
        res = accept_uploads([("z.zip", _zip_with("a.csv", body, comp), "")], AttachmentsCfg())
        assert res.files == [] and res.skipped == ["a.csv: unsupported compression"]
    stored = bytearray(_zip_with("a.csv", b"1,2,3", zipfile.ZIP_STORED))
    for sig, off in ((b"PK\x03\x04", 18), (b"PK\x01\x02", 20)):
        i = stored.find(sig)
        stored[i + off : i + off + 8] = struct.pack("<II", 2**30, 2**30)
    bad = [bytes(stored), _corrupt(_zip_with("a.csv", body, zipfile.ZIP_DEFLATED))]
    for raw in bad:
        with pytest.raises(IntakeError) as e:
            accept_uploads([("z.zip", raw, "")], AttachmentsCfg())
        assert e.value.status_code == 400
        assert "could not be read as a zip archive" in str(e.value)


def test_budget_is_per_request_across_zips_and_plain_files():
    cfg = AttachmentsCfg(max_unzipped_mb=1)
    blob = b"a" * (900 * 1024)
    with pytest.raises(IntakeError) as e:
        accept_uploads(
            [("a.zip", _zip({"a.csv": blob}), ""), ("b.zip", _zip({"b.csv": blob}), "")], cfg
        )
    assert e.value.status_code == 413
    with pytest.raises(IntakeError) as e:
        accept_uploads([("a.csv", blob, ""), ("b.zip", _zip({"b.csv": blob}), "")], cfg)
    assert e.value.status_code == 413


def test_member_cap_is_per_request():
    z = _zip({f"f{i}.csv": b"1" for i in range(30)})
    with pytest.raises(IntakeError) as e:
        accept_uploads([("a.zip", z, ""), ("b.zip", z, "")], AttachmentsCfg())
    assert e.value.status_code == 413


def test_central_directory_flood_is_413():
    flood = _zip({f"{i}.x": b"" for i in range(1001)})
    with pytest.raises(IntakeError) as e:
        accept_uploads([("f.zip", flood, "")], AttachmentsCfg())
    assert e.value.status_code == 413
    assert "too many entries" in str(e.value)


def test_skipped_list_is_capped():
    z = _zip({f"{i}.x": b"" for i in range(200)})
    res = accept_uploads([("f.zip", z, "")], AttachmentsCfg())
    assert len(res.skipped) == 51
    assert res.skipped[-1] == "...and 150 more"


def test_duplicate_names_across_request_get_suffixes():
    z = _zip({"c.csv": b"1"})
    res = accept_uploads(
        [("c.csv", b"0", ""), ("a.zip", z, ""), ("b.zip", z, ""), ("c.csv", b"2", "")],
        AttachmentsCfg(max_files=5),
    )
    assert [f.filename for f in res.files] == ["c.csv", "c (2).csv", "c (3).csv", "c (4).csv"]


def test_safe_name_strips_drive_letters_and_control_chars():
    res = accept_uploads(
        [("C:evil.csv", b"1", ""), ("a\x00b.csv", b"1", ""), ("..\\..\\w.txt", b"1", "")],
        AttachmentsCfg(),
    )
    assert [f.filename for f in res.files] == ["evil.csv", "ab.csv", "w.txt"]
    res = accept_uploads(
        [("m.zip", _zip({"C:x.csv": b"1", "dir/__MACOSX/y.csv": b"1", "..": b"1"}), "")],
        AttachmentsCfg(),
    )
    assert [f.filename for f in res.files] == ["x.csv"]
    with pytest.raises(IntakeError) as e:
        accept_uploads([(".hidden.csv", b"1", "")], AttachmentsCfg())
    assert e.value.status_code == 400
