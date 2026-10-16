"""The demo scenario seeded by reset_demo.py, run through the real solver and
scheduler in memory: most farms get slots, and the deliberately overloaded
district shows the waitlist path."""
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import firestore_store as store  # noqa: E402
import main  # noqa: E402
import pickups  # noqa: E402
import reset_demo  # noqa: E402
from scheduler import plan_pickups  # noqa: E402
from solver import solve_matches  # noqa: E402

TODAY = date(2026, 10, 20)


def capture_seed(monkeypatch):
    captured = {"companies": [], "demand": [], "listings": [], "crews": []}
    monkeypatch.setattr(store, "save_company", lambda db, c: captured["companies"].append(c) or c)
    monkeypatch.setattr(store, "save_demand", lambda db, cid, d: captured["demand"].append({**d, "company_id": cid}) or d)

    def save_listing(db, farmer_id, extracted, language):
        doc = {**extracted, "id": f"l{len(captured['listings']) + 1}", "farmer_id": farmer_id,
               "quantity_remaining_kg": extracted["quantity_kg"]}
        captured["listings"].append(doc)
        return doc
    monkeypatch.setattr(store, "save_listing", save_listing)

    db = MagicMock()
    db.collection.return_value.document.return_value.set.side_effect = lambda doc: captured["crews"].append(doc)
    reset_demo.seed_buyers(db)
    reset_demo.seed_listings(db, TODAY)
    return captured


def test_scenario_has_slots_and_a_visible_waitlist(monkeypatch):
    seed = capture_seed(monkeypatch)
    assert len(seed["companies"]) == 5 and len(seed["crews"]) == 8
    assert all("(demo)" in c["name"] for c in seed["companies"])
    assert all(d["price_offer_per_kg"] <= 1.5 for d in seed["demand"]), "farm-gate prices, not Rs 8/kg"

    listings = [main._to_solver_listing(d) for d in seed["listings"]]
    demands = [main._to_solver_demand(d) for d in seed["demand"]]
    matches = solve_matches(listings, demands, today=TODAY)
    assert len({m.listing_id for m in matches}) >= 20, "almost every farm finds a reachable buyer"

    by_listing = {d["id"]: d for d in seed["listings"]}
    match_docs = [{"id": f"m{i}", "listing_id": m.listing_id, "company_id": m.company_id,
                   "matched_kg": m.matched_kg, "status": "proposed"} for i, m in enumerate(matches)]
    jobs, unknown = pickups.build_jobs(match_docs, by_listing, {}, TODAY)
    assert unknown == []
    crews = [pickups.crew_from_doc(c) for c in seed["crews"]]
    result = plan_pickups(jobs, crews, TODAY, time_limit_seconds=0)

    scheduled = {a.match_id for a in result.assignments}
    assert len(scheduled) >= 0.6 * len(match_docs), (len(scheduled), len(match_docs))
    assert result.unschedulable, "the overloaded district should put someone on the waitlist"
    waitlisted_places = {by_listing[next(m["listing_id"] for m in match_docs if m["id"] == u["match_id"])]["village_or_district"]
                         for u in result.unschedulable}
    assert "Patiala" in waitlisted_places
