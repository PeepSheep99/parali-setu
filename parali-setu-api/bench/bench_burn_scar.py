"""Experiment: can Sentinel-2 see burn scars that NASA FIRMS fire detections miss?

FIRMS sees a fire only if a satellite passes while it burns; Punjab's counted
fires fell after 2021 while the burned area did not, which suggests burning
moved to times the satellites miss. A burn scar stays on the ground for
weeks, so a 10 m optical satellite should see it whenever it burned.

Method (Google Earth Engine, Sentinel-2 surface reflectance, cloud-masked):
- NBR = (NIR - SWIR2) / (NIR + SWIR2); dNBR = NBR before - NBR after.
  Before: 1-20 Oct 2024; after: 20 Nov - 10 Dec 2024.
- "Burned" sample: FIRMS fire pixels from the 2024 season (fires_2024.json).
- "Not seen burning" sample: random points in the same districts at least
  2 km from every FIRMS detection that season.
- At each point: dNBR averaged over 60 m around it; share above the standard
  thresholds (0.1 low severity, 0.27 moderate).

Harvesting alone lowers NBR too, so the honest test is the gap between the
two samples, not either number alone.

    python -m bench.bench_burn_scar           # writes bench/results/burn_scar.json
"""
from __future__ import annotations

import json
import math
import random
import statistics
import time
from pathlib import Path

import ee

ROOT = Path(__file__).resolve().parent.parent
FIRES = ROOT.parent / "parali-setu-frontend" / "data" / "fires_2024.json"
OUT = ROOT / "bench" / "results" / "burn_scar.json"
N = 150
SEED = 7


def s2_nbr(start: str, end: str, region) -> ee.Image:
    def mask(img):
        scl = img.select("SCL")
        clear = scl.eq(4).Or(scl.eq(5)).Or(scl.eq(6)).Or(scl.eq(7))   # vegetation, bare soil, water, unclassified
        return img.updateMask(clear)
    col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterDate(start, end).filterBounds(region)
           .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 60)).map(mask))
    return col.median().normalizedDifference(["B8", "B12"]).rename("nbr")


def far_from_fires(lat, lon, fires, km=2.0) -> bool:
    for flat, flon, _ in fires:
        if abs(flat - lat) < 0.03 and abs(flon - lon) < 0.03:
            d = math.hypot((flat - lat) * 111, (flon - lon) * 111 * math.cos(math.radians(lat)))
            if d < km:
                return False
    return True


def run():
    ee.Initialize(project="parali-setu-aibuildercup-2026")
    data = json.loads(FIRES.read_text(encoding="utf-8"))
    rng = random.Random(SEED)
    fires = data["points"]
    burned = rng.sample([p for p in fires if p[2] <= 45], N)          # fires by mid-November, so the scar is in the 'after' image
    lats = [p[0] for p in fires]
    lons = [p[1] for p in fires]
    unseen = []
    while len(unseen) < N:
        lat, lon = rng.uniform(min(lats), max(lats)), rng.uniform(min(lons), max(lons))
        if far_from_fires(lat, lon, fires):
            unseen.append([lat, lon])
    region = ee.Geometry.Rectangle([min(lons) - .1, min(lats) - .1, max(lons) + .1, max(lats) + .1])
    before = s2_nbr("2024-10-01", "2024-10-21", region)
    after = s2_nbr("2024-11-20", "2024-12-11", region)
    dnbr = before.subtract(after).rename("dnbr").addBands(before.rename("nbr_before")).addBands(after.rename("nbr_after"))

    def sample(points, label):
        fc = ee.FeatureCollection([ee.Feature(ee.Geometry.Point([p[1], p[0]]).buffer(60), {"i": i}) for i, p in enumerate(points)])
        rows = dnbr.reduceRegions(collection=fc, reducer=ee.Reducer.mean(), scale=10).getInfo()["features"]
        return [{"label": label, **{k: r["properties"].get(k) for k in ("dnbr", "nbr_before", "nbr_after")}} for r in rows]

    t0 = time.time()
    rows = sample(burned, "firms_fire") + sample(unseen, "no_firms_fire")
    rows = [r for r in rows if r["dnbr"] is not None]

    def stats(label):
        v = [r["dnbr"] for r in rows if r["label"] == label]
        return {"n": len(v), "median_dnbr": round(statistics.median(v), 3),
                "share_above_0_10": round(100 * sum(x > 0.10 for x in v) / len(v), 1),
                "share_above_0_27": round(100 * sum(x > 0.27 for x in v) / len(v), 1),
                "median_nbr_after": round(statistics.median(r["nbr_after"] for r in rows if r["label"] == label and r["nbr_after"] is not None), 3)}

    out = {"method": __doc__.split("Method")[1].split("Harvesting")[0].strip(), "seed": SEED,
           "firms_fire": stats("firms_fire"), "no_firms_fire": stats("no_firms_fire"),
           "seconds": round(time.time() - t0, 1), "rows": rows, "ran_at": time.strftime("%Y-%m-%d %H:%M")}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("firms_fire", "no_firms_fire", "seconds")}, indent=1))


if __name__ == "__main__":
    run()
