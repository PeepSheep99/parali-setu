"""Pickup planning service: the glue between Firestore and scheduler.py.

Pure functions (job building, plan interpretation) are kept separate from
the Firestore orchestration so they can be tested without a database.
"""
from __future__ import annotations

from datetime import date, timedelta

import firestore_store as store
from geo import DISTRICT_COORDS, district_from_text
from scheduler import (
    HORIZON_DAYS,
    Crew,
    LockedSlot,
    PickupJob,
    ScheduleResult,
    acres_from_kg,
    plan_pickups,
)

ACTIVE_STATUSES = ("proposed", "waitlisted", "scheduled")
REASON_LOCATION_UNKNOWN = "We don't know where this farm is yet."
# When a farmer gives no sowing date we plan as if it were this many days
# after the stubble is ready, and say so wherever the slot is shown.
ASSUMED_WINDOW_DAYS = 10


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


def crew_from_doc(doc: dict) -> Crew:
    return Crew(
        id=doc["id"], company_id=doc["company_id"],
        depot_lat=doc["depot_lat"], depot_lon=doc["depot_lon"],
        shift_start_min=doc.get("shift_start_min", 7 * 60),
        shift_end_min=doc.get("shift_end_min", 18 * 60),
        acres_per_day=doc.get("acres_per_day", 20.0),
    )


def build_jobs(matches: list[dict], listings: dict[str, dict], locked_slots: dict[str, list[dict]],
               today: date) -> tuple[list[PickupJob], list[dict]]:
    """Turns active matches into scheduler jobs. A match's acres are its
    share of the listing (matched kg at 1.75 t/acre). A scheduled match with
    locked slots becomes one job per locked visit, each pinned to its slot.
    Returns (jobs, unschedulable) where unschedulable covers farms we can't
    place on a map."""
    jobs, unschedulable = [], []
    for match in matches:
        listing = listings.get(match["listing_id"]) or {}
        location = listing_location(listing)
        if location is None:
            unschedulable.append({"match_id": match["id"], "reason": REASON_LOCATION_UNKNOWN})
            continue
        lat, lon, _ = location
        earliest, latest, _ = listing_window(listing, today)
        locks = locked_slots.get(match["id"]) or []
        if match.get("status") == "scheduled" and locks:
            for slot in locks:
                jobs.append(PickupJob(
                    match_id=f"{match['id']}#v{slot['visit']}", company_id=match["company_id"],
                    lat=lat, lon=lon, acres=slot["acres"], earliest=earliest, latest=latest,
                    locked=LockedSlot(crew_id=slot["crew_id"], day=date.fromisoformat(slot["date"]),
                                      window_start_min=slot["window_start_min"],
                                      window_end_min=slot["window_end_min"])))
            continue
        jobs.append(PickupJob(
            match_id=match["id"], company_id=match["company_id"], lat=lat, lon=lon,
            acres=acres_from_kg(match["matched_kg"]), earliest=earliest, latest=latest))
    return jobs, unschedulable


def base_match_id(job_id: str) -> str:
    return job_id.split("#v", 1)[0]


def slots_from_result(result: ScheduleResult, company_id: str, locked_job_ids: set[str]) -> list[dict]:
    slots = []
    for a in result.assignments:
        match_id = base_match_id(a.match_id)
        visit = int(a.match_id.split("#v", 1)[1]) if "#v" in a.match_id else a.visit
        locked = a.match_id in locked_job_ids
        slots.append({
            "id": f"slot_{match_id}_{visit}", "match_id": match_id, "visit": visit, "company_id": company_id,
            "crew_id": a.crew_id, "date": a.day.isoformat(),
            "window_start_min": a.window_start_min, "window_end_min": a.window_end_min,
            "planned_start_min": a.start_min, "planned_end_min": a.end_min,
            "sequence": a.sequence, "acres": a.acres,
            "locked": locked, "status": "locked" if locked else "tentative",
        })
    return slots


def plan_company(db, company_id: str, today: date | None = None, time_limit_seconds: int = 2) -> dict:
    """Re-plans every active match of one buyer and writes the result.

    - proposed with a slot: stays proposed, offer shows the tentative slot
    - proposed or waitlisted without a slot: waitlisted, with the reason
    - waitlisted that now fits: back to proposed
    - scheduled (locked) that can't be kept: stays scheduled, flagged for a
      person to resolve -- a promise is never silently moved
    """
    today = today or date.today()
    matches = [m for m in store.get_matches_for_company(db, company_id) if m.get("status", "proposed") in ACTIVE_STATUSES]
    crews = [crew_from_doc(c) for c in store.get_crews_for_company(db, company_id)]
    listings = {lid: doc for lid in {m["listing_id"] for m in matches} if (doc := store.get_listing(db, lid))}
    locked: dict[str, list[dict]] = {}
    for slot in store.get_slots_for_company(db, company_id):
        if slot.get("locked") and slot.get("status") == "locked":
            locked.setdefault(slot["match_id"], []).append(slot)

    jobs, unschedulable = build_jobs(matches, listings, locked, today)
    result = plan_pickups(jobs, crews, today, horizon_days=HORIZON_DAYS, time_limit_seconds=time_limit_seconds)
    unschedulable += result.unschedulable
    locked_job_ids = {j.match_id for j in jobs if j.locked is not None}
    store.replace_company_plan(db, company_id, slots_from_result(result, company_id, locked_job_ids))

    reasons: dict[str, str] = {}
    for u in unschedulable:
        reasons.setdefault(base_match_id(u["match_id"]), u["reason"])
    summary = {"company_id": company_id, "scheduled": 0, "proposed_with_slot": 0, "waitlisted": 0, "needs_attention": 0}
    for match in matches:
        status = match.get("status", "proposed")
        reason = reasons.get(match["id"])
        if status == "scheduled":
            summary["scheduled"] += 1
            if reason:
                summary["needs_attention"] += 1
                store.update_match_fields(db, match["id"], {"schedule_note": reason})
            continue
        if reason:
            summary["waitlisted"] += 1
            if status == "waitlisted":
                store.update_match_fields(db, match["id"], {"status_reason": reason})
            else:
                store.update_match_status(db, match["id"], "waitlisted", {"status_reason": reason})
        else:
            summary["proposed_with_slot"] += 1
            if status == "waitlisted":
                store.update_match_status(db, match["id"], "proposed", {"status_reason": None})
    return summary


def plan_companies(db, company_ids, **kwargs) -> list[dict]:
    return [plan_company(db, cid, **kwargs) for cid in sorted(set(company_ids))]


def window_label(slot: dict) -> str:
    def hhmm(m: int) -> str:
        return f"{m // 60:02d}:{m % 60:02d}"
    return f"{slot['date']} {hhmm(slot['window_start_min'])}-{hhmm(slot['window_end_min'])}"
