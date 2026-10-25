"""Load the MSK genomics + clinical files in ./data into MongoDB.

Collections written (each is dropped and rebuilt, so re-running is safe):

  samples     one doc per tumour sample: patient, OS, and the genes that are
              mutated / amplified / deleted (stored as lists, not 718 zeros)
  treatments  one doc per patient-drug line: drug, class, PFS months/status
  genes       the 718 genes on the panel

Usage:
  python scripts/load_to_mongo.py --dry-run     # parse + count, no database
  python scripts/load_to_mongo.py               # needs MONGODB_URI in .env
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB_NAME = "biocurate"
BATCH = 5000

ALTERATIONS = {
    "mutations": "cell2mutation_labeled.txt",
    "amplifications": "cell2cnamplification_labeled.txt",
    "deletions": "cell2cndeletion_labeled.txt",
}


def _read_env_uri() -> str | None:
    if os.environ.get("MONGODB_URI"):
        return os.environ["MONGODB_URI"]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "MONGODB_URI" and value.strip():
                return value.strip().strip('"').strip("'")
    return None


def _altered_genes(path: Path) -> dict[str, list[str]]:
    # Line 1 is a title ("\tmutation"), line 2 the gene header, then one row per sample.
    matrix = pd.read_csv(path, sep="\t", skiprows=1, index_col=0)
    matrix = matrix.loc[:, ~matrix.columns.str.startswith("Unnamed")]
    hits = matrix.astype(bool)
    return {sample: list(hits.columns[row]) for sample, row in zip(hits.index, hits.values, strict=True)}


def build_samples() -> list[dict]:
    os_df = pd.read_csv(DATA / "OS_time_adjusted.txt", sep="\t").drop_duplicates("SAMPLE_ID")
    os_by_sample = os_df.set_index("SAMPLE_ID").to_dict("index")

    altered = {field: _altered_genes(DATA / name) for field, name in ALTERATIONS.items()}
    sample_ids = altered["mutations"].keys()

    docs = []
    for sid in sample_ids:
        clin = os_by_sample.get(sid, {})
        status = clin.get("OS_STATUS")
        docs.append({
            "_id": sid,
            "patient_id": clin.get("PATIENT_ID", sid[:9]),
            "os_months": None if pd.isna(clin.get("OS_MONTHS")) else float(clin["OS_MONTHS"]),
            "os_status": status,
            "deceased": None if status is None else status.startswith("1"),
            **{field: altered[field].get(sid, []) for field in ALTERATIONS},
        })
    return docs


def build_treatments() -> list[dict]:
    pfs = pd.read_csv(DATA / "pfs_months.txt", sep="\t")
    pfs.columns = [c.lower() for c in pfs.columns]
    pfs["progressed"] = pfs["pfs_status"].astype(str).str.startswith("1")
    pfs = pfs.astype(object).where(pfs.notna(), None)
    return pfs.to_dict("records")


def build_genes() -> list[dict]:
    genes = pd.read_csv(DATA / "gene2ind.txt", sep="\t")
    return [{"_id": g, "index": int(i)} for i, g in zip(genes["index"], genes["GENE_NAME"], strict=True)]


def insert(db, name: str, docs: list[dict]) -> None:
    db[name].drop()
    for start in range(0, len(docs), BATCH):
        db[name].insert_many(docs[start:start + BATCH], ordered=False)
        print(f"  {name}: {min(start + BATCH, len(docs))}/{len(docs)}", end="\r")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="Parse files, print counts, skip MongoDB.")
    args = parser.parse_args()

    print("Reading files from", DATA)
    samples, treatments, genes = build_samples(), build_treatments(), build_genes()
    print(f"samples={len(samples)}  treatments={len(treatments)}  genes={len(genes)}")
    print("example sample:", {k: (v[:5] if isinstance(v, list) else v) for k, v in samples[0].items()})
    print("example treatment:", treatments[0])
    if args.dry_run:
        return 0

    uri = _read_env_uri()
    if not uri:
        print("MONGODB_URI not set. Add it to .env (see README steps).", file=sys.stderr)
        return 1

    from pymongo import ASCENDING, MongoClient

    client = MongoClient(uri, serverSelectionTimeoutMS=15000)
    client.admin.command("ping")
    db = client[DB_NAME]
    insert(db, "samples", samples)
    insert(db, "treatments", treatments)
    insert(db, "genes", genes)

    db.samples.create_index([("patient_id", ASCENDING)])
    for field in ALTERATIONS:
        db.samples.create_index([(field, ASCENDING)])
    db.treatments.create_index([("patient_id", ASCENDING)])
    db.treatments.create_index([("drug", ASCENDING)])
    db.treatments.create_index([("drug_class", ASCENDING)])
    print(f"Done. Database '{DB_NAME}' is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
