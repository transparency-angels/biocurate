#!/usr/bin/env python3
"""Validate the Agent Plugin in `plugin/` against the parts of the spec that bite.

Run it before publishing, and in CI:

    python scripts/validate_plugin.py            # validates ./plugin
    python scripts/validate_plugin.py path/to/plugin

Checks the rules that actually break a plugin in the wild:

- plugin.json carries only the ten permitted top-level fields, with $schema and
  name present, and a conforming name.
- mcp.json declares an explicit transport type on every server.
- Every immediate child of skills/ has a SKILL.md with valid frontmatter, and
  nothing deeper is mistaken for a skill.
- Skill names conform and match their directory, so the two ways of referring
  to a skill do not diverge.
- Bodies stay under the 500-line guidance, and every relative link resolves.

Exit code is 0 when clean, 1 when anything failed. Warnings never fail the run.

The upstream schemas live at https://agent-plugins.org/schemas/1.0.0/ ; this is
a local check so the repo does not need network access to validate itself.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"

PERMITTED_PLUGIN_FIELDS = {
    "$schema", "name", "version", "description", "author", "homepage",
    "repository", "license", "keywords", "extensions",
}
REQUIRED_PLUGIN_FIELDS = {"$schema", "name"}
VALID_TRANSPORTS = {"stdio", "streamable-http", "sse"}

# Skill and plugin names: lowercase alphanumerics with hyphens or periods.
NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")
SKILL_NAME_RE = re.compile(r"^[a-z0-9-]+$")
RESERVED_IN_SKILL_NAME = ("anthropic", "claude")

MAX_SKILL_NAME = 64
MAX_DESCRIPTION = 1024
MAX_BODY_LINES = 500

FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate(root: Path) -> Report:
    report = Report()
    if not root.is_dir():
        report.error(f"{root} is not a directory")
        return report
    _check_manifest(root / "plugin.json", report)
    _check_mcp(root / "mcp.json", report)
    _check_skills(root / "skills", report)
    return report


# --------------------------------------------------------------------------- #
# plugin.json


def _check_manifest(path: Path, report: Report) -> None:
    manifest = _load_json(path, report)
    if manifest is None:
        return
    if not isinstance(manifest, dict):
        report.error("plugin.json must be a JSON object")
        return

    for missing in sorted(REQUIRED_PLUGIN_FIELDS - manifest.keys()):
        report.error(f"plugin.json is missing the required field {missing!r}")

    for extra in sorted(manifest.keys() - PERMITTED_PLUGIN_FIELDS):
        report.error(
            f"plugin.json has the non-conforming top-level field {extra!r}. "
            "Portable MCP config belongs in mcp.json; client-specific data "
            "belongs under `extensions`."
        )

    if manifest.get("$schema") != PLUGIN_SCHEMA:
        report.error(f"plugin.json $schema must be {PLUGIN_SCHEMA!r}")

    name = manifest.get("name")
    if not isinstance(name, str) or not NAME_RE.fullmatch(name) or len(name) > MAX_SKILL_NAME:
        report.error(
            f"plugin.json name={name!r} must be 1 to 64 lowercase alphanumerics, "
            "hyphens or periods"
        )

    if "description" not in manifest:
        report.warn("plugin.json has no description; catalogues will show the name alone")


# --------------------------------------------------------------------------- #
# mcp.json


def _check_mcp(path: Path, report: Report) -> None:
    if not path.exists():
        report.warn("no mcp.json; the plugin ships skills only")
        return
    mcp = _load_json(path, report)
    if mcp is None:
        return
    if mcp.get("$schema") != MCP_SCHEMA:
        report.error(f"mcp.json $schema must be {MCP_SCHEMA!r}")

    servers = mcp.get("mcpServers")
    if not isinstance(servers, dict) or not servers:
        report.error("mcp.json needs a non-empty `mcpServers` object")
        return

    for name, server in servers.items():
        if not isinstance(server, dict):
            report.error(f"mcp.json server {name!r} must be an object")
            continue
        transport = server.get("type")
        if transport not in VALID_TRANSPORTS:
            report.error(
                f"mcp.json server {name!r} declares type={transport!r}; "
                f"it must be one of {sorted(VALID_TRANSPORTS)}"
            )
        if transport == "stdio" and not server.get("command"):
            report.error(f"mcp.json server {name!r} is stdio but has no `command`")
        if transport in ("streamable-http", "sse") and not server.get("url"):
            report.error(f"mcp.json server {name!r} is {transport} but has no `url`")


# --------------------------------------------------------------------------- #
# skills


def _check_skills(skills_dir: Path, report: Report) -> None:
    if not skills_dir.is_dir():
        report.warn("no skills/ directory; the plugin ships MCP servers only")
        return

    found = 0
    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if not skill_md.is_file():
            report.error(
                f"skills/{child.name}/ has no SKILL.md. Clients do not search deeper, "
                "so this directory is invisible."
            )
            continue
        found += 1
        _check_skill(child, skill_md, report)

    # A nested SKILL.md is silently ignored by conformant clients, which reads
    # as "my skill did not install" rather than as an error. Catch it here.
    for nested in skills_dir.glob("*/*/SKILL.md"):
        report.warn(
            f"{nested.relative_to(skills_dir.parent)} is nested too deep to be a skill; "
            "clients only look one level under skills/"
        )

    if found == 0:
        report.warn("skills/ contains no skills")


def _check_skill(skill_dir: Path, skill_md: Path, report: Report) -> None:
    label = f"skills/{skill_dir.name}"
    text = skill_md.read_text(encoding="utf-8")

    match = FRONT_MATTER_RE.match(text)
    if match is None:
        report.error(f"{label}/SKILL.md has no YAML frontmatter")
        return
    front = _parse_front_matter(match.group(1))
    body = text[match.end():]

    name = front.get("name", "")
    if not name:
        report.error(f"{label}/SKILL.md frontmatter has no `name`")
    else:
        if len(name) > MAX_SKILL_NAME:
            report.error(f"{label}: name is over {MAX_SKILL_NAME} characters")
        if not SKILL_NAME_RE.fullmatch(name):
            report.error(
                f"{label}: name={name!r} must be lowercase letters, numbers and hyphens only"
            )
        for word in RESERVED_IN_SKILL_NAME:
            if word in name.lower():
                report.error(f"{label}: name must not contain the reserved word {word!r}")
        if name != skill_dir.name:
            report.error(
                f"{label}: frontmatter name={name!r} does not match the directory name. "
                "Keep them identical so the two ways of naming a skill agree."
            )

    description = front.get("description", "")
    if not description:
        report.error(f"{label}/SKILL.md frontmatter has no `description`")
    else:
        if len(description) > MAX_DESCRIPTION:
            report.error(f"{label}: description is over {MAX_DESCRIPTION} characters")
        lowered = description.lower()
        if lowered.startswith(("i ", "i'", "you ")):
            report.warn(
                f"{label}: description should be third person "
                "(\"Reviews...\"), not first or second"
            )
        if " use when" not in lowered and " use this" not in lowered:
            report.warn(
                f"{label}: description does not say when to use the skill, which is "
                "what routing depends on"
            )

    n_lines = len(body.splitlines())
    if n_lines > MAX_BODY_LINES:
        report.warn(
            f"{label}: body is {n_lines} lines, over the {MAX_BODY_LINES}-line guidance. "
            "Move detail into reference files."
        )

    _check_links(skill_dir, skill_md, body, report, label)


def _check_links(
    skill_dir: Path, skill_md: Path, body: str, report: Report, label: str
) -> None:
    for target in MD_LINK_RE.findall(body):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        path = (skill_dir / target.split("#", 1)[0]).resolve()
        if not path.exists():
            report.error(f"{label}: SKILL.md links to {target!r}, which does not exist")
            continue
        # Files linked from a reference file rather than from SKILL.md get read
        # partially, so keep every reference one hop from SKILL.md.
        if path.suffix == ".md":
            nested = MD_LINK_RE.findall(path.read_text(encoding="utf-8"))
            for deeper in nested:
                if deeper.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                report.warn(
                    f"{label}: {target} links on to {deeper!r}. Keep references one "
                    "level deep from SKILL.md."
                )
    _ = skill_md


# --------------------------------------------------------------------------- #
# helpers


def _load_json(path: Path, report: Report) -> dict | None:
    if not path.exists():
        report.error(f"{path.name} is missing")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        report.error(f"{path.name} is not valid JSON: {e}")
        return None


def _parse_front_matter(raw: str) -> dict[str, str]:
    """Read the flat `key: value` frontmatter a SKILL.md uses.

    Values may be folded across continuation lines, which is common for a long
    description. PyYAML is used when present; the fallback handles the flat
    subset the spec requires so validation still works in a minimal install.
    """
    try:
        import yaml

        parsed = yaml.safe_load(raw)
        if isinstance(parsed, dict):
            return {str(k): str(v).strip() for k, v in parsed.items() if v is not None}
    except Exception:
        pass

    out: dict[str, str] = {}
    key: str | None = None
    for line in raw.splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)
        if m:
            key = m.group(1)
            out[key] = m.group(2).strip().strip("\"'")
        elif key and line.strip():
            out[key] = f"{out[key]} {line.strip()}".strip()
    return out


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent / "plugin"
    report = validate(root)

    for warning in report.warnings:
        print(f"warning: {warning}")
    for error in report.errors:
        print(f"error: {error}")

    if report.ok:
        print(f"{root} is a conforming Agent Plugin ({len(report.warnings)} warnings)")
        return 0
    print(f"{root} has {len(report.errors)} errors")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
