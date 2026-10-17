"""Pickup planning: locations, windows, depot choice, offer expiry, planning
a depot (with partner crews), and collect-and-pay."""
from datetime import date, datetime, timedelta

import firestore_store as store
import operations
import pickups
from geo import DISTRICT_COORDS
from scheduler import Assignment, ScheduleResult

TODAY = date(2026, 10, 17)
SANGRUR = DISTRICT_COORDS["Sangrur"]


def test_location_is_exact_when_shared_else_the_district_hq():
    assert pickups.listing_location({"lat": 30.1, "lon": 75.8}) == (30.1, 75.8, False)
    assert pickups.listing_location({"village_or_district": "Bahadurpur, Sangrur"}) == (*SANGRUR, True)
    assert pickups.listing_location({"village_or_district": "somewhere unknown"}) is None


def test_district_comes_from_the_text_or_the_nearest_hq():
    assert pickups.listing_district({"village_or_district": "ਸੰਗਰੂਰ"}) == "Sangrur"
    assert pickups.listing_district({"lat": SANGRUR[0] + 0.05, "lon": SANGRUR[1]}) == "Sangrur"
    assert pickups.listing_district({}) is None


def test_window_ends_the_day_before_sowing_or_is_marked_assumed():
    assert pickups.listing_window({"ready_by": "2026-10-18", "sowing_deadline": "2026-10-25"}, TODAY) == (
        date(2026, 10, 18), date(2026, 10, 24), False)
    earliest, latest, assumed = pickups.listing_window({}, TODAY)
    assert assumed and latest - earliest == timedelta(days=pickups.ASSUMED_WINDOW_DAYS)


def test_offers_lapse_after_the_hold_but_bookings_never_do():
    created = datetime(2026, 10, 17, 9, 0, tzinfo=pickups.IST)
    offer = {"status": "offered", "created_at": created.isoformat()}
    assert not pickups.offer_expired(offer, created + timedelta(hours=pickups.OFFER_HOLD_HOURS - 1))
    assert pickups.offer_expired(offer, created + timedelta(hours=pickups.OFFER_HOLD_HOURS))
    assert not pickups.offer_expired({**offer, "status": "booked"}, created + timedelta(days=3))


def test_depot_choice_follows_the_plan_then_distance():
    near = {"id": "near", "lat": SANGRUR[0], "lon": SANGRUR[1], "radius_km": 70}
    other = {"id": "other", "lat": SANGRUR[0] + 0.3, "lon": SANGRUR[1], "radius_km": 70}
    assert pickups.choose_depot([near, other], {}, *SANGRUR)["id"] == "near"
    assert pickups.choose_depot([near, other], {"other": 500.0}, *SANGRUR)["id"] == "other"
    assert pickups.choose_depot([near], {}, SANGRUR[0] + 3, SANGRUR[1]) is None, "out of every depot's reach"


def test_slots_record_partner_crews_and_locks():
    a = Assignment("b1", 0, "p1", TODAY, 480, 600, 480, 660, 1, 5.0)
    slots = pickups.slots_from_result(ScheduleResult([a], []), "d1", locked_job_ids=set(), partner_crew_ids={"p1"})
    assert slots[0]["partner"] is True and slots[0]["status"] == "tentative" and slots[0]["booking_id"] == "b1"


def _book(db, district, acres, ready, sowing, n):
    lat, lon = DISTRICT_COORDS[district]
    listing = store.save_listing(db, f"farmer_{n}", {
        "acres": acres, "quantity_kg": acres * 1750.0, "crop_type": "rice_stubble", "district": district,
        "village_or_district": district, "ready_by": ready.isoformat(), "sowing_deadline": sowing.isoformat(),
        "lat": lat + 0.02 * n, "lon": lon}, "Hindi")
    booking, _ = operations.book_listing(db, listing, TODAY)
    return booking


def test_every_booking_gets_a_slot_and_partners_cover_the_overflow(world):
    # Patiala has one own crew: six farms due within three days need hired crews.
    bookings = [_book(world, "Patiala", 12, TODAY, TODAY + timedelta(days=3), n) for n in range(6)]
    summary = pickups.plan_depot(world, "dep_patiala")
    assert summary["unschedulable"] == 0 and summary["offered"] == 6
    assert summary["on_partner_crews"] > 0
    for b in bookings:
        assert store.get_slots_for_booking(world, b["id"]), "a slot for every farm"


def test_stale_offers_expire_and_free_their_slots(world):
    booking = _book(world, "Sangrur", 6, TODAY, TODAY + timedelta(days=6), 1)
    pickups.plan_depot(world, booking["depot_id"])
    assert store.get_slots_for_booking(world, booking["id"])
    later = pickups.now_ist() + timedelta(hours=pickups.OFFER_HOLD_HOURS + 1)
    assert pickups.expire_stale_offers(world, later) == [booking["id"]]
    assert store.get_booking(world, booking["id"])["status"] == "expired"
    assert store.get_slots_for_booking(world, booking["id"]) == []


def test_collecting_pays_the_farmer_the_same_day_and_adds_stock(world):
    booking = _book(world, "Sangrur", 8, TODAY, TODAY + timedelta(days=6), 1)
    pickups.plan_depot(world, booking["depot_id"])
    store.update_booking_status(world, booking["id"], "booked")
    result = pickups.complete_pickup(world, booking["id"], collected_kg=13000)
    assert result["booking"]["status"] == "paid"
    assert result["purchase"]["amount_inr"] == round(13000 * booking["price_per_kg"], 2)
    assert result["purchase"]["paid_on"] == TODAY.isoformat() and result["purchase"]["simulated"] is True
    move = result["inventory_move"]
    assert (move["kind"], move["tonnes"], move["depot_id"]) == ("inbound", 13.0, booking["depot_id"])
    assert operations.depot_stock_t(world, booking["depot_id"]) == 13.0
