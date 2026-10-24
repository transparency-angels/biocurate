"""Hour-0 Atlas spike: which server features does this cluster support?

Checks (each reported PASS/FAIL, independently):
  (a) autoEmbed vector index + $vectorSearch with {"query": {"text": ...}}
  (b) Atlas Search index + $rankFusion over $search and $vectorSearch
  (c) a multi-document transaction across two collections

Everything lives in `spike_*` collections of the configured database and is
dropped at the end. Run: uv run python scripts/atlas_spike.py
"""

from __future__ import annotations

import asyncio
import re
import sys

from pymongo.operations import SearchIndexModel

from co_scientist.config import load_config
from co_scientist.storage.atlas.client import connect_atlas, shutdown_clients
from co_scientist.storage.atlas.indexes import wait_for_search_index

PREFIX = "spike_"
_SAFE = re.compile(r"^spike_$")

PASSAGES = [
    ("kinase", "EGFR inhibitors slow tumour growth in non-small cell lung cancer."),
    ("kinase", "BRAF V600E mutations drive melanoma and respond to vemurafenib."),
    ("kinase", "Imatinib targets BCR-ABL in chronic myeloid leukaemia."),
    ("immune", "PD-1 blockade restores T cell function in exhausted tumours."),
    ("immune", "CAR-T cells target CD19 in B cell malignancies."),
    ("immune", "Regulatory T cells suppress anti-tumour immunity."),
    ("metab", "Warburg effect: tumours favour glycolysis even with oxygen present."),
    ("metab", "Metformin activates AMPK and lowers hepatic glucose output."),
    ("metab", "Ketogenic diets alter lipid metabolism in epilepsy."),
    ("neuro", "Amyloid beta plaques accumulate in Alzheimer's disease brains."),
    ("neuro", "Tau hyperphosphorylation correlates with cognitive decline."),
    ("neuro", "Dopaminergic neuron loss underlies Parkinson's disease."),
    ("gen", "CRISPR-Cas9 enables targeted genome editing in human cells."),
    ("gen", "Base editors convert single nucleotides without double-strand breaks."),
    ("gen", "RNA interference silences gene expression post-transcriptionally."),
    ("micro", "Gut microbiota composition influences host immune development."),
    ("micro", "Antibiotic resistance spreads by horizontal gene transfer."),
    ("micro", "Bacteriophages can lyse multidrug-resistant bacteria."),
    ("cardio", "Statins lower LDL cholesterol by inhibiting HMG-CoA reductase."),
    ("cardio", "Atrial fibrillation raises stroke risk via thrombus formation."),
]
QUERY = "drugs that block a mutated cancer signalling enzyme"


async def drop_spike(db) -> None:
    """Drop only collections named exactly `spike_*`. Never drops the database."""
    if not _SAFE.fullmatch(PREFIX):
        raise ValueError("unsafe spike prefix")
    for name in await db.list_collection_names():
        if name.startswith(PREFIX):
            await db.drop_collection(name)


async def check_autoembed(db) -> str:
    coll = db[PREFIX + "auto"]
    await coll.insert_many([{"kind": k, "text": t} for k, t in PASSAGES])
    await coll.create_search_index(
        SearchIndexModel(
            definition={
                "fields": [
                    {
                        "type": "autoEmbed",
                        "modality": "text",
                        "path": "text",
                        "model": "voyage-4",
                    },
                    {"type": "filter", "path": "kind"},
                ]
            },
            name="spike_auto",
            type="vectorSearch",
        )
    )
    if not await wait_for_search_index(coll, "spike_auto", timeout_s=600, poll_s=10):
        return "FAIL: index never became queryable within 10 min"
    cur = await coll.aggregate(
        [
            {
                "$vectorSearch": {
                    "index": "spike_auto",
                    "path": "text",
                    "query": {"text": QUERY},
                    "numCandidates": 20,
                    "limit": 3,
                }
            },
            {"$project": {"_id": 0, "text": 1}},
        ]
    )
    rows = await cur.to_list()
    return f"PASS: {len(rows)} hits, top={rows[0]['text'][:50]!r}" if rows else "FAIL: no hits"


async def check_rank_fusion(db) -> str:
    coll = db[PREFIX + "auto"]
    await coll.create_search_index(
        SearchIndexModel(
            definition={"mappings": {"dynamic": True}}, name="spike_text", type="search"
        )
    )
    if not await wait_for_search_index(coll, "spike_text", timeout_s=600, poll_s=10):
        return "FAIL: search index never became queryable"
    cur = await coll.aggregate(
        [
            {
                "$rankFusion": {
                    "input": {
                        "pipelines": {
                            "lexical": [
                                {"$search": {"index": "spike_text", "text": {"query": "kinase cancer", "path": "text"}}},
                                {"$limit": 10},
                            ],
                            "semantic": [
                                {
                                    "$vectorSearch": {
                                        "index": "spike_auto",
                                        "path": "text",
                                        "query": {"text": QUERY},
                                        "numCandidates": 20,
                                        "limit": 10,
                                    }
                                }
                            ],
                        }
                    }
                }
            },
            {"$limit": 5},
            {"$project": {"_id": 0, "text": 1}},
        ]
    )
    rows = await cur.to_list()
    return f"PASS: {len(rows)} fused hits" if rows else "FAIL: no hits"


async def check_transaction(client, db) -> str:
    a, b = db[PREFIX + "tx_a"], db[PREFIX + "tx_b"]
    await db.create_collection(PREFIX + "tx_a")  # collections must pre-exist in a txn
    await db.create_collection(PREFIX + "tx_b")
    async with client.start_session() as s, await s.start_transaction():
        await a.insert_one({"x": 1}, session=s)
        await b.insert_one({"y": 2}, session=s)
    ok = await a.count_documents({}) == 1 and await b.count_documents({}) == 1
    return "PASS" if ok else "FAIL: documents missing after commit"


async def main() -> int:
    cfg = load_config()
    conn = await connect_atlas(cfg)
    db = conn.client[cfg.storage.atlas_db]
    results: dict[str, str] = {}
    try:
        await drop_spike(db)
        checks = {
            "a autoEmbed + $vectorSearch": lambda: check_autoembed(db),
            "b $rankFusion": lambda: check_rank_fusion(db),
            "c transaction": lambda: check_transaction(conn.client, db),
        }
        for label, fn in checks.items():
            try:
                results[label] = await fn()
            except Exception as e:
                results[label] = f"FAIL: {type(e).__name__}: {str(e)[:200]}"
    finally:
        await drop_spike(db)
        await shutdown_clients()
    for label, res in results.items():
        print(f"{label}: {res}")
    return 0 if all(r.startswith("PASS") for r in results.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
