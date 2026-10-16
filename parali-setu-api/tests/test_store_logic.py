"""Pure-logic tests for firestore_store: remaining-quantity arithmetic and the
match lifecycle rules. The Firestore transactions only read, call these, and
write, so testing these covers the decisions without a database."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from firestore_store import (  # noqa: E402
    MATCH_TRANSITIONS,
    can_transition,
    demand_remaining_kg,
    demand_remaining_update,
    listing_remaining_update,
)


def test_listing_decrement_closes_listing_when_exhausted():
    assert listing_remaining_update({"quantity_kg": 500, "quantity_remaining_kg": 500}, -200) == {
        "quantity_remaining_kg": 300, "status": "open"}
    assert listing_remaining_update({"quantity_kg": 500, "quantity_remaining_kg": 300}, -300) == {
        "quantity_remaining_kg": 0, "status": "matched"}


def test_listing_restore_reopens_and_never_exceeds_original():
    assert listing_remaining_update({"quantity_kg": 500, "quantity_remaining_kg": 0}, 200) == {
        "quantity_remaining_kg": 200, "status": "open"}
    assert listing_remaining_update({"quantity_kg": 500, "quantity_remaining_kg": 400}, 300)["quantity_remaining_kg"] == 500


def test_listing_legacy_doc_without_remaining_uses_full_quantity():
    assert listing_remaining_update({"quantity_kg": 500}, -100)["quantity_remaining_kg"] == 400


def test_demand_remaining_falls_back_to_quantity_needed():
    assert demand_remaining_kg({"quantity_needed_kg": 3000}) == 3000
    assert demand_remaining_kg({"quantity_needed_kg": 3000, "quantity_remaining_kg": 1200}) == 1200


def test_demand_decrement_and_restore_are_clamped():
    """Regression: demand capacity used to never go down, so the same
    kilograms could be sold to every new listing."""
    assert demand_remaining_update({"quantity_needed_kg": 3000}, -1000) == {"quantity_remaining_kg": 2000}
    assert demand_remaining_update({"quantity_needed_kg": 3000, "quantity_remaining_kg": 500}, -900) == {
        "quantity_remaining_kg": 0}
    assert demand_remaining_update({"quantity_needed_kg": 3000, "quantity_remaining_kg": 2900}, 500) == {
        "quantity_remaining_kg": 3000}


def test_lifecycle_allows_the_happy_path():
    path = ["proposed", "scheduled", "collected", "paid"]
    for current, nxt in zip(path, path[1:]):
        assert can_transition(current, nxt), (current, nxt)


def test_lifecycle_refuses_skips_and_terminal_moves():
    assert not can_transition("proposed", "collected")
    assert not can_transition("proposed", "paid")
    assert not can_transition("collected", "rejected")
    assert not can_transition("paid", "proposed")
    assert not can_transition("rejected", "scheduled")
    assert MATCH_TRANSITIONS["paid"] == set() and MATCH_TRANSITIONS["rejected"] == set()


def test_lifecycle_waitlist_round_trip_and_missing_status_defaults_to_proposed():
    assert can_transition("proposed", "waitlisted")
    assert can_transition("waitlisted", "proposed")
    assert can_transition(None, "scheduled")
