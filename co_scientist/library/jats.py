"""Pure, offline parser that turns Europe PMC JATS XML into anchored passages.

Each passage gets a stable anchor such as ``PMC1234567#F2`` so it can be cited and
looked up later. No network or database access happens here.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Literal

_WS = re.compile(r"\s+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_PREFERRED_DATES = ("epub", "ppub")
_FLOATS = ("fig", "table-wrap")
_WRAPPERS = (
    "fig-group",
    "boxed-text",
    "list",
    "list-item",
    "disp-quote",
    "statement",
    "def-list",
    "def-item",
    "def",
    "glossary",
    "gloss-group",
    "term-head",
)


@dataclass(frozen=True)
class Passage:
    anchor_id: str
    pmcid: str
    kind: Literal["abstract", "paragraph", "figure", "table"]
    section: str
    label: str | None
    text: str
    ordinal: int


@dataclass(frozen=True)
class PaperMeta:
    pmcid: str
    title: str
    doi: str | None
    year: int | None
    journal: str | None


def _clean(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _text(el: ET.Element | None) -> str:
    """Whitespace-collapsed text of an element, keeping inline children's text."""
    if el is None:
        return ""
    return _clean("".join(el.itertext()))


def _text_without(el: ET.Element, skip: tuple[str, ...]) -> str:
    """Text of ``el`` excluding descendants tagged in ``skip`` (their tails are kept)."""
    out = [el.text or ""]
    for child in el:
        if child.tag not in skip:
            out.append(_text_without(child, skip))
        out.append(child.tail or "")
    return "".join(out)


def _strip_namespaces(root: ET.Element) -> None:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.rsplit("}", 1)[1]


def _join(*parts: str) -> str:
    return " ".join(p for p in parts if p)


def _split_text(text: str, max_chars: int) -> list[str]:
    """Greedy sentence packing; oversized sentences are hard-split on whitespace."""
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    for sentence in _SENTENCE_END.split(text):
        while len(sentence) > max_chars:
            cut = sentence.rfind(" ", 0, max_chars + 1)
            if cut <= 0:
                cut = max_chars
            pieces.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        if sentence:
            pieces.append(sentence)
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if current and len(current) + 1 + len(piece) <= max_chars:
            current = f"{current} {piece}"
        else:
            if current:
                chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return chunks


def _meta(root: ET.Element, pmcid: str) -> PaperMeta:
    article_meta = root.find("./front/article-meta")
    if article_meta is None:
        article_meta = root.find(".//article-meta")
    title = doi = None
    year = None
    if article_meta is not None:
        title = _text(article_meta.find("./title-group/article-title"))
        for aid in article_meta.findall("article-id"):
            if aid.get("pub-id-type") == "doi" and _text(aid):
                doi = _text(aid)
        dates = [d for d in article_meta.findall("pub-date") if _text(d.find("year")).isdigit()]
        chosen = None
        for wanted in _PREFERRED_DATES:
            chosen = next(
                (d for d in dates if wanted in (d.get("pub-type"), d.get("date-type"))), None
            )
            if chosen is not None:
                break
        if chosen is None and dates:
            chosen = dates[0]
        if chosen is not None:
            year = int(_text(chosen.find("year")))
    journal = _text(root.find(".//journal-meta//journal-title")) or None
    return PaperMeta(pmcid=pmcid, title=title or "", doi=doi, year=year, journal=journal)


class _Collector:
    def __init__(self, pmcid: str, max_chars: int) -> None:
        self.pmcid = pmcid
        self.max_chars = max_chars
        self.passages: list[Passage] = []
        self.top_count = 0
        self.counters: dict[int, dict[str, int]] = {}

    def add(
        self,
        anchor: str,
        kind: Literal["abstract", "paragraph", "figure", "table"],
        section: str,
        label: str | None,
        text: str,
    ) -> None:
        if not text:
            return
        chunks = _split_text(text, self.max_chars)
        for n, chunk in enumerate(chunks, 1):
            suffix = f".{n}" if len(chunks) > 1 else ""
            self.passages.append(
                Passage(
                    anchor_id=f"{self.pmcid}#{anchor}{suffix}",
                    pmcid=self.pmcid,
                    kind=kind,
                    section=section,
                    label=label,
                    text=chunk,
                    ordinal=len(self.passages),
                )
            )

    def float_text(self, el: ET.Element, label: str, *, footnotes: bool) -> str:
        parts = [label]
        caption = el.find("caption")
        if caption is not None:
            parts.extend(_text(child) for child in caption)
            if not len(caption):
                parts.append(_text(caption))
        if footnotes:
            parts.extend(_text(fn) for fn in el.findall("./table-wrap-foot//fn"))
        return _join(*parts)

    def emit_float(self, el: ET.Element, path: list[str], top: int) -> None:
        is_table = el.tag == "table-wrap"
        label = _text(el.find("label")) or None
        text = self.float_text(el, label or "", footnotes=is_table)
        kind: Literal["figure", "table"] = "table" if is_table else "figure"
        text = text or ("Table" if is_table else "Figure")
        counts = self.counters.setdefault(top, {"p": 0, "f": 0, "t": 0})
        key = "t" if is_table else "f"
        counts[key] += 1
        anchor = el.get("id") or f"s{top}.{key}{counts[key]}"
        self.add(anchor, kind, " > ".join(path), label, text)

    def walk(self, el: ET.Element, path: list[str], top: int) -> None:
        """Visit children of ``el`` in document order (body, a ``sec`` or a wrapper)."""
        for child in el:
            tag = child.tag
            if tag == "sec":
                if top == 0:
                    self.top_count += 1
                    self.walk_sec(child, path, self.top_count)
                else:
                    self.walk_sec(child, path, top)
            elif tag == "p":
                counts = self.counters.setdefault(top, {"p": 0, "f": 0, "t": 0})
                counts["p"] += 1
                anchor = child.get("id") or f"s{top}.p{counts['p']}"
                text = _clean(_text_without(child, _FLOATS))
                self.add(anchor, "paragraph", " > ".join(path), None, text)
                for fl in child.iter():
                    if fl.tag in _FLOATS:
                        self.emit_float(fl, path, top)
            elif tag in _FLOATS:
                self.emit_float(child, path, top)
            elif tag in _WRAPPERS:
                self.walk(child, path, top)

    def walk_sec(self, sec: ET.Element, path: list[str], top: int) -> None:
        title = _text(sec.find("title"))
        new_path = [*path, title] if title else path
        self.walk(sec, new_path, top)

    def run_body(self, body: ET.Element) -> None:
        self.walk(body, [], 0)


def parse_jats(xml: str, pmcid: str, *, max_chars: int = 2000) -> tuple[PaperMeta, list[Passage]]:
    """Parse a JATS document into paper metadata and ordered, anchored passages."""
    if max_chars < 1:
        raise ValueError(f"max_chars must be >= 1, got {max_chars}")
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ValueError(f"Invalid JATS XML for {pmcid}: {exc}") from exc
    _strip_namespaces(root)

    collector = _Collector(pmcid, max_chars)
    abstract = root.find("./front/article-meta/abstract")
    if abstract is not None:
        for j, p in enumerate(abstract.iter("p"), 1):
            collector.add(f"abstract.p{j}", "abstract", "Abstract", None, _text(p))
    body = root.find("body")
    if body is not None:
        collector.run_body(body)
    return _meta(root, pmcid), collector.passages
