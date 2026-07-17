"""Builds the ACRIS-only extension to the buildings/parties dataset:
data/acris_extension_buildings.csv and data/acris_extension_parties.csv.

For every "new" parcel identified in data/final_search_parcels.csv (a
borough/block/lot tied to one of the six universities that isn't already in
pt_2.csv), this pulls EVERY document ACRIS has on file for that parcel (not
just the one that surfaced it in the name search) and every party on those
documents - mirroring how the original pt_1/pt_2 pipeline builds a full
deed/mortgage history per building, just keyed off ACRIS block/lot directly
instead of an HPD registration.

Run once to (re)generate the two extension CSVs; data_prep.py picks them up
automatically on next app start.
"""

import sys
import pandas as pd

LEGALS_PATH = "data/real_property_legals.csv"
PARTIES_PATH = "data/real_property_parties.csv"
CHUNKSIZE = 1_000_000

LEGALS_RENAME = {
    "DOCUMENT ID": "document_id", "BOROUGH": "borough", "BLOCK": "block", "LOT": "lot",
    "STREET NUMBER": "street_number", "STREET NAME": "street_name", "PROPERTY TYPE": "property_type",
}
PARTIES_RENAME = {
    "DOCUMENT ID": "document_id", "PARTY TYPE": "party_type", "NAME": "name",
    "ADDRESS 1": "address_1", "ADDRESS 2": "address_2", "COUNTRY": "country",
    "CITY": "city", "STATE": "state", "ZIP": "zip",
}

BORO_LABEL_TO_CODE = {
    "Manhattan": "1",
    "Bronx": "2",
    "Brooklyn": "3",
    "Queens": "4",
    "Staten Island": "5",
}

# Raw corporationname string per school, deliberately chosen to be an EXACT
# existing key in data_prep.OWNER_MAP, so these new rows resolve to the same
# owner_group/owner_display as the HPD-sourced rows without touching
# OWNER_MAP at all. The real ACRIS party name (whatever variant spelling
# matched) is preserved separately in the parties table's "name" column.
CANONICAL_CORPORATIONNAME = {
    "Columbia University": "COLUMBIA UNIVERSITY",
    "New York University": "NEW YORK UNIVERSITY",
    "Pratt Institute": "PRATT INSTITUTE",
    "Fordham University": "FORDHAM UNIVERSITY",
    "The New School": "THE NEW SCHOOL",
    "St. John's University": "ST JOHNS UNIVERSITY, NEW YORK",
}


def load_new_parcels():
    df = pd.read_csv("data/final_search_parcels.csv")
    new = df[df["is_new"]].copy()
    new["borough_code"] = new["boro_label"].map(BORO_LABEL_TO_CODE)
    new["bbl"] = list(zip(new["borough_code"], new["BLOCK"].astype(str), new["LOT"].astype(str)))
    # A BBL could in principle appear twice if two schools' name searches
    # both matched documents on it - keep first, note the rest.
    dupes = new[new.duplicated("bbl", keep=False)]
    if not dupes.empty:
        print(f"  ! {dupes['bbl'].nunique()} BBL(s) matched more than one school - keeping first occurrence:",
              file=sys.stderr)
        print(dupes[["school", "boro_label", "BLOCK", "LOT"]].to_string(index=False), file=sys.stderr)
    new = new.drop_duplicates("bbl", keep="first").reset_index(drop=True)
    return new


def scan_legals_for_bbls(bbl_set):
    """Every document tied to any of these BBLs, plus the most complete
    street number/name we can find for each BBL (some legals rows have
    blank street fields even when others for the same BBL don't)."""
    bbl_to_doc_ids = {bbl: set() for bbl in bbl_set}
    bbl_to_street = {}
    bbl_to_proptype = {}

    total_rows = 0
    for i, chunk in enumerate(pd.read_csv(LEGALS_PATH, dtype=str, chunksize=CHUNKSIZE)):
        total_rows += len(chunk)
        chunk = chunk.rename(columns=LEGALS_RENAME)
        chunk = chunk.assign(bbl_key=list(zip(chunk["borough"], chunk["block"], chunk["lot"])))
        hits = chunk[chunk["bbl_key"].isin(bbl_set)]
        for row in hits.itertuples(index=False):
            bbl = row.bbl_key
            bbl_to_doc_ids[bbl].add(row.document_id)
            if bbl not in bbl_to_street and isinstance(row.street_name, str) and row.street_name.strip():
                bbl_to_street[bbl] = (row.street_number, row.street_name)
            if bbl not in bbl_to_proptype and isinstance(row.property_type, str) and row.property_type.strip():
                bbl_to_proptype[bbl] = row.property_type
        if (i + 1) % 20 == 0:
            found = sum(len(v) for v in bbl_to_doc_ids.values())
            print(f"  legals chunk {i+1}: {total_rows:,} rows scanned, {found:,} doc-id hits so far", file=sys.stderr)

    return bbl_to_doc_ids, bbl_to_street, bbl_to_proptype


def scan_parties_for_docs(doc_id_set):
    matches = []
    total_rows = 0
    for i, chunk in enumerate(pd.read_csv(PARTIES_PATH, dtype=str, chunksize=CHUNKSIZE)):
        total_rows += len(chunk)
        chunk = chunk.rename(columns=PARTIES_RENAME)
        hits = chunk[chunk["document_id"].isin(doc_id_set)]
        if not hits.empty:
            matches.append(hits[list(PARTIES_RENAME.values())])
        if (i + 1) % 10 == 0:
            print(f"  parties chunk {i+1}: {total_rows:,} rows scanned, "
                  f"{sum(len(m) for m in matches):,} matches so far", file=sys.stderr)
    return pd.concat(matches, ignore_index=True) if matches else pd.DataFrame(columns=list(PARTIES_RENAME.values()))


def main():
    new_parcels = load_new_parcels()
    print(f"Loaded {len(new_parcels)} new parcels to extend the dataset with.", file=sys.stderr)

    bbl_set = set(new_parcels["bbl"])
    print("\nStep 1: scanning real_property_legals.csv for ALL documents on these BBLs...", file=sys.stderr)
    bbl_to_doc_ids, bbl_to_street, bbl_to_proptype = scan_legals_for_bbls(bbl_set)

    all_doc_ids = set()
    for doc_ids in bbl_to_doc_ids.values():
        all_doc_ids.update(doc_ids)
    print(f"Found {len(all_doc_ids):,} distinct documents across all new parcels.", file=sys.stderr)

    print("\nStep 2: scanning real_property_parties.csv for ALL parties on those documents...", file=sys.stderr)
    parties_raw = scan_parties_for_docs(all_doc_ids)
    print(f"Found {len(parties_raw):,} party rows.", file=sys.stderr)

    # --- Build extension_buildings.csv ---
    building_rows = []
    for row in new_parcels.itertuples(index=False):
        bbl = row.bbl
        street_num, street_name = bbl_to_street.get(bbl, (None, None))
        if street_name:
            address = f"{street_num} {street_name}".strip() if street_num else street_name.strip()
            building_address = f"{address}, {row.boro_label}, NY"
        else:
            building_address = f"Block {row.BLOCK} Lot {row.LOT}, {row.boro_label}, NY"
        parcel_key = f"{row.borough_code}-{row.BLOCK}-{row.LOT}"
        building_rows.append({
            "parcel_key": parcel_key,
            "corporationname": CANONICAL_CORPORATIONNAME[row.school],
            "building_address": building_address,
            "boro": row.boro_label.upper(),
            "block": row.BLOCK,
            "lot": row.LOT,
            "property_type": bbl_to_proptype.get(bbl),
        })
    buildings_ext = pd.DataFrame(building_rows).drop_duplicates(subset="parcel_key")
    buildings_ext.to_csv("data/acris_extension_buildings.csv", index=False)
    print(f"\nWrote data/acris_extension_buildings.csv ({len(buildings_ext)} rows).", file=sys.stderr)

    # --- Build extension_parties.csv ---
    doc_id_to_parcel_keys = {}
    for row in new_parcels.itertuples(index=False):
        parcel_key = f"{row.borough_code}-{row.BLOCK}-{row.LOT}"
        for doc_id in bbl_to_doc_ids[row.bbl]:
            doc_id_to_parcel_keys.setdefault(doc_id, []).append(parcel_key)

    party_rows = []
    for row in parties_raw.itertuples(index=False):
        for parcel_key in doc_id_to_parcel_keys.get(row.document_id, []):
            party_rows.append({
                "parcel_key": parcel_key,
                "document_id": row.document_id,
                "party_type": row.party_type,
                "name": row.name,
                "address_1": row.address_1,
                "address_2": row.address_2,
                "city": row.city,
                "state": row.state,
                "zip": row.zip,
                "country": row.country,
            })
    parties_ext = pd.DataFrame(party_rows).drop_duplicates()
    parties_ext.to_csv("data/acris_extension_parties.csv", index=False)
    print(f"Wrote data/acris_extension_parties.csv ({len(parties_ext)} rows).", file=sys.stderr)


if __name__ == "__main__":
    main()
