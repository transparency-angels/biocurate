"""Config loading."""

from __future__ import annotations


def test_load_config_records_overlay_path(tmp_path) -> None:
    from co_scientist.config import load_config

    overlay = tmp_path / "o.toml"
    overlay.write_text('[storage]\nbackend = "atlas"\n')
    cfg = load_config(overlay)
    assert cfg._overlay_path == overlay.resolve()
    assert "_overlay_path" not in str(cfg.model_dump())
    assert load_config()._overlay_path is None


def test_attachments_cfg_defaults() -> None:
    from co_scientist.config import Config, load_config

    for cfg in (Config(), load_config()):
        a = cfg.attachments
        assert (a.max_files, a.max_file_mb, a.max_unzipped_mb) == (5, 25, 512)
        assert (a.max_zip_members, a.max_session_mb, a.max_total_mb) == (50, 125, 2048)
