"""Europe PMC access for the evidence library: OA search and JATS full text."""

from __future__ import annotations

import httpx

from ..tools.builtins.europe_pmc import EUROPE_PMC_URL

FULLTEXT_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
USER_AGENT = "biocurate/0.1 (+https://github.com/transparency-angels/biocurate)"


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )


async def fetch_jats(client: httpx.AsyncClient, pmcid: str) -> str | None:
    """Full-text JATS for a PMCID; None when Europe PMC has none (404)."""
    r = await client.get(FULLTEXT_URL.format(pmcid=pmcid))
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.text


async def search_oa_pmcids(client: httpx.AsyncClient, query: str, max_papers: int) -> list[str]:
    """PMCIDs of open-access papers with full text that match `query`."""
    r = await client.get(
        EUROPE_PMC_URL,
        params={
            "query": f"({query}) AND OPEN_ACCESS:Y AND HAS_FT:Y",
            "format": "json",
            "pageSize": max_papers,
            "resultType": "lite",
        },
    )
    r.raise_for_status()
    hits = r.json().get("resultList", {}).get("result", [])
    out: list[str] = []
    for hit in hits:
        pmcid = hit.get("pmcid")
        if pmcid and pmcid not in out:
            out.append(pmcid)
    return out[:max_papers]
