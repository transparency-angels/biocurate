## What this changes

<!-- One paragraph. What behaviour is different after this merges? -->

## Why

<!-- The problem it solves. Link the issue if there is one. -->

## Checklist

- [ ] `ruff check co_scientist scripts` passes
- [ ] `pytest co_scientist/tests/unit -q` passes
- [ ] Tests cover the change, and fail without it
- [ ] Storage changes go through a numbered migration
- [ ] `python scripts/validate_plugin.py` passes, if `plugin/` changed
- [ ] New MCP tools are documented in a skill, if any were added
- [ ] Prompt changes say what the paper does and why this differs
