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
    assert e.value.status_code in (400, 413)
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
    assert e.value.status_code in (400, 413)

    flood = _zip({f"f{i}.csv": b"1" for i in range(51)})
    with pytest.raises(IntakeError) as e:
        accept_uploads([("f.zip", flood, "")], AttachmentsCfg())
    assert e.value.status_code == 413
