"""Check: is "straight line x 1.3 at 30 km/h" a fair stand-in for Punjab's roads?

The routing model (scheduler.py) prices travel as straight-line distance x
ROAD_FACTOR at TRAVEL_KMH. This asks the Google Maps Routes API
(computeRouteMatrix, driving, no traffic) for 100 real depot-to-farm trips
-- 20 farms per depot, placed like the planner benchmark's farms -- and
compares distance and time with what the model assumed.

    python -m bench.bench_routes             # writes bench/results/routes.json

Uses the gcloud user's credentials; about 100 route elements (well inside the
Maps Platform monthly free usage).
"""
from __future__ import annotations

import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from geo import haversine_km  # noqa: E402
from scheduler import ROAD_FACTOR, TRAVEL_KMH  # noqa: E402

OUT = ROOT / "bench" / "results" / "routes.json"
URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
PROJECT = "ai-builder-cup-aidatlas"


def token() -> str:
    return subprocess.run("gcloud auth print-access-token", shell=True, capture_output=True, text=True, check=True).stdout.strip()


def waypoint(lat, lon):
    return {"waypoint": {"location": {"latLng": {"latitude": lat, "longitude": lon}}}}


def run():
    from bench.bench_planners import build_depots_and_crews, build_farms
    depots, _ = build_depots_and_crews()
    farms = build_farms(400, 11, depots)
    headers = {"Authorization": f"Bearer {token()}", "X-Goog-User-Project": PROJECT, "Content-Type": "application/json",
               "X-Goog-FieldMask": "originIndex,destinationIndex,distanceMeters,duration,condition"}
    rows = []
    with httpx.Client(timeout=60) as client:
        for d in depots:
            mine = [f for f in farms if f.depot_id == d["id"]][:20]
            body = {"origins": [waypoint(d["lat"], d["lon"])], "destinations": [waypoint(f.lat, f.lon) for f in mine],
                    "travelMode": "DRIVE", "routingPreference": "TRAFFIC_UNAWARE"}
            r = client.post(URL, headers=headers, json=body)
            r.raise_for_status()
            for el in r.json():
                if el.get("condition") != "ROUTE_EXISTS":
                    continue
                f = mine[el["destinationIndex"]]
                straight = haversine_km(d["lat"], d["lon"], f.lat, f.lon)
                road_km = el["distanceMeters"] / 1000
                road_min = float(el["duration"].rstrip("s")) / 60
                rows.append({"depot": d["id"], "straight_km": round(straight, 2), "road_km": round(road_km, 2),
                             "road_min": round(road_min, 1), "model_km": round(straight * ROAD_FACTOR, 2),
                             "model_min": round(straight * ROAD_FACTOR / TRAVEL_KMH * 60, 1)})
            print(d["id"], len(rows), flush=True)
    ratio = [r["road_km"] / r["straight_km"] for r in rows if r["straight_km"] > 1]
    km_err = [(r["model_km"] - r["road_km"]) / r["road_km"] for r in rows if r["road_km"] > 1]
    min_err = [(r["model_min"] - r["road_min"]) / r["road_min"] for r in rows if r["road_min"] > 1]
    speed = [r["road_km"] / (r["road_min"] / 60) for r in rows if r["road_min"] > 1]
    out = {
        "n": len(rows), "assumed": {"road_factor": ROAD_FACTOR, "travel_kmh": TRAVEL_KMH},
        "road_factor": {"median": round(statistics.median(ratio), 2), "p10": round(sorted(ratio)[len(ratio) // 10], 2),
                        "p90": round(sorted(ratio)[len(ratio) * 9 // 10], 2)},
        "model_km_error_pct": {"median": round(100 * statistics.median(km_err), 1),
                               "median_abs": round(100 * statistics.median(abs(e) for e in km_err), 1)},
        "google_kmh": {"median": round(statistics.median(speed), 1)},
        "model_minutes_error_pct": {"median": round(100 * statistics.median(min_err), 1),
                                    "median_abs": round(100 * statistics.median(abs(e) for e in min_err), 1)},
        "rows": rows, "ran_at": time.strftime("%Y-%m-%d %H:%M"),
    }
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, indent=1))


if __name__ == "__main__":
    run()
