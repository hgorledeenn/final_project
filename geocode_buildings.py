"""One-off script: geocodes each building address via NYC Planning Labs'
free GeoSearch API (https://geosearch.planninglabs.nyc) and caches the
results to data/building_coords.csv so the Flask app never has to hit the
network at request time. Safe to re-run - already-geocoded buildings are
skipped, so an interrupted run can just be resumed.
"""

import csv
import os
import time

import requests

from data_prep import load_data

GEOSEARCH_URL = "https://geosearch.planninglabs.nyc/v2/search"
OUTPUT_PATH = "data/building_coords.csv"
REQUEST_DELAY_SECONDS = 0.3
MAX_RETRIES = 3
FIELDNAMES = ["buildingid", "lat", "lon", "confidence", "match_type"]


def _load_existing():
    if not os.path.exists(OUTPUT_PATH):
        return {}
    with open(OUTPUT_PATH, newline="") as f:
        return {int(row["buildingid"]): row for row in csv.DictReader(f)}


def geocode(address):
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(GEOSEARCH_URL, params={"text": address, "size": 1}, timeout=15)
            resp.raise_for_status()
            features = resp.json().get("features", [])
            if not features:
                return None
            feature = features[0]
            lon, lat = feature["geometry"]["coordinates"]
            props = feature["properties"]
            return {
                "lat": lat,
                "lon": lon,
                "confidence": props.get("confidence"),
                "match_type": props.get("match_type"),
            }
        except requests.exceptions.RequestException as e:
            last_error = e
            time.sleep(1.5 * attempt)
    print(f"  ! giving up after {MAX_RETRIES} attempts: {last_error}")
    return None


def main():
    buildings, _ = load_data()
    existing = _load_existing()

    is_new_file = not os.path.exists(OUTPUT_PATH)
    f = open(OUTPUT_PATH, "a", newline="")
    writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
    if is_new_file:
        writer.writeheader()

    done_ids = set(existing.keys())
    total = len(buildings)
    geocoded_now = 0
    failed = []

    try:
        for i, building in enumerate(buildings.to_dict(orient="records"), start=1):
            building_id = building["buildingid"]
            if building_id in done_ids:
                continue

            result = geocode(building["building_address"])
            if result is None:
                failed.append(building["building_address"])
                print(f"[{i}/{total}] NO MATCH: {building['building_address']}")
            else:
                writer.writerow({"buildingid": building_id, **result})
                f.flush()
                geocoded_now += 1
                print(f"[{i}/{total}] {building['building_address']} -> {result['lat']}, {result['lon']}")

            time.sleep(REQUEST_DELAY_SECONDS)
    finally:
        f.close()

    print(f"\nDone. Geocoded {geocoded_now} new building(s) this run.")
    if failed:
        print(f"{len(failed)} address(es) had no match:")
        for address in failed:
            print(f"  - {address}")


if __name__ == "__main__":
    main()
