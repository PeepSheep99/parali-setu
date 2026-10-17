"""Static data for the fire map on the landing page and the ops console.

Pulls, once, from Earth Engine:
- every NASA FIRMS fire pixel in Punjab and Haryana from 1 Oct to 30 Nov of a
  season, with its day (the same collection forecast/firms_history.py counts)
- Punjab and Haryana district outlines (FAO GAUL 2025), simplified for the web

and writes a compact JSON to the frontend: points as [lat, lon, day], with day
0 = 1 Oct. Real detections only; nothing is interpolated.

    python -m forecast.fire_map_data --season 2024
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import ee

from forecast.firms_history import STATES

OUT_DIR = Path(__file__).resolve().parents[2] / "parali-setu-frontend" / "data"
BBOX = [73.8, 27.6, 77.6, 32.6]          # Punjab and Haryana with a margin


def pull(season: int, project: str) -> dict:
    ee.Initialize(project=project)
    districts = (ee.FeatureCollection("FAO/GAUL/2025/level2")
                 .filter(ee.Filter.eq("GAUL0_NAME", "India"))
                 .filter(ee.Filter.inList("GAUL1_NAME", list(STATES))))
    states = districts.union(maxError=500)
    region = ee.Geometry.Rectangle(BBOX)
    start = date(season, 10, 1)
    geometry = states.geometry()

    def sample(img):
        day = ee.Date(img.get("system:time_start")).difference(ee.Date(start.isoformat()), "day").floor()
        pts = img.sample(region=geometry, scale=1000, geometries=True, dropNulls=True)
        return pts.map(lambda f: f.set("d", day))

    # Earth Engine returns at most 5,000 features per request: one request per
    # three days keeps each well under that, even at the peak.
    feats = []
    for offset in range(0, 61, 3):
        lo = ee.Date(start.isoformat()).advance(offset, "day")
        images = ee.ImageCollection("FIRMS").filterDate(lo, lo.advance(3, "day")).select("T21")
        chunk = images.map(sample).flatten().getInfo()["features"]
        feats += chunk
        print(f"day {offset:>2}: {len(chunk)} fire pixels", flush=True)
    points = sorted({(round(f["geometry"]["coordinates"][1], 3), round(f["geometry"]["coordinates"][0], 3),
                      int(f["properties"]["d"])) for f in feats if f["properties"]["d"] < 61},
                    key=lambda p: (p[2], p[0], p[1]))

    simple = districts.map(lambda f: f.simplify(1500)).select(["GAUL1_NAME", "GAUL2_NAME"]).getInfo()["features"]
    outlines = []
    def polygons(geom):
        # Simplifying can turn a district into a GeometryCollection; take its polygons.
        if geom["type"] == "Polygon":
            return [geom["coordinates"]]
        if geom["type"] == "MultiPolygon":
            return geom["coordinates"]
        if geom["type"] == "GeometryCollection":
            return [p for g in geom["geometries"] for p in polygons(g)]
        return []

    for f in simple:
        rings = [[[round(x, 3), round(y, 3)] for x, y in poly[0]] for poly in polygons(f["geometry"])]
        if not rings:
            raise ValueError(f"no outline for {f['properties']['GAUL2_NAME']}")
        outlines.append({"state": f["properties"]["GAUL1_NAME"], "district": f["properties"]["GAUL2_NAME"], "rings": rings})
    return {"season": season, "start": start.isoformat(), "days": 61, "source": "NASA FIRMS (MODIS) via Google Earth Engine; FAO GAUL 2025 districts",
            "points": [list(p) for p in points], "districts": outlines}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=2024)
    parser.add_argument("--project", default="parali-setu-aibuildercup-2026")
    args = parser.parse_args()
    data = pull(args.season, args.project)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"fires_{args.season}.json"
    path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(f"{len(data['points'])} fire points, {len(data['districts'])} districts -> {path} ({path.stat().st_size // 1024} KB)")
