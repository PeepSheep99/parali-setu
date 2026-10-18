"""Pickup planning service: the glue between Firestore and scheduler.py.

Pure functions (job building, plan interpretation, depot choice, offer
expiry) are kept separate from the Firestore orchestration so they can be
tested without a database.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import re
import firestore_store as store
from costs import road_km
from geo import DISTRICT_COORDS, district_from_text
from scheduler import (
    HORIZON_DAYS,
    STRAW_T_PER_ACRE,
    Crew,
    LockedSlot,
    PickupJob,
    ScheduleResult,
    acres_from_kg,
    plan_pickups,
    reason_code,
)

REASON_LOCATION_UNKNOWN = "We don't know where this farm is yet."
# When a farmer gives no sowing date we plan as if it were this many days
# after the stubble is ready, and say so wherever the slot is shown.
ASSUMED_WINDOW_DAYS = 10
# An offer the farmer hasn't accepted lapses after this, so abandoned offers
# never hold crew time. The farmer sees the deadline on the offer.
OFFER_HOLD_HOURS = 4
# Farms and crews are in India; Cloud Run's clock is UTC. Planning uses IST
# so "today" and today's earliest slot are right for the farmer.
IST = timezone(timedelta(hours=5, minutes=30))
SAME_DAY_LEAD_MIN = 120      # no slot starts within 2 h of the offer
# A new request needs at least 24 hours' notice: time to call the farmer,
# confirm the details and line up a baler and crew. Counted from when the
# farmer asked, rounded up to the hour so no promised window starts sooner.
NOTICE_HOURS = 24
LAST_START_MIN = 17 * 60     # a notice ending after 5 pm moves to the next morning


def notice_start(booking: dict) -> tuple[date, int] | None:
    """(earliest day, earliest minute that day) a new request can be picked up."""
    created = booking.get("requested_at")
    if not created or NOTICE_HOURS <= 0:
        return None
    ready = datetime.fromisoformat(str(created)).astimezone(now_ist().tzinfo) + timedelta(hours=NOTICE_HOURS)
    minute = ready.hour * 60 + ready.minute
    minute = -(-minute // 60) * 60   # up to the hour
    if minute > LAST_START_MIN:
        return ready.date() + timedelta(days=1), 0
    return ready.date(), minute
OFFER_BEFORE_SLOT_MIN = 60  # an offer lapses at least 1 h before its slot starts


def now_ist() -> datetime:
    return datetime.now(IST)


def listing_location(listing: dict) -> tuple[float, float, bool] | None:
    """(lat, lon, approximate). A shared location is exact; otherwise the
    district HQ named in the listing, flagged approximate; else None."""
    if listing.get("lat") is not None and listing.get("lon") is not None:
        return listing["lat"], listing["lon"], False
    district = district_from_text(listing.get("district") or listing.get("village_or_district"))
    if district:
        lat, lon = DISTRICT_COORDS[district]
        return lat, lon, True
    return None


def listing_district(listing: dict) -> str | None:
    """The district a listing is priced in: named in the text, else the
    nearest district HQ to a shared location."""
    named = district_from_text(listing.get("district") or listing.get("village_or_district"))
    if named:
        return named
    if listing.get("lat") is not None and listing.get("lon") is not None:
        return min(DISTRICT_COORDS, key=lambda d: road_km(listing["lat"], listing["lon"], *DISTRICT_COORDS[d]))
    return None


def _parse_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def listing_window(listing: dict, today: date) -> tuple[date, date, bool]:
    """(earliest pickup day, last pickup day, window_assumed). The last
    pickup day is the day before sowing, so the field can be prepared."""
    earliest = max(today, _parse_date(listing.get("ready_by")) or today)
    sowing = _parse_date(listing.get("sowing_deadline"))
    if sowing is None:
        return earliest, earliest + timedelta(days=ASSUMED_WINDOW_DAYS), True
    return earliest, sowing - timedelta(days=1), False


def slot_start(slot: dict) -> datetime:
    day = datetime.fromisoformat(slot["date"]).replace(tzinfo=None)
    return (day + timedelta(minutes=slot["window_start_min"])).replace(tzinfo=now_ist().tzinfo)


def offer_expires_at(booking: dict, slots: list[dict] | None = None) -> datetime | None:
    """The offer holds for OFFER_HOLD_HOURS, but never past an hour before the
    pickup slot it offers: a farmer is not shown a slot that has begun."""
    created = booking.get("created_at")
    if not created:
        return None
    expires = datetime.fromisoformat(created) + timedelta(hours=OFFER_HOLD_HOURS)
    if slots:
        expires = min(expires, min(slot_start(s) for s in slots) - timedelta(minutes=OFFER_BEFORE_SLOT_MIN))
    return expires


def offer_expired(booking: dict, now: datetime, slots: list[dict] | None = None) -> bool:
    expires = offer_expires_at(booking, slots)
    return booking.get("status") in ("offered", "unschedulable") and expires is not None and now >= expires


def choose_depot(depots: list[dict], planned_share: dict[str, float], lat: float, lon: float) -> dict | None:
    """The depot a new booking goes to: the one the procurement plan intends
    for this district (largest planned tonnes) if it can reach the farm,
    else the nearest depot whose radius covers the farm."""
    in_reach = [d for d in depots if road_km(lat, lon, d["lat"], d["lon"]) <= d.get("radius_km", 80)]
    if not in_reach:
        return None
    planned = [d for d in in_reach if planned_share.get(d["id"], 0) > 0]
    if planned:
        return max(planned, key=lambda d: planned_share[d["id"]])
    return min(in_reach, key=lambda d: road_km(lat, lon, d["lat"], d["lon"]))


def crew_from_doc(doc: dict) -> Crew:
    return Crew(
        id=doc["id"], depot_id=doc["depot_id"],
        depot_lat=doc["depot_lat"], depot_lon=doc["depot_lon"],
        shift_start_min=doc.get("shift_start_min", 7 * 60),
        shift_end_min=doc.get("shift_end_min", 18 * 60),
        acres_per_day=doc.get("acres_per_day", 20.0),
        partner=doc.get("partner", False),
    )


def build_jobs(bookings: list[dict], listings: dict[str, dict], locked_slots: dict[str, list[dict]],
               today: date) -> tuple[list[PickupJob], list[dict]]:
    """Turns active bookings into scheduler jobs. A booked farm with locked
    slots becomes one job per locked visit, each pinned to its slot.
    Returns (jobs, unschedulable) where unschedulable covers farms we can't
    place on a map."""
    jobs, unschedulable = [], []
    for booking in bookings:
        listing = listings.get(booking["listing_id"]) or {}
        location = listing_location(listing)
        if location is None:
            unschedulable.append({"booking_id": booking["id"], "reason": REASON_LOCATION_UNKNOWN})
            continue
        lat, lon, _ = location
        earliest, latest, _ = listing_window(listing, today)
        locks = locked_slots.get(booking["id"]) or []
        if booking.get("status") in ("booked", "verified") and locks:
            for slot in locks:
                jobs.append(PickupJob(
                    booking_id=f"{booking['id']}#v{slot['visit']}", depot_id=booking["depot_id"],
                    lat=lat, lon=lon, acres=slot["acres"], earliest=earliest, latest=latest,
                    locked=LockedSlot(crew_id=slot["crew_id"], day=date.fromisoformat(slot["date"]),
                                      window_start_min=slot["window_start_min"],
                                      window_end_min=slot["window_end_min"])))
            continue
        not_before = 0
        notice = notice_start(booking)
        if notice and notice[0] >= earliest:
            earliest, not_before = notice
        jobs.append(PickupJob(
            booking_id=booking["id"], depot_id=booking["depot_id"], lat=lat, lon=lon,
            acres=acres_from_kg(booking["kg"]), earliest=earliest, latest=latest, not_before_min=not_before))
    return jobs, unschedulable


def base_booking_id(job_id: str) -> str:
    return job_id.split("#v", 1)[0]


def slots_from_result(result: ScheduleResult, depot_id: str, locked_job_ids: set[str],
                      partner_crew_ids: set[str] = frozenset()) -> list[dict]:
    slots = []
    for a in result.assignments:
        booking_id = base_booking_id(a.booking_id)
        visit = int(a.booking_id.split("#v", 1)[1]) if "#v" in a.booking_id else a.visit
        locked = a.booking_id in locked_job_ids
        slots.append({
            "id": f"slot_{booking_id}_{visit}", "booking_id": booking_id, "visit": visit, "depot_id": depot_id,
            "crew_id": a.crew_id, "partner": a.crew_id in partner_crew_ids, "date": a.day.isoformat(),
            "window_start_min": a.window_start_min, "window_end_min": a.window_end_min,
            "planned_start_min": a.start_min, "planned_end_min": a.end_min,
            "sequence": a.sequence, "acres": a.acres,
            "locked": locked, "status": "locked" if locked else "tentative",
        })
    return slots


def window_label(slot: dict) -> str:
    def hhmm(m: int) -> str:
        return f"{m // 60:02d}:{m % 60:02d}"
    return f"{slot['date']} {hhmm(slot['window_start_min'])}-{hhmm(slot['window_end_min'])}"


# ---- Firestore orchestration

def expire_stale_offers(db, now: datetime | None = None) -> list[str]:
    """Lapses offers nobody accepted within OFFER_HOLD_HOURS and frees their
    tentative slots. Booked pickups never expire."""
    now = now or now_ist()
    expired = []
    for booking in store.get_bookings(db, ("offered", "unschedulable")):
        if offer_expired(booking, now, store.get_slots_for_booking(db, booking["id"])):
            try:
                store.update_booking_status(db, booking["id"], "expired", {"status_reason_code": "expired"})
            except store.InvalidTransition:
                continue
            store.delete_tentative_slots(db, booking["id"])
            expired.append(booking["id"])
    return expired


def plan_depot(db, depot_id: str, today: date | None = None, time_limit_seconds: int = 2) -> dict:
    """Re-plans every active booking of one depot and writes the result.

    - offered with a slot: stays offered with its tentative slot
    - offered or unschedulable without a slot: unschedulable, with the reason
    - unschedulable that now fits: back to offered
    - booked (locked) that can't be kept: stays booked, flagged for a person
      to resolve -- a promise is never silently moved
    """
    not_before = None
    if today is None:
        now = now_ist()
        today = now.date()
        not_before = now.hour * 60 + now.minute + SAME_DAY_LEAD_MIN
    bookings = [b for b in store.get_bookings_for_depot(db, depot_id) if b.get("status") in store.ACTIVE_BOOKING_STATUSES]
    crew_docs = store.get_crews_for_depot(db, depot_id)
    crews = [crew_from_doc(c) for c in crew_docs]
    listings = {lid: doc for lid in {b["listing_id"] for b in bookings} if (doc := store.get_listing(db, lid))}
    locked: dict[str, list[dict]] = {}
    used: dict[tuple[str, date], float] = {}
    for slot in store.get_slots_for_depot(db, depot_id):
        if slot.get("locked") and slot.get("status") == "locked":
            locked.setdefault(slot["booking_id"], []).append(slot)
        elif slot.get("status") == "collected" and slot["date"] >= today.isoformat():
            key = (slot["crew_id"], date.fromisoformat(slot["date"]))
            used[key] = used.get(key, 0.0) + slot["acres"]

    jobs, unschedulable = build_jobs(bookings, listings, locked, today)
    result = plan_pickups(jobs, crews, today, horizon_days=HORIZON_DAYS, time_limit_seconds=time_limit_seconds,
                          not_before_min_today=not_before, used_acres=used)
    unschedulable += result.unschedulable
    locked_job_ids = {j.booking_id for j in jobs if j.locked is not None}
    partner_ids = {c["id"] for c in crew_docs if c.get("partner")}
    slots = slots_from_result(result, depot_id, locked_job_ids, partner_ids)
    store.replace_depot_plan(db, depot_id, slots)

    reasons: dict[str, str] = {}
    for u in unschedulable:
        reasons.setdefault(base_booking_id(u["booking_id"]), u["reason"])
    on_partner = {s["booking_id"] for s in slots if s["partner"]}
    summary = {"depot_id": depot_id, "booked": 0, "offered": 0, "unschedulable": 0, "needs_attention": 0,
               "on_partner_crews": len(on_partner)}
    for booking in bookings:
        status = booking.get("status")
        reason = reasons.get(booking["id"])
        if status in ("booked", "verified"):
            summary["booked"] += 1
            if reason:
                summary["needs_attention"] += 1
                store.update_booking_fields(db, booking["id"], {"schedule_note": reason})
            continue
        if reason:
            summary["unschedulable"] += 1
            extra = {"status_reason": reason, "status_reason_code": reason_code(reason)}
            if status == "unschedulable":
                store.update_booking_fields(db, booking["id"], extra)
            else:
                store.update_booking_status(db, booking["id"], "unschedulable", extra)
        else:
            summary["offered"] += 1
            if status == "unschedulable":
                store.update_booking_status(db, booking["id"], "offered", {"status_reason": None, "status_reason_code": None})
    return summary


def plan_depots(db, depot_ids, **kwargs) -> list[dict]:
    return [plan_depot(db, did, **kwargs) for did in sorted(set(depot_ids))]


def complete_pickup(db, booking_id: str, collected_kg: float | None = None) -> dict:
    """The crew has collected a farm: the booking moves to collected, the
    farmer is paid the same day (a simulated UPI transfer of collected kg x
    the posted price they were offered), the booking moves to paid, and the
    straw is added to the depot's stock.

    All of it is one transaction (store.record_pickup): a crash halfway can't
    leave a farm collected but unpaid, or paid without stock. A crew can't
    mark a farm collected before the day it is scheduled, and a depot can't
    take in more straw than it has room for."""
    booking = store.get_booking(db, booking_id)
    if booking is None:
        raise KeyError("booking not found")
    kg = collected_kg if collected_kg is not None else booking["kg"]
    today = now_ist().date().isoformat()
    slots = store.get_slots_for_booking(db, booking_id)
    if not slots:
        raise BookingError("This pickup has no scheduled slot, so it can't be marked collected")
    first_day = min(s["date"] for s in slots)
    if today < first_day:
        raise BookingError(f"This pickup is scheduled for {first_day}; it can't be marked collected before then")
    try:
        return store.record_pickup(db, booking_id, kg, [s["id"] for s in slots], today)
    except store.LedgerError as exc:
        raise BookingError(str(exc)) from exc


def replace_open_offers(db, farmer_id: str) -> list[str]:
    """A farmer holds one open offer at a time: a new listing replaces any
    offer they have not accepted (accepted pickups are untouched). Returns the
    depots whose plans changed so the caller can re-plan them."""
    depots = []
    for booking in store.get_bookings_for_farmer(db, farmer_id):
        if booking.get("status") not in ("offered", "unschedulable"):
            continue
        try:
            store.update_booking_status(db, booking["id"], "cancelled", {"status_reason_code": "replaced"})
        except store.InvalidTransition:
            continue
        store.delete_tentative_slots(db, booking["id"])
        depots.append(booking["depot_id"])
    return depots


VERIFY_CHECKS = ("phone", "location", "acres", "price")


def verify_booking(db, booking: dict, by: str, checks: dict | None = None, notes: str | None = None) -> dict:
    """A person has called the farmer and confirmed the details: only now is
    the pickup put on a crew's dispatch sheet."""
    record = {"status": "verified", "by": by, "at": now_ist().isoformat(), "notes": notes or None,
              "checks": {k: bool((checks or {}).get(k, True)) for k in VERIFY_CHECKS}}
    try:
        return store.update_booking_status(db, booking["id"], "verified", {"verification": record})
    except store.InvalidTransition as exc:
        raise BookingError(str(exc)) from exc


def flag_booking(db, booking: dict, by: str, notes: str) -> dict:
    """The call found something to fix (a wrong village, a different acreage):
    the pickup stays booked and is not dispatched until it is fixed."""
    if booking.get("status") != "booked":
        raise BookingError("Only a booked pickup awaiting its call can be marked for a change")
    record = {"status": "needs_change", "by": by, "at": now_ist().isoformat(), "notes": notes}
    store.update_booking_fields(db, booking["id"], {"verification": record})
    return {**booking, "verification": record}


def booking_view(db, booking: dict, depots: dict[str, dict] | None = None) -> dict:
    """A booking as the apps show it: depot name, slots, arrival window,
    payout estimate and when an unaccepted offer lapses."""
    depots = depots if depots is not None else {}
    depot = depots.get(booking["depot_id"]) or store.get_depot(db, booking["depot_id"]) or {}
    slots = store.get_slots_for_booking(db, booking["id"])
    expires = offer_expires_at(booking, slots)
    return {
        **booking,
        "depot_name": depot.get("name", booking["depot_id"]),
        "slots": slots,
        "pickup_window": window_label(slots[0]) if slots else None,
        "payout_estimate_inr": round(booking["kg"] * booking["price_per_kg"], 2),
        "offer_expires_at": expires.isoformat() if expires and booking.get("status") in ("offered", "unschedulable") else None,
        "partner_crew": any(s.get("partner") for s in slots),
        "booking_code": booking_code(booking["id"]),
        "verification": booking.get("verification") or ({"status": "verified"} if booking.get("status") in
                                                          ("verified", "collected", "paid") else None),
    }


class BookingError(ValueError):
    """A booking action the farmer or ops can't take right now."""


def accept_booking(db, booking: dict, accepted_by: str) -> dict:
    """Locks an offered slot: the booking becomes `booked` and later re-plans
    fit new work around it. Raises BookingError if there is no slot, the
    offer has lapsed, or the booking is not in a state that can be accepted."""
    if not store.get_slots_for_booking(db, booking["id"]):
        raise BookingError("There is no pickup slot to accept yet")
    if offer_expired(booking, now_ist(), store.get_slots_for_booking(db, booking["id"])):
        raise BookingError("This offer has expired -- please list again for a new slot")
    try:
        updated = store.update_booking_status(db, booking["id"], "booked",
                                              {"slot_accepted_at": now_ist().isoformat(), "accepted_by": accepted_by,
                                               "verification": {"status": "pending"}})
    except store.InvalidTransition as exc:
        raise BookingError(str(exc)) from exc
    locked = store.set_slots_status(db, booking["id"], "locked", locked=True)
    return {"booking": booking_view(db, updated), "slots": locked, "pickup_window": window_label(locked[0])}


def complete_quantities(fields: dict) -> dict:
    """Area and weight are derived from each other in code (1.75 t/acre),
    never by Gemini, so the planners always have both."""
    fields = dict(fields)
    if fields.get("acres") and not fields.get("quantity_kg"):
        fields["quantity_kg"] = round(fields["acres"] * STRAW_T_PER_ACRE * 1000, 1)
    elif fields.get("quantity_kg") and not fields.get("acres"):
        fields["acres"] = acres_from_kg(fields["quantity_kg"])
    return fields


def normalise_phone(text) -> str | None:
    """A 10-digit Indian mobile number as +91XXXXXXXXXX, or None."""
    digits = re.sub(r"\D", "", str(text or ""))
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return f"+91{digits}" if re.fullmatch(r"[6-9]\d{9}", digits) else None


def mask_phone(phone: str | None) -> str | None:
    return f"+91 ******{phone[-4:]}" if phone and len(phone) >= 4 else None


def booking_code(booking_id: str) -> str:
    """A short reference a farmer can read out, e.g. PS-7F3K."""
    letters = re.sub(r"[^A-Za-z0-9]", "", booking_id or "")[-4:].upper()
    return f"PS-{letters}"


def agent_missing_fields(fields: dict) -> list[str]:
    """What the talking agent needs before it may offer a pickup: the listing
    details plus who is selling and how to reach them."""
    missing = missing_fields(fields)
    if not fields.get("farmer_name"):
        missing.append("name")
    if not normalise_phone(fields.get("contact")):
        missing.append("phone")
    return missing


def missing_fields(fields: dict) -> list[str]:
    missing = []
    if not fields.get("quantity_kg") and not fields.get("acres"):
        missing.append("quantity")
    if not fields.get("crop_type"):
        missing.append("crop_type")
    if listing_location(fields) is None:
        missing.append("location")
    if not fields.get("sowing_deadline"):
        missing.append("sowing_deadline")
    return missing
