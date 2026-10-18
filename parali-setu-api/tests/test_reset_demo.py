"""The demo scenario reset_demo.py seeds, run in memory through the real
planners: every farm gets a slot, Patiala's overflow goes to on-call crews,
the demo run leaves real stock and payouts, and the delivery plan has no
shortfall."""
import firestore_store as store
import operations
import reset_demo


def test_full_demo_season(world):
    listings = reset_demo.seed_listings(world, operations.pickups.now_ist().date())
    assert len(listings) == sum(reset_demo.LISTINGS_PER_DISTRICT.values())
    booked = reset_demo.place_requests(world, listings, operations.pickups.now_ist().date())
    assert all(booked), "every demo farm is within a depot's reach"
    summaries = operations.pickups.plan_depots(world, {b["depot_id"] for b in booked})
    assert sum(s["unschedulable"] for s in summaries) == 0, "every farm gets a slot"
    patiala = next(s for s in summaries if s["depot_id"] == "dep_patiala")
    assert patiala["on_partner_crews"] > 0, "Patiala's single crew is topped up by partners"

    run = reset_demo.demo_run(world)
    assert all(run[stage] > 0 for stage in ("offered", "booked", "verified")), run
    history = reset_demo.seed_history(world, operations.pickups.now_ist().date())
    assert history["collected"] == len(reset_demo.HISTORY_FARMS), "earlier pickups give stock and payouts at any hour"
    statuses = {b["status"] for b in store.get_bookings(world)}
    assert {"offered", "booked", "verified", "paid"} <= statuses, "ops sees every stage of a pickup"
    today = operations.pickups.now_ist().date().isoformat()
    for b in store.get_bookings(world, ("paid",)):
        slots = store.get_slots_for_booking(world, b["id"])
        if slots:   # board pickups are collected only once their slot day has come; history has no slots
            assert min(s["date"] for s in slots) <= today
    assert run["paid_inr"] + history["paid_inr"] > 0
    assert sum(operations.depot_stock_t(world, d["id"]) for d in store.get_depots(world)) > 0

    deliveries = operations.run_deliveries(world)
    assert deliveries["shortfall_t"] == 0


def test_demo_names_are_marked_and_assumptions_are_stated(world):
    assert all("(demo)" in c["name"] and c["demo"] for c in store.get_customers(world))
    partners = [c for d in store.get_depots(world) for c in store.get_crews_for_depot(world, d["id"]) if c["partner"]]
    assert len(partners) == reset_demo.ONCALL_CREWS_PER_DEPOT * len(reset_demo.DEPOTS)
    assert all(c["on_call"] and "crew" not in c["name"].lower() for c in partners), "contractors and CHCs by name"
    own = [c for d in store.get_depots(world) for c in store.get_crews_for_depot(world, d["id"]) if not c["partner"]]
    assert all(c["name"].endswith("'s crew") and c["leader"] for c in own)
    plan = store.get_plan(world, "procurement_current")
    assert set(plan["assumptions"]) >= {"booking_share", "forecast_market_share", "forecast"}


def test_synthetic_farmers_read_like_real_requests_with_masked_phones(world):
    listings = reset_demo.seed_listings(world, operations.pickups.now_ist().date())
    assert len({l["farmer_name"] for l in listings}) == len(listings), "every farmer has their own name"
    assert all(l["contact"].startswith("+91 ******") and len(l["contact"]) == 14 for l in listings), "masked only"
    for l in listings:
        village, district = l["village_or_district"].split(", ")
        assert village in reset_demo.VILLAGES[district] and "demo" not in l["village_or_district"]
