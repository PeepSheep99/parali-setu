"""Shared geography for the demo region: district HQ coordinates and
straight-line distance. Used by the fire-data batch job (labelling FIRMS
detections), the pickup scheduler (travel times) and listings whose farmer
didn't share a location (district centroid fallback, marked approximate).
"""
from __future__ import annotations

import math

# District HQ coordinates for the 8 demo districts -- real, publicly known
# lat/lon. A farm without a shared location is placed at its district HQ,
# which is an approximation and is labelled as one wherever it's shown.
DISTRICT_COORDS = {
    "Sangrur": (30.2458, 75.8421),
    "Patiala": (30.3398, 76.3869),
    "Bathinda": (30.2110, 74.9455),
    "Ludhiana": (30.9010, 75.8573),
    "Moga": (30.8230, 75.1710),
    "Karnal": (29.6857, 76.9905),
    "Kaithal": (29.8014, 76.3996),
    "Kurukshetra": (29.9695, 76.8783),
}

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def nearest_district(lat: float, lon: float) -> str:
    """Straight-line nearest-HQ match -- a demo-scale approximation (no real
    district polygon boundaries used), not a cadastral claim."""
    return min(DISTRICT_COORDS, key=lambda d: haversine_km(lat, lon, *DISTRICT_COORDS[d]))


def district_from_text(text: str | None) -> str | None:
    """Finds one of the demo districts named in free text such as a
    village_or_district field ("Sangrur", "near Patiala"). None if absent."""
    if not text:
        return None
    lowered = text.lower()
    return next((d for d in DISTRICT_COORDS if d.lower() in lowered), None)
