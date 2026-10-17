"""Resets Parali Setu's demo data in Firestore to a known, realistic state.

WIPES Parali Setu's own operational collections (never AidAtlas's, never the
satellite fire batch or the forecasts), then seeds, through the same code the
API uses:
- 5 Parali Setu depots with our own crews and a pool of hired partner crews
  (Patiala has a single own crew, so partner crews visibly step in there)
- 5 demo customers, one per industry segment, with 12-month forward orders
  priced by the cost model
- today's posted prices from the procurement LP
- ~25 farmer listings, booked at the posted price and given pickup slots
- a small demo run: a few bookings accepted, collected and paid, so stock,
  payouts and impact start from real activity rather than zero
- the delivery plan from depots to customer orders

Customer and farmer names are invented and marked "(demo)".

    python reset_demo.py --yes                # full demo
    python reset_demo.py --yes --no-listings  # depots, crews, customers, orders only
"""
from __future__ import annotations

import argparse
import random
from datetime import date, timedelta

import firestore_store as store
import operations
import pickups
from geo import DISTRICT_COORDS

WIPE_COLLECTIONS = (
    "listings", "listing_drafts", "bookings", "depots", "crews", "pickup_slots", "posted_prices",
    "purchases", "inventory_moves", "customers", "orders", "deliveries", "plans", "conversations",
    "no_burn_proofs", "farmers",
    # collections of the earlier marketplace design, cleared if still present
    "matches", "demand", "companies", "payouts", "negotiation_sessions",
)

# id, name, district, storage capacity (t), radius (km), own crews
DEPOTS = [
    ("dep_sangrur", "Sangrur depot", "Sangrur", 8000, 70, 2),
    ("dep_patiala", "Patiala depot", "Patiala", 6000, 60, 1),
    ("dep_bathinda", "Bathinda depot", "Bathinda", 6000, 90, 2),   # also serves western Moga
    ("dep_ludhiana", "Ludhiana depot", "Ludhiana", 6000, 90, 2),   # also serves Moga
    ("dep_karnal", "Karnal depot", "Karnal", 6000, 90, 2),         # also serves Kaithal, Kurukshetra
]
# Hired baler capacity each depot can call on per day (a simulated partner pool).
PARTNER_CREWS_PER_DEPOT = 3

# id, name, segment, district, tonnes per month (12-month forward order)
CUSTOMERS = [
    ("cust_cbg", "Sangrur Bio-CNG (demo)", "cbg", "Sangrur", 400),
    ("cust_power", "Malwa Biomass Power (demo)", "biomass_power", "Bathinda", 500),
    ("cust_boiler", "Ludhiana Textile Boilers (demo)", "industrial_boilers", "Ludhiana", 300),
    ("cust_pellet", "GT Road Pellets (demo)", "pellets", "Karnal", 250),
    ("cust_board", "Patiala Board & Pack (demo)", "packaging", "Patiala", 100),
]

LISTINGS_PER_DISTRICT = {
    "Sangrur": 4, "Patiala": 6, "Bathinda": 3, "Ludhiana": 3,
    "Moga": 2, "Karnal": 3, "Kaithal": 2, "Kurukshetra": 2,
}
DEMO_ACCEPTED = 6
DEMO_COLLECTED = 4


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


def seed_depots(db) -> None:
    for depot_id, name, district, capacity, radius, own_crews in DEPOTS:
        lat, lon = DISTRICT_COORDS[district]
        store.save_depot(db, {"id": depot_id, "name": name, "district": district, "lat": lat, "lon": lon,
                              "capacity_t": capacity, "radius_km": radius})
        crews = [(f"{depot_id}_crew{k + 1}", f"Crew {k + 1}", False) for k in range(own_crews)]
        crews += [(f"{depot_id}_partner{k + 1}", f"Partner baler {k + 1}", True) for k in range(PARTNER_CREWS_PER_DEPOT)]
        for crew_id, crew_name, partner in crews:
            store.save_crew(db, {"id": crew_id, "depot_id": depot_id, "name": crew_name, "partner": partner,
                                 "depot_lat": lat, "depot_lon": lon, "shift_start_min": 7 * 60,
                                 "shift_end_min": 18 * 60, "acres_per_day": 20.0})


def seed_customers_and_orders(db, today: date) -> None:
    start = operations.add_months(date(today.year, today.month, 1), 1)
    for cid, name, segment, district, per_month in CUSTOMERS:
        lat, lon = DISTRICT_COORDS[district]
        site = (round(lat + 0.06, 5), round(lon - 0.05, 5))
        store.save_customer(db, {"id": cid, "name": name, "segment": segment, "district": district,
                                 "lat": site[0], "lon": site[1], "demo": True})
        quote = operations.quote_order(db, site, start, 12, today=today)
        store.save_order(db, {
            "customer_id": cid, "product": "baled paddy straw",
            "tonnes_by_month": {operations.add_months(start, i).isoformat(): per_month for i in range(12)},
            "site": {"lat": site[0], "lon": site[1], "district": district}, "quote": quote,
            "total_t": per_month * 12,
        })


def seed_listings(db, today: date, seed: int = 17) -> list[dict]:
    rng = random.Random(seed)
    listings, n = [], 0
    for district, count in LISTINGS_PER_DISTRICT.items():
        base_lat, base_lon = DISTRICT_COORDS[district]
        for _ in range(count):
            n += 1
            acres = rng.choice([4, 5, 6, 7, 8, 9, 10, 11, 12, 14])
            ready = today + timedelta(days=rng.randint(0, 2))
            sowing = ready + timedelta(days=rng.randint(4, 8))
            if district == "Patiala":
                # One own crew and every farm due within three days: more acres
                # than it can bale, so hired partner crews step in.
                acres = rng.choice([10, 12, 14])
                ready, sowing = today, today + timedelta(days=3)
            listings.append(store.save_listing(db, f"demo_farmer_{n}", {
                "acres": acres, "quantity_kg": acres * 1750.0, "crop_type": "rice_stubble",
                "village_or_district": f"{district} (demo farm {n})", "district": district,
                "ready_by": ready.isoformat(), "sowing_deadline": sowing.isoformat(),
                "lat": round(base_lat + rng.uniform(-0.12, 0.12), 5),
                "lon": round(base_lon + rng.uniform(-0.12, 0.12), 5),
                "quality_grade": rng.choice(["unknown", "dry", "dry", "wet"]),
            }, rng.choice(["Hindi", "Punjabi"])))
    return listings


def demo_run(db) -> dict:
    """Accepts a few offers and collects some of them, through the same
    functions the API calls, so the counters start from real activity."""
    offered = [b for b in store.get_bookings(db, ("offered",)) if store.get_slots_for_booking(db, b["id"])]
    offered.sort(key=lambda b: (b["depot_id"], b["id"]))
    accepted = []
    for booking in offered[:DEMO_ACCEPTED]:
        store.update_booking_status(db, booking["id"], "booked",
                                    {"slot_accepted_at": pickups.now_ist().isoformat(), "accepted_by": "demo seed"})
        store.set_slots_status(db, booking["id"], "locked", locked=True)
        accepted.append(booking["id"])
    collected = [pickups.complete_pickup(db, bid)["purchase"]["amount_inr"] for bid in accepted[:DEMO_COLLECTED]]
    return {"accepted": len(accepted), "collected": len(collected), "paid_inr": round(sum(collected), 2)}


def run(include_listings: bool) -> None:
    db = store.get_firestore_client()
    today = pickups.now_ist().date()
    print("wiped:", {k: v for k, v in wipe(db).items() if v})
    seed_depots(db)
    operations.run_procurement(db, today)          # base prices for quoting
    seed_customers_and_orders(db, today)
    plan = operations.run_procurement(db, today, repost_today=True)   # now with the order book
    print(f"seeded {len(DEPOTS)} depots, {len(CUSTOMERS)} customers; plan: committed {plan['committed_t']} t, "
          f"shortfall {plan['shortfall_t']} t, partner share {plan['partner_share']}")
    print("posted prices:", {r["district"]: r["price_per_kg"] for r in store.get_posted_prices_for_day(db, today.isoformat())})
    if include_listings:
        listings = seed_listings(db, today)
        booked = [operations.book_listing(db, listing, today)[0] for listing in listings]
        summaries = pickups.plan_depots(db, {b["depot_id"] for b in booked if b})
        print(f"seeded {len(listings)} listings -> {sum(1 for b in booked if b)} bookings")
        for s in summaries:
            print("  ", s)
        print("demo run:", demo_run(db))
    deliveries = operations.run_deliveries(db, today)
    print(f"delivery plan: shortfall {deliveries['shortfall_t']} t, haul Rs {deliveries['haul_cost_inr']}, "
          f"storage Rs {deliveries['storage_cost_inr']}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="confirm wiping Parali Setu's demo collections")
    parser.add_argument("--no-listings", action="store_true", help="seed depots, crews, customers and orders only")
    args = parser.parse_args()
    if not args.yes:
        parser.error("this wipes Parali Setu's Firestore collections; re-run with --yes to confirm")
    run(include_listings=not args.no_listings)
