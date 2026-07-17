"""Cast a wide net over real_property_parties.csv NAME values, mirroring a
manual "contains: columbia" search on the Open Data portal - no word-boundary
narrowing, no pre-decided alias list. Just: which distinct NAME spellings
contain a broad keyword for each school, and how often does each show up?

Output is for a human to read and decide what's really the university vs.
noise (title companies, unrelated LLCs, street names, etc.) - nothing here
gets merged into the app's dataset automatically.
"""

import sys
import pandas as pd

PARTIES_PATH = "data/real_property_parties.csv"
CHUNKSIZE = 1_000_000

BROAD_KEYWORDS = {
    "Columbia University": ["COLUMBIA"],
    "New York University": ["NYU", "NEW YORK UNIVERSITY"],
    "Pratt Institute": ["PRATT"],
    "Fordham University": ["FORDHAM"],
    "The New School": ["NEW SCHOOL"],
    "St. John's University": ["ST JOHN", "SAINT JOHN"],
}

# name -> {"school": ..., "keyword": ..., "row_count": int, "doc_ids": set()}
seen = {}


def record(school, keyword, sub):
    for name, group in sub.groupby("NAME"):
        key = (school, name)
        entry = seen.setdefault(key, {"school": school, "keyword": keyword, "row_count": 0, "doc_ids": set()})
        entry["row_count"] += len(group)
        entry["doc_ids"].update(group["DOCUMENT ID"].tolist())


def main():
    total_rows = 0
    for i, chunk in enumerate(
        pd.read_csv(PARTIES_PATH, dtype=str, usecols=["DOCUMENT ID", "NAME"], chunksize=CHUNKSIZE)
    ):
        total_rows += len(chunk)
        upper = chunk["NAME"].str.upper()
        for school, keywords in BROAD_KEYWORDS.items():
            for kw in keywords:
                mask = upper.str.contains(kw, na=False, regex=False)
                if mask.any():
                    record(school, kw, chunk[mask])
        if (i + 1) % 5 == 0:
            print(f"  chunk {i+1}: {total_rows:,} rows scanned, {len(seen):,} distinct names so far", file=sys.stderr)

    rows = []
    for (school, name), info in seen.items():
        rows.append({
            "school": school,
            "matched_keyword": info["keyword"],
            "name": name,
            "row_count": info["row_count"],
            "doc_count": len(info["doc_ids"]),
        })

    out = pd.DataFrame(rows).sort_values(["school", "row_count"], ascending=[True, False])
    out.to_csv("data/broad_name_candidates.csv", index=False)
    print(f"\nWrote data/broad_name_candidates.csv ({len(out):,} distinct name/school rows).", file=sys.stderr)
    print("\nDistinct name spellings found per school:", file=sys.stderr)
    print(out.groupby("school").size(), file=sys.stderr)


if __name__ == "__main__":
    main()
