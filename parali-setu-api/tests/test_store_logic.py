"""Booking lifecycle and store helpers, against the in-memory Firestore."""
import pytest

import firestore_store as store


def test_booking_lifecycle_allows_only_the_documented_moves():
    assert store.can_transition("offered", "booked")
    assert store.can_transition("offered", "expired")
    assert store.can_transition("unschedulable", "offered")
    assert store.can_transition("booked", "verified") and store.can_transition("verified", "collected")
    assert not store.can_transition("booked", "collected"), "no crew goes before a person has confirmed the pickup"
    assert store.can_transition("collected", "paid")
    assert not store.can_transition("booked", "offered"), "an accepted slot is never silently un-accepted"
    assert not store.can_transition("offered", "paid"), "nobody is paid before collection"
    for terminal in ("paid", "expired", "cancelled"):
        assert store.BOOKING_TRANSITIONS[terminal] == set()


def test_update_booking_status_enforces_the_lifecycle(fake_db):
    booking = store.save_booking(fake_db, {"farmer_id": "f1", "kg": 1000, "price_per_kg": 0.6, "depot_id": "d1"})
    assert booking["status"] == "offered"
    updated = store.update_booking_status(fake_db, booking["id"], "booked", {"accepted_by": "farmer"})
    assert updated["status"] == "booked" and updated["accepted_by"] == "farmer"
    with pytest.raises(store.InvalidTransition):
        store.update_booking_status(fake_db, booking["id"], "offered")
    with pytest.raises(KeyError):
        store.update_booking_status(fake_db, "missing", "booked")


def test_posted_prices_are_keyed_by_day_and_district(fake_db):
    assert store.price_doc_id("2026-10-17", "Fatehgarh Sahib") == "2026-10-17_fatehgarh_sahib"
    store.save_posted_prices(fake_db, [{"date": "2026-10-17", "district": "Sangrur", "price_per_kg": 0.6}])
    assert store.get_posted_price(fake_db, "2026-10-17", "Sangrur")["price_per_kg"] == 0.6
    assert store.get_posted_price(fake_db, "2026-10-18", "Sangrur") is None


def test_replanning_keeps_locked_slots_and_drops_stale_tentative_ones(fake_db):
    def slot(sid, status):
        return {"id": sid, "booking_id": sid, "depot_id": "d1", "status": status, "locked": status == "locked",
                "date": "2026-10-18", "planned_start_min": 480}
    for s in (slot("a", "locked"), slot("b", "tentative"), slot("c", "collected")):
        fake_db.collection("pickup_slots").document(s["id"]).set(s)
    store.replace_depot_plan(fake_db, "d1", [slot("d", "tentative")])
    assert sorted(s["id"] for s in fake_db.docs("pickup_slots")) == ["a", "c", "d"]
