#!/usr/bin/env bash
# sync.sh — Sync changes from this worktree to the target repository (default: /Users/qinqian/biocurate)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="${1:-/Users/qinqian/biocurate}"

echo "============================================================"
echo "Syncing Biocurate Changes"
echo "Source: $SCRIPT_DIR"
echo "Target: $TARGET_DIR"
echo "============================================================"

if [ ! -d "$TARGET_DIR" ]; then
    echo "Error: Target directory '$TARGET_DIR' does not exist." >&2
    exit 1
fi

# List of specific modified files & directories to sync
FILES_TO_SYNC=(
    # TypeScript Interfaces for Frontend
    "types/sources.ts"
    "types/overview.ts"
    "types/index.ts"

    # Core Agents & Logic
    "co_scientist/agents/metareview.py"
    "co_scientist/agents/reflection.py"
    "co_scientist/agents/supervisor.py"
    "co_scientist/agents/schemas.py"
    "co_scientist/agents/generation.py"
    "co_scientist/agents/evolution.py"

    # Tool Loop & LLM Client
    "co_scientist/llm/tool_loop.py"

    # Web & CLI Endpoints
    "co_scientist/web/app.py"
    "co_scientist/web/templates/overview.html"
    "co_scientist/cli.py"

    # Prompts
    "config/prompts/metareview_final.md"
    "config/prompts/reflection_review.md"

    # Models & Safety
    "co_scientist/models/hypothesis.py"
    "co_scientist/models/review.py"
    "co_scientist/safety/citation_verifier.py"
    "co_scientist/safety/quoting.py"

    # Tools
    "co_scientist/tools/web_fetch.py"
    "co_scientist/tools/builtins/pubmed.py"
    "co_scientist/tools/builtins/arxiv.py"
    "co_scientist/tools/builtins/europe_pmc.py"

    # Tests & Scripts
    "co_scientist/tests/unit/test_metareview_sources.py"
    "scripts/verify_metareview_citations.py"
    "scripts/verify_med_sources_fetch.py"
)

echo "Copying modified files..."
SYNCED_COUNT=0
for rel_path in "${FILES_TO_SYNC[@]}"; do
    src_file="$SCRIPT_DIR/$rel_path"
    dest_file="$TARGET_DIR/$rel_path"

    if [ -f "$src_file" ]; then
        mkdir -p "$(dirname "$dest_file")"
        cp "$src_file" "$dest_file"
        echo "  [OK] $rel_path"
        SYNCED_COUNT=$((SYNCED_COUNT + 1))
    fi
done

echo ""
echo "Successfully synced $SYNCED_COUNT files to $TARGET_DIR."
echo "============================================================"