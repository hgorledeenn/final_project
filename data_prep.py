"""Loads and cleans data/pt_2.csv into buildings + parties tables for the Flask app."""

import re
import pandas as pd

CSV_PATH = "data/pt_2.csv"
COORDS_PATH = "data/building_coords.csv"

# Distinct color per owner group, used for map markers.
OWNER_COLORS = {
    "Columbia University": "#1d4ed8",
    "New York University": "#7c3aed",
    "Pratt Institute": "#0f9d58",
    "Fordham University": "#dc2626",
    "The New School": "#ea580c",
    "St. John's University": "#0891b2",
}
DEFAULT_OWNER_COLOR = "#10131a"

# Word-boundary phrases that identify the university itself (as opposed to
# some other grantor/grantee) when it shows up as a named party on a
# document. Used to estimate acquisition years (_estimate_acquired_years)
# and for the comprehensive ACRIS parcel search (find_university_properties.py).
#
# These are deliberately full institutional phrases, not bare surnames or
# generic words - e.g. "COLUMBIA" alone also matches unrelated entities like
# "Columbia Title Co." or "Columbia Realty LLC" citywide, and "PRATT"/
# "FORDHAM"/"ST JOHN" are common surnames, neighborhood, and street names.
# An earlier version of this list used single generic words and produced
# tens of thousands of false-positive parcel matches - see the comprehensive
# search script's git history/output for that failure mode.
OWNER_NAME_ALIASES = {
    "Columbia University": ["COLUMBIA UNIV", "COLUMBIA CLLG", "COLUMBIA COLLEGE IN THE CITY"],
    "New York University": ["NEW YORK UNIVERSITY", "NYU"],
    "Pratt Institute": ["PRATT INSTITUTE", "PRATT INSTUTUTE"],
    "Fordham University": ["FORDHAM UNIVERSITY", "FORDHAM UNIV"],
    "The New School": ["NEW SCHOOL"],
    "St. John's University": ["ST JOHNS UNIVERSITY", "ST. JOHNS UNIVERSITY", "SAINT JOHNS UNIVERSITY", "ST JOHN'S UNIVERSITY"],
}


def name_matches_owner(name, owner_group):
    """Word-boundary check: does `name` contain one of owner_group's aliases
    as a whole phrase, not just as a substring of some unrelated word?
    """
    if not isinstance(name, str):
        return False
    upper = name.upper()
    for alias in OWNER_NAME_ALIASES.get(owner_group, []):
        if re.search(r"\b" + re.escape(alias) + r"\b", upper):
            return True
    return False

# Maps every raw corporationname spelling/typo found in the data to a
# (owner group, cleaned display name) pair. Distinct legal entities (e.g. NYU
# itself vs. its real-estate subsidiary vs. its law-school foundation) are
# kept separate in "display name" since that distinction is often the story,
# but grouped under one "owner group" for browsing/filtering.
OWNER_MAP = {
    "TRUSTEES OF COLUMBIA UNIVERSITY": ("Columbia University", "Trustees of Columbia University"),
    "TRUSTEE OF COLUMBIA UNIVERSITY": ("Columbia University", "Trustees of Columbia University"),
    "TRUSTEES OF COLUMBIA UNIVERSITY CIT": ("Columbia University", "Trustees of Columbia University"),
    "THE TRUSTEES OF COLUMBIA UNIVERSITY": ("Columbia University", "Trustees of Columbia University"),
    "TRUSTEES OF COLUMBIA UNIVERSITY`": ("Columbia University", "Trustees of Columbia University"),
    "COLUMBIA UNIVERSITY": ("Columbia University", "Columbia University"),
    "TEACHERS COLLEGE-COLUMBIA UNIV": ("Columbia University", "Teachers College, Columbia University"),
    "NEW YORK UNIVERSITY": ("New York University", "New York University"),
    "New York University": ("New York University", "New York University"),
    "NEW YORK UNIVESITY": ("New York University", "New York University"),
    "NYU REAL ESTATE CORP": ("New York University", "NYU Real Estate Corp"),
    "NYU REAL ESATE CORP": ("New York University", "NYU Real Estate Corp"),
    "NYU School of Law Foundation": ("New York University", "NYU School of Law Foundation"),
    "NYU SCHOOL OF LAW FOUNDATION": ("New York University", "NYU School of Law Foundation"),
    "PRATT INSTITUTE": ("Pratt Institute", "Pratt Institute"),
    "PRATT INSTUTUTE FACILITIES DEPARTMENT": ("Pratt Institute", "Pratt Institute Facilities Department"),
    "FORDHAM UNIVERSITY": ("Fordham University", "Fordham University"),
    "THE NEW SCHOOL": ("The New School", "The New School"),
    "ST JOHNS UNIVERSITY, NEW YORK": ("St. John's University", "St. John's University"),
    "St. Johns University": ("St. John's University", "St. John's University"),
    "ST. JOHNS UNIVERSITY": ("St. John's University", "St. John's University"),
}

# Official ACRIS "Property Types Codes" reference table
# (https://data.cityofnewyork.us/City-Government/ACRIS-property-Types-Codes/exn5-fbir)
PROPERTY_TYPE_MAP = {
    "CA": "Adjacent Condominium Unit to Be Combined",
    "FS": "4 Family with Store/Office",
    "F5": "5-6 Family with Store/Office",
    "F1": "1-3 Family with Store/Office",
    "F4": "4-6 Family with Store/Office",
    "D1": "Dwelling Only - 1 Family",
    "D2": "Dwelling Only - 2 Family",
    "D3": "Dwelling Only - 3 Family",
    "D4": "Dwelling Only - 4 Family",
    "D5": "Dwelling Only - 5 Family",
    "D6": "Dwelling Only - 6 Family",
    "SC": "Single Residential Condo Unit",
    "MC": "Multiple Residential Condo Units",
    "SP": "Single Residential Coop Unit",
    "MP": "Multiple Residential Coop Unit",
    "CC": "Commercial Condo Unit(s)",
    "AP": "Apartment Building",
    "OF": "Office Building",
    "IB": "Industrial Building",
    "RB": "Retail Building",
    "VL": "Vacant Land",
    "MU": "Multiple Properties",
    "OT": "Other",
    "PA": "Pre-ACRIS",
    "MR": "Maids Room",
    "SR": "Storage Room",
    "PS": "Parking Space",
    "BS": "Bulk Sale of Condominiums",
    "RS": "Religious Structure",
    "CK": "Condo Unit Without Kitchen",
    "RE": "Real Estate Investment Trust",
    "R1": "Real Est. Inv. Tr. - 1,2,3 Family",
    "R2": "Real Est. Inv. Tr. - 4-6 Family and Comm.",
    "RP": "1-2 Family with Attached Garage and/or Vacant Land",
    "GR": "Garage, 1 or 2 Family Only",
    "NA": "Not Applicable",
    "EA": "Entertainment/Amusement",
    "UT": "Utility",
    "VR": "Residential Vacant Land",
    "VN": "Non-Residential Vacant Land",
    "CP": "Commercial Coop Unit(s)",
    "CR": "Commercial Real Estate",
    "TS": "Timeshare",
    "RG": "1-2 Family Dwelling with Attached Garage",
    "RV": "1-2 Family Dwelling with Vacant Land",
    "SA": "Adjacent Cooperative Unit to Be Combined",
    "SM": "Under $1M Condo in Combined Sale of $1M+",
    "HC": "HDFC Exemption Property",
}

# ACRIS convention: Party Type 1 is generally the grantor/mortgagor (seller or
# borrower on the recorded document), Party Type 2 the grantee/mortgagee
# (buyer or lender), and Party Type 3 an additional party (e.g. a trustee or
# co-borrower). This dataset doesn't include the document type itself, so we
# label these generically rather than claiming a specific deed/mortgage role.
PARTY_TYPE_LABELS = {
    1: "Party 1 (e.g. seller/borrower)",
    2: "Party 2 (e.g. buyer/lender)",
    3: "Party 3 (additional party)",
}

ZIP_RE = re.compile(r"(\d{5})\s*$")
DOC_ID_DATE_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})\d+$")


def _extract_zip(address):
    if not isinstance(address, str):
        return None
    match = ZIP_RE.search(address)
    return match.group(1) if match else None


def _clean_zip(zip_value):
    if not isinstance(zip_value, str):
        return None
    digits = re.sub(r"\D", "", zip_value)[:5]
    return digits if len(digits) == 5 else None


def _normalize_name(name):
    if not isinstance(name, str):
        return name
    return re.sub(r"\s+", " ", name).strip()


def _recorded_date(document_id):
    if not isinstance(document_id, str):
        return None
    match = DOC_ID_DATE_RE.match(document_id)
    if not match:
        return None
    year, month, day = match.groups()
    if not (1966 <= int(year) <= 2100):
        return None
    return f"{year}-{month}-{day}"


def _estimate_acquired_years(buildings, parties):
    """Rough proxy for when a university acquired each parcel: the earliest
    year the university's own name appears as the buyer/borrower (ACRIS
    Party 2 convention) on a document tied to that building's block/lot.

    This is an approximation, not a verified acquisition date - the dataset
    has no document-type field, so it can't tell a purchase deed apart from
    a refinancing or correction filing, and it only catches parties on
    documents that are digitized in ACRIS (digital coverage for many NYC
    boroughs really only gets dense from the early-to-mid 2000s on). Most
    older acquisitions won't get an estimate at all.
    """
    merged = parties.merge(buildings[["buildingid", "owner_group"]], on="buildingid", how="left")
    merged = merged[(merged["party_type"] == 2) & merged["recorded_date"].notna()]

    is_owner_party = merged.apply(lambda row: name_matches_owner(row["name"], row["owner_group"]), axis=1)
    merged = merged[is_owner_party]
    earliest = merged.groupby("buildingid")["recorded_date"].min()
    return earliest.str[:4].astype(int)


def load_data():
    df = pd.read_csv(CSV_PATH, dtype={"zip": "string"})

    owner_groups = df["corporationname"].map(lambda n: OWNER_MAP.get(n, (n.title(), n.title()))[0])
    owner_display = df["corporationname"].map(lambda n: OWNER_MAP.get(n, (n.title(), n.title()))[1])
    df = df.assign(owner_group=owner_groups, owner_display=owner_display)

    df["property_type_label"] = df["property_type"].map(PROPERTY_TYPE_MAP).fillna(df["property_type"])
    df["building_zip"] = df["building_address"].map(_extract_zip)
    df["boro_label"] = df["boro"].str.title()

    building_cols = [
        "buildingid", "registrationid", "owner_group", "owner_display",
        "building_address", "boro_label", "block", "lot", "bin",
        "property_type", "property_type_label", "building_zip",
    ]
    buildings = (
        df[building_cols]
        .drop_duplicates(subset="buildingid")
        .sort_values(["owner_group", "boro_label", "building_address"])
        .reset_index(drop=True)
    )

    party_cols = [
        "buildingid", "document_id", "party_type", "name", "address_1",
        "address_2", "city", "state", "zip", "country",
    ]
    parties = df[party_cols].dropna(subset=["name"]).drop_duplicates().copy()
    parties["name"] = parties["name"].map(_normalize_name)
    parties["party_type_label"] = parties["party_type"].map(PARTY_TYPE_LABELS).fillna("Party")
    parties["zip"] = parties["zip"].map(_clean_zip)
    parties["recorded_date"] = parties["document_id"].map(_recorded_date)
    parties = parties.drop_duplicates().sort_values(
        ["buildingid", "recorded_date", "party_type"], na_position="last"
    ).reset_index(drop=True)

    try:
        coords = pd.read_csv(COORDS_PATH)
        buildings = buildings.merge(coords[["buildingid", "lat", "lon"]], on="buildingid", how="left")
    except FileNotFoundError:
        buildings["lat"] = None
        buildings["lon"] = None

    buildings["marker_color"] = buildings["owner_group"].map(OWNER_COLORS).fillna(DEFAULT_OWNER_COLOR)

    acquired_years = _estimate_acquired_years(buildings, parties)
    buildings["acquired_year"] = buildings["buildingid"].map(acquired_years)

    buildings = buildings.astype(object).where(pd.notnull(buildings), None)
    parties = parties.astype(object).where(pd.notnull(parties), None)

    return buildings, parties


def build_people(buildings, parties):
    """One row per unique name across all deed/mortgage records: which
    institutions' buildings they're tied to, and how many properties/
    documents they show up on. Grouping is by exact name as recorded in
    ACRIS, so minor variations in punctuation or multi-person entries
    (e.g. "SCHWARTZ, BONNIE SUE GONG SZETO &") won't be merged together -
    that kind of entity resolution is beyond what this dataset supports.
    """
    merged = parties.merge(buildings[["buildingid", "owner_group"]], on="buildingid", how="left")

    counts = merged.groupby("name").agg(
        properties=("buildingid", "nunique"),
        documents=("document_id", "nunique"),
    )
    owner_groups = merged.groupby("name")["owner_group"].apply(
        lambda s: sorted({v for v in s if v})
    )
    roles = merged.groupby("name")["party_type_label"].apply(
        lambda s: sorted({v for v in s if v})
    )

    people = counts.join(owner_groups.rename("owner_groups")).join(roles.rename("roles"))
    people = people.reset_index()
    people["owner_count"] = people["owner_groups"].map(len)
    people["owners_display"] = people["owner_groups"].map(lambda l: ", ".join(l) if l else "—")
    people["roles_display"] = people["roles"].map(lambda l: ", ".join(r.split(" (")[0] for r in l))

    people = people.sort_values(
        ["properties", "documents", "name"], ascending=[False, False, True]
    ).reset_index(drop=True)
    people["person_id"] = people.index

    return people
