"""Paddy-season NASA FIRMS fire detections, counted per district per day,
for the supply-timing forecast.

Fires are a proxy for *when* paddy is harvested and the straw lies on the
field, not for how much straw there is: enforcement has cut fire counts since
2022 while the burnt area held steady. Volume comes from district rice
production; this series supplies the timing.

Earth Engine does the counting. Each daily FIRMS image in the paddy window
(1 Sep - 31 Dec) is reduced over the FAO GAUL 2025 district polygons for
Punjab and Haryana; one season takes about 20 seconds.

    python -m forecast.firms_history --from 2001 --to 2025 --out forecast/data/fires_daily.csv
    python -m forecast.firms_history --from 2001 --to 2025 --out ... --bq parali_forecast.fires_daily
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

STATES = ("Punjab", "Haryana")
SEASON_START = "09-01"   # paddy harvest and burning run Sep-Dec
SEASON_END = "12-31"
FIRMS_SCALE_M = 1000     # FIRMS is a 1 km product
FIELDS = ("date", "state", "district", "fire_pixels")


def season_rows(year: int, project: str) -> list[dict]:
    """Daily fire-pixel counts per district for one paddy season. Districts
    with no fire on a day are omitted; the weekly series fills zeros."""
    import ee

    ee.Initialize(project=project)
    districts = (
        ee.FeatureCollection("FAO/GAUL/2025/level2")
        .filter(ee.Filter.eq("GAUL0_NAME", "India"))
        .filter(ee.Filter.inList("GAUL1_NAME", list(STATES)))
        .select(["GAUL1_NAME", "GAUL2_NAME"])
    )
    images = ee.ImageCollection("FIRMS").filterDate(f"{year}-{SEASON_START}", f"{year + 1}-01-01").select("T21")

    def per_day(img):
        fires = img.gt(0).selfMask().rename("fires")
        counted = fires.reduceRegions(collection=districts, reducer=ee.Reducer.count(), scale=FIRMS_SCALE_M)
        day = ee.Date(img.get("system:time_start")).format("YYYY-MM-dd")
        return counted.filter(ee.Filter.gt("count", 0)).map(lambda f: ee.Feature(None, {
            "date": day, "state": f.get("GAUL1_NAME"), "district": f.get("GAUL2_NAME"), "fire_pixels": f.get("count"),
        }))

    features = images.map(per_day).flatten().getInfo()["features"]
    return [{k: f["properties"][k] for k in FIELDS} for f in features]


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: (r["date"], r["state"], r["district"])))


def load_to_bigquery(rows: list[dict], table: str, project: str) -> int:
    from google.cloud import bigquery

    client = bigquery.Client(project=project)
    schema = [
        bigquery.SchemaField("date", "DATE"), bigquery.SchemaField("state", "STRING"),
        bigquery.SchemaField("district", "STRING"), bigquery.SchemaField("fire_pixels", "INT64"),
    ]
    job = client.load_table_from_json(
        rows, f"{project}.{table}",
        job_config=bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_TRUNCATE"),
    )
    job.result()
    return job.output_rows


def main(argv: list[str] | None = None) -> None:
    import firestore_store as store

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="first", type=int, default=2001)
    parser.add_argument("--to", dest="last", type=int, default=2025)
    parser.add_argument("--out", type=Path, default=Path("forecast/data/fires_daily.csv"))
    parser.add_argument("--bq", help="dataset.table to load, replacing its contents")
    args = parser.parse_args(argv)

    rows: list[dict] = []
    for year in range(args.first, args.last + 1):
        season = season_rows(year, store.PROJECT_ID)
        rows += season
        print(f"{year}: {len(season)} district-days, {sum(r['fire_pixels'] for r in season)} fire pixels", file=sys.stderr)
    write_csv(rows, args.out)
    print(f"wrote {len(rows)} rows to {args.out}")
    if args.bq:
        print(f"loaded {load_to_bigquery(rows, args.bq, store.PROJECT_ID)} rows into {args.bq}")


if __name__ == "__main__":
    main()
