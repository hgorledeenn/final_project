import pandas as pd
from flask import Flask, abort, render_template, request

from data_prep import build_people, load_data

app = Flask(__name__)
BUILDINGS, PARTIES = load_data()
PEOPLE = build_people(BUILDINGS, PARTIES)


def _sorted_options(series):
    return sorted(series.dropna().unique().tolist())


@app.route("/")
def dashboard():
    total_buildings = len(BUILDINGS)
    total_owners = BUILDINGS["owner_group"].nunique()
    total_parties = PARTIES["name"].nunique()

    by_owner = BUILDINGS["owner_group"].value_counts()
    by_boro = BUILDINGS["boro_label"].value_counts()
    by_property_type = BUILDINGS["property_type_label"].value_counts().head(8)

    return render_template(
        "dashboard.html",
        total_buildings=total_buildings,
        total_owners=total_owners,
        total_parties=total_parties,
        owner_labels=by_owner.index.tolist(),
        owner_values=by_owner.values.tolist(),
        boro_labels=by_boro.index.tolist(),
        boro_values=by_boro.values.tolist(),
        property_labels=by_property_type.index.tolist(),
        property_values=by_property_type.values.tolist(),
    )


@app.route("/buildings")
def buildings_list():
    owner = request.args.get("owner", "")
    boro = request.args.get("boro", "")
    property_type = request.args.get("property_type", "")
    search = request.args.get("q", "").strip().lower()

    rows = BUILDINGS
    if owner:
        rows = rows[rows["owner_group"] == owner]
    if boro:
        rows = rows[rows["boro_label"] == boro]
    if property_type:
        rows = rows[rows["property_type_label"] == property_type]
    if search:
        rows = rows[rows["building_address"].str.lower().str.contains(search, na=False)]

    return render_template(
        "buildings.html",
        buildings=rows.to_dict(orient="records"),
        owners=_sorted_options(BUILDINGS["owner_group"]),
        boros=_sorted_options(BUILDINGS["boro_label"]),
        property_types=_sorted_options(BUILDINGS["property_type_label"]),
        selected_owner=owner,
        selected_boro=boro,
        selected_property_type=property_type,
        search=request.args.get("q", ""),
        result_count=len(rows),
        total_count=len(BUILDINGS),
    )


@app.route("/map")
def map_view():
    mappable = BUILDINGS.dropna(subset=["lat", "lon"])
    points = [
        {
            "id": b["buildingid"],
            "lat": b["lat"],
            "lon": b["lon"],
            "color": b["marker_color"],
            "address": b["building_address"],
            "owner": b["owner_display"],
            "owner_group": b["owner_group"],
            "boro": b["boro_label"],
            "property_type": b["property_type_label"],
        }
        for b in mappable.to_dict(orient="records")
    ]

    legend = (
        BUILDINGS[["owner_group", "marker_color"]]
        .drop_duplicates()
        .sort_values("owner_group")
        .to_dict(orient="records")
    )

    return render_template(
        "map.html",
        points=points,
        legend=legend,
        mapped_count=len(points),
        total_count=len(BUILDINGS),
        owners=_sorted_options(BUILDINGS["owner_group"]),
        boros=_sorted_options(BUILDINGS["boro_label"]),
        property_types=_sorted_options(BUILDINGS["property_type_label"]),
    )


@app.route("/people")
def people_list():
    owner = request.args.get("owner", "")
    search = request.args.get("q", "").strip().lower()
    multi_only = request.args.get("multi") == "1"

    rows = PEOPLE
    if owner:
        rows = rows[rows["owner_groups"].map(lambda owners: owner in owners)]
    if search:
        rows = rows[rows["name"].str.lower().str.contains(search, na=False)]
    if multi_only:
        rows = rows[rows["owner_count"] > 1]

    result_count = len(rows)
    display_limit = 500
    rows = rows.head(display_limit)

    return render_template(
        "people.html",
        people=rows.to_dict(orient="records"),
        owners=_sorted_options(BUILDINGS["owner_group"]),
        selected_owner=owner,
        search=request.args.get("q", ""),
        multi_only=multi_only,
        result_count=result_count,
        shown_count=len(rows),
        total_count=len(PEOPLE),
    )


@app.route("/people/<int:person_id>")
def person_detail(person_id):
    person_rows = PEOPLE[PEOPLE["person_id"] == person_id]
    if person_rows.empty:
        abort(404)
    person = person_rows.iloc[0].to_dict()

    related = PARTIES[PARTIES["name"] == person["name"]].merge(
        BUILDINGS[["buildingid", "building_address", "owner_display", "owner_group", "boro_label"]],
        on="buildingid",
        how="left",
    )

    properties = []
    for building_id, group in related.groupby("buildingid", sort=False):
        first = group.iloc[0]
        properties.append(
            {
                "buildingid": building_id,
                "building_address": first["building_address"],
                "owner_display": first["owner_display"],
                "boro_label": first["boro_label"],
                "roles": sorted({r for r in group["party_type_label"] if r}),
                "documents": group["document_id"].nunique(),
            }
        )
    properties.sort(key=lambda p: p["building_address"] or "")

    documents = related[["document_id", "recorded_date", "party_type_label", "building_address", "buildingid"]]
    documents = documents.drop_duplicates().to_dict(orient="records")
    documents.sort(key=lambda d: d["recorded_date"] or "", reverse=True)

    return render_template("person_detail.html", person=person, properties=properties, documents=documents)


@app.route("/buildings/<int:building_id>")
def building_detail(building_id):
    building_rows = BUILDINGS[BUILDINGS["buildingid"] == building_id]
    if building_rows.empty:
        abort(404)
    building = building_rows.iloc[0].to_dict()

    related = PARTIES[PARTIES["buildingid"] == building_id]
    documents = []
    for document_id, group in related.groupby("document_id", sort=False):
        recorded_date = group["recorded_date"].iloc[0]
        documents.append(
            {
                "document_id": document_id,
                "recorded_date": None if pd.isna(recorded_date) else recorded_date,
                "parties": group.to_dict(orient="records"),
            }
        )
    documents.sort(key=lambda d: d["recorded_date"] or "", reverse=True)

    return render_template("building_detail.html", building=building, documents=documents)


if __name__ == "__main__":
    app.run(debug=True)
