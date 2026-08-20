"""Web console shell — offline assets, sidebar context, pipeline progress.

The asset test is the load-bearing one: the UI regressing to a CDN <script>
would make the console blank on a machine with no network, which is exactly
the setup this tool is meant for.
"""

from __future__ import annotations

import re
from pathlib import Path

from co_scientist.web.app import _env_row, _stages

WEB = Path(__file__).resolve().parents[2] / "web"


class FakeHyp:
    def __init__(self, state="draft", matches_played=0, parent_ids=None):
        self.state = state
        self.matches_played = matches_played
        self.parent_ids = parent_ids or []


class FakeSession:
    def __init__(self, status="running", final_overview=None):
        self.status = status
        self.final_overview = final_overview


# ------------------------------- offline assets ----------------------------- #


def test_templates_reference_no_remote_assets() -> None:
    remote = re.compile(r'(src|href)\s*=\s*["\']https?://', re.I)
    for path in (WEB / "templates").glob("*.html"):
        assert not remote.search(path.read_text(encoding="utf-8")), (
            f"{path.name} pulls a remote asset; the console must render offline"
        )


def test_static_assets_exist() -> None:
    assert (WEB / "static" / "app.css").is_file()
    assert (WEB / "static" / "app.js").is_file()


def test_base_template_links_local_assets() -> None:
    html = (WEB / "templates" / "base.html").read_text(encoding="utf-8")
    assert "/static/app.css" in html
    assert "/static/app.js" in html


# ---------------------------------- env row --------------------------------- #


def test_env_row_reports_backend_and_workspace_off(tmp_cfg) -> None:
    row = _env_row(tmp_cfg)
    assert row["workspace"] == "off"
    assert row["workspace_on"] is False
    assert row["model"] == tmp_cfg.models.generation


def test_env_row_shows_workspace_when_configured(tmp_cfg, tmp_path: Path) -> None:
    tmp_cfg.workspace.root = str(tmp_path)
    row = _env_row(tmp_cfg)
    assert row["workspace_on"] is True
    assert str(tmp_path) in row["workspace"]


def test_env_row_flags_cli_backend(tmp_cfg) -> None:
    tmp_cfg.llm.provider = "claude_cli"
    assert _env_row(tmp_cfg)["is_cli"] is True
    tmp_cfg.llm.provider = "openrouter"
    assert _env_row(tmp_cfg)["is_cli"] is False


# ---------------------------------- stages ---------------------------------- #


def test_stages_marks_first_unreached_as_active_while_running() -> None:
    steps = _stages(FakeSession(status="running"), [])
    assert steps[0]["label"] == "Generation"
    assert steps[0]["state"] == "active"
    # Only one active marker, so the rail can't show two "current" stages.
    assert [s["state"] for s in steps].count("active") == 1


def test_stages_no_active_marker_once_session_ends() -> None:
    steps = _stages(FakeSession(status="done", final_overview="x/overview.md"), [])
    assert "active" not in [s["state"] for s in steps]


def test_stages_tracks_pipeline_evidence() -> None:
    hyps = [
        FakeHyp(state="in_tournament", matches_played=12),
        FakeHyp(state="draft", parent_ids=["hyp_parent"]),
    ]
    steps = {s["label"]: s["state"] for s in _stages(FakeSession(), hyps)}
    assert steps["Generation"] == "done"
    assert steps["Reflection"] == "done"      # in_tournament implies reviewed
    assert steps["Ranking"] == "done"         # a match was played
    assert steps["Evolution"] == "done"       # a hypothesis has a parent
    assert steps["Meta-review"] != "done"     # no overview written yet


def test_stages_meta_review_needs_the_overview() -> None:
    session = FakeSession(status="done", final_overview="artifacts/s/final/overview.md")
    steps = {s["label"]: s["state"] for s in _stages(session, [FakeHyp()])}
    assert steps["Meta-review"] == "done"


def test_stages_always_returns_five_ordered_steps() -> None:
    steps = _stages(FakeSession(), [])
    assert [s["label"] for s in steps] == [
        "Generation", "Reflection", "Ranking", "Evolution", "Meta-review",
    ]
