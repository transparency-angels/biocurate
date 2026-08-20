"""Tests for the shipped Agent Plugin in `plugin/`.

Two things can rot here without anyone noticing: the plugin can drift out of
spec so clients silently refuse to load it, and a skill can reference an MCP
tool that no longer exists so the agent follows an instruction into a dead end.
Both are cheap to check and expensive to discover in the field.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from co_scientist.mcp.session_server import TOOL_SCHEMAS

sys_path_root = Path(__file__).resolve().parents[3]
PLUGIN_DIR = sys_path_root / "plugin"

TOOL_REF_RE = re.compile(r"`?co-scientist:([a-z_]+)`?")
# Only pick up commands written as code. Prose says "the AI co-scientist
# research session", which is not a CLI invocation.
CLI_REF_RE = re.compile(r"co-scientist ([a-z][a-z-]*)")
CODE_SPAN_RE = re.compile(r"`([^`]+)`")
CODE_BLOCK_RE = re.compile(r"```[a-z]*\n(.*?)```", re.DOTALL)


def _code_only(text: str) -> str:
    """Everything inside inline code spans and fenced blocks, prose dropped.

    Fenced blocks are pulled out first: leaving their backtick fences in place
    throws off the pairing of every inline span after them.
    """
    blocks = CODE_BLOCK_RE.findall(text)
    return "\n".join(blocks + CODE_SPAN_RE.findall(CODE_BLOCK_RE.sub("", text)))


def _validator():
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "validate_plugin", sys_path_root / "scripts" / "validate_plugin.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Registered before exec so the module's dataclasses can resolve their own
    # string annotations under `from __future__ import annotations`.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _skill_files() -> list[Path]:
    return sorted(PLUGIN_DIR.glob("skills/*/SKILL.md"))


# --------------------------------------------------------------------------- #
# spec conformance


def test_the_shipped_plugin_conforms() -> None:
    report = _validator().validate(PLUGIN_DIR)
    assert report.errors == []


def test_the_manifest_declares_the_spec_version() -> None:
    manifest = json.loads((PLUGIN_DIR / "plugin.json").read_text())
    assert manifest["$schema"].endswith("/1.0.0/plugin.schema.json")
    assert manifest["name"] == "co-scientist"


def test_the_mcp_server_launches_the_session_server() -> None:
    mcp = json.loads((PLUGIN_DIR / "mcp.json").read_text())
    server = mcp["mcpServers"]["co-scientist"]
    assert server["type"] == "stdio"
    assert server["command"] == "co-scientist"
    assert server["args"] == ["mcp-server"]


def test_there_is_at_least_one_skill() -> None:
    assert len(_skill_files()) >= 5


# --------------------------------------------------------------------------- #
# skills against the real tool surface


@pytest.mark.parametrize("skill_md", _skill_files(), ids=lambda p: p.parent.name)
def test_skill_only_references_tools_that_exist(skill_md: Path) -> None:
    referenced = set(TOOL_REF_RE.findall(skill_md.read_text(encoding="utf-8")))
    unknown = referenced - set(TOOL_SCHEMAS)
    assert not unknown, (
        f"{skill_md.parent.name} references MCP tools that do not exist: {sorted(unknown)}"
    )


@pytest.mark.parametrize("skill_md", _skill_files(), ids=lambda p: p.parent.name)
def test_skill_only_references_cli_commands_that_exist(skill_md: Path) -> None:
    from co_scientist.cli import app

    commands = {c.name or (c.callback.__name__ if c.callback else "") for c in app.registered_commands}
    commands |= {g.name for g in app.registered_groups}
    referenced = set(CLI_REF_RE.findall(_code_only(skill_md.read_text(encoding="utf-8"))))
    unknown = {c for c in referenced if c not in commands}
    assert not unknown, (
        f"{skill_md.parent.name} references CLI commands that do not exist: {sorted(unknown)}"
    )


def test_every_write_tool_is_taught_by_some_skill() -> None:
    """A tool nothing documents is a tool the agent will use badly, or not at all."""
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in _skill_files())
    for tool in ("session_start", "review_record", "match_record", "hypothesis_record",
                 "feedback_add", "overview_get"):
        assert f"co-scientist:{tool}" in corpus, f"no skill explains {tool}"


def test_recording_discipline_is_stated_in_the_writing_skills() -> None:
    """The invariant the whole design rests on has to be in the instructions."""
    for name in ("reviewing-hypotheses", "ranking-hypotheses", "evolving-hypotheses"):
        text = (PLUGIN_DIR / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        assert "does not exist" in text, (
            f"{name} does not tell the agent that unrecorded output does not count"
        )
