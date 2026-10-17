"""The stock and money ledger: straw in (pickups), straw out (deliveries) and
farmer payouts must always agree with each other.

Each test here pins down one way the ledger used to go wrong:
- a payout written in four steps could stop halfway (collected, never paid)
- nothing ever took straw out of a depot, so stock only grew
- collected straw was counted twice in the delivery plan (stock + intake)
- a depot could take in more straw than it can hold
- a crew could mark a farm collected days before its slot
- a delivery plan with no solution reported "0 t short"
"""
from datetime import date, datetime, timedelta

import pytest

import deliveries as dl
import firestore_store as store
import operations
import pickups
from fakes import Transaction
from test_api_flows import _offer, api, client  # noqa: F401  (api is a fixture)


def _verified(api_state, farmer="f1"):
    booking = _offer(api_state, farmer)["booking"]
    client.post(f"/ops/bookings/{booking['id']}/accept")
    client.post(f"/ops/bookings/{booking['id']}/verify", json={"notes": "called"})
    return store.get_booking(api_state["db"], booking["id"])


def _at(monkeypatch, day: date, hour: int = 9):
    monkeypatch.setattr(pickups, "now_ist", lambda: datetime(day.year, day.month, day.day, hour, tzinfo=pickups.IST))


def _ledger(db, depot_id):
    depot = store.get_depot(db, depot_id)
    moves = store.get_inventory_moves(db, depot_id)
    return depot.get("stock_t", 0.0), store.stock_from_moves(moves), moves


# ---- payouts are all-or-nothing

def test_a_failure_halfway_through_a_payout_writes_nothing(api, monkeypatch):
    db = api["db"]
    booking = _verified(api)
    real_update = Transaction.update

    def crash_on_depot(self, ref, fields):
        if ref.id == booking["depot_id"]:
            raise RuntimeError("network dropped mid-payout")
        return real_update(self, ref, fields)

    monkeypatch.setattr(Transaction, "update", crash_on_depot)
    with pytest.raises(RuntimeError):
        pickups.complete_pickup(db, booking["id"])
    assert store.get_booking(db, booking["id"])["status"] == "verified", "not stuck in 'collected'"
    assert store.get_purchases(db) == [] and store.get_inventory_moves(db) == []

    monkeypatch.setattr(Transaction, "update", real_update)
    paid = pickups.complete_pickup(db, booking["id"])          # the retry goes through cleanly
    assert paid["booking"]["status"] == "paid"
    assert len(store.get_purchases(db)) == 1


def test_a_retried_collect_can_never_pay_twice(api):
    booking = _verified(api)
    assert client.post(f"/stops/{booking['id']}/collected", json={}).status_code == 200
    assert client.post(f"/stops/{booking['id']}/collected", json={}).status_code == 409
    assert len(store.get_purchases(api["db"])) == 1
    assert len([m for m in store.get_inventory_moves(api["db"]) if m["kind"] == "inbound"]) == 1


def test_payout_stock_and_booking_agree_to_the_kilo(api):
    db = api["db"]
    booking = _verified(api)
    body = client.post(f"/stops/{booking['id']}/collected", json={"collected_kg": 16_240}).json()
    assert body["purchase"]["kg"] == 16_240 and body["inventory_move"]["tonnes"] == 16.24
    assert body["purchase"]["amount_inr"] == round(16_240 * booking["price_per_kg"], 2)
    running, from_moves, _ = _ledger(db, booking["depot_id"])
    assert running == from_moves == 16.24
    paid = store.get_booking(db, booking["id"])
    assert paid["payout_inr"] == body["purchase"]["amount_inr"] and paid["collected_kg"] == 16_240
    assert all(s["status"] == "collected" for s in store.get_slots_for_booking(db, booking["id"]))


# ---- collecting: when and how much

def test_a_farm_cannot_be_collected_before_its_slot_day(api, monkeypatch):
    db = api["db"]
    booking = _verified(api)
    slot_day = date.fromisoformat(min(s["date"] for s in store.get_slots_for_booking(db, booking["id"])))
    _at(monkeypatch, slot_day - timedelta(days=1))
    resp = client.post(f"/stops/{booking['id']}/collected", json={})
    assert resp.status_code == 409 and slot_day.isoformat() in resp.json()["detail"]
    assert store.get_purchases(db) == []
    _at(monkeypatch, slot_day, 16)
    assert client.post(f"/stops/{booking['id']}/collected", json={}).status_code == 200


def test_a_full_depot_refuses_more_straw_and_nothing_is_paid(api):
    db = api["db"]
    booking = _verified(api)
    db.collection("depots").document(booking["depot_id"]).update({"capacity_t": 10.0})
    resp = client.post(f"/stops/{booking['id']}/collected", json={})          # 17.5 t into 10 t of room
    assert resp.status_code == 409 and "room for 10.0 t" in resp.json()["detail"]
    assert store.get_booking(db, booking["id"])["status"] == "verified"
    assert store.get_purchases(db) == [] and _ledger(db, booking["depot_id"])[1] == 0


# ---- straw out: deliveries leave the depot

def _collected_depot(api_state):
    booking = _verified(api_state)
    client.post(f"/stops/{booking['id']}/collected", json={})
    operations.run_deliveries(api_state["db"])
    return booking["depot_id"]


def _first_delivery(db, depot_id):
    rows = sorted((d for d in store.get_deliveries(db) if d["depot_id"] == depot_id), key=lambda d: d["month"])
    assert rows, "the demo order book plans deliveries from this depot"
    return rows[0]


def test_a_shipped_delivery_takes_straw_out_of_stock(api, monkeypatch):
    db = api["db"]
    depot_id = _collected_depot(api)
    delivery = _first_delivery(db, depot_id)
    _at(monkeypatch, date.fromisoformat(delivery["month"]) + timedelta(days=1))
    tonnes = min(delivery["tonnes"], 10.0)
    body = client.post(f"/deliveries/{delivery['id']}/shipped", json={"tonnes": tonnes}).json()
    assert body["inventory_move"]["kind"] == "outbound" and body["delivery"]["status"] == "shipped"
    running, from_moves, moves = _ledger(db, depot_id)
    assert running == from_moves == round(17.5 - tonnes, 3)
    inbound = sum(m["tonnes"] for m in moves if m["kind"] == "inbound")
    outbound = sum(m["tonnes"] for m in moves if m["kind"] == "outbound")
    assert inbound - outbound == from_moves
    assert client.get("/inventory").json()["depots"][0]["outbound_t"] >= 0
    assert client.post(f"/deliveries/{delivery['id']}/shipped", json={}).status_code == 409, "ships once"


def test_a_depot_cannot_ship_straw_it_does_not_hold(api, monkeypatch):
    db = api["db"]
    depot_id = _collected_depot(api)
    delivery = _first_delivery(db, depot_id)
    db.collection("deliveries").document(delivery["id"]).update({"tonnes": 500.0})
    _at(monkeypatch, date.fromisoformat(delivery["month"]) + timedelta(days=1))
    resp = client.post(f"/deliveries/{delivery['id']}/shipped", json={"tonnes": 400})
    assert resp.status_code == 409 and "holds 17.5 t" in resp.json()["detail"]
    assert _ledger(db, depot_id)[1] == 17.5


def test_a_delivery_cannot_ship_before_its_month(api):
    db = api["db"]
    depot_id = _collected_depot(api)
    later = [d for d in store.get_deliveries(db) if d["depot_id"] == depot_id and d["month"] > "2026-10-17"]
    assert later
    assert client.post(f"/deliveries/{later[0]['id']}/shipped", json={"tonnes": 1}).status_code == 409


def test_a_new_plan_keeps_shipped_deliveries_and_counts_them_as_delivered(api, monkeypatch):
    db = api["db"]
    depot_id = _collected_depot(api)
    delivery = _first_delivery(db, depot_id)
    _at(monkeypatch, date.fromisoformat(delivery["month"]) + timedelta(days=1))
    shipped_t = min(delivery["tonnes"], 10.0)
    client.post(f"/deliveries/{delivery['id']}/shipped", json={"tonnes": shipped_t})
    order = next(o for o in store.get_orders(db) if o["id"] == delivery["order_id"])
    asked = order["tonnes_by_month"][delivery["month"]]

    operations.run_deliveries(db, pickups.now_ist().date())
    kept = store.get_delivery(db, delivery["id"])
    assert kept["status"] == "shipped" and kept["shipped_t"] == shipped_t
    planned_again = sum(d["tonnes"] for d in store.get_deliveries(db, order["id"])
                        if d["month"] == delivery["month"] and d.get("status") != "shipped")
    short = sum(s["tonnes"] for s in store.get_plan(db, "deliveries_current")["shortfall"]
                if s["order_id"] == order["id"] and s["month"] == delivery["month"])
    assert planned_again + short == pytest.approx(asked - shipped_t, abs=0.05), "shipped tonnes are not planned twice"


# ---- the delivery plan's view of supply

def test_collected_straw_is_counted_once_not_as_stock_and_intake(api):
    db = api["db"]
    today = pickups.now_ist().date()

    def supply():
        depots, _, _ = operations._delivery_inputs(db, today)
        return {d.id: (d.opening_t, sum(d.inbound_t_by_month)) for d in depots}

    booking = _verified(api)
    before = supply()[booking["depot_id"]]
    assert before[1] >= 17.5, "the plan expected at least this much straw into the depot this season"
    client.post(f"/stops/{booking['id']}/collected", json={})
    after = supply()[booking["depot_id"]]
    assert after[0] == pytest.approx(before[0] + 17.5), "collected straw is now stock"
    assert sum(after) == pytest.approx(sum(before), abs=0.01), "and no longer also planned intake"


def test_more_straw_than_room_is_reported_as_overflow_not_a_failed_plan():
    depot = dl.DepotStock("d", 30.9, 75.8, capacity_t=10.0, opening_t=0.0, inbound_t_by_month=(100.0, 0.0))
    order = dl.OrderLine("o", "c", 30.9, 75.9, tonnes_by_month=(20.0, 5.0))
    plan = dl.plan_deliveries([depot], [order], 2)
    assert plan.status == "optimal", "used to come back infeasible"
    assert plan.total_shortfall_t == 0
    # 20 t ship now, 10 t (the depot's room) are kept for next month's 5 t, the rest has nowhere to go
    assert plan.total_overflow_t == pytest.approx(100 - 20 - 10, abs=0.01), "everything we can't store or ship is visible"
    assert plan.stock[("d", 0)] == pytest.approx(10.0)


def test_no_plan_never_reads_as_zero_shortfall():
    failed = dl.DeliveryPlan(status="infeasible")
    assert failed.total_shortfall_t is None and failed.total_overflow_t is None
