"""Take the human-curated plausible name list (data/plausible_name_candidates.csv)
and find every parcel (borough/block/lot) those names are tied to in ACRIS,
then compare against the buildings already in the app's dataset (data/pt_2.csv,
via data_prep.load_data()).

Purely a research/comparison script - does not touch app.py or pt_2.csv.
"""

import sys
import pandas as pd

from data_prep import load_data

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


def load_plausible_names():
    df = pd.read_csv("data/plausible_name_candidates.csv")
    name_to_school = dict(zip(df["name"], df["school"]))
    return name_to_school


def scan_parties(name_to_school):
    names = set(name_to_school)
    matches = []
    total_rows = 0
    for i, chunk in enumerate(
        pd.read_csv(PARTIES_PATH, dtype=str, usecols=["DOCUMENT ID", "PARTY TYPE", "NAME"], chunksize=CHUNKSIZE)
    ):
        total_rows += len(chunk)
        hits = chunk[chunk["NAME"].isin(names)].copy()
        if not hits.empty:
            hits["school"] = hits["NAME"].map(name_to_school)
            matches.append(hits)
        if (i + 1) % 10 == 0:
            print(f"  parties chunk {i+1}: {total_rows:,} rows scanned, "
                  f"{sum(len(m) for m in matches):,} matches so far", file=sys.stderr)
    return pd.concat(matches, ignore_index=True) if matches else pd.DataFrame()


def scan_legals(document_ids):
    doc_id_set = set(document_ids)
    matches = []
    for i, chunk in enumerate(pd.read_csv(LEGALS_PATH, dtype=str, chunksize=CHUNKSIZE)):
        hits = chunk[chunk["DOCUMENT ID"].isin(doc_id_set)]
        if not hits.empty:
            matches.append(hits)
    return pd.concat(matches, ignore_index=True) if matches else pd.DataFrame()


def scan_master(document_ids):
    doc_id_set = set(document_ids)
    matches = []
    for i, chunk in enumerate(pd.read_csv(MASTER_PATH, dtype=str, chunksize=CHUNKSIZE)):
        hits = chunk[chunk["DOCUMENT ID"].isin(doc_id_set)]
        if not hits.empty:
            matches.append(hits)
    return pd.concat(matches, ignore_index=True) if matches else pd.DataFrame()


def main():
    name_to_school = load_plausible_names()
    print(f"Loaded {len(name_to_school):,} plausible names across "
          f"{len(set(name_to_school.values()))} schools.", file=sys.stderr)

    print("\nStep 1: scanning real_property_parties.csv for these exact names...", file=sys.stderr)
    parties_hits = scan_parties(name_to_school)
    print(f"Found {len(parties_hits):,} party rows across {parties_hits['DOCUMENT ID'].nunique():,} documents.",
          file=sys.stderr)

    doc_ids = parties_hits["DOCUMENT ID"].unique().tolist()

    print("\nStep 2: scanning real_property_legals.csv for BBLs...", file=sys.stderr)
    legals_hits = scan_legals(doc_ids)
    print(f"Found legals rows for {legals_hits['DOCUMENT ID'].nunique():,} documents.", file=sys.stderr)

    print("\nStep 3: scanning real_property_master.csv for doc type/date...", file=sys.stderr)
    master_hits = scan_master(doc_ids)
    print(f"Found master rows for {master_hits['DOCUMENT ID'].nunique():,} documents.", file=sys.stderr)

    legals_small = legals_hits[["DOCUMENT ID", "BOROUGH", "BLOCK", "LOT", "STREET NUMBER", "STREET NAME"]].drop_duplicates()
    master_small = master_hits[["DOCUMENT ID", "DOC. TYPE", "DOC. DATE", "DOC. AMOUNT"]].drop_duplicates()

    combined = parties_hits.merge(legals_small, on="DOCUMENT ID", how="left")
    combined = combined.merge(master_small, on="DOCUMENT ID", how="left")
    combined["boro_label"] = combined["BOROUGH"].map(BORO_CODE_TO_LABEL)
    combined.to_csv("data/final_search_raw.csv", index=False)
    print(f"\nWrote data/final_search_raw.csv ({len(combined):,} rows).", file=sys.stderr)

    parcels = combined.dropna(subset=["boro_label", "BLOCK", "LOT"]).drop_duplicates(
        subset=["school", "boro_label", "BLOCK", "LOT"]
    )[["school", "boro_label", "BLOCK", "LOT", "STREET NUMBER", "STREET NAME", "NAME", "PARTY TYPE", "DOC. TYPE", "DOC. DATE"]]
    parcels["BLOCK"] = parcels["BLOCK"].astype(int)
    parcels["LOT"] = parcels["LOT"].astype(int)
    parcels.to_csv("data/final_search_parcels.csv", index=False)
    print(f"Wrote data/final_search_parcels.csv ({len(parcels):,} distinct school/BBL rows).", file=sys.stderr)

    # Compare against the app's current buildings dataset.
    buildings, _ = load_data()
    buildings["block"] = buildings["block"].astype(int)
    buildings["lot"] = buildings["lot"].astype(int)
    current_bbls = set(
        zip(buildings["owner_group"], buildings["boro_label"], buildings["block"], buildings["lot"])
    )

    parcels["is_new"] = parcels.apply(
        lambda r: (r["school"], r["boro_label"], r["BLOCK"], r["LOT"]) not in current_bbls, axis=1
    )

    print("\n=== Comparison vs. current 238-building dataset ===", file=sys.stderr)
    for school, g in parcels.groupby("school"):
        total = len(g)
        new = g["is_new"].sum()
        print(f"{school}: {total} distinct parcels found via ACRIS search, {new} not in current dataset, "
              f"{total - new} already known", file=sys.stderr)

    parcels.to_csv("data/final_search_parcels.csv", index=False)


if __name__ == "__main__":
    main()
