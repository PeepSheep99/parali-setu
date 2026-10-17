"""Firestore read/write helpers for Parali Setu's data model. Thin wrappers
only: numbers come from the planners (procurement.py, scheduler.py,
deliveries.py, costs.py) and language from extraction.py.

Collections
- listings, listing_drafts    a farmer's field and the draft before confirming
- bookings                    a farmer selling a field's straw to a Parali Setu depot
- depots, crews, pickup_slots our storage sites, baling crews and planned visits
- posted_prices               farm-gate price per district per day
- purchases                   same-day payouts to farmers (simulated)
- inventory_moves             straw in (pickups) and out (deliveries) per depot
- customers, orders, deliveries   companies, their forward orders, the plan
- plans, forecasts            planner and forecaster outputs
- conversations               the farmer agent's turns, tool facts and draft
- farmers, no_burn_proofs, fire_detections   trust and satellite data

Shares the ai-builder-cup-aidatlas project with AidAtlas, whose only
collection ("allocations") does not overlap.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from google.cloud import firestore

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "ai-builder-cup-aidatlas")


def get_firestore_client() -> firestore.Client:
    return firestore.Client(project=PROJECT_ID)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get(db: firestore.Client, collection: str, doc_id: str) -> dict | None:
    doc = db.collection(collection).document(doc_id).get()
    return doc.to_dict() if doc.exists else None


def _where(db: firestore.Client, collection: str, field: str, value) -> list[dict]:
    return [d.to_dict() for d in db.collection(collection).where(field, "==", value).stream()]


def _all(db: firestore.Client, collection: str) -> list[dict]:
    return [d.to_dict() for d in db.collection(collection).stream()]


def _save(db: firestore.Client, collection: str, prefix: str, doc: dict) -> dict:
    doc = {**doc, "id": doc.get("id") or _new_id(prefix)}
    doc.setdefault("created_at", _now())
    db.collection(collection).document(doc["id"]).set(doc)
    return doc


# ---- listings and drafts

LISTING_OPTIONAL_FIELDS = ("acres", "sowing_deadline", "lat", "lon", "quality_note", "draft_id", "district", "contact",
                           "farmer_name", "location_source", "conversation_id")


def save_listing(db: firestore.Client, farmer_id: str, fields: dict, language: str) -> dict:
    listing = {
        "farmer_id": farmer_id,
        "quantity_kg": fields.get("quantity_kg"),
        "crop_type": fields.get("crop_type"),
        "village_or_district": fields.get("village_or_district"),
        "ready_by": fields.get("ready_by"),
        "quality_grade": fields.get("quality_grade", "unknown"),
        "language": language,
    }
    for field in LISTING_OPTIONAL_FIELDS:
        if fields.get(field) is not None:
            listing[field] = fields[field]
    return _save(db, "listings", "listing", listing)


def get_listing(db: firestore.Client, listing_id: str) -> dict | None:
    return _get(db, "listings", listing_id)


def save_draft(db: firestore.Client, draft: dict) -> dict:
    draft = {**draft, "updated_at": _now()}
    return _save(db, "listing_drafts", "draft", draft)


def get_draft(db: firestore.Client, draft_id: str) -> dict | None:
    return _get(db, "listing_drafts", draft_id)


# ---- bookings

# offered: a slot is planned and the posted price shown; the farmer has not
#   accepted yet, and the offer lapses after a few hours so it never holds
#   crew time forever.
# booked: the farmer accepted; the slot is locked.
# collected -> paid: the crew collected; the same-day payout is recorded.
# unschedulable: no slot can exist (for example the sowing date has passed).
BOOKING_TRANSITIONS = {
    "offered": {"booked", "expired", "cancelled", "unschedulable"},
    "unschedulable": {"offered", "expired", "cancelled"},
    "booked": {"verified", "cancelled"},          # a person calls the farmer before dispatch
    "verified": {"collected", "cancelled"},
    "collected": {"paid"},
    "paid": set(),
    "expired": set(),
    "cancelled": set(),
}
ACTIVE_BOOKING_STATUSES = ("offered", "unschedulable", "booked", "verified")


class InvalidTransition(ValueError):
    pass


def can_transition(current: str | None, new_status: str) -> bool:
    return new_status in BOOKING_TRANSITIONS.get(current or "offered", set())


def save_booking(db: firestore.Client, booking: dict) -> dict:
    return _save(db, "bookings", "booking", {"status": "offered", **booking})


def get_booking(db: firestore.Client, booking_id: str) -> dict | None:
    return _get(db, "bookings", booking_id)


def get_bookings_for_farmer(db: firestore.Client, farmer_id: str) -> list[dict]:
    return sorted(_where(db, "bookings", "farmer_id", farmer_id), key=lambda b: b.get("created_at", ""), reverse=True)


def get_bookings_for_depot(db: firestore.Client, depot_id: str) -> list[dict]:
    return _where(db, "bookings", "depot_id", depot_id)


def get_bookings(db: firestore.Client, statuses: tuple[str, ...] | None = None) -> list[dict]:
    if statuses:
        return [d.to_dict() for d in db.collection("bookings").where("status", "in", list(statuses)).stream()]
    return _all(db, "bookings")


def booking_transition_update(booking: dict, new_status: str, extra: dict) -> dict:
    """The fields to write for a lifecycle move, or InvalidTransition."""
    current = booking.get("status", "offered")
    if not can_transition(current, new_status):
        raise InvalidTransition(f"A booking that is {current} cannot become {new_status}.")
    return {**extra, "status": new_status, "status_updated_at": _now()}


@firestore.transactional
def _transition_booking(transaction: firestore.Transaction, ref, new_status: str, extra: dict) -> dict:
    snap = ref.get(transaction=transaction)
    if not snap.exists:
        raise KeyError("booking not found")
    booking = snap.to_dict()
    update = booking_transition_update(booking, new_status, extra)
    transaction.update(ref, update)
    return {**booking, **update}


def update_booking_status(db: firestore.Client, booking_id: str, status: str, extra: dict | None = None) -> dict:
    """Moves a booking along its lifecycle atomically. Raises KeyError for an
    unknown booking and InvalidTransition for a move the lifecycle forbids."""
    ref = db.collection("bookings").document(booking_id)
    return _transition_booking(db.transaction(), ref, status, extra or {})


def update_booking_fields(db: firestore.Client, booking_id: str, fields: dict) -> None:
    db.collection("bookings").document(booking_id).update(fields)


# ---- depots, crews, slots

def save_depot(db: firestore.Client, depot: dict) -> dict:
    return _save(db, "depots", "depot", depot)


def get_depot(db: firestore.Client, depot_id: str) -> dict | None:
    return _get(db, "depots", depot_id)


def get_depots(db: firestore.Client) -> list[dict]:
    return sorted(_all(db, "depots"), key=lambda d: d.get("name", d["id"]))


def save_crew(db: firestore.Client, crew: dict) -> dict:
    return _save(db, "crews", "crew", crew)


def get_crews_for_depot(db: firestore.Client, depot_id: str) -> list[dict]:
    return sorted(_where(db, "crews", "depot_id", depot_id), key=lambda c: (c.get("partner", False), c["id"]))


def get_slots_for_depot(db: firestore.Client, depot_id: str) -> list[dict]:
    return _where(db, "pickup_slots", "depot_id", depot_id)


def get_slots_for_booking(db: firestore.Client, booking_id: str) -> list[dict]:
    return sorted(_where(db, "pickup_slots", "booking_id", booking_id), key=lambda s: (s["date"], s["planned_start_min"]))


def replace_depot_plan(db: firestore.Client, depot_id: str, slots: list[dict]) -> None:
    """Writes a fresh plan for one depot: tentative slots not in the new plan
    are removed; locked and collected slots are only updated (their promised
    windows never change here)."""
    keep_ids = {s["id"] for s in slots}
    batch = db.batch()
    for old in get_slots_for_depot(db, depot_id):
        if old.get("status") == "tentative" and old["id"] not in keep_ids:
            batch.delete(db.collection("pickup_slots").document(old["id"]))
    for slot in slots:
        batch.set(db.collection("pickup_slots").document(slot["id"]), slot, merge=True)
    batch.commit()


def delete_tentative_slots(db: firestore.Client, booking_id: str) -> None:
    batch = db.batch()
    for slot in get_slots_for_booking(db, booking_id):
        if slot.get("status") == "tentative":
            batch.delete(db.collection("pickup_slots").document(slot["id"]))
    batch.commit()


def set_slots_status(db: firestore.Client, booking_id: str, status: str, locked: bool | None = None) -> list[dict]:
    slots = get_slots_for_booking(db, booking_id)
    update = {"status": status, **({"locked": locked} if locked is not None else {})}
    batch = db.batch()
    for slot in slots:
        batch.update(db.collection("pickup_slots").document(slot["id"]), update)
    if slots:
        batch.commit()
    return [{**s, **update} for s in slots]


# ---- prices, purchases, inventory

def price_doc_id(day: str, district: str) -> str:
    return f"{day}_{district.lower().replace(' ', '_')}"


def save_posted_prices(db: firestore.Client, rows: list[dict]) -> None:
    batch = db.batch()
    for row in rows:
        batch.set(db.collection("posted_prices").document(price_doc_id(row["date"], row["district"])), row)
    if rows:
        batch.commit()


def get_posted_price(db: firestore.Client, day: str, district: str) -> dict | None:
    return _get(db, "posted_prices", price_doc_id(day, district))


def get_posted_prices_for_day(db: firestore.Client, day: str) -> list[dict]:
    return sorted(_where(db, "posted_prices", "date", day), key=lambda r: r["district"])


def save_purchase(db: firestore.Client, purchase: dict) -> dict:
    return _save(db, "purchases", "purchase", purchase)


def get_purchases(db: firestore.Client) -> list[dict]:
    return _all(db, "purchases")


def save_inventory_move(db: firestore.Client, move: dict) -> dict:
    return _save(db, "inventory_moves", "move", move)


def get_inventory_moves(db: firestore.Client, depot_id: str | None = None) -> list[dict]:
    return _where(db, "inventory_moves", "depot_id", depot_id) if depot_id else _all(db, "inventory_moves")


def stock_from_moves(moves: list[dict]) -> float:
    return round(sum(m["tonnes"] if m["kind"] == "inbound" else -m["tonnes"] for m in moves), 3)


# ---- the stock ledger: every move and its money in one transaction

class LedgerError(ValueError):
    """A stock or payout write the ledger refuses (depot full, not enough
    stock, wrong state). Nothing has been written when this is raised."""


def run_in_transaction(db, fn, *args):
    """Runs fn(transaction, *args) atomically: all of its writes land or none
    do. fn must do every read before its first write (a Firestore rule)."""
    txn = db.transaction()
    if isinstance(txn, firestore.Transaction):
        return firestore.transactional(fn)(txn, *args)
    try:                       # the in-memory fake buffers writes until fn returns
        result = fn(txn, *args)
    except Exception:
        txn.rollback()
        raise
    txn.commit()
    return result


def _depot_stock(db, transaction, depot_ref) -> tuple[dict, float]:
    snap = depot_ref.get(transaction=transaction)
    if not snap.exists:
        raise LedgerError("depot not found")
    depot = snap.to_dict()
    stock = depot.get("stock_t")
    if stock is None:          # depots seeded before the running balance existed
        stock = stock_from_moves(get_inventory_moves(db, depot["id"]))
    return depot, float(stock)


def record_pickup(db, booking_id: str, kg: float, slot_ids: list[str], today: str) -> dict:
    """Collected -> paid in one transaction: the booking, its slots, the
    farmer's payout, the inbound stock move and the depot's running stock.
    Ids are derived from the booking, so a retry can never pay twice."""
    booking_ref = db.collection("bookings").document(booking_id)

    def txn_fn(transaction):
        snap = booking_ref.get(transaction=transaction)
        if not snap.exists:
            raise KeyError("booking not found")
        booking = snap.to_dict()
        collected = booking_transition_update(booking, "collected", {"collected_kg": kg})
        paid = booking_transition_update({**booking, **collected}, "paid", {})
        depot_ref = db.collection("depots").document(booking["depot_id"])
        depot, stock = _depot_stock(db, transaction, depot_ref)
        tonnes = round(kg / 1000, 3)
        if stock + tonnes > depot["capacity_t"] + 1e-6:
            raise LedgerError(f"{depot.get('name', depot['id'])} has room for {round(depot['capacity_t'] - stock, 1)} t, "
                              f"not {tonnes} t: move stock out before collecting more")
        purchase = {"id": f"purchase_{booking_id}", "created_at": _now(), "booking_id": booking_id,
                    "farmer_id": booking["farmer_id"], "depot_id": booking["depot_id"],
                    "district": booking.get("district"), "kg": kg, "price_per_kg": booking["price_per_kg"],
                    "amount_inr": round(kg * booking["price_per_kg"], 2), "paid_on": today,
                    "method": "UPI", "simulated": True}
        move = {"id": f"move_in_{booking_id}", "created_at": _now(), "depot_id": booking["depot_id"],
                "kind": "inbound", "tonnes": tonnes, "date": today, "booking_id": booking_id}
        update = {**collected, **paid, "status": "paid", "collected_at": collected["status_updated_at"],
                  "purchase_id": purchase["id"], "payout_inr": purchase["amount_inr"]}
        transaction.update(booking_ref, update)
        transaction.set(db.collection("purchases").document(purchase["id"]), purchase)
        transaction.set(db.collection("inventory_moves").document(move["id"]), move)
        transaction.update(depot_ref, {"stock_t": round(stock + tonnes, 3)})
        for sid in slot_ids:
            transaction.update(db.collection("pickup_slots").document(sid), {"status": "collected"})
        return {"booking": {**booking, **update}, "purchase": purchase, "inventory_move": move}

    return run_in_transaction(db, txn_fn)


def record_shipment(db, delivery_id: str, tonnes: float | None, today: str) -> dict:
    """A planned delivery leaves the depot: the outbound stock move, the
    depot's running stock and the delivery's shipped record, atomically.
    Refused if the depot holds less straw than the truck would carry."""
    delivery_ref = db.collection("deliveries").document(delivery_id)

    def txn_fn(transaction):
        snap = delivery_ref.get(transaction=transaction)
        if not snap.exists:
            raise KeyError("delivery not found")
        delivery = snap.to_dict()
        if delivery.get("status") == "shipped":
            raise LedgerError("This delivery has already shipped")
        if delivery["month"] > today:
            raise LedgerError(f"This delivery is planned for {delivery['month'][:7]}; it can't ship before its month")
        t = round(float(tonnes if tonnes is not None else delivery["tonnes"]), 3)
        if t <= 0 or t > delivery["tonnes"] * 1.05 + 1e-6:
            raise LedgerError("Shipped tonnes must be more than 0 and at most 5% over the plan")
        depot_ref = db.collection("depots").document(delivery["depot_id"])
        depot, stock = _depot_stock(db, transaction, depot_ref)
        if t > stock + 1e-6:
            raise LedgerError(f"{depot.get('name', depot['id'])} holds {round(stock, 1)} t, not {t} t")
        move = {"id": f"move_out_{delivery_id}", "created_at": _now(), "depot_id": delivery["depot_id"],
                "kind": "outbound", "tonnes": t, "date": today, "delivery_id": delivery_id,
                "order_id": delivery["order_id"]}
        shipped = {"status": "shipped", "shipped_t": t, "shipped_on": today}
        transaction.set(db.collection("inventory_moves").document(move["id"]), move)
        transaction.update(depot_ref, {"stock_t": round(stock - t, 3)})
        transaction.update(delivery_ref, shipped)
        return {"delivery": {**delivery, **shipped}, "inventory_move": move}

    return run_in_transaction(db, txn_fn)


# ---- customers, orders, deliveries

def save_customer(db: firestore.Client, customer: dict) -> dict:
    return _save(db, "customers", "customer", customer)


def get_customer(db: firestore.Client, customer_id: str) -> dict | None:
    return _get(db, "customers", customer_id)


def get_customers(db: firestore.Client) -> list[dict]:
    return sorted(_all(db, "customers"), key=lambda c: c.get("name", c["id"]))


def save_order(db: firestore.Client, order: dict) -> dict:
    return _save(db, "orders", "order", {"status": "confirmed", **order})


def update_order_status(db: firestore.Client, order_id: str, status: str) -> dict | None:
    order = _get(db, "orders", order_id)
    if order is None:
        return None
    order = {**order, "status": status, "status_at": _now()}
    db.collection("orders").document(order_id).set(order)
    return order


def get_orders(db: firestore.Client, customer_id: str | None = None) -> list[dict]:
    rows = _where(db, "orders", "customer_id", customer_id) if customer_id else _all(db, "orders")
    return sorted(rows, key=lambda o: o.get("created_at", ""))


def replace_deliveries(db: firestore.Client, rows: list[dict]) -> None:
    """Writes a fresh delivery plan. Shipped deliveries are history and are
    kept; the planner has already taken them off what each order still needs."""
    shipped = set()
    batch = db.batch()
    for doc in db.collection("deliveries").stream():
        if (doc.to_dict() or {}).get("status") == "shipped":
            shipped.add(doc.id)
        else:
            batch.delete(doc.reference)
    for row in rows:
        if row["id"] not in shipped:
            batch.set(db.collection("deliveries").document(row["id"]), {"status": "planned", **row})
    batch.commit()


def get_delivery(db: firestore.Client, delivery_id: str) -> dict | None:
    return _get(db, "deliveries", delivery_id)


def get_deliveries(db: firestore.Client, order_id: str | None = None) -> list[dict]:
    rows = _where(db, "deliveries", "order_id", order_id) if order_id else _all(db, "deliveries")
    return sorted(rows, key=lambda r: (r["month"], r["depot_id"]))


# ---- planner and forecaster outputs

def save_plan(db: firestore.Client, plan_id: str, plan: dict) -> None:
    db.collection("plans").document(plan_id).set({**plan, "id": plan_id, "updated_at": _now()})


def get_plan(db: firestore.Client, plan_id: str) -> dict | None:
    return _get(db, "plans", plan_id)


def get_forecast(db: firestore.Client, forecast_id: str) -> dict | None:
    return _get(db, "forecasts", forecast_id)


# ---- farmer agent conversations

def save_conversation(db: firestore.Client, conversation: dict) -> dict:
    return _save(db, "conversations", "conv", {**conversation, "updated_at": _now()})


def get_conversation(db: firestore.Client, conversation_id: str) -> dict | None:
    return _get(db, "conversations", conversation_id)


def get_recent_conversations(db: firestore.Client, limit: int = 100) -> list[dict]:
    query = db.collection("conversations").order_by("updated_at", direction="DESCENDING").limit(limit)
    return [d.to_dict() for d in query.stream()]


# ---- trust and satellite data

def get_farmer(db: firestore.Client, farmer_id: str) -> dict | None:
    return _get(db, "farmers", farmer_id)


def save_farmer_trust_score(db: firestore.Client, farmer_id: str, trust_score: float) -> None:
    db.collection("farmers").document(farmer_id).set({"id": farmer_id, "trust_score": trust_score}, merge=True)


def save_no_burn_proof(db: firestore.Client, farmer_id: str, proof: dict) -> dict:
    return _save(db, "no_burn_proofs", "proof", {**proof, "farmer_id": farmer_id})


def get_fire_data_coverage(db: firestore.Client) -> dict | None:
    """The {start_date, end_date} the last fire batch covered -- checked
    before treating an empty result as "no fire", since an absence of rows
    can't tell "checked and none" from "never checked"."""
    return _get(db, "fire_detections", "_meta")


def get_fire_detections_near(db: firestore.Client, district: str | None, date_str: str | None) -> list[dict]:
    """Detections from the last fire batch for a district (the `_meta` doc
    has no district_guess, so the filter skips it), optionally on one date."""
    if not district:
        return []
    detections = _where(db, "fire_detections", "district_guess", district)
    return [d for d in detections if d.get("detected_at") == date_str] if date_str else detections
