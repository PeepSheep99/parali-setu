"""The demo scenario reset_demo.py seeds, run in memory through the real
planners: every farm gets a slot, Patiala's overflow goes to partner crews,
the demo run leaves real stock and payouts, and the delivery plan has no
shortfall."""
import firestore_store as store
import operations
import reset_demo


def test_full_demo_season(world):
    listings = reset_demo.seed_listings(world, operations.pickups.now_ist().date())
    assert len(listings) == sum(reset_demo.LISTINGS_PER_DISTRICT.values())
    booked = [operations.book_listing(world, listing)[0] for listing in listings]
    assert all(booked), "every demo farm is within a depot's reach"
    summaries = operations.pickups.plan_depots(world, {b["depot_id"] for b in booked})
    assert sum(s["unschedulable"] for s in summaries) == 0, "every farm gets a slot"
    patiala = next(s for s in summaries if s["depot_id"] == "dep_patiala")
    assert patiala["on_partner_crews"] > 0, "Patiala's single crew is topped up by partners"

    run = reset_demo.demo_run(world)
    assert run["accepted"] == reset_demo.DEMO_ACCEPTED
    assert 1 <= run["collected"] <= reset_demo.DEMO_COLLECTED, "only farms whose slot day has come are collected"
    today = operations.pickups.now_ist().date().isoformat()
    for b in store.get_bookings(world, ("paid",)):
        assert min(s["date"] for s in store.get_slots_for_booking(world, b["id"])) <= today
    assert run["paid_inr"] > 0
    assert sum(operations.depot_stock_t(world, d["id"]) for d in store.get_depots(world)) > 0

    deliveries = operations.run_deliveries(world)
    assert deliveries["shortfall_t"] == 0


def test_demo_names_are_marked_and_assumptions_are_stated(world):
    assert all("(demo)" in c["name"] and c["demo"] for c in store.get_customers(world))
    partners = [c for d in store.get_depots(world) for c in store.get_crews_for_depot(world, d["id"]) if c["partner"]]
    assert len(partners) == reset_demo.ONCALL_CREWS_PER_DEPOT * len(reset_demo.DEPOTS)
    assert all(c["on_call"] and c["name"].startswith("On-call crew") for c in partners)
    plan = store.get_plan(world, "procurement_current")
    assert set(plan["assumptions"]) >= {"booking_share", "forecast_market_share", "forecast"}
