"""Comprehensive search for parcels tied to any of these universities.

The Flask app's current building list is derived from HPD Multiple Dwelling
Registrations (see pt_1.ipynb / pt_2.ipynb) - which only covers registered
residential rental buildings. Academic buildings, libraries, athletic
facilities, and large campus lots (e.g. block 1973 lot 1) are never HPD
"multiple dwellings," so they never enter that pipeline, regardless of who
owns them.

This script instead searches ACRIS directly: it scans the full (multi-GB)
real_property_parties.csv for any party name matching one of the university
aliases, then joins to real_property_legals.csv (for borough/block/lot) and
real_property_master.csv (for document type + date, so we can tell an actual
deed transfer apart from a mortgage, easement, etc.). It streams all three
files in chunks with a restricted column set, so it never needs to hold the
full files in memory.

Output: data/university_properties_matches.csv - one row per matching
(document, party, parcel) combination, for review before deciding how to
merge this into the app's main dataset.
"""

import re

import pandas as pd

from data_prep import OWNER_NAME_ALIASES

PARTIES_PATH = "data/real_property_parties.csv"
LEGALS_PATH = "data/real_property_legals.csv"
MASTER_PATH = "data/real_property_master.csv"
OUTPUT_PATH = "data/university_properties_matches.csv"

CHUNK_SIZE = 500_000

BOROUGH_NAMES = {1: "MANHATTAN", 2: "BRONX", 3: "BROOKLYN", 4: "QUEENS", 5: "STATEN ISLAND"}


def _match_owner_group(name):
    if not isinstance(name, str):
        return None
    upper = name.upper()
    for owner_group, aliases in OWNER_NAME_ALIASES.items():
        if any(alias in upper for alias in aliases):
            return owner_group
    return None


def find_matching_parties():
    print(f"Scanning {PARTIES_PATH} for university name matches...")
    matches = []
    usecols = ["DOCUMENT ID", "PARTY TYPE", "NAME"]
    for i, chunk in enumerate(pd.read_csv(PARTIES_PATH, usecols=usecols, chunksize=CHUNK_SIZE, low_memory=False)):
        chunk["owner_group"] = chunk["NAME"].map(_match_owner_group)
        hits = chunk[chunk["owner_group"].notna()].copy()
        if not hits.empty:
            matches.append(hits)
        print(f"  chunk {i + 1}: {len(hits)} matches (running total {sum(len(h) for h in matches)})")
    result = pd.concat(matches, ignore_index=True) if matches else pd.DataFrame(columns=usecols + ["owner_group"])
    print(f"Total matching party rows: {len(result)}")
    return result


def fetch_legals(document_ids):
    print(f"Scanning {LEGALS_PATH} for {len(document_ids)} matching document IDs...")
    matches = []
    usecols = ["DOCUMENT ID", "BOROUGH", "BLOCK", "LOT", "PROPERTY TYPE", "STREET NUMBER", "STREET NAME"]
    for i, chunk in enumerate(pd.read_csv(LEGALS_PATH, usecols=usecols, chunksize=CHUNK_SIZE, low_memory=False)):
        hits = chunk[chunk["DOCUMENT ID"].isin(document_ids)]
        if not hits.empty:
            matches.append(hits)
        if (i + 1) % 10 == 0:
            print(f"  chunk {i + 1}: running total {sum(len(h) for h in matches)}")
    result = pd.concat(matches, ignore_index=True) if matches else pd.DataFrame(columns=usecols)
    print(f"Total matching legal records: {len(result)}")
    return result


def fetch_master(document_ids):
    print(f"Scanning {MASTER_PATH} for {len(document_ids)} matching document IDs...")
    matches = []
    usecols = ["DOCUMENT ID", "DOC. TYPE", "DOC. DATE"]
    for i, chunk in enumerate(pd.read_csv(MASTER_PATH, usecols=usecols, chunksize=CHUNK_SIZE, low_memory=False)):
        hits = chunk[chunk["DOCUMENT ID"].isin(document_ids)]
        if not hits.empty:
            matches.append(hits)
        if (i + 1) % 5 == 0:
            print(f"  chunk {i + 1}: running total {sum(len(h) for h in matches)}")
    result = pd.concat(matches, ignore_index=True) if matches else pd.DataFrame(columns=usecols)
    print(f"Total matching master records: {len(result)}")
    return result


def main():
    parties = find_matching_parties()
    document_ids = set(parties["DOCUMENT ID"].unique())

    legals = fetch_legals(document_ids)
    master = fetch_master(document_ids)

    merged = parties.merge(legals, on="DOCUMENT ID", how="left").merge(master, on="DOCUMENT ID", how="left")
    merged["borough_name"] = merged["BOROUGH"].map(BOROUGH_NAMES)

    merged.columns = [re.sub(r"[.\s]+", "_", c).strip("_").lower() for c in merged.columns]
    merged.to_csv(OUTPUT_PATH, index=False)
    print(f"\nWrote {len(merged)} rows to {OUTPUT_PATH}")

    print("\nDistinct (borough, block, lot) parcels found per university:")
    parcels = merged.dropna(subset=["block", "lot"]).drop_duplicates(subset=["borough", "block", "lot", "owner_group"])
    print(parcels.groupby("owner_group")[["block"]].count().rename(columns={"block": "parcels"}))

    check = merged[(merged["borough"] == 1) & (merged["block"] == 1973) & (merged["lot"] == 1)]
    print(f"\nBlock 1973 Lot 1 (Manhattan) check: {len(check)} matching row(s)")
    if not check.empty:
        print(check[["document_id", "party_type", "name", "owner_group", "doc_type", "doc_date"]].to_string())


if __name__ == "__main__":
    main()
