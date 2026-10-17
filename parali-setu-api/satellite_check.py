"""After a pickup, did the field stay unburned? Checked from Sentinel-2.

NASA FIRMS sees a fire only while a satellite is overhead, and burning in
Punjab has moved to times it misses. A burn scar stays on the ground for
weeks, so after we collect a farm we compare Sentinel-2 images of the field
from before and after the pickup (Google Earth Engine, 10 m, cloud-masked):

    NBR = (NIR - SWIR2) / (NIR + SWIR2)        dNBR = NBR before - NBR after

A scar is dNBR above BURN_DNBR (the standard moderate-severity threshold)
with a charred surface after (NBR_after below 0). Tested on the 2024 season
(bench/bench_burn_scar.py, 150 FIRMS fire locations, 150 random points 2 km
or more from any FIRMS fire): the dNBR bar alone is met at 81% and 21% of
them; the full rule, which also needs the char, at 66% and 11%. It is kept
strict on purpose: a scar is evidence against a farmer, so it must not be
harvest mistaken for fire.

Run in the daily fire job (fetch_fire_data.py); results go on the booking as
`field_check`. Nothing here decides a payout: it is evidence for the impact
count and for a person to look at.
"""
from __future__ import annotations

from datetime import date, timedelta

BURN_DNBR = 0.27
BEFORE_DAYS = 30      # images from this long before the pickup
AFTER_START, AFTER_END = 3, 25    # and from these days after it
FIELD_RADIUS_M = 60


def verdict(dnbr: float | None, nbr_after: float | None) -> str:
    if dnbr is None or nbr_after is None:
        return "no_clear_image"
    return "burn_scar" if dnbr > BURN_DNBR and nbr_after < 0 else "no_burn_scar"


def window(collected_on: date) -> tuple[tuple[str, str], tuple[str, str]]:
    before = ((collected_on - timedelta(days=BEFORE_DAYS)).isoformat(), collected_on.isoformat())
    after = ((collected_on + timedelta(days=AFTER_START)).isoformat(), (collected_on + timedelta(days=AFTER_END)).isoformat())
    return before, after


def due(collected_on: date, today: date) -> bool:
    """A field can be judged once the 'after' window has closed."""
    return today >= collected_on + timedelta(days=AFTER_END)


def measure(fields: list[dict]) -> list[dict]:
    """fields: [{"id", "lat", "lon", "collected_on"}]. One Earth Engine call
    per pickup date. Returns [{"id", "dnbr", "nbr_after", "verdict"}]."""
    import ee

    def nbr(start, end, region):
        def mask(img):
            scl = img.select("SCL")
            return img.updateMask(scl.eq(4).Or(scl.eq(5)).Or(scl.eq(6)).Or(scl.eq(7)))
        col = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterDate(start, end).filterBounds(region)
               .filter(ee.Filter.lt("CLOUDY_PIXEL_PERCENTAGE", 60)).map(mask))
        return col.median().normalizedDifference(["B8", "B12"])

    out = []
    by_day: dict[str, list[dict]] = {}
    for f in fields:
        by_day.setdefault(str(f["collected_on"])[:10], []).append(f)
    for day, group in by_day.items():
        (b0, b1), (a0, a1) = window(date.fromisoformat(day))
        fc = ee.FeatureCollection([ee.Feature(ee.Geometry.Point([f["lon"], f["lat"]]).buffer(FIELD_RADIUS_M), {"id": f["id"]})
                                   for f in group])
        before, after = nbr(b0, b1, fc.geometry()), nbr(a0, a1, fc.geometry())
        img = before.subtract(after).rename("dnbr").addBands(after.rename("nbr_after"))
        for row in img.reduceRegions(collection=fc, reducer=ee.Reducer.mean(), scale=10).getInfo()["features"]:
            p = row["properties"]
            dnbr, after_v = p.get("dnbr"), p.get("nbr_after")
            out.append({"id": p["id"], "dnbr": None if dnbr is None else round(dnbr, 3),
                        "nbr_after": None if after_v is None else round(after_v, 3), "verdict": verdict(dnbr, after_v)})
    return out


def refresh(db, today: date, measure_fn=measure) -> dict:
    """Checks every paid pickup whose 'after' window has closed and that has
    no verdict yet. Returns counts by verdict."""
    import firestore_store as store
    import pickups
    todo = []
    for b in store.get_bookings(db, ("paid",)):
        if (b.get("field_check") or {}).get("verdict") in ("burn_scar", "no_burn_scar"):
            continue
        collected = date.fromisoformat(str(b.get("collected_at") or b.get("status_updated_at"))[:10])
        listing = store.get_listing(db, b["listing_id"]) or {}
        loc = pickups.listing_location(listing)
        if loc is None or not due(collected, today):
            continue
        todo.append({"id": b["id"], "lat": loc[0], "lon": loc[1], "collected_on": collected})
    counts: dict[str, int] = {}
    for r in measure_fn(todo) if todo else []:
        store.update_booking_fields(db, r["id"], {"field_check": {**r, "checked_on": today.isoformat(), "source": "Sentinel-2"}})
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return counts


def summary(bookings: list[dict], today: date) -> dict:
    """For the impact page: paid pickups by field-check state."""
    out = {"checked_clear": 0, "burn_scar": 0, "waiting_for_images": 0, "no_clear_image": 0}
    for b in bookings:
        v = (b.get("field_check") or {}).get("verdict")
        if v == "no_burn_scar":
            out["checked_clear"] += 1
        elif v == "burn_scar":
            out["burn_scar"] += 1
        elif v == "no_clear_image":
            out["no_clear_image"] += 1
        else:
            out["waiting_for_images"] += 1
    return out
