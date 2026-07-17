"""Backwards version of the pt_1/pt_2 pipeline.

Instead of starting from HPD registrations and joining in ACRIS by BBL, this
starts from ACRIS Real Property Parties, filters directly for the six
universities' own name aliases (same word-boundary aliases as data_prep.py),
then merges in the borough/block/lot (via real_property_legals.csv) and
doc type/date (via real_property_master.csv) using DOCUMENT ID as the key.

Purely a research/comparison script - does not touch app.py or pt_2.csv.
"""

import re
import sys
import pandas as pd

from data_prep import OWNER_NAME_ALIASES

PARTIES_PATH = "data/real_property_parties.csv"
LEGALS_PATH = "data/real_property_legals.csv"
MASTER_PATH = "data/real_property_master.csv"
CHUNKSIZE = 1_000_000

BORO_CODE_TO_LABEL = {
    "1": "Manhattan",
    "2": "Bronx",
    "3": "Brooklyn",
    "4": "Queens",
    "5": "Staten Island",
}

ALL_ALIASES = [a for aliases in OWNER_NAME_ALIASES.values() for a in aliases]
CHEAP_FILTER_RE = r"\b(?:" + "|".join(re.escape(a) for a in ALL_ALIASES) + r")\b"

OWNER_PATTERNS = {
    owner: re.compile(r"\b(?:" + "|".join(re.escape(a) for a in aliases) + r")\b")
    for owner, aliases in OWNER_NAME_ALIASES.items()
}


def assign_owner(name):
    upper = name.upper()
    for owner, pattern in OWNER_PATTERNS.items():
        if pattern.search(upper):
            return owner
    return None


def scan_parties():
    matches = []
    total_rows = 0
    for i, chunk in enumerate(
        pd.read_csv(PARTIES_PATH, dtype=str, chunksize=CHUNKSIZE)
    ):
        total_rows += len(chunk)
        upper_names = chunk["NAME"].str.upper()
        mask = upper_names.str.contains(CHEAP_FILTER_RE, regex=True, na=False)
        hits = chunk[mask].copy()
        if not hits.empty:
            hits["owner_group"] = hits["NAME"].map(assign_owner)
            hits = hits[hits["owner_group"].notna()]
            matches.append(hits)
        print(
            f"  parties chunk {i+1}: {total_rows:,} rows scanned, "
            f"{sum(len(m) for m in matches):,} matches so far",
            file=sys.stderr,
        )
    return pd.concat(matches, ignore_index=True) if matches else pd.DataFrame()


def scan_legals(document_ids):
    doc_id_set = set(document_ids)
    matches = []
    for i, chunk in enumerate(
        pd.read_csv(LEGALS_PATH, dtype=str, chunksize=CHUNKSIZE)
    ):
        hits = chunk[chunk["DOCUMENT ID"].isin(doc_id_set)]
        if not hits.empty:
            matches.append(hits)
        if (i + 1) % 5 == 0:
            print(f"  legals chunk {i+1}, {sum(len(m) for m in matches):,} matches so far", file=sys.stderr)
    return pd.concat(matches, ignore_index=True) if matches else pd.DataFrame()


def scan_master(document_ids):
    doc_id_set = set(document_ids)
    matches = []
    for i, chunk in enumerate(
        pd.read_csv(MASTER_PATH, dtype=str, chunksize=CHUNKSIZE)
    ):
        hits = chunk[chunk["DOCUMENT ID"].isin(doc_id_set)]
        if not hits.empty:
            matches.append(hits)
        if (i + 1) % 5 == 0:
            print(f"  master chunk {i+1}, {sum(len(m) for m in matches):,} matches so far", file=sys.stderr)
    return pd.concat(matches, ignore_index=True) if matches else pd.DataFrame()


def main():
    print("Step 1: scanning real_property_parties.csv for university name aliases...", file=sys.stderr)
    parties_hits = scan_parties()
    print(f"Found {len(parties_hits):,} party rows matching a university alias "
          f"across {parties_hits['DOCUMENT ID'].nunique():,} documents.", file=sys.stderr)

    doc_ids = parties_hits["DOCUMENT ID"].unique().tolist()

    print("\nStep 2: scanning real_property_legals.csv for those documents' BBLs...", file=sys.stderr)
    legals_hits = scan_legals(doc_ids)
    print(f"Found legals rows for {legals_hits['DOCUMENT ID'].nunique():,} of those documents.", file=sys.stderr)

    print("\nStep 3: scanning real_property_master.csv for doc type/date...", file=sys.stderr)
    master_hits = scan_master(doc_ids)
    print(f"Found master rows for {master_hits['DOCUMENT ID'].nunique():,} of those documents.", file=sys.stderr)

    legals_small = legals_hits[["DOCUMENT ID", "BOROUGH", "BLOCK", "LOT", "STREET NUMBER", "STREET NAME"]].drop_duplicates()
    master_small = master_hits[["DOCUMENT ID", "DOC. TYPE", "DOC. DATE", "DOC. AMOUNT"]].drop_duplicates()

    combined = parties_hits.merge(legals_small, on="DOCUMENT ID", how="left")
    combined = combined.merge(master_small, on="DOCUMENT ID", how="left")
    combined["boro_label"] = combined["BOROUGH"].map(BORO_CODE_TO_LABEL)

    combined.to_csv("data/backwards_search_raw.csv", index=False)
    print(f"\nWrote data/backwards_search_raw.csv ({len(combined):,} rows).", file=sys.stderr)

    # Distinct parcels per owner (dedupe on boro/block/lot).
    parcels = combined.dropna(subset=["boro_label", "BLOCK", "LOT"]).drop_duplicates(
        subset=["owner_group", "boro_label", "BLOCK", "LOT"]
    )[["owner_group", "boro_label", "BLOCK", "LOT", "STREET NUMBER", "STREET NAME", "PARTY TYPE", "DOC. TYPE", "DOC. DATE"]]
    parcels.to_csv("data/backwards_search_parcels.csv", index=False)
    print(f"Wrote data/backwards_search_parcels.csv ({len(parcels):,} distinct owner/BBL rows).", file=sys.stderr)

    print("\nDistinct parcels found per owner (backwards search):", file=sys.stderr)
    counts = parcels.groupby("owner_group").size()
    print(counts, file=sys.stderr)


if __name__ == "__main__":
    main()
