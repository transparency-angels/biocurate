"""Map stored hypotheses to the React app's `ResearchSession` (frontend/src/types/research.ts).

Pure: the route fetches rows and hands them in, so the shape is testable offline.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import urlsplit

from ..models import Hypothesis
from ..models.hypothesis import CitedPaper

SHOWN_STATES = ("in_tournament", "pinned")
_REVIEW = re.compile(r"\breviews?\b|\bmeta-?analys", re.I)
_CLINICAL = re.compile(r"\btrials?\b|\bcohorts?\b|\bpatients?\b", re.I)
_LIBRARY_URL = re.compile(r"^https://europepmc\.org/article/PMC/(PMC\w+)(?:#|$)")
_UPLOAD = "upload://"
_HEADING = re.compile(r"^#{1,6}\s")


def select_hypotheses(hypotheses: Iterable[Hypothesis]) -> list[Hypothesis]:
    """Tournament and pinned hypotheses (plus reviewed ones before the tournament), by Elo."""
    hyps = list(hypotheses)
    states = set(SHOWN_STATES)
    if not any(h.state == "in_tournament" for h in hyps):
        states.add("reviewed")
    chosen = [h for h in hyps if h.state in states]
    return sorted(chosen, key=lambda h: (h.elo is None, -(h.elo or 0.0)))


def candidate_key(h: Hypothesis) -> str | None:
    de = h.data_evidence or {}
    if isinstance(de.get("candidate_key"), str) and de["candidate_key"]:
        return de["candidate_key"]
    parts = [de.get("biomarker"), de.get("alteration_type"), de.get("drug")]
    if all(isinstance(p, str) and p for p in parts):
        return "|".join(parts)
    return None


def linked_candidate_keys(hypotheses: Iterable[Hypothesis]) -> list[str]:
    keys = (candidate_key(h) for h in hypotheses)
    return list(dict.fromkeys(k for k in keys if k))


def library_pmcid(url: str) -> str | None:
    """The PMC id when `url` is a library passage link, else None."""
    m = _LIBRARY_URL.match(url or "")
    return m.group(1) if m else None


def _split_text(full_text: str) -> tuple[str, str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", full_text or "") if p.strip()]
    # A leading title heading repeats `title`; it is not the abstract.
    while paras and _HEADING.match(paras[0]) and "\n" not in paras[0] and len(paras) > 1:
        paras.pop(0)
    if not paras:
        return "", ""
    return paras[0], "\n\n".join(paras[1:])


def _fmt(v: Any) -> str:
    return f"{v:.3g}" if isinstance(v, float) else str(v)


def _description(ev: Mapping[str, Any]) -> str:
    biomarker = ev.get("biomarker")
    if not biomarker:
        return ""
    alteration = ev.get("alteration_type") or "alteration"
    text = f"{biomarker} {alteration}"
    if ev.get("drug"):
        text += f" and survival on {ev['drug']}"
    stats = []
    if ev.get("delta_os_months") is not None:
        stats.append(f"Δ median OS {_fmt(ev['delta_os_months'])} months")
    if ev.get("p_value") is not None:
        stats.append(f"p = {_fmt(ev['p_value'])}")
    if ev.get("sample_size") is not None:
        stats.append(f"n = {ev['sample_size']}")
    return f"{text} ({', '.join(stats)})" if stats else text


def _data(
    h: Hypothesis, candidates: Mapping[str, Mapping[str, Any]],
    points_by_key: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    key = candidate_key(h)
    if key is None:
        return {"description": "", "metric": "", "unit": ""}, []
    ev = {**candidates.get(key, {}), **(h.data_evidence or {})}
    doc = points_by_key.get(key) or {}
    summary = {
        "description": _description(ev),
        "metric": str(doc.get("metric") or ev.get("metric") or ""),
        "unit": str(doc.get("unit") or ""),
    }
    points = [
        {"id": str(p["sample_id"]), "label": str(p["sample_id"]),
         "group": str(p.get("group", "")), "value": float(p["value"])}
        for p in doc.get("points", [])
        if p.get("sample_id") is not None and isinstance(p.get("value"), int | float)
    ]
    return summary, points


def _source(
    hid: str, n: int, c: CitedPaper, journals: Mapping[str, str],
    attachments: Mapping[str, tuple[str, str]],
) -> dict[str, Any]:
    url: str | None = c.url
    publication = ""
    dataset = False
    if c.url.startswith(_UPLOAD):
        att_id = c.url[len(_UPLOAD):].split("#", 1)[0]
        filename, kind = attachments.get(att_id, ("Uploaded file", ""))
        publication, dataset, url = filename, kind == "tabular", None
    else:
        pmcid = library_pmcid(c.url)
        publication = journals.get(pmcid, "") if pmcid else ""
        parts = urlsplit(c.url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            url = None
        if not publication:
            publication = parts.hostname or ""
    haystack = f"{c.title} {publication}"
    if dataset:
        evidence = "Dataset"
    elif _REVIEW.search(haystack):
        evidence = "Review"
    elif _CLINICAL.search(haystack):
        evidence = "Clinical study"
    else:
        evidence = "Experimental study"
    return {
        "id": f"{hid}-s{n}", "title": c.title, "publication": publication, "year": c.year,
        "evidenceType": evidence, "description": c.excerpt or "", "url": url,
    }


def to_research_session(
    session_id: str,
    hypotheses: Iterable[Hypothesis],
    report: Mapping[str, Any] | None,
    points_by_key: Mapping[str, Mapping[str, Any]],
    *,
    journals: Mapping[str, str] | None = None,
    attachments: Mapping[str, tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Build a `ResearchSession`.

    `journals` maps library PMC ids to journal names; `attachments` maps attachment ids
    to `(filename, kind)` for `upload://` citations.
    """
    candidates = {
        c["candidate_key"]: c for c in (report or {}).get("candidates", [])
        if isinstance(c, Mapping) and c.get("candidate_key")
    }
    out = []
    for rank, h in enumerate(select_hypotheses(hypotheses), 1):
        abstract, explanation = _split_text(h.full_text)
        summary, points = _data(h, candidates, points_by_key)
        out.append({
            "id": h.id, "rank": rank, "title": h.title, "summary": h.summary,
            "abstract": abstract, "explanation": explanation,
            "dataSummary": summary, "dataPoints": points,
            "sources": [
                _source(h.id, n, c, journals or {}, attachments or {})
                for n, c in enumerate(h.citations, 1)
            ],
        })
    return {"id": session_id, "isDemo": False, "hypotheses": out}
