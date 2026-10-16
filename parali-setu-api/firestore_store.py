"""Firestore read/write helpers for Parali Setu's data model (PRD
docs/PARALI_SETU_PRD.md, Section 10). Thin wrappers only -- no business
logic here, that's solver.py (numbers) and extraction.py (language).

Shares the ai-builder-cup-aidatlas GCP project with AidAtlas but uses
disjoint collection names (listings/companies/demand/matches/forecasts
vs. AidAtlas's single "allocations" collection) -- confirmed no overlap
before reusing the project.
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


def save_listing(db: firestore.Client, farmer_id: str, extracted: dict, language: str) -> dict:
    quantity_kg = extracted.get("quantity_kg")
    listing = {
        "id": _new_id("listing"),
        "farmer_id": farmer_id,
        "quantity_kg": quantity_kg,
        "quantity_remaining_kg": quantity_kg,
        "crop_type": extracted.get("crop_type"),
        "village_or_district": extracted.get("village_or_district"),
        "ready_by": extracted.get("ready_by"),
        "contact": extracted.get("contact"),
        "quality_grade": extracted.get("quality_grade", "unknown"),
        "status": "open",
        "language": language,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.collection("listings").document(listing["id"]).set(listing)
    return listing


def get_open_listings(db: firestore.Client) -> list[dict]:
    docs = db.collection("listings").where("status", "==", "open").stream()
    return [d.to_dict() for d in docs]


def get_listing(db: firestore.Client, listing_id: str) -> dict | None:
    doc = db.collection("listings").document(listing_id).get()
    return doc.to_dict() if doc.exists else None


def save_company(db: firestore.Client, company: dict) -> dict:
    company = {**company, "id": company.get("id") or _new_id("company")}
    db.collection("companies").document(company["id"]).set(company)
    return company


def save_demand(db: firestore.Client, company_id: str, demand: dict) -> dict:
    demand = {
        "custom_constraints": [],
        **demand,
        "id": demand.get("id") or _new_id("demand"),
        "company_id": company_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    demand.setdefault("quantity_remaining_kg", demand.get("quantity_needed_kg", 0))
    db.collection("demand").document(demand["id"]).set(demand)
    return demand


def demand_remaining_kg(doc: dict) -> float:
    """What a demand can still absorb. Docs written before this field
    existed fall back to their full quantity_needed_kg."""
    remaining = doc.get("quantity_remaining_kg")
    return doc.get("quantity_needed_kg", 0) if remaining is None else remaining


def get_open_demand(db: firestore.Client) -> list[dict]:
    """Only demand with capacity left. Before this filter every solve saw
    every demand at its full original quantity, so the same kilograms could
    be sold again and again."""
    docs = db.collection("demand").stream()
    return [d for d in (doc.to_dict() for doc in docs) if demand_remaining_kg(d) > 1e-6]


def get_demand(db: firestore.Client, demand_id: str) -> dict | None:
    doc = db.collection("demand").document(demand_id).get()
    return doc.to_dict() if doc.exists else None


def get_demand_for_company(db: firestore.Client, company_id: str) -> list[dict]:
    docs = db.collection("demand").where("company_id", "==", company_id).stream()
    return [d.to_dict() for d in docs]


def listing_remaining_update(doc: dict, delta_kg: float) -> dict:
    """Fields to write after changing a listing's remaining quantity by
    `delta_kg` (negative when matched, positive when a match is rejected).
    Clamped to [0, quantity_kg]; status follows the remaining quantity."""
    total = doc.get("quantity_kg", 0) or 0
    remaining = doc.get("quantity_remaining_kg")
    if remaining is None:
        remaining = total
    new_remaining = round(min(total, max(0.0, remaining + delta_kg)), 2)
    return {"quantity_remaining_kg": new_remaining, "status": "matched" if new_remaining <= 1e-6 else "open"}


def demand_remaining_update(doc: dict, delta_kg: float) -> dict:
    """Same as listing_remaining_update, for a buyer's standing demand."""
    total = doc.get("quantity_needed_kg", 0) or 0
    new_remaining = round(min(total, max(0.0, demand_remaining_kg(doc) + delta_kg)), 2)
    return {"quantity_remaining_kg": new_remaining}


@firestore.transactional
def _adjust_remaining(transaction: firestore.Transaction, listing_ref, demand_ref, delta_kg: float) -> None:
    """Reads both docs inside the transaction, then writes both, so two
    near-simultaneous solves cannot double-commit the same kilograms."""
    listing_snap = listing_ref.get(transaction=transaction)
    demand_snap = demand_ref.get(transaction=transaction)
    if listing_snap.exists:
        transaction.update(listing_ref, listing_remaining_update(listing_snap.to_dict(), delta_kg))
    if demand_snap.exists:
        transaction.update(demand_ref, demand_remaining_update(demand_snap.to_dict(), delta_kg))


def _close_out_matched_quantity(db: firestore.Client, match_results: list) -> None:
    """Decrements both sides of every new match: the listing's remaining
    quantity (flipping it to status="matched" once exhausted) and the
    buyer demand's remaining capacity. The listing half was a round-4/5
    judge-eval fix; the demand half closes the same gap on the buyer side,
    where every solve previously saw full original capacity."""
    for r in match_results:
        _adjust_remaining(
            db.transaction(),
            db.collection("listings").document(r.listing_id),
            db.collection("demand").document(r.demand_id),
            -r.matched_kg,
        )


def save_matches(db: firestore.Client, match_results: list) -> list[dict]:
    """Overwrites nothing -- each solver run creates fresh match docs.
    Deterministic doc ids aren't used here (unlike AidAtlas's allocations)
    because a listing can legitimately re-match differently after a
    negotiation; callers that want "latest match for this listing" should
    filter by listing_id and sort by created_at.
    """
    saved = []
    batch = db.batch()
    for r in match_results:
        match_doc = {
            "id": _new_id("match"),
            "listing_id": r.listing_id,
            "demand_id": r.demand_id,
            "farmer_id": r.farmer_id,
            "company_id": r.company_id,
            "matched_kg": r.matched_kg,
            "price_agreed_per_kg": r.price_agreed_per_kg,
            "urgency_multiplier_applied": r.urgency_multiplier_applied,
            "status": "proposed",
            "negotiation_log": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        batch.set(db.collection("matches").document(match_doc["id"]), match_doc)
        saved.append(match_doc)
    if saved:
        batch.commit()
        _close_out_matched_quantity(db, match_results)
    return saved


def get_matches_for_company(db: firestore.Client, company_id: str) -> list[dict]:
    docs = db.collection("matches").where("company_id", "==", company_id).stream()
    return [d.to_dict() for d in docs]


def get_match(db: firestore.Client, match_id: str) -> dict | None:
    doc = db.collection("matches").document(match_id).get()
    return doc.to_dict() if doc.exists else None


# Allowed moves in the match lifecycle (docs: Lucid "Listing and match
# lifecycle"). The buyer pre-commits by posting standing demand, so a match
# goes straight from proposed to scheduled when the farmer accepts a slot.
MATCH_TRANSITIONS = {
    "proposed": {"scheduled", "waitlisted", "rejected"},
    "waitlisted": {"proposed", "scheduled", "rejected"},
    "scheduled": {"collected", "rejected"},
    "collected": {"paid"},
    "paid": set(),
    "rejected": set(),
}


class InvalidTransition(ValueError):
    pass


def can_transition(current: str | None, new_status: str) -> bool:
    return new_status in MATCH_TRANSITIONS.get(current or "proposed", set())


@firestore.transactional
def _transition_match(transaction: firestore.Transaction, db: firestore.Client, match_ref, new_status: str, extra: dict) -> dict:
    snap = match_ref.get(transaction=transaction)
    if not snap.exists:
        raise KeyError("match not found")
    match = snap.to_dict()
    current = match.get("status", "proposed")
    if not can_transition(current, new_status):
        raise InvalidTransition(f"A match that is {current} cannot become {new_status}.")

    listing_snap = demand_snap = None
    if new_status == "rejected":
        listing_ref = db.collection("listings").document(match["listing_id"])
        demand_ref = db.collection("demand").document(match["demand_id"])
        listing_snap = listing_ref.get(transaction=transaction)
        demand_snap = demand_ref.get(transaction=transaction)

    update = {**extra, "status": new_status, "status_updated_at": datetime.now(timezone.utc).isoformat()}
    transaction.update(match_ref, update)
    if listing_snap is not None and listing_snap.exists:
        transaction.update(listing_snap.reference, listing_remaining_update(listing_snap.to_dict(), match["matched_kg"]))
    if demand_snap is not None and demand_snap.exists:
        transaction.update(demand_snap.reference, demand_remaining_update(demand_snap.to_dict(), match["matched_kg"]))
    return {**match, **update}


def update_match_status(db: firestore.Client, match_id: str, status: str, extra: dict | None = None) -> dict:
    """Moves a match along the lifecycle atomically. Rejecting a match puts
    its kilograms back on both the listing and the buyer's demand. Raises
    KeyError for an unknown match and InvalidTransition for a move the
    lifecycle doesn't allow."""
    match_ref = db.collection("matches").document(match_id)
    return _transition_match(db.transaction(), db, match_ref, status, extra or {})


def append_negotiation_log(db: firestore.Client, match_id: str, entry: dict) -> None:
    entry = {**entry, "timestamp": datetime.now(timezone.utc).isoformat()}
    db.collection("matches").document(match_id).update(
        {"negotiation_log": firestore.ArrayUnion([entry])}
    )


def update_match_price(db: firestore.Client, match_id: str, new_price_per_kg: float) -> None:
    db.collection("matches").document(match_id).update({"price_agreed_per_kg": new_price_per_kg})


def get_farmer(db: firestore.Client, farmer_id: str) -> dict | None:
    doc = db.collection("farmers").document(farmer_id).get()
    return doc.to_dict() if doc.exists else None


def save_farmer_trust_score(db: firestore.Client, farmer_id: str, trust_score: float) -> None:
    db.collection("farmers").document(farmer_id).set(
        {"id": farmer_id, "trust_score": trust_score}, merge=True
    )


def get_trust_scores_by_farmer_ids(db: firestore.Client, farmer_ids: list[str]) -> dict[str, float]:
    """Batched by Firestore's own `in` filter (max 30 per call -- fine at
    demo scale) rather than one get() per farmer, since this runs on every
    solve across however many open listings there are.
    """
    scores: dict[str, float] = {}
    unique_ids = list(dict.fromkeys(farmer_ids))
    for i in range(0, len(unique_ids), 30):
        chunk = unique_ids[i : i + 30]
        docs = db.collection("farmers").where("id", "in", chunk).stream()
        for doc in docs:
            data = doc.to_dict()
            if data.get("trust_score") is not None:
                scores[data["id"]] = data["trust_score"]
    return scores


def save_no_burn_proof(db: firestore.Client, farmer_id: str, proof: dict) -> dict:
    proof = {
        **proof,
        "id": _new_id("proof"),
        "farmer_id": farmer_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.collection("no_burn_proofs").document(proof["id"]).set(proof)
    return proof


def get_fire_data_coverage(db: firestore.Client) -> dict | None:
    """The {start_date, end_date} fetch_fire_data.py's last run actually
    covered -- read before trusting an empty fire_detections result as
    "no fire," since a plain absence of rows can't tell "we checked and
    there was none" from "we never checked that window" on its own.
    """
    doc = db.collection("fire_detections").document("_meta").get()
    return doc.to_dict() if doc.exists else None


def get_fire_detections_near(db: firestore.Client, district: str | None, date_str: str | None) -> list[dict]:
    """Reads whatever fetch_fire_data.py last wrote (Part A) -- never
    queries Earth Engine live itself. `district` is the nearest-HQ guess
    already attached to each detection; `date_str` narrows to the
    specific claimed date if given, else any detection for that district
    in the current batch counts as corroborating evidence.
    """
    if not district:
        return []
    # The "_meta" doc has no district_guess field, so this filter already
    # excludes it naturally (a Firestore `where` skips docs missing the field).
    docs = db.collection("fire_detections").where("district_guess", "==", district).stream()
    detections = [d.to_dict() for d in docs]
    if date_str:
        detections = [d for d in detections if d.get("detected_at") == date_str]
    return detections


def save_negotiation_session(db: firestore.Client, match_id: str, session: dict) -> dict:
    """Feature 2: the full auditable transcript of one agent-to-agent
    negotiation run -- every proposed price, every narration, the
    outcome. Separate from matches/{id}.negotiation_log (the existing
    human-counter-offer log) since this is a distinct capability.
    """
    session = {
        **session,
        "id": _new_id("negsession"),
        "match_id": match_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    db.collection("negotiation_sessions").document(session["id"]).set(session)
    return session


def get_company(db: firestore.Client, company_id: str) -> dict | None:
    doc = db.collection("companies").document(company_id).get()
    return doc.to_dict() if doc.exists else None


def get_companies(db: firestore.Client) -> list[dict]:
    return [d.to_dict() for d in db.collection("companies").stream()]


def get_crews_for_company(db: firestore.Client, company_id: str) -> list[dict]:
    docs = db.collection("crews").where("company_id", "==", company_id).stream()
    return [d.to_dict() for d in docs]


def get_slots_for_company(db: firestore.Client, company_id: str) -> list[dict]:
    docs = db.collection("pickup_slots").where("company_id", "==", company_id).stream()
    return [d.to_dict() for d in docs]


def get_slots_for_match(db: firestore.Client, match_id: str) -> list[dict]:
    docs = db.collection("pickup_slots").where("match_id", "==", match_id).stream()
    return sorted((d.to_dict() for d in docs), key=lambda s: (s["date"], s["planned_start_min"]))


def replace_company_plan(db: firestore.Client, company_id: str, slots: list[dict]) -> None:
    """Writes a fresh plan for one buyer: every tentative slot is replaced;
    locked and collected slots are only updated (their promised windows
    never change here)."""
    existing = get_slots_for_company(db, company_id)
    keep_ids = {s["id"] for s in slots}
    batch = db.batch()
    for old in existing:
        if old.get("status") == "tentative" and old["id"] not in keep_ids:
            batch.delete(db.collection("pickup_slots").document(old["id"]))
    for slot in slots:
        batch.set(db.collection("pickup_slots").document(slot["id"]), slot, merge=True)
    batch.commit()


def set_slots_status(db: firestore.Client, match_id: str, status: str, locked: bool | None = None) -> list[dict]:
    slots = get_slots_for_match(db, match_id)
    update = {"status": status, **({"locked": locked} if locked is not None else {})}
    batch = db.batch()
    for slot in slots:
        batch.update(db.collection("pickup_slots").document(slot["id"]), update)
    if slots:
        batch.commit()
    return [{**s, **update} for s in slots]


def update_match_fields(db: firestore.Client, match_id: str, fields: dict) -> None:
    db.collection("matches").document(match_id).update(fields)


def save_payout(db: firestore.Client, payout: dict) -> dict:
    payout = {**payout, "id": payout.get("id") or _new_id("payout"),
              "created_at": datetime.now(timezone.utc).isoformat()}
    db.collection("payouts").document(payout["id"]).set(payout)
    return payout


def get_negotiation_session(db: firestore.Client, session_id: str) -> dict | None:
    doc = db.collection("negotiation_sessions").document(session_id).get()
    return doc.to_dict() if doc.exists else None


def mark_negotiation_session_confirmed(db: firestore.Client, session_id: str) -> None:
    db.collection("negotiation_sessions").document(session_id).update(
        {"confirmed_at": datetime.now(timezone.utc).isoformat()}
    )


def get_forecast_for_company(db: firestore.Client, company_id: str) -> dict | None:
    """Reads whatever forecast_pipeline.py last wrote (PRD 12/13.1) --
    never computed here, never live. None if the pipeline hasn't run for
    this company yet; callers must show 'not yet available', not a
    fabricated recommendation (PRD 8.2.2)."""
    doc = db.collection("forecasts").document(f"forecast_{company_id}").get()
    return doc.to_dict() if doc.exists else None
