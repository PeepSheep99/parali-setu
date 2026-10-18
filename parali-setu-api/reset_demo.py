"""Resets Parali Setu's demo data in Firestore to a known, realistic state.

WIPES Parali Setu's own operational collections (never AidAtlas's, never the
satellite fire batch or the forecasts), then seeds, through the same code the
API uses:
- 5 Parali Setu depots with our own crews and a pool of on-call crews
  (Patiala has a single own crew, so on-call crews visibly step in there)
- 5 demo customers, one per industry segment, with 12-month forward orders
  priced by the cost model
- today's posted prices from the procurement LP
- ~60 synthetic farmers over today and the next two days (Punjabi and
  Haryanvi names, real villages of each district, masked phone numbers),
  booked at the posted price and given pickup slots by the routing model
- every stage of a pickup on the board: offers waiting for the farmer,
  bookings waiting for our call, confirmed pickups, and today's collected
  and paid ones, so ops, stock, payouts and impact start from real activity
- the delivery plan from depots to customer orders

Customer names are marked "(demo)". Farmers and crews are synthetic but read
like real ones; the ops console says so in a banner, and phone numbers are
stored only masked (+91 ******1234), so no real number is ever shown.

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
    "no_burn_proofs", "farmers", "fire_alerts",
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
# Crews hired for a day when our own are full. The scheduler uses them only
# after our own crews (scheduler.plan_pickups' second pass), so an unused
# on-call crew costs nothing; ops sees each one as a hire on the dispatch board.
ONCALL_CREWS_PER_DEPOT = 8
# Our own crews, by their leader; on-call crews are local baler contractors and
# custom hiring centres (CHCs) we hire by the day.
OWN_CREW_LEADERS = {
    "dep_sangrur": ["Jaswinder Singh", "Harbhajan Singh"],
    "dep_patiala": ["Kulwant Singh"],
    "dep_bathinda": ["Gurlal Singh", "Makhan Singh"],
    "dep_ludhiana": ["Avtar Singh", "Sukhpal Singh"],
    "dep_karnal": ["Rajbir Singh", "Satish Kumar"],
}
ONCALL_CREWS = {
    "dep_sangrur": ["Longowal CHC", "Sidhu Baler Service", "Dhuri Kisan Seva", "Cheema Agro Works",
                    "Bhawanigarh CHC", "Mann Tractor Hire", "Sunam Baler Co.", "Ubhawal Farm Services"],
    "dep_patiala": ["Samana CHC", "Grewal Balers", "Rakhra Kisan Seva", "Sanaur Agro Hire",
                    "Ghanaur CHC", "Virk Baler Service", "Dakala Farm Services", "Sekhon Tractor Co."],
    "dep_bathinda": ["Bhucho CHC", "Brar Baler Service", "Goniana Kisan Seva", "Maur Agro Works",
                     "Rampura Phul CHC", "Dhillon Tractor Hire", "Nathana Balers", "Talwandi Farm Services"],
    "dep_ludhiana": ["Jagraon CHC", "Gill Baler Service", "Raikot Kisan Seva", "Sudhar Agro Works",
                     "Mullanpur CHC", "Sandhu Tractor Hire", "Dakha Balers", "Sidhwan Bet Farm Services"],
    "dep_karnal": ["Nilokheri CHC", "Chahal Baler Service", "Assandh Kisan Seva", "Taraori Agro Works",
                   "Pehowa CHC", "Kamboj Tractor Hire", "Pundri Balers", "Indri Farm Services"],
}

# id, name, segment, district, tonnes per month (12-month forward order)
CUSTOMERS = [
    ("cust_cbg", "Sangrur Bio-CNG (demo)", "cbg", "Sangrur", 400),
    ("cust_power", "Malwa Biomass Power (demo)", "biomass_power", "Bathinda", 500),
    ("cust_boiler", "Ludhiana Textile Boilers (demo)", "industrial_boilers", "Ludhiana", 300),
    ("cust_pellet", "GT Road Pellets (demo)", "pellets", "Karnal", 250),
    ("cust_board", "Patiala Board & Pack (demo)", "packaging", "Patiala", 100),
]

LISTINGS_PER_DISTRICT = {
    "Sangrur": 10, "Patiala": 9, "Bathinda": 8, "Ludhiana": 8,
    "Moga": 5, "Karnal": 8, "Kaithal": 6, "Kurukshetra": 6,
}
# Real villages and towns of each district (the farm pin is near the district centre).
VILLAGES = {
    "Sangrur": ["Longowal", "Bhawanigarh", "Cheema", "Ubhawal", "Balian", "Kanoi", "Bahadurpur", "Dhuri"],
    "Patiala": ["Rakhra", "Samana", "Ghanaur", "Bhunerheri", "Dakala", "Sanaur", "Kalomajra"],
    "Bathinda": ["Bhucho", "Rampura Phul", "Goniana", "Talwandi Sabo", "Maur", "Nathana", "Kotfatta"],
    "Ludhiana": ["Jagraon", "Raikot", "Sidhwan Bet", "Dakha", "Mullanpur", "Sudhar", "Halwara"],
    "Moga": ["Dharamkot", "Baghapurana", "Nihal Singh Wala", "Kot Ise Khan", "Badhni Kalan", "Ajitwal"],
    "Karnal": ["Nilokheri", "Gharaunda", "Assandh", "Taraori", "Nissing", "Indri"],
    "Kaithal": ["Pundri", "Cheeka", "Rajound", "Kalayat", "Siwan", "Dhand"],
    "Kurukshetra": ["Pehowa", "Thanesar", "Ladwa", "Shahabad", "Ismailabad", "Babain"],
}
PUNJAB_FIRST = ["Gurmeet", "Harpreet", "Jaswant", "Baldev", "Sukhdev", "Kulwinder", "Jagtar", "Paramjit",
                "Gurdev", "Harjinder", "Balwinder", "Manjit", "Amarjit", "Gurnam", "Sukhwinder", "Rajinder",
                "Lakhvir", "Darshan", "Nachhattar", "Bhupinder", "Iqbal", "Charanjit", "Hardeep", "Mohinder"]
PUNJAB_WOMEN = ["Harjeet Kaur", "Simranjit Kaur", "Manpreet Kaur", "Kuldeep Kaur", "Gurpreet Kaur", "Rajwant Kaur"]
PUNJAB_LAST = ["Sidhu", "Gill", "Dhillon", "Sandhu", "Brar", "Grewal", "Mann", "Sekhon", "Cheema", "Virk",
               "Bains", "Randhawa"]
HARYANA_NAMES = ["Rajbir Malik", "Satbir Chahal", "Sunil Kumar", "Pardeep Saini", "Naresh Kamboj",
                 "Surender Sangwan", "Jagdish Saini", "Ramesh Kumar", "Dharambir Singh", "Vinod Kumar",
                 "Kamla Devi", "Sunita Devi", "Balwan Singh", "Mahavir Singh", "Anil Kamboj", "Ravinder Virk"]
HARYANA = {"Karnal", "Kaithal", "Kurukshetra"}


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
                              "capacity_t": capacity, "radius_km": radius, "stock_t": 0.0})
        leaders = OWN_CREW_LEADERS[depot_id]
        crews = [(f"{depot_id}_crew{k + 1}", f"{leaders[k].split()[0]}'s crew", False, leaders[k])
                 for k in range(own_crews)]
        crews += [(f"{depot_id}_oncall{k + 1}", ONCALL_CREWS[depot_id][k], True, None)
                  for k in range(ONCALL_CREWS_PER_DEPOT)]
        for crew_id, crew_name, partner, leader in crews:
            store.save_crew(db, {"id": crew_id, "depot_id": depot_id, "name": crew_name, "partner": partner,
                                 "on_call": partner, "leader": leader, "depot_lat": lat, "depot_lon": lon,
                                 "shift_start_min": 7 * 60, "shift_end_min": 18 * 60, "acres_per_day": 20.0})


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


def farmer_name(rng: random.Random, district: str) -> str:
    if district in HARYANA and rng.random() < 0.7:
        return rng.choice(HARYANA_NAMES)
    if rng.random() < 0.15:
        return rng.choice(PUNJAB_WOMEN)
    surname = f" {rng.choice(PUNJAB_LAST)}" if rng.random() < 0.6 else ""
    return f"{rng.choice(PUNJAB_FIRST)} Singh{surname}"


def seed_listings(db, today: date, seed: int = 17) -> list[dict]:
    """Synthetic farmers placing requests as if through the pickup page:
    name, masked phone, village, acres, when the straw is ready and when they
    must sow."""
    rng = random.Random(seed)
    listings, n, used = [], 0, set()
    for district, count in LISTINGS_PER_DISTRICT.items():
        base_lat, base_lon = DISTRICT_COORDS[district]
        # Districts without a depot of their own stay close to their HQ, within
        # reach of the depot that serves them.
        spread = 0.12 if any(d[2] == district for d in DEPOTS) else 0.06
        for _ in range(count):
            n += 1
            name = farmer_name(rng, district)
            while name in used:
                name = farmer_name(rng, district)
            used.add(name)
            acres = rng.choice([3, 4, 5, 5, 6, 6, 7, 8, 8, 9, 10, 12, 14, 15])
            ready = today + timedelta(days=rng.choices([0, 1, 2], weights=[3, 4, 3])[0])
            sowing = ready + timedelta(days=rng.randint(3, 7))
            if district == "Patiala":
                # One own crew and every farm due within three days: more acres
                # than it can bale, so on-call crews step in.
                acres = rng.choice([8, 10, 12, 14])
                ready, sowing = today, today + timedelta(days=3)
            phone = f"9{rng.randint(6, 9)}{rng.randint(10000000, 99999999)}"
            language = "Hindi" if district in HARYANA else rng.choices(["Punjabi", "Hindi", "English"],
                                                                        weights=[7, 2, 1])[0]
            listings.append(store.save_listing(db, f"demo_farmer_{n}", {
                "farmer_name": name, "contact": pickups.mask_phone(phone),   # stored masked: never a real number
                "acres": acres, "quantity_kg": acres * 1750.0, "crop_type": "rice_stubble",
                "village_or_district": f"{rng.choice(VILLAGES[district])}, {district}", "district": district,
                "ready_by": ready.isoformat(), "sowing_deadline": sowing.isoformat(),
                "lat": round(base_lat + rng.uniform(-spread, spread), 5),
                "lon": round(base_lon + rng.uniform(-spread, spread), 5),
                "quality_grade": rng.choice(["unknown", "dry", "dry", "wet"]),
            }, language))
    return listings


def place_requests(db, listings: list[dict], today: date) -> list[dict | None]:
    """Books each synthetic request at today's posted price. They were placed
    two days ago, so the 24 hours' notice is already behind them and the board
    is full from tomorrow whatever time of day the demo is reset."""
    asked = (pickups.now_ist() - timedelta(days=2)).isoformat()
    booked = []
    for listing in listings:
        booking = operations.book_listing(db, listing, today)[0]
        if booking:
            store.update_booking_fields(db, booking["id"], {"requested_at": asked})
        booked.append(booking)
    return booked


def demo_run(db, seed: int = 23) -> dict:
    """Moves the seeded offers through the same functions the API calls, so
    the board shows every stage: today's pickups confirmed and some already
    collected and paid; tomorrow's mostly confirmed, some waiting for our
    call, a few still offers; later ones mostly waiting."""
    rng = random.Random(seed)
    today = pickups.now_ist().date()
    first_day = {b["id"]: min(s["date"] for s in slots) for b in store.get_bookings(db, ("offered",))
                 if (slots := store.get_slots_for_booking(db, b["id"]))}
    offered = sorted((b for b in store.get_bookings(db, ("offered",)) if b["id"] in first_day),
                     key=lambda b: (first_day[b["id"]], b["depot_id"], b["id"]))
    counts = {"offered": 0, "booked": 0, "verified": 0, "collected": 0}
    paid = []
    for booking in offered:
        days_out = (date.fromisoformat(first_day[booking["id"]]) - today).days
        r = rng.random()
        if days_out <= 0:
            stage = "collected" if r < 0.45 else "verified"
        elif days_out == 1:
            stage = "verified" if r < 0.55 else "booked" if r < 0.85 else "offered"
        else:
            stage = "verified" if r < 0.25 else "booked" if r < 0.6 else "offered"
        counts[stage] += 1
        if stage == "offered":
            continue
        store.update_booking_status(db, booking["id"], "booked",
                                    {"slot_accepted_at": pickups.now_ist().isoformat(), "accepted_by": "farmer (agent)"})
        store.set_slots_status(db, booking["id"], "locked", locked=True)
        if stage in ("verified", "collected"):
            pickups.verify_booking(db, store.get_booking(db, booking["id"]), by="Parali Setu ops")
        if stage == "collected":
            paid.append(pickups.complete_pickup(db, booking["id"])["purchase"]["amount_inr"])
    return {**counts, "paid_inr": round(sum(paid), 2)}


# Pickups already done this season, so stock, payouts and impact start from real
# activity whatever time of day the demo is reset (after the last shift the
# planner has no slots left today, so nothing on the board can be collected).
HISTORY_FARMS = [("Sangrur", 9), ("Patiala", 7), ("Bathinda", 11), ("Ludhiana", 6), ("Kurukshetra", 8), ("Karnal", 10)]


def seed_history(db, today: date, seed: int = 31) -> dict:
    rng = random.Random(seed)
    paid = []
    for k, (district, acres) in enumerate(HISTORY_FARMS, 1):
        base_lat, base_lon = DISTRICT_COORDS[district]
        listing = store.save_listing(db, f"demo_farmer_done_{k}", {
            "farmer_name": farmer_name(rng, district), "contact": pickups.mask_phone(f"98{rng.randint(10000000, 99999999)}"),
            "acres": acres, "quantity_kg": acres * 1750.0, "crop_type": "rice_stubble",
            "village_or_district": f"{rng.choice(VILLAGES[district])}, {district}", "district": district,
            "ready_by": (today - timedelta(days=2)).isoformat(), "sowing_deadline": (today + timedelta(days=3)).isoformat(),
            "lat": round(base_lat + rng.uniform(-0.06, 0.06), 5), "lon": round(base_lon + rng.uniform(-0.06, 0.06), 5),
            "quality_grade": "dry"}, "Punjabi" if district not in HARYANA else "Hindi")
        booking, _ = operations.book_listing(db, listing, today)
        if booking is None:
            continue
        store.update_booking_status(db, booking["id"], "booked", {"accepted_by": "farmer (agent)"})
        pickups.verify_booking(db, store.get_booking(db, booking["id"]), by="Parali Setu ops")
        paid.append(store.record_pickup(db, booking["id"], booking["kg"], [], today.isoformat())["purchase"]["amount_inr"])
    return {"collected": len(paid), "paid_inr": round(sum(paid), 2)}


# Two real fields from the 2024 season, so the Sentinel-2 field check
# (satellite_check.py) has results to show: one near Sangrur where NASA FIRMS
# saw a cluster of fires on 2 Nov 2024, and one near Karnal with no fire within
# 4 km all season. Both "collected" on 29 Oct 2024; the daily job checks them.
# Checked on 18 Oct 2026: Sangrur dNBR 0.64 with a charred surface (burn scar),
# Karnal dNBR -0.03 (no burn scar).
SATELLITE_EXAMPLES = [
    ("example_2024_sangrur", "Sangrur", 30.236, 75.96),
    ("example_2024_karnal", "Karnal", 29.62, 76.90),
]


def seed_satellite_examples(db) -> int:
    for ex_id, district, lat, lon in SATELLITE_EXAMPLES:
        listing = store.save_listing(db, f"farmer_{ex_id}", {
            "acres": 1, "quantity_kg": 1750.0, "crop_type": "rice_stubble", "district": district,
            "village_or_district": f"{district} (2024 field, satellite check example)", "lat": lat, "lon": lon,
            "ready_by": "2024-10-28", "sowing_deadline": "2024-11-10"}, "English")
        store.save_booking(db, {
            "id": f"booking_{ex_id}", "listing_id": listing["id"], "farmer_id": f"farmer_{ex_id}",
            "depot_id": "dep_sangrur" if district == "Sangrur" else "dep_karnal", "district": district,
            "kg": 1750.0, "price_per_kg": 0.6, "status": "paid", "collected_kg": 1750.0,
            "collected_on": "2024-10-29", "satellite_example": True})
    return len(SATELLITE_EXAMPLES)


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
        booked = place_requests(db, listings, today)
        summaries = pickups.plan_depots(db, {b["depot_id"] for b in booked if b})
        print(f"seeded {len(listings)} listings -> {sum(1 for b in booked if b)} bookings")
        for s in summaries:
            print("  ", s)
        print("demo run:", demo_run(db))
        print("earlier pickups:", seed_history(db, today))
    print("satellite examples:", seed_satellite_examples(db))
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
