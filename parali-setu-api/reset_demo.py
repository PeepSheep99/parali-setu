"""Resets Parali Setu's demo data in Firestore to a known, realistic state.

WIPES Parali Setu's own collections (never AidAtlas's, never the satellite
fire batch or the BigQuery ML forecasts), then seeds:
- 5 demo buyers with Punjab/Haryana collection depots (ids co_1..co_5 match
  the existing forecast documents, so the Recommendation card stays valid)
- 8 crews, standing demand at farm-gate prices with ceilings
- ~25 waiting farmer listings across the 8 demo districts, with Patiala
  deliberately over capacity so the waitlist path is visible

then runs the real matching and pickup planning, exactly as the API does.
All names are invented and marked "(demo)".

    python reset_demo.py --yes              # full demo
    python reset_demo.py --yes --no-listings  # buyers, crews, demand only
                                              # (run the live smoke test on this)
"""
from __future__ import annotations

import argparse
import random
from datetime import date, timedelta

import firestore_store as store
import pickups
from geo import DISTRICT_COORDS

WIPE_COLLECTIONS = (
    "listings", "matches", "demand", "companies", "crews", "pickup_slots", "payouts",
    "listing_drafts", "negotiation_sessions", "no_burn_proofs", "farmers",
)

BUYERS = [
    # id, name, product, depot district, service radius km
    ("co_1", "Leafware Plates (demo)", "disposable_plates", "Sangrur", 45),
    ("co_2", "Malwa Pellets (demo)", "biofuel_pellets", "Bathinda", 75),
    ("co_3", "Doaba Board & Pack (demo)", "packaging_board", "Ludhiana", 75),
    ("co_4", "GT Road Composites (demo)", "road_composite", "Karnal", 75),
    ("co_5", "Capital Plates (demo)", "disposable_plates", "Patiala", 40),
]
CREWS_PER_BUYER = {"co_1": 2, "co_2": 2, "co_3": 2, "co_4": 1, "co_5": 1}
# (buyer, crop, tonnes needed, farm-gate offer Rs/kg, max Rs/kg)
DEMAND = [
    ("co_1", "rice_stubble", 120, 1.10, 1.35),
    ("co_2", "rice_stubble", 200, 1.20, 1.45),
    ("co_2", "wheat_stubble", 60, 0.90, 1.10),
    ("co_3", "rice_stubble", 150, 1.00, 1.25),
    ("co_4", "rice_stubble", 120, 0.95, 1.20),
    ("co_4", "wheat_stubble", 40, 0.80, 1.00),
    ("co_5", "rice_stubble", 150, 1.15, 1.40),
]
# Listings per district; Patiala gets more than its one 40 km crew can serve.
LISTINGS_PER_DISTRICT = {
    "Sangrur": 3, "Patiala": 6, "Bathinda": 3, "Ludhiana": 3,
    "Moga": 2, "Karnal": 3, "Kaithal": 2, "Kurukshetra": 3,
}


def wipe(db) -> dict:
    counts = {}
    for name in WIPE_COLLECTIONS:
        docs = list(db.collection(name).stream())
        for i in range(0, len(docs), 400):
            batch = db.batch()
            for d in docs[i:i + 400]:
                batch.delete(d.reference)
            batch.commit()
        counts[name] = len(docs)
    return counts


def seed_buyers(db) -> None:
    for cid, name, product, district, radius in BUYERS:
        lat, lon = DISTRICT_COORDS[district]
        store.save_company(db, {"id": cid, "name": name, "product_lines": [product], "depot_district": district,
                                "depot_lat": lat, "depot_lon": lon, "service_radius_km": radius, "demo": True})
        for k in range(CREWS_PER_BUYER[cid]):
            crew_id = f"{cid}_crew{k + 1}"
            db.collection("crews").document(crew_id).set({
                "id": crew_id, "company_id": cid, "name": f"Crew {k + 1}", "depot_lat": lat, "depot_lon": lon,
                "shift_start_min": 7 * 60, "shift_end_min": 18 * 60, "acres_per_day": 20.0,
            })
    for i, (cid, crop, tonnes, offer, ceiling) in enumerate(DEMAND, start=1):
        company = next(b for b in BUYERS if b[0] == cid)
        lat, lon = DISTRICT_COORDS[company[3]]
        store.save_demand(db, cid, {
            "id": f"demand_{i}", "product": company[2], "crop_type": crop,
            "quantity_needed_kg": tonnes * 1000, "price_offer_per_kg": offer, "max_price_per_kg": ceiling,
            "accepted_quality_grades": ["unknown", "dry", "wet", "mixed"],
            "depot_lat": lat, "depot_lon": lon, "service_radius_km": company[4],
        })


def seed_listings(db, today: date, seed: int = 17) -> int:
    rng = random.Random(seed)
    n = 0
    for district, count in LISTINGS_PER_DISTRICT.items():
        base_lat, base_lon = DISTRICT_COORDS[district]
        for _ in range(count):
            n += 1
            acres = rng.choice([3, 4, 5, 6, 8, 10, 12, 15])
            ready = today + timedelta(days=rng.randint(0, 2))
            sowing = ready + timedelta(days=rng.randint(3, 7))
            if district == "Patiala":
                # Deliberate overload: ~60 acres all ready today, two pickup
                # days before sowing, one 20-acre/day crew -> a visible waitlist.
                acres = rng.choice([8, 10, 12])
                ready = today
                sowing = today + timedelta(days=2)
            store.save_listing(db, f"demo_farmer_{n}", {
                "acres": acres, "quantity_kg": acres * 1750.0,
                "crop_type": "wheat_stubble" if n % 9 == 0 else "rice_stubble",
                "village_or_district": f"{district}", "ready_by": ready.isoformat(),
                "sowing_deadline": sowing.isoformat(),
                "lat": round(base_lat + rng.uniform(-0.12, 0.12), 5),
                "lon": round(base_lon + rng.uniform(-0.12, 0.12), 5),
                "quality_grade": rng.choice(["unknown", "unknown", "dry", "dry", "wet"]),
            }, rng.choice(["Hindi", "Punjabi"]))
    return n


def run(include_listings: bool) -> None:
    from main import _run_global_solve  # the API's own matching, not a copy

    db = store.get_firestore_client()
    print("wiped:", wipe(db))
    seed_buyers(db)
    print(f"seeded {len(BUYERS)} buyers, {sum(CREWS_PER_BUYER.values())} crews, {len(DEMAND)} demand records")
    if not include_listings:
        print("no listings seeded (--no-listings)")
        return
    count = seed_listings(db, pickups.now_ist().date())
    matches = _run_global_solve(db)
    plans = pickups.plan_companies(db, [b[0] for b in BUYERS])
    print(f"seeded {count} listings -> {len(matches)} matches")
    for plan in plans:
        print("  ", plan)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="confirm wiping Parali Setu's demo collections")
    parser.add_argument("--no-listings", action="store_true", help="seed buyers, crews and demand only")
    args = parser.parse_args()
    if not args.yes:
        parser.error("this wipes Parali Setu's Firestore collections; re-run with --yes to confirm")
    run(include_listings=not args.no_listings)
