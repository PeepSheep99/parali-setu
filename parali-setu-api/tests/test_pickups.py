"""Tests for the pickup planning service (pickups.py), using an in-memory
stand-in for Firestore."""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import firestore_store as store  # noqa: E402
import pickups  # noqa: E402
from geo import DISTRICT_COORDS  # noqa: E402

TODAY = date(2026, 10, 20)


def test_location_prefers_shared_coordinates_then_district():
    assert pickups.listing_location({"lat": 30.1, "lon": 75.9}) == (30.1, 75.9, False)
    lat, lon = DISTRICT_COORDS["Patiala"]
    assert pickups.listing_location({"village_or_district": "Rajpura, Patiala"}) == (lat, lon, True)
    assert pickups.listing_location({"village_or_district": "somewhere"}) is None


def test_window_ends_the_day_before_sowing_or_is_assumed():
    listing = {"ready_by": "2026-10-22", "sowing_deadline": "2026-10-28"}
    assert pickups.listing_window(listing, TODAY) == (date(2026, 10, 22), date(2026, 10, 27), False)
    earliest, latest, assumed = pickups.listing_window({}, TODAY)
    assert (earliest, latest, assumed) == (TODAY, TODAY + timedelta(days=pickups.ASSUMED_WINDOW_DAYS), True)
    past_ready = pickups.listing_window({"ready_by": "2026-10-01"}, TODAY)
    assert past_ready[0] == TODAY, "a ready date in the past means ready now"


def test_build_jobs_expands_locked_visits_and_reports_unknown_locations():
    matches = [
        {"id": "m1", "listing_id": "l1", "company_id": "c1", "matched_kg": 3500, "status": "proposed"},
        {"id": "m2", "listing_id": "l2", "company_id": "c1", "matched_kg": 1750, "status": "scheduled"},
        {"id": "m3", "listing_id": "l3", "company_id": "c1", "matched_kg": 1750, "status": "proposed"},
    ]
    listings = {"l1": {"village_or_district": "Sangrur"}, "l2": {"lat": 30.2, "lon": 75.8}, "l3": {}}
    locked = {"m2": [{"visit": 0, "acres": 1.0, "crew_id": "k1", "date": "2026-10-21",
                      "window_start_min": 540, "window_end_min": 720}]}
    jobs, unschedulable = pickups.build_jobs(matches, listings, locked, TODAY)
    by_id = {j.match_id: j for j in jobs}
    assert by_id["m1"].acres == 2.0 and by_id["m1"].locked is None
    assert by_id["m2#v0"].locked.day == date(2026, 10, 21)
    assert unschedulable == [{"match_id": "m3", "reason": pickups.REASON_LOCATION_UNKNOWN}]


class FakeStore:
    """Just enough of firestore_store for plan_company."""

    def __init__(self, matches, listings, crews, slots=None):
        self.matches = {m["id"]: dict(m) for m in matches}
        self.listings = listings
        self.crews = crews
        self.slots = {s["id"]: dict(s) for s in (slots or [])}

    def install(self, monkeypatch):
        monkeypatch.setattr(store, "get_matches_for_company", lambda db, cid: [m for m in self.matches.values() if m["company_id"] == cid])
        monkeypatch.setattr(store, "get_crews_for_company", lambda db, cid: [c for c in self.crews if c["company_id"] == cid])
        monkeypatch.setattr(store, "get_listing", lambda db, lid: self.listings.get(lid))
        monkeypatch.setattr(store, "get_slots_for_company", lambda db, cid: [s for s in self.slots.values() if s["company_id"] == cid])
        monkeypatch.setattr(store, "replace_company_plan", self.replace_company_plan)
        monkeypatch.setattr(store, "update_match_fields", lambda db, mid, fields: self.matches[mid].update(fields))
        monkeypatch.setattr(store, "update_match_status", self.update_match_status)

    def replace_company_plan(self, db, cid, slots):
        for sid in [sid for sid, s in self.slots.items() if s["company_id"] == cid and s["status"] == "tentative"]:
            del self.slots[sid]
        for s in slots:
            self.slots[s["id"]] = {**self.slots.get(s["id"], {}), **s}

    def update_match_status(self, db, mid, status, extra=None):
        assert store.can_transition(self.matches[mid].get("status"), status), (self.matches[mid]["status"], status)
        self.matches[mid].update({**(extra or {}), "status": status})
        return self.matches[mid]


def _crew(cid="k1", company="c1", acres=20.0):
    lat, lon = DISTRICT_COORDS["Sangrur"]
    return {"id": cid, "company_id": company, "depot_lat": lat, "depot_lon": lon, "acres_per_day": acres}


def _listing(lid, ready="2026-10-20", sowing="2026-10-21"):
    return {"id": lid, "village_or_district": "Sangrur", "ready_by": ready, "sowing_deadline": sowing}


def test_plan_gives_slots_and_waitlists_the_overflow(monkeypatch):
    # Sowing on the 21st means the only pickup day is the 20th: one 20-acre
    # crew-day fits two 8.75-acre farms (15.3 t each), not three.
    matches = [{"id": f"m{i}", "listing_id": f"l{i}", "company_id": "c1", "farmer_id": f"f{i}",
                "matched_kg": 15312.5, "price_agreed_per_kg": 1.0, "status": "proposed"} for i in range(3)]
    fake = FakeStore(matches, {f"l{i}": _listing(f"l{i}") for i in range(3)}, [_crew()])
    fake.install(monkeypatch)

    summary = pickups.plan_company(None, "c1", today=TODAY, time_limit_seconds=0)
    assert summary["proposed_with_slot"] == 2 and summary["waitlisted"] == 1
    waitlisted = [m for m in fake.matches.values() if m["status"] == "waitlisted"]
    assert len(waitlisted) == 1 and waitlisted[0]["status_reason"]
    assert {s["match_id"] for s in fake.slots.values()} == {m["id"] for m in fake.matches.values() if m["status"] == "proposed"}
    assert all(s["status"] == "tentative" and s["date"] == "2026-10-20" for s in fake.slots.values())


def test_waitlisted_farm_is_promoted_when_a_crew_is_added(monkeypatch):
    matches = [{"id": f"m{i}", "listing_id": f"l{i}", "company_id": "c1", "farmer_id": f"f{i}",
                "matched_kg": 15312.5, "price_agreed_per_kg": 1.0, "status": "proposed"} for i in range(3)]
    fake = FakeStore(matches, {f"l{i}": _listing(f"l{i}") for i in range(3)}, [_crew()])
    fake.install(monkeypatch)
    pickups.plan_company(None, "c1", today=TODAY, time_limit_seconds=0)

    fake.crews.append(_crew("k2"))
    summary = pickups.plan_company(None, "c1", today=TODAY, time_limit_seconds=0)
    assert summary["waitlisted"] == 0
    assert all(m["status"] == "proposed" for m in fake.matches.values())


def test_locked_promise_is_flagged_not_moved_when_it_cannot_be_kept(monkeypatch):
    matches = [{"id": "m1", "listing_id": "l1", "company_id": "c1", "farmer_id": "f1",
                "matched_kg": 1750, "price_agreed_per_kg": 1.0, "status": "scheduled"}]
    slot = {"id": "slot_m1_0", "match_id": "m1", "visit": 0, "company_id": "c1", "crew_id": "gone",
            "date": "2026-10-20", "window_start_min": 540, "window_end_min": 720, "planned_start_min": 560,
            "planned_end_min": 590, "sequence": 1, "acres": 1.0, "locked": True, "status": "locked"}
    fake = FakeStore(matches, {"l1": _listing("l1", sowing="2026-10-25")}, [_crew()], [slot])
    fake.install(monkeypatch)

    summary = pickups.plan_company(None, "c1", today=TODAY, time_limit_seconds=0)
    assert summary["needs_attention"] == 1
    assert fake.matches["m1"]["status"] == "scheduled", "a promise is never silently moved or dropped"
    assert fake.matches["m1"]["schedule_note"]
    assert fake.slots["slot_m1_0"]["crew_id"] == "gone", "the locked slot record stays as promised"


def test_window_label():
    assert pickups.window_label({"date": "2026-10-21", "window_start_min": 540, "window_end_min": 720}) == "2026-10-21 09:00-12:00"
