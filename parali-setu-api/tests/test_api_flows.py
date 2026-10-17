"""The API end to end over HTTP, against the in-memory Parali Setu (`world`):
the farmer's speak-once/confirm-once booking, accepting, cancelling and
expiry; ops collecting and paying, crews and re-planning; customers quoting
and ordering. Gemini and speech are mocked; the planners are real."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

import firestore_store as store
import main
import pickups

client = TestClient(main.app)
SANGRUR_FIELDS = {"acres": 10, "crop_type": "rice_stubble", "village_or_district": "Bahadurpur, Sangrur"}


@pytest.fixture
def api(world, monkeypatch):
    state = {"extracted": {}, "questions": 0}
    monkeypatch.setattr(main, "get_gemini_client", lambda: object())
    monkeypatch.setattr(main, "synthesize_speech", lambda text, lang: b"mp3")
    monkeypatch.setattr(main, "extract_listing", lambda c, text, lang: dict(state["extracted"]))

    def ask(c, missing, lang):
        state["questions"] += 1
        return "Kitne kille, aur kab tak khet khali chahiye?"
    monkeypatch.setattr(main, "follow_up_question", ask)
    monkeypatch.setattr(main, "explain_offer", lambda c, offer, lang: f"{offer['price_per_kg']} {offer['pickup_window']}")
    monkeypatch.setattr(main, "explain_price", lambda c, facts, lang: f"why {facts['price_per_kg']}")
    state["db"] = world
    return state


def _draft(api, fields, farmer="f1", language="Hindi"):
    api["extracted"] = dict(fields)
    return client.post("/listings/draft", data={"farmer_id": farmer, "language": language, "text": "..."}).json()


def _offer(api, farmer="f1", sowing="2026-10-24"):
    draft = _draft(api, {**SANGRUR_FIELDS, "sowing_deadline": sowing}, farmer)
    return client.post(f"/listings/{draft['draft_id']}/confirm", json={"farmer_id": farmer}).json()


# ---- farmer

def test_one_question_covers_everything_missing_and_is_asked_only_once(api):
    first = _draft(api, {"acres": 10, "crop_type": "rice_stubble"})
    assert first["missing_fields"] == ["location", "sowing_deadline"]
    assert first["follow_up"]["text"] and first["confirm_summary"] is None
    assert first["fields"]["quantity_kg"] == 17500.0, "kg is derived in code from acres at 1.75 t/acre"

    api["extracted"] = {"village_or_district": "Sangrur"}
    second = client.post("/listings/draft", data={"farmer_id": "f1", "draft_id": first["draft_id"], "text": "Sangrur"}).json()
    assert api["questions"] == 1, "never a second question"
    assert second["follow_up"] is None and second["district"] == "Sangrur"
    assert second["confirm_summary"]["text"]


def test_confirm_books_at_the_posted_price_with_a_slot(api):
    body = _offer(api)
    booking = body["booking"]
    assert body["status"] == "offered" and booking["status"] == "offered"
    posted = store.get_posted_price(api["db"], "2026-10-17", "Sangrur")
    assert booking["price_per_kg"] == posted["price_per_kg"] == body["price"]["price_per_kg"]
    assert booking["pickup_window"] and booking["slots"]
    assert booking["payout_estimate_inr"] == round(17500 * booking["price_per_kg"], 2)
    assert booking["offer_expires_at"].startswith("2026-10-17T13:00")
    assert body["explanation"]["text"] == f"{booking['price_per_kg']} {booking['pickup_window']}"
    assert body["impact_if_collected"]["acres_cleared"] == 10.0


def test_confirm_only_once_and_needs_a_place(api):
    draft = _draft(api, {**SANGRUR_FIELDS, "sowing_deadline": "2026-10-24"})
    assert client.post(f"/listings/{draft['draft_id']}/confirm", json={"farmer_id": "f1"}).status_code == 200
    assert client.post(f"/listings/{draft['draft_id']}/confirm", json={"farmer_id": "f1"}).status_code == 409
    nowhere = _draft(api, {"acres": 4, "crop_type": "rice_stubble"})
    assert client.post(f"/listings/{nowhere['draft_id']}/confirm", json={"farmer_id": "f1"}).status_code == 422


def test_a_farm_beyond_every_depot_is_told_so(api):
    draft = _draft(api, {"acres": 4, "crop_type": "rice_stubble", "sowing_deadline": "2026-10-24"})
    store.save_draft(api["db"], {**store.get_draft(api["db"], draft["draft_id"]),
                                 "fields": {**store.get_draft(api["db"], draft["draft_id"])["fields"],
                                            "lat": 28.61, "lon": 77.21, "quantity_kg": 7000.0}})
    body = client.post(f"/listings/{draft['draft_id']}/confirm", json={"farmer_id": "f1"}).json()
    assert body["status"] == "out_of_area"


def test_accept_locks_the_slot_and_only_the_farmer_can(api):
    booking = _offer(api)["booking"]
    assert client.post(f"/bookings/{booking['id']}/accept", json={"farmer_id": "someone_else"}).status_code == 404
    body = client.post(f"/bookings/{booking['id']}/accept", json={"farmer_id": "f1"}).json()
    assert body["booking"]["status"] == "booked" and body["slots"][0]["locked"] is True
    assert client.post(f"/bookings/{booking['id']}/accept", json={"farmer_id": "f1"}).status_code == 409


def test_an_expired_offer_cannot_be_accepted(api, monkeypatch):
    booking = _offer(api)["booking"]
    later = pickups.now_ist() + timedelta(hours=pickups.OFFER_HOLD_HOURS + 1)
    monkeypatch.setattr(pickups, "now_ist", lambda: later)
    resp = client.post(f"/bookings/{booking['id']}/accept", json={"farmer_id": "f1"})
    assert resp.status_code == 409 and "expired" in resp.json()["detail"]


def test_cancel_frees_the_slot(api):
    booking = _offer(api)["booking"]
    body = client.post(f"/bookings/{booking['id']}/cancel", json={"farmer_id": "f1"}).json()
    assert body["booking"]["status"] == "cancelled"
    assert all(s["status"] == "cancelled" for s in store.get_slots_for_booking(api["db"], booking["id"]))
    assert client.get("/farmers/f1/bookings").json()["bookings"] == []


def test_price_explanation_uses_the_posted_reason(api):
    booking = _offer(api)["booking"]
    body = client.get(f"/bookings/{booking['id']}/price-explanation", params={"language": "Hindi"}).json()
    assert body["explanation"] == f"why {booking['price_per_kg']}"
    assert body["reason_code"] in ("base", "scarce")


# ---- ops

def test_collect_and_pay_flows_into_stock_payouts_and_impact(api):
    booking = _offer(api)["booking"]
    assert client.post(f"/stops/{booking['id']}/collected", json={}).status_code == 409, "collect only after acceptance"
    client.post(f"/ops/bookings/{booking['id']}/accept")
    assert store.get_booking(api["db"], booking["id"])["accepted_by"] == "ops (demo)"
    assert client.post(f"/stops/{booking['id']}/collected", json={"collected_kg": 99999}).status_code == 422
    paid = client.post(f"/stops/{booking['id']}/collected", json={}).json()
    assert paid["booking"]["status"] == "paid" and paid["purchase"]["method"] == "UPI"

    impact = client.get("/impact").json()
    assert impact["collected"]["tonnes_diverted"] == 17.5 and impact["farmers_paid"] == 1
    assert client.get("/purchases", params={"farmer_id": "f1"}).json()["total_inr"] == paid["purchase"]["amount_inr"]
    stock = {d["depot_id"]: d["stock_t"] for d in client.get("/inventory").json()["depots"]}
    assert stock[booking["depot_id"]] == 17.5
    mine = client.get("/farmers/f1/bookings").json()["bookings"][0]
    assert mine["status"] == "paid" and mine["payout_inr"] == paid["purchase"]["amount_inr"]


def test_depot_schedule_shows_farms_crews_and_arrival_windows(api):
    booking = _offer(api)["booking"]
    sheet = client.get(f"/depots/{booking['depot_id']}/schedule").json()
    stops = [s for r in sheet["route_sheets"] for s in r["stops"]]
    stop = next(s for s in stops if s["booking_id"] == booking["id"])
    assert stop["village"] == "Bahadurpur, Sangrur" and stop["sowing_deadline"] == "2026-10-24"
    assert stop["planned_start_min"] >= stop["window_start_min"]
    assert all("crew_name" in r and "partner" in r for r in sheet["route_sheets"])
    assert client.get("/depots/nope/schedule").status_code == 404


def test_adding_a_crew_replans_the_depot(api):
    body = client.post("/depots/dep_patiala/crews", json={"name": "Crew 2", "acres_per_day": 20}).json()
    assert body["crew"]["depot_id"] == "dep_patiala" and body["plan"]["depot_id"] == "dep_patiala"
    names = [c["name"] for d in client.get("/depots").json()["depots"] if d["id"] == "dep_patiala" for c in d["crews"]]
    assert "Crew 2" in names
    assert client.post("/depots/dep_patiala/crews", json={"name": "", "acres_per_day": 20}).status_code == 422


def test_ops_summary_and_plans(api):
    _offer(api)
    summary = client.get("/ops/summary").json()
    assert summary["bookings_by_status"]["offered"] >= 1 and summary["procurement_shortfall_t"] == 0
    assert client.get("/plan/procurement").json()["status"] == "optimal"
    rerun = client.post("/plan/procurement").json()
    assert rerun["plan"]["status"] == "optimal" and rerun["deliveries"]["status"] == "optimal"


def test_prices_and_forecast_are_public(api):
    all_prices = client.get("/prices/today").json()["prices"]
    assert len(all_prices) == 8
    assert client.get("/prices/today", params={"district": "ਸੰਗਰੂਰ"}).json()["district"] == "Sangrur"
    assert client.get("/prices/today", params={"district": "Mars"}).status_code == 404
    forecast = client.get("/forecast").json()
    assert forecast["supply_live"]["model"].startswith("TimesFM")
    assert len(forecast["demand_segments"]) == 4 and forecast["district_straw"]["Sangrur"]["year"] == 2019


# ---- customers

def test_customer_quote_then_order_lands_in_the_delivery_plan(api):
    quote = client.post("/customers/cust_board/quote", json={"tonnes_per_month": 50, "months": 3,
                                                             "start_month": "2026-12-01"}).json()
    assert quote["total_t"] == 150 and quote["quote"]["depot_id"] == "dep_patiala"
    assert quote["total_inr"] == pytest.approx(150 * quote["quote"]["price_per_t"], abs=0.5)
    before = len(store.get_orders(api["db"], "cust_board"))
    body = client.post("/customers/cust_board/orders", json={"tonnes_per_month": 50, "months": 3,
                                                             "start_month": "2026-12-01"}).json()
    assert body["order"]["tonnes_by_month"] == {"2026-12-01": 50, "2027-01-01": 50, "2027-02-01": 50}
    assert sum(d["tonnes"] for d in body["deliveries"]) == pytest.approx(150)
    orders = client.get("/customers/cust_board/orders").json()["orders"]
    assert len(orders) == before + 1 and all("deliveries" in o for o in orders)
    assert client.post("/customers/nope/quote", json={"tonnes_per_month": 1, "months": 1,
                                                      "start_month": "2026-12-01"}).status_code == 404
    assert client.post("/customers/cust_board/orders", json={"tonnes_per_month": 0, "months": 1,
                                                             "start_month": "2026-12-01"}).status_code == 422
