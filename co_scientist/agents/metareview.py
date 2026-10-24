"""Meta-review agent — periodic system feedback + final research overview.

Two actions:
- `GenerateSystemFeedback`           — Sonnet + thinking; writes a SystemFeedback row.
  The body is auto-injected into future Generation/Evolution prompts via the
  `latest_system_feedback` query the agents already perform.
- `GenerateFinalResearchOverview`    — Opus + max thinking; writes the markdown
  report and updates `sessions.final_overview`.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from typing import Any

from .. import ids
from ..llm.prompts import render
from ..llm.routing import route
from ..llm.types import AgentCallSpec, CachedBlock, CallContext
from ..logging import get_logger
from ..models import SystemFeedback, Task, TaskResult
from ..models.hypothesis import CitedPaper
from ..models.review import Evidence
from ..storage.artifacts import session_root, write_json, write_text
from ..storage.repos import feedback as fb_repo
from ..storage.repos import hypotheses as hyp_repo
from ..storage.repos import reviews as rev_repo
from ..storage.repos import sessions as sess_repo
from ..storage.repos import tournaments as tourney_repo
from .base import BaseAgent
from .schemas import RECORD_SYSTEM_FEEDBACK_TOOL

log = get_logger("metareview")


class MetaReviewAgent(BaseAgent):
    name = "metareview"

    async def execute(self, task: Task) -> TaskResult:
        if task.action == "GenerateSystemFeedback":
            return await self._system_feedback(task)
        if task.action == "GenerateFinalResearchOverview":
            return await self._final_overview(task)
        raise ValueError(f"MetaReviewAgent does not handle action {task.action!r}")

    # ----------------------------- system feedback ----------------------------- #

    async def _system_feedback(self, task: Task) -> TaskResult:
        session = await sess_repo.fetch(self.deps.db, task.session_id)
        if session is None:
            raise RuntimeError(f"session {task.session_id} missing")

        reviews = await rev_repo.list_for_session(self.deps.db, session.id)
        if not reviews:
            return TaskResult(kind="noop", extra={"reason": "no reviews yet"})

        reviews_block = "\n\n---\n\n".join(
            f"### Review of `{r.hypothesis_id}` (kind={r.kind}, verdict={r.verdict or '?'})\n{r.body[:3000]}"
            for r in reviews[:50]
        )
        rationales = await tourney_repo.recent_rationales(self.deps.db, session.id, limit=50)
        debate_block = "\n\n---\n\n".join(rat[:1500] for rat in rationales if rat)

        prompt = render(
            "metareview.system",
            goal=session.research_plan.objective,
            preferences="; ".join(session.research_plan.preferences),
            reviews=reviews_block,
            debate_rationales=debate_block,
            sources=self._source_block(*(await self._hydrate_sources([], reviews))),
        )
        r = route(self.deps.cfg, "metareview", "system")
        spec = AgentCallSpec(
            route=r,
            system_blocks=[
                CachedBlock(self._system_prompt_header(), cache=True),
                CachedBlock(
                    f"# Research goal\n{session.research_goal}\n\n"
                    f"# Preferences\n{'; '.join(session.research_plan.preferences)}",
                    cache=True,
                ),
            ],
            user_blocks=[CachedBlock(prompt, cache=False)],
            tools=[RECORD_SYSTEM_FEEDBACK_TOOL],
            tool_choice={"type": "tool", "name": "record_system_feedback"},
            max_output_tokens=4096,
        )
        ctx = CallContext(
            session_id=session.id, task_id=task.id,
            agent="metareview", action="GenerateSystemFeedback", mode="system",
        )
        resp = await self.deps.llm.call(spec, ctx)
        record = self._final_tool_use(resp, "record_system_feedback")
        if record is None:
            return TaskResult(kind="noop", extra={"reason": "no record_system_feedback"})

        narrative = record.get("narrative") or ""
        if record.get("common_weaknesses"):
            narrative += "\n\n**Common weaknesses:** " + "; ".join(record["common_weaknesses"])
        if record.get("common_strengths"):
            narrative += "\n\n**Common strengths:** " + "; ".join(record["common_strengths"])
        if record.get("suggested_focus_areas"):
            narrative += "\n\n**Suggested focus:** " + "; ".join(record["suggested_focus_areas"])

        fb_id = ids.feedback_id()
        artifact_path = await write_json(
            self.deps.cfg, session.id, "system_feedback", fb_id, record
        )
        await fb_repo.insert(self.deps.db, SystemFeedback(
            id=fb_id, session_id=session.id, created_at=datetime.now(UTC),
            source="meta_review", kind="system_feedback",
            target_id=None, text=narrative.strip()[:8000],
            artifact_path=artifact_path, active=True,
        ))
        return TaskResult(
            kind="system_feedback_generated",
            extra={"feedback_id": fb_id, "n_reviews": len(reviews)},
        )

    # ----------------------------- sources ----------------------------- #

    async def _read_record(self, artifact_path: str | None) -> dict[str, Any]:
        """Load the `record` payload of a hypothesis/review artifact.

        Citations and evidence are deliberately not columns — the repos note
        "citations live in the JSON artifact, not the row" — so the only way to
        recover them is to read the artifact back off disk.
        """
        if not artifact_path:
            return {}
        base = self.deps.cfg.data_dir.resolve()
        try:
            path = (self.deps.cfg.data_dir / artifact_path).resolve()
            path.relative_to(base)          # refuse to read outside data_dir
        except (ValueError, OSError):
            return {}

        def _load() -> dict[str, Any]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
            record = payload.get("record")
            return record if isinstance(record, dict) else {}

        return await asyncio.to_thread(_load)

    async def _hydrate_sources(self, hypotheses: list, reviews: list) -> tuple[list, list]:
        """Refill `citations` / `evidence` from artifacts before formatting."""
        hyps_out = []
        for h in hypotheses:
            record = await self._read_record(getattr(h, "artifact_path", None))
            cites = []
            for c in record.get("citations") or []:
                if isinstance(c, dict) and c.get("url") and c.get("title"):
                    cites.append(CitedPaper(
                        title=str(c["title"]), url=str(c["url"]),
                        excerpt=c.get("excerpt"), doi=c.get("doi"),
                        year=c.get("year") if isinstance(c.get("year"), int) else None,
                        line_range=c.get("line_range"),
                    ))
            hyps_out.append(h.model_copy(update={"citations": cites}))

        reviews_out = []
        for r in reviews:
            record = await self._read_record(getattr(r, "artifact_path", None))
            evidence = []
            for e in record.get("evidence") or []:
                if isinstance(e, dict) and e.get("url"):
                    evidence.append(Evidence(
                        claim=str(e.get("claim", "")),
                        url=str(e["url"]),
                        excerpt=str(e.get("excerpt", "")),
                        line_range=e.get("line_range"),
                    ))
            reviews_out.append(r.model_copy(update={"evidence": evidence}))

        return hyps_out, reviews_out

    _CITATION_RE = re.compile(
        r"\[S(\d+)(?:,\s*L(\d+)(?:\s*-\s*(?:L)?(\d+))?)?\]",
        re.IGNORECASE,
    )

    @classmethod
    def extract_citations(cls, text: str) -> list[dict[str, Any]]:
        """Parse citations matching [S#, L#-L#] or [S#, L#] or [S#] from text.

        Returns a list of dicts with keys:
          - 'raw': e.g. '[S1, L3-L5]'
          - 'source': e.g. 'S1'
          - 'source_idx': 1
          - 'start_line': 3 (or None)
          - 'end_line': 5 (or None)
          - 'line_range': 'L3-L5' (or None)
        """
        citations: list[dict[str, Any]] = []
        for m in cls._CITATION_RE.finditer(text):
            source_idx = int(m.group(1))
            start = int(m.group(2)) if m.group(2) else None
            end = int(m.group(3)) if m.group(3) else start
            line_str = None
            if start is not None:
                line_str = f"L{start}-L{end}" if start != end else f"L{start}"
            citations.append({
                "raw": m.group(0),
                "source": f"S{source_idx}",
                "source_idx": source_idx,
                "start_line": start,
                "end_line": end,
                "line_range": line_str,
            })
        return citations

    @staticmethod
    def _extract_line_range(text: str) -> str | None:
        """Extract a line number or line range (e.g. 'L3-L5' or 'L12') from text."""
        if not text:
            return None
        nums = [int(n) for n in re.findall(r"\[L(\d+)\]", text, re.IGNORECASE)]
        if nums:
            min_l, max_l = min(nums), max(nums)
            return f"L{min_l}-L{max_l}" if min_l != max_l else f"L{min_l}"
        m = re.search(r"\[?L(\d+)(?:\s*-\s*(?:L)?(\d+))\]?", text, re.IGNORECASE)
        if m:
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else start
            return f"L{start}-L{end}" if start != end else f"L{start}"
        return None

    @staticmethod
    def _collect_sources(hypotheses: list, reviews: list) -> dict[str, dict[str, Any]]:
        """Extract and deduplicate sources across hypotheses and reviews by URL."""
        seen: dict[str, dict[str, Any]] = {}

        for h in hypotheses:
            for c in getattr(h, "citations", []) or []:
                url = getattr(c, "url", "")
                if not url:
                    continue
                excerpt = getattr(c, "excerpt", "") or ""
                lr = getattr(c, "line_range", None) or MetaReviewAgent._extract_line_range(excerpt)
                doi = getattr(c, "doi", None)
                year = getattr(c, "year", None)
                if url not in seen:
                    seen[url] = {
                        "title": getattr(c, "title", "") or "(untitled)",
                        "url": url,
                        "doi": doi,
                        "year": year,
                        "excerpt": excerpt,
                        "excerpts": [excerpt] if excerpt else [],
                        "line_range": lr,
                        "refs": [],
                    }
                else:
                    if excerpt and excerpt not in seen[url]["excerpts"]:
                        seen[url]["excerpts"].append(excerpt)
                    if not seen[url]["excerpt"] and excerpt:
                        seen[url]["excerpt"] = excerpt
                    if not seen[url]["line_range"] and lr:
                        seen[url]["line_range"] = lr
                    if not seen[url].get("doi") and doi:
                        seen[url]["doi"] = doi
                    if not seen[url].get("year") and year:
                        seen[url]["year"] = year
                seen[url]["refs"].append(h.id)

        for r in reviews:
            for ev in getattr(r, "evidence", []) or []:
                url = getattr(ev, "url", "")
                if not url:
                    continue
                excerpt = getattr(ev, "excerpt", "") or ""
                lr = getattr(ev, "line_range", None) or MetaReviewAgent._extract_line_range(excerpt)
                if url not in seen:
                    seen[url] = {
                        "title": getattr(ev, "claim", "") or "(claim)",
                        "url": url,
                        "doi": None,
                        "year": None,
                        "excerpt": excerpt,
                        "excerpts": [excerpt] if excerpt else [],
                        "line_range": lr,
                        "refs": [],
                    }
                else:
                    if excerpt and excerpt not in seen[url]["excerpts"]:
                        seen[url]["excerpts"].append(excerpt)
                    if not seen[url]["excerpt"] and excerpt:
                        seen[url]["excerpt"] = excerpt
                    if not seen[url]["line_range"] and lr:
                        seen[url]["line_range"] = lr
                seen[url]["refs"].append(r.hypothesis_id)

        return seen

    @classmethod
    def _source_block(cls, hypotheses: list, reviews: list, *, limit: int = 40) -> str:
        """The literature the session actually saw, deduped by URL.

        Meta-review runs without tools, so unless we hand it the sources
        gathered downstream it has nothing to cite — and correctly refuses to
        invent any, producing an overview with no references at all. Both
        `Hypothesis.citations` and `Review.evidence` carry verified URLs
        (verified in the sense that Generation/Reflection could only record a
        URL that appeared in one of their own tool results).
        """
        seen = cls._collect_sources(hypotheses, reviews)
        if not seen:
            return ""

        lines: list[str] = []
        for i, (url, meta) in enumerate(list(seen.items())[:limit], start=1):
            refs = ", ".join(dict.fromkeys(meta["refs"]))[:120]
            line_range = meta.get("line_range") or cls._extract_line_range(meta["excerpt"])
            line_info = f" (lines: {line_range})" if line_range else ""
            line = f"- [S{i}] {meta['title'][:200]}{line_info}\n  {url}"
            if meta["excerpt"]:
                line += f'\n  > "{meta["excerpt"][:1000]}"'
            if refs:
                line += f"\n  (supports: {refs})"
            lines.append(line)
        if len(seen) > limit:
            lines.append(f"- …and {len(seen) - limit} more sources not shown.")
        return "\n".join(lines)

    @classmethod
    def _excerpt_to_bullets(cls, excerpt: str, max_bullets: int = 3) -> list[str]:
        """Convert raw excerpt text into 2-3 concise summary bullet sentences."""
        if not excerpt:
            return []
        cleaned = re.sub(r"\[(?:s\d+,\s*)?l\d+(?:\s*-\s*l?\d+)?\]\s*", "", excerpt, flags=re.IGNORECASE)
        cleaned = " ".join(cleaned.split())
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", cleaned) if s.strip()]
        bullets: list[str] = []
        for s in sentences:
            if len(s) >= 10:
                if not s.endswith((".", "!", "?")):
                    s += "."
                bullets.append(s)
            if len(bullets) >= max_bullets:
                break
        if not bullets and cleaned:
            summary = cleaned[:200]
            if not summary.endswith((".", "!", "?")):
                summary += "."
            bullets.append(summary)
        return bullets

    @classmethod
    def _enrich_sources_section(cls, text: str, seen: dict[str, dict[str, Any]]) -> str:
        """Ensure each - [S#] entry in the # Sources section has 2-3 indented sub-bullets."""
        if not seen:
            return text

        sources_match = re.search(r"(^|\n)(#+\s*Sources\b[^\n]*\n)(.*)$", text, re.IGNORECASE | re.DOTALL)
        if not sources_match:
            return text

        prefix = text[:sources_match.start(2)]
        header = sources_match.group(2)
        sources_body = sources_match.group(3)

        source_by_idx: dict[int, dict[str, Any]] = {
            i: meta for i, (url, meta) in enumerate(seen.items(), start=1)
        }

        lines = sources_body.splitlines()
        out_lines: list[str] = []
        i = 0
        n = len(lines)
        source_re = re.compile(r"^-\s*\[S(\d+)\]\s*(.*)$", re.IGNORECASE)

        while i < n:
            line = lines[i]
            m = source_re.match(line)
            if m:
                s_idx = int(m.group(1))
                out_lines.append(line)
                i += 1
                has_subbullets = False
                while i < n and (lines[i].startswith("  ") or lines[i].startswith("\t")):
                    out_lines.append(lines[i])
                    if lines[i].lstrip().startswith(("-", "*")):
                        has_subbullets = True
                    i += 1

                if not has_subbullets:
                    meta = source_by_idx.get(s_idx)
                    if meta:
                        bullets = cls._excerpt_to_bullets(meta.get("excerpt", ""))
                        for b in bullets:
                            out_lines.append(f"  - {b}")
            else:
                out_lines.append(line)
                i += 1

        return prefix + header + "\n".join(out_lines)

    @classmethod
    def _format_sources_raw(cls, session_id: str, seen: dict[str, dict[str, Any]]) -> str:
        """Format the raw excerpts log for all papers consulted in the session."""
        now = datetime.now(UTC).isoformat()
        header = [
            "================================================================================",
            "RAW SOURCES LOG",
            f"Session:   {session_id}",
            f"Generated: {now}",
            "Format:    Source index, title, URL, line numbers, and verbatim excerpts.",
            "================================================================================",
            "",
        ]
        entries: list[str] = []
        for i, (url, meta) in enumerate(seen.items(), start=1):
            refs = ", ".join(dict.fromkeys(meta.get("refs") or [])) or "(none)"
            line_range = meta.get("line_range") or cls._extract_line_range(meta.get("excerpt", "")) or "(unspecified)"
            block = [
                "--------------------------------------------------------------------------------",
                f"SOURCE:     [S{i}]",
                f"TITLE:      {meta.get('title', '(untitled)')}",
                f"URL:        {url}",
            ]
            if meta.get("doi"):
                block.append(f"DOI:        {meta['doi']}")
            if meta.get("year"):
                block.append(f"YEAR:       {meta['year']}")
            block.extend([
                f"LINE RANGE: {line_range}",
                f"REFERENCES: {refs}",
                "EXCERPTS:",
            ])
            excerpts = meta.get("excerpts") or ([meta["excerpt"]] if meta.get("excerpt") else [])
            if not excerpts:
                block.append("  (no excerpt recorded)")
            else:
                for idx, exc in enumerate(excerpts, start=1):
                    if len(excerpts) > 1:
                        block.append(f"  --- Excerpt {idx} ---")
                    for eline in exc.strip().splitlines():
                        block.append(f"  {eline}")
            block.append("--------------------------------------------------------------------------------")
            entries.append("\n".join(block))

        return "\n".join(header) + "\n\n".join(entries) + "\n"

    # ----------------------------- final overview ----------------------------- #

    async def _final_overview(self, task: Task) -> TaskResult:
        session = await sess_repo.fetch(self.deps.db, task.session_id)
        if session is None:
            raise RuntimeError(f"session {task.session_id} missing")

        top = await hyp_repo.top_by_elo(self.deps.db, session.id, k=10)
        all_hyps = await hyp_repo.list_for_session(self.deps.db, session.id)
        if not top and not all_hyps:
            return TaskResult(kind="noop", extra={"reason": "no hypotheses"})
        if not top:
            top = all_hyps[:10]

        # Fetch all reviews for the session in one query, then group by
        # hypothesis_id. Beats N+1 list_for_hypothesis() calls for top-K.
        reviews_by_hyp: dict[str, list] = {}
        for rv in await rev_repo.list_for_session(self.deps.db, session.id):
            reviews_by_hyp.setdefault(rv.hypothesis_id, []).append(rv)

        # Build the top-hypotheses block: summary + best review + winning rationale
        chunks: list[str] = []
        for h in top:
            review_lines: list[str] = []
            for r in reviews_by_hyp.get(h.id, []):
                review_lines.append(
                    f"  - {r.kind}: verdict={r.verdict or '?'} "
                    f"(n={r.scores.novelty}, c={r.scores.correctness}, t={r.scores.testability})"
                )
            elo_s = f"{h.elo:.0f}" if h.elo is not None else "—"
            chunks.append(
                f"### `{h.id}` (Elo {elo_s}, strategy `{h.strategy}`)\n"
                f"**Title.** {h.title}\n\n"
                f"{h.summary}\n\n"
                f"**Reviews:**\n" + ("\n".join(review_lines) or "  (none)")
            )
        top_block = "\n\n---\n\n".join(chunks)

        latest_fb = await fb_repo.latest_system_feedback(self.deps.db, session.id)

        all_reviews = [rv for group in reviews_by_hyp.values() for rv in group]
        hydrated_hyps, hydrated_reviews = await self._hydrate_sources(top, all_reviews)
        seen_sources = self._collect_sources(hydrated_hyps, hydrated_reviews)
        sources = self._source_block(hydrated_hyps, hydrated_reviews)

        prompt = render(
            "metareview.final",
            goal=session.research_plan.objective,
            preferences="; ".join(session.research_plan.preferences),
            system_feedback=latest_fb.text if latest_fb else "",
            top_hypotheses_block=top_block,
            sources=sources,
        )
        r = route(self.deps.cfg, "metareview", "final")
        spec = AgentCallSpec(
            route=r,
            system_blocks=[
                CachedBlock(self._system_prompt_header(), cache=True),
                CachedBlock(
                    f"# Research goal\n{session.research_goal}\n\n"
                    f"# Preferences\n{'; '.join(session.research_plan.preferences)}",
                    cache=True,
                ),
            ],
            user_blocks=[CachedBlock(prompt, cache=False)],
            tools=[],            # No tools — write the markdown directly
            tool_choice=None,
            max_output_tokens=8192,
        )
        ctx = CallContext(
            session_id=session.id, task_id=task.id,
            agent="metareview", action="GenerateFinalResearchOverview", mode="final",
        )
        resp = await self.deps.llm.call(spec, ctx)
        text = self._final_text(resp)
        if not text.strip():
            text = "# Research overview\n\n_(No content was generated; see transcripts.)_"

        # Ensure # Sources section has indented sub-bullets summarizing the excerpts
        text = self._enrich_sources_section(text, seen_sources)

        citations = self.extract_citations(text)
        log.info(
            "final_overview_citations",
            n_citations=len(citations),
            line_level=sum(1 for c in citations if c["line_range"] is not None),
        )

        overview_path = await write_text(
            self.deps.cfg, session.id, "final", "overview", ".md", text
        )

        # Write sources.raw logging verbatim excerpts with line numbers
        sources_raw_content = self._format_sources_raw(session.id, seen_sources)
        sources_raw_path = await write_text(
            self.deps.cfg, session.id, "final", "sources", ".raw", sources_raw_content
        )
        try:
            root = session_root(self.deps.cfg, session.id)
            (root / "sources.raw").write_text(sources_raw_content, encoding="utf-8")
        except Exception as e:
            log.warning("failed_writing_root_sources_raw", err=str(e))

        return TaskResult(
            kind="final_overview_generated",
            extra={
                "overview_path": overview_path,
                "sources_raw_path": sources_raw_path,
                "n_top": len(top),
                "citations": citations,
            },
        )
