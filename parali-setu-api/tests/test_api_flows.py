"""Endpoint tests for the Milestone A fixes, with Firestore and Gemini mocked.
No credentials or network needed."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import firestore_store as store  # noqa: E402
import main  # noqa: E402

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def fake_db(monkeypatch):
    monkeypatch.setattr(store, "get_firestore_client", lambda: MagicMock())
    monkeypatch.setattr(main, "get_gemini_client", lambda: MagicMock())


MATCH = {
    "id": "m1", "listing_id": "l1", "demand_id": "d1", "farmer_id": "f1", "company_id": "c1",
    "matched_kg": 500, "price_agreed_per_kg": 1.0, "status": "proposed",
}


def test_confirm_price_uses_the_session_price_not_the_request(monkeypatch):
    calls = {}
    monkeypatch.setattr(store, "get_match", lambda db, mid: dict(MATCH))
    monkeypatch.setattr(store, "get_negotiation_session", lambda db, sid: {
        "id": sid, "match_id": "m1", "outcome": "converged", "final_price_per_kg": 1.12})
    monkeypatch.setattr(store, "update_match_price", lambda db, mid, price: calls.setdefault("price", price))
    monkeypatch.setattr(store, "mark_negotiation_session_confirmed", lambda db, sid: calls.setdefault("confirmed", sid))
    monkeypatch.setattr(store, "append_negotiation_log", lambda db, mid, entry: None)

    resp = client.post("/matches/m1/confirm-price", json={"session_id": "s1", "new_price_per_kg": 50})
    assert resp.status_code == 200
    assert resp.json()["new_price_per_kg"] == 1.12
    assert calls == {"price": 1.12, "confirmed": "s1"}


@pytest.mark.parametrize("session, code", [
    (None, 404),
    ({"id": "s1", "match_id": "other", "outcome": "converged", "final_price_per_kg": 1.1}, 404),
    ({"id": "s1", "match_id": "m1", "outcome": "no_overlap", "final_price_per_kg": None}, 409),
    ({"id": "s1", "match_id": "m1", "outcome": "converged", "final_price_per_kg": 1.1, "confirmed_at": "x"}, 409),
])
def test_confirm_price_refuses_unusable_sessions(monkeypatch, session, code):
    monkeypatch.setattr(store, "get_match", lambda db, mid: dict(MATCH))
    monkeypatch.setattr(store, "get_negotiation_session", lambda db, sid: session)
    monkeypatch.setattr(store, "update_match_price", lambda *a: pytest.fail("price must not change"))
    assert client.post("/matches/m1/confirm-price", json={"session_id": "s1"}).status_code == code


def test_confirm_price_requires_a_session_id():
    assert client.post("/matches/m1/confirm-price", json={"new_price_per_kg": 12}).status_code == 422


def test_status_endpoint_maps_lifecycle_errors(monkeypatch):
    def refuse(db, mid, status, extra):
        raise store.InvalidTransition("A match that is proposed cannot become paid.")
    monkeypatch.setattr(store, "update_match_status", refuse)
    resp = client.post("/matches/m1/status", json={"status": "paid"})
    assert resp.status_code == 409 and "cannot become paid" in resp.json()["detail"]

    def missing(db, mid, status, extra):
        raise KeyError("match not found")
    monkeypatch.setattr(store, "update_match_status", missing)
    assert client.post("/matches/m1/status", json={"status": "scheduled"}).status_code == 404

    assert client.post("/matches/m1/status", json={"status": "teleported"}).status_code == 422


def test_negotiate_reports_the_ceiling_when_a_counter_offer_is_too_high(monkeypatch):
    monkeypatch.setattr(store, "get_match", lambda db, mid: dict(MATCH))
    monkeypatch.setattr(main, "parse_negotiation_price", lambda c, text, price: {
        "is_price_request": True, "requested_price_per_kg": 50})
    monkeypatch.setattr(store, "get_open_listings", lambda db: [])
    monkeypatch.setattr(store, "get_listing", lambda db, lid: {
        "id": "l1", "farmer_id": "f1", "quantity_kg": 500, "quantity_remaining_kg": 0, "crop_type": "rice_stubble"})
    monkeypatch.setattr(store, "get_trust_scores_by_farmer_ids", lambda db, ids: {})
    monkeypatch.setattr(store, "get_open_demand", lambda db: [])
    monkeypatch.setattr(store, "get_demand", lambda db, did: {
        "id": "d1", "company_id": "c1", "crop_type": "rice_stubble", "quantity_needed_kg": 500,
        "quantity_remaining_kg": 0, "price_offer_per_kg": 1.0})
    monkeypatch.setattr(store, "append_negotiation_log", lambda *a: None)
    monkeypatch.setattr(store, "update_match_price", lambda *a: pytest.fail("price must not change"))

    body = client.post("/negotiate", json={"match_id": "m1", "raw_text": "I want 50 rupees a kilo"}).json()
    assert body["outcome"] == "not_feasible"
    assert body["buyer_ceiling_per_kg"] == 1.2
    assert "at most" in body["reason"]


def test_negotiate_within_ceiling_restores_capacity_for_the_resolve(monkeypatch):
    """The match's own listing and demand are fully used by this match; the
    renegotiation must still find it feasible by restoring its kilograms."""
    updated = {}
    monkeypatch.setattr(store, "get_match", lambda db, mid: dict(MATCH))
    monkeypatch.setattr(main, "parse_negotiation_price", lambda c, text, price: {
        "is_price_request": True, "requested_price_per_kg": 1.1})
    monkeypatch.setattr(store, "get_open_listings", lambda db: [])
    monkeypatch.setattr(store, "get_listing", lambda db, lid: {
        "id": "l1", "farmer_id": "f1", "quantity_kg": 500, "quantity_remaining_kg": 0, "crop_type": "rice_stubble"})
    monkeypatch.setattr(store, "get_trust_scores_by_farmer_ids", lambda db, ids: {})
    monkeypatch.setattr(store, "get_open_demand", lambda db: [])
    monkeypatch.setattr(store, "get_demand", lambda db, did: {
        "id": "d1", "company_id": "c1", "crop_type": "rice_stubble", "quantity_needed_kg": 500,
        "quantity_remaining_kg": 0, "price_offer_per_kg": 1.0})
    monkeypatch.setattr(store, "append_negotiation_log", lambda *a: None)
    monkeypatch.setattr(store, "update_match_price", lambda db, mid, price: updated.setdefault("price", price))

    body = client.post("/negotiate", json={"match_id": "m1", "raw_text": "1.10 a kilo please"}).json()
    assert body == {"outcome": "updated", "new_price_per_kg": 1.1}
    assert updated["price"] == 1.1


def test_global_solve_saves_matches_for_every_waiting_listing(monkeypatch):
    """Regression: only the triggering listing's matches used to be saved."""
    saved = {}
    monkeypatch.setattr(store, "get_open_listings", lambda db: [
        {"id": "l_new", "farmer_id": "f1", "quantity_kg": 300, "crop_type": "rice_stubble"},
        {"id": "l_waiting", "farmer_id": "f2", "quantity_kg": 200, "crop_type": "rice_stubble"},
    ])
    monkeypatch.setattr(store, "get_trust_scores_by_farmer_ids", lambda db, ids: {})
    monkeypatch.setattr(store, "get_open_demand", lambda db: [
        {"id": "d1", "company_id": "c1", "crop_type": "rice_stubble", "quantity_needed_kg": 1000,
         "quantity_remaining_kg": 1000, "price_offer_per_kg": 1.0},
    ])
    monkeypatch.setattr(store, "save_matches", lambda db, results: saved.setdefault(
        "listing_ids", sorted(r.listing_id for r in results)) and [])

    main._run_global_solve(MagicMock())
    assert saved["listing_ids"] == ["l_new", "l_waiting"]


def test_solver_sees_remaining_demand_not_original_quantity():
    d = main._to_solver_demand({"id": "d1", "company_id": "c1", "crop_type": "rice_stubble",
                               "quantity_needed_kg": 3000, "quantity_remaining_kg": 400,
                               "price_offer_per_kg": 1.0, "max_price_per_kg": 1.5})
    assert d.quantity_needed_kg == 400
    assert d.ceiling_per_kg == 1.5


def test_request_bounds_reject_garbage():
    bad_demand = {"product": "pellets", "crop_type": "rice_stubble", "quantity_needed_kg": -5, "price_offer_per_kg": 1}
    assert client.post("/companies/c1/demand", json=bad_demand).status_code == 422
    bad_crop = {"product": "pellets", "crop_type": "sugarcane", "quantity_needed_kg": 5, "price_offer_per_kg": 1}
    assert client.post("/companies/c1/demand", json=bad_crop).status_code == 422
    assert client.post("/negotiate/agents", json={"match_id": "m1", "farmer_floor": 1, "max_turns": 50}).status_code == 422


def test_cors_allows_our_site_and_refuses_others():
    ok = client.options("/health", headers={"Origin": "https://parali-setu.web.app", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "https://parali-setu.web.app"
    other = client.options("/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert other.headers.get("access-control-allow-origin") is None


def test_collected_records_a_payout_and_moves_to_paid(monkeypatch):
    transitions, payouts = [], []
    scheduled = {**MATCH, "status": "scheduled", "matched_kg": 1750, "price_agreed_per_kg": 1.2}
    monkeypatch.setattr(store, "get_match", lambda db, mid: dict(scheduled))
    monkeypatch.setattr(store, "update_match_status", lambda db, mid, status, extra=None: (
        transitions.append(status), {**scheduled, **(extra or {}), "status": status})[1])
    monkeypatch.setattr(store, "set_slots_status", lambda db, mid, status: [])
    monkeypatch.setattr(store, "save_payout", lambda db, p: (payouts.append(p), {**p, "id": "p1"})[1])

    body = client.post("/stops/m1/collected", json={"collected_kg": 1600}).json()
    assert transitions == ["collected", "paid"]
    assert payouts[0]["amount_inr"] == 1920.0 and payouts[0]["simulated"] is True
    assert body["match"]["payout_inr"] == 1920.0

    assert client.post("/stops/m1/collected", json={"collected_kg": 5000}).status_code == 422


def test_collected_refuses_a_match_that_was_never_scheduled(monkeypatch):
    monkeypatch.setattr(store, "get_match", lambda db, mid: dict(MATCH))

    def refuse(db, mid, status, extra=None):
        raise store.InvalidTransition("A match that is proposed cannot become collected.")
    monkeypatch.setattr(store, "update_match_status", refuse)
    monkeypatch.setattr(store, "save_payout", lambda *a: pytest.fail("no payout without a collection"))
    assert client.post("/stops/m1/collected", json={}).status_code == 409


def test_buyer_read_endpoints(monkeypatch):
    monkeypatch.setattr(store, "get_companies", lambda db: [
        {"id": "co_2", "name": "Malwa Pellets (demo)"}, {"id": "co_1", "name": "Leafware Plates (demo)"},
        {"id": "smoke_co", "name": "Smoke", "smoke": True}])
    assert [c["id"] for c in client.get("/companies").json()["companies"]] == ["co_1", "co_2"]

    monkeypatch.setattr(store, "get_demand_for_company", lambda db, cid: [
        {"id": "d1", "company_id": cid, "crop_type": "rice_stubble", "quantity_needed_kg": 1000,
         "quantity_remaining_kg": 400, "price_offer_per_kg": 1.0}])
    d = client.get("/companies/co_1/demand").json()["demand"][0]
    assert d["quantity_remaining_kg"] == 400 and d["ceiling_per_kg"] == 1.2

    monkeypatch.setattr(store, "get_matches_for_company", lambda db, cid: [
        {"farmer_id": "f1", "status": "paid", "matched_kg": 1750, "collected_kg": 1750, "payout_inr": 1925.0},
        {"farmer_id": "f2", "status": "scheduled", "matched_kg": 3500},
        {"farmer_id": "f3", "status": "proposed", "matched_kg": 999}])
    imp = client.get("/buyers/co_1/impact").json()
    assert imp["payouts_inr"] == 1925.0 and imp["farmers_paid"] == 1
    assert imp["collected"]["acres_cleared"] == 1.0 and imp["scheduled"]["acres_cleared"] == 2.0
