"""Parali Setu API. Parali Setu buys paddy straw from farmers at a posted
price, collects it with its own (and partner) crews before the sowing
deadline, pays the same day, stores it at depots and supplies companies all
year under forward orders.

Layers, and who owns which output:
  Language   Gemini (extraction.py), Speech-to-Text / Text-to-Speech (speech.py)
             -> understands and explains; never produces a number
  Planning   procurement.py (LP: what to buy, posted price), scheduler.py
             (routing: who collects when), deliveries.py (LP: what ships
             where), costs.py (quotes)  -> every price, quantity and slot
  Forecast   forecast/ (BigQuery TimesFM on NASA FIRMS history, APY crop data)
  State      Firestore (firestore_store.py)
"""
from __future__ import annotations

import base64
import os
from datetime import date
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import firestore_store as store
import operations
import pickups
from extraction import (
    explain_offer,
    explain_price,
    extract_listing,
    follow_up_question,
    read_no_burn_proof,
    read_stubble_quality,
)
from forecast.demand_segments import EX_SITU_SOURCE, EX_SITU_TOTAL_T, SEGMENTS, segment_totals
from geo import district_from_text
from gemini_client import get_gemini_client
from impact import impact_for_kg, punjab_scenario
from phrases import confirm_summary
from scheduler import STRAW_T_PER_ACRE, acres_from_kg
from speech import synthesize_speech, transcribe_audio
from trust import score_no_burn_submission

app = FastAPI(title="Parali Setu API")

# Only our own Firebase Hosting site (and local development) may call the
# API from a browser. Override with a comma-separated ALLOWED_ORIGINS.
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "ALLOWED_ORIGINS",
        "https://parali-setu.web.app,https://parali-setu.firebaseapp.com,http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if o.strip()
]
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"])

Language = Literal["Hindi", "Punjabi", "English"]
CropType = Literal["rice_stubble", "wheat_stubble"]
MAX_QUANTITY_KG = 10_000_000.0
Phone = Field(default=None, pattern=r"^\+?[0-9 ]{10,15}$")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

DRAFT_FIELDS = ("quantity_kg", "acres", "crop_type", "village_or_district", "ready_by", "sowing_deadline", "contact")


def _today() -> date:
    return pickups.now_ist().date()


def _complete_quantities(fields: dict) -> dict:
    """Area and weight are derived from each other in code (1.75 t/acre),
    never by Gemini, so the planners always have both."""
    fields = dict(fields)
    if fields.get("acres") and not fields.get("quantity_kg"):
        fields["quantity_kg"] = round(fields["acres"] * STRAW_T_PER_ACRE * 1000, 1)
    elif fields.get("quantity_kg") and not fields.get("acres"):
        fields["acres"] = acres_from_kg(fields["quantity_kg"])
    return fields


def _missing_fields(fields: dict) -> list[str]:
    missing = []
    if not fields.get("quantity_kg") and not fields.get("acres"):
        missing.append("quantity")
    if not fields.get("crop_type"):
        missing.append("crop_type")
    if pickups.listing_location(fields) is None:
        missing.append("location")
    if not fields.get("sowing_deadline"):
        missing.append("sowing_deadline")
    return missing


def _spoken(text: str | None, language: str) -> dict | None:
    if not text:
        return None
    audio = synthesize_speech(text, language)
    return {"text": text, "audio_base64": base64.b64encode(audio).decode("ascii") if audio else None}


async def _transcribe_upload(audio: UploadFile, language: str) -> str:
    audio_bytes = await audio.read()
    if audio.content_type and "wav" in audio.content_type:
        audio_format, sample_rate = "linear16", 16000
    else:
        audio_format, sample_rate = "webm_opus", 48000
    transcript = transcribe_audio(audio_bytes, language, sample_rate_hertz=sample_rate, audio_format=audio_format)
    if transcript is None:
        raise HTTPException(status_code=422, detail="Could not hear that clearly -- please try again or type it")
    return transcript


def _posted_price(db, district: str) -> dict:
    """Today's posted price for a district; runs the procurement planner
    once if today's prices haven't been posted yet."""
    today = _today().isoformat()
    row = store.get_posted_price(db, today, district)
    if row is None:
        operations.run_procurement(db)
        row = store.get_posted_price(db, today, district)
    if row is None:
        raise HTTPException(status_code=503, detail="Today's prices are not available yet -- please try again shortly")
    return row


def _booking_view(db, booking: dict, depots: dict[str, dict] | None = None) -> dict:
    """A booking as the apps show it: depot name, slots, arrival window,
    payout estimate and when an unaccepted offer lapses."""
    depots = depots if depots is not None else {}
    depot = depots.get(booking["depot_id"]) or store.get_depot(db, booking["depot_id"]) or {}
    slots = store.get_slots_for_booking(db, booking["id"])
    expires = pickups.offer_expires_at(booking)
    return {
        **booking,
        "depot_name": depot.get("name", booking["depot_id"]),
        "slots": slots,
        "pickup_window": pickups.window_label(slots[0]) if slots else None,
        "payout_estimate_inr": round(booking["kg"] * booking["price_per_kg"], 2),
        "offer_expires_at": expires.isoformat() if expires and booking.get("status") in ("offered", "unschedulable") else None,
        "partner_crew": any(s.get("partner") for s in slots),
    }


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/fire-detections")
def fire_detections():
    """The last NASA FIRMS batch (fetch_fire_data.py), refreshed daily,
    never computed here."""
    db = store.get_firestore_client()
    coverage = store.get_fire_data_coverage(db)
    detections = [d.to_dict() for d in db.collection("fire_detections").stream() if d.id != "_meta"]
    return {"detections": detections, "coverage": coverage}


@app.get("/impact")
def impact_summary():
    """Impact of straw actually collected so far, plus what is booked.
    Deterministic: impact.py."""
    db = store.get_firestore_client()
    collected_kg = booked_kg = paid_inr = 0.0
    farmers = set()
    for b in store.get_bookings(db, ("booked", "collected", "paid")):
        if b["status"] == "booked":
            booked_kg += b["kg"]
        else:
            collected_kg += b.get("collected_kg") or b["kg"]
            paid_inr += b.get("payout_inr") or 0.0
            farmers.add(b["farmer_id"])
    return {"collected": impact_for_kg(collected_kg), "booked": impact_for_kg(booked_kg),
            "paid_to_farmers_inr": round(paid_inr, 2), "farmers_paid": len(farmers)}


@app.get("/impact/scenario")
def impact_scenario(share_pct: float = Query(5.0, ge=0, le=100)):
    """Landing-page slider: impact if this share of Punjab's paddy straw were
    collected instead of burned. Deterministic: impact.py."""
    return punjab_scenario(share_pct)


@app.get("/prices/today")
def prices_today(district: str | None = Query(None, max_length=60)):
    """Today's posted farm-gate price, per district or for all of them."""
    db = store.get_firestore_client()
    if district:
        name = district_from_text(district)
        if name is None:
            raise HTTPException(status_code=404, detail="We don't buy in that district yet")
        return _posted_price(db, name)
    rows = store.get_posted_prices_for_day(db, _today().isoformat())
    if not rows:
        operations.run_procurement(db)
        rows = store.get_posted_prices_for_day(db, _today().isoformat())
    return {"date": _today().isoformat(), "prices": rows}


# ---------------------------------------------------------------------------
# Farmer: speak once, confirm once, get a slot and a price
# ---------------------------------------------------------------------------

@app.post("/listings/draft")
async def listing_draft(
    farmer_id: str = Form(..., min_length=1, max_length=64),
    language: Language = Form("Hindi"),
    text: str | None = Form(None, max_length=1000),
    draft_id: str | None = Form(None, max_length=64),
    lat: float | None = Form(None, ge=-90, le=90),
    lon: float | None = Form(None, ge=-180, le=180),
    audio: UploadFile | None = File(None),
    photo: UploadFile | None = File(None),
):
    """Step 1: understand what the farmer said (voice or text, optional photo
    and location). Returns the draft for the confirm card and -- only the
    first time something is missing -- ONE question asking for all of it.
    Nothing is booked until /confirm."""
    db = store.get_firestore_client()
    client = get_gemini_client()

    draft = None
    if draft_id:
        draft = store.get_draft(db, draft_id)
        if draft is None or draft.get("farmer_id") != farmer_id:
            raise HTTPException(status_code=404, detail="Draft not found")
        if draft.get("listing_id"):
            raise HTTPException(status_code=409, detail="This listing was already confirmed")

    if audio is not None:
        utterance = await _transcribe_upload(audio, language)
    elif text and text.strip():
        utterance = text.strip()
    elif draft is None:
        raise HTTPException(status_code=422, detail="Say or type what you want to list")
    else:
        utterance = ""

    transcript = " ".join(t for t in ((draft or {}).get("transcript", ""), utterance) if t).strip()
    fields = dict((draft or {}).get("fields") or {})
    if utterance:
        extracted = extract_listing(client, transcript, language)
        if extracted is None:
            raise HTTPException(status_code=503, detail="Could not understand that right now -- please try again")
        for key in DRAFT_FIELDS:
            if extracted.get(key) is not None:
                fields[key] = extracted[key]
    if lat is not None and lon is not None:
        fields["lat"], fields["lon"] = lat, lon
    fields = _complete_quantities(fields)

    quality = (draft or {}).get("quality") or {"grade": "unknown", "note": None}
    if photo is not None:
        result = read_stubble_quality(client, await photo.read(), mime_type=photo.content_type or "image/jpeg")
        if result and result.get("quality_grade"):
            quality = {"grade": result["quality_grade"], "note": result.get("note")}

    missing = _missing_fields(fields)
    asked_before = bool((draft or {}).get("asked_follow_up"))
    follow_up = None
    if missing and not asked_before:
        follow_up = _spoken(follow_up_question(client, missing, language), language)

    saved = store.save_draft(db, {
        **(draft or {}), "farmer_id": farmer_id, "language": language, "transcript": transcript,
        "fields": fields, "quality": quality, "missing_fields": missing,
        "asked_follow_up": asked_before or follow_up is not None,
    })
    location = pickups.listing_location(fields)
    district = pickups.listing_district(fields)
    return {
        "draft_id": saved["id"],
        "transcript": transcript,
        "fields": fields,
        "district": district,
        "quality": quality,
        "location_approximate": location[2] if location else None,
        "missing_fields": missing,
        "follow_up": follow_up,
        "confirm_summary": None if follow_up else _spoken(confirm_summary(fields, language), language),
    }


class DraftEdits(BaseModel):
    acres: float | None = Field(default=None, gt=0, le=1000)
    crop_type: CropType | None = None
    village_or_district: str | None = Field(default=None, max_length=120)
    ready_by: date | None = None
    sowing_deadline: date | None = None
    contact: str | None = Phone


class ConfirmDraftRequest(BaseModel):
    farmer_id: str = Field(min_length=1, max_length=64)
    edits: DraftEdits | None = None


@app.post("/listings/{draft_id}/confirm")
def confirm_listing(draft_id: str, req: ConfirmDraftRequest):
    """Step 2: the farmer confirmed the card. The listing is saved, priced at
    today's posted price for its district, sent to the depot the procurement
    plan intends, and given a pickup slot by the scheduler (our crews first,
    partner crews if ours can't make it before sowing)."""
    db = store.get_firestore_client()
    client = get_gemini_client()
    draft = store.get_draft(db, draft_id)
    if draft is None or draft.get("farmer_id") != req.farmer_id:
        raise HTTPException(status_code=404, detail="Draft not found")
    if draft.get("listing_id"):
        raise HTTPException(status_code=409, detail="This listing was already confirmed")

    fields = dict(draft.get("fields") or {})
    if req.edits:
        edits = req.edits.model_dump(exclude_none=True)
        if "acres" in edits:
            fields.pop("quantity_kg", None)   # re-derive weight from the corrected area
        for key, value in edits.items():
            fields[key] = value.isoformat() if isinstance(value, date) else value
    fields = _complete_quantities(fields)
    if not fields.get("quantity_kg") or not fields.get("crop_type"):
        raise HTTPException(status_code=422, detail="Tell us how much stubble and which crop before confirming")
    location = pickups.listing_location(fields)
    district = pickups.listing_district(fields)
    if location is None or district is None:
        raise HTTPException(status_code=422, detail="Tell us your village or district, or share your location")

    language = draft.get("language", "Hindi")
    quality = draft.get("quality") or {}
    listing = store.save_listing(db, req.farmer_id, {
        **fields, "district": district, "quality_grade": quality.get("grade", "unknown"),
        "quality_note": quality.get("note"), "draft_id": draft_id,
    }, language)
    store.save_draft(db, {**draft, "listing_id": listing["id"], "fields": fields})

    booking, price = operations.book_listing(db, listing)
    if booking is None:
        return {"listing": listing, "status": "out_of_area", "district": district, "price": price}
    pickups.expire_stale_offers(db)
    pickups.plan_depot(db, booking["depot_id"])
    view = _booking_view(db, store.get_booking(db, booking["id"]))

    explanation = None
    if view["status"] == "offered" and view["pickup_window"]:
        explanation = explain_offer(client, {
            "price_per_kg": view["price_per_kg"], "district": district, "kg": view["kg"],
            "payout_inr": view["payout_estimate_inr"], "pickup_window": view["pickup_window"],
        }, language)
    return {
        "listing": listing,
        "status": view["status"],
        "booking": view,
        "price": price,
        "impact_if_collected": impact_for_kg(view["kg"]),
        "window_assumed": pickups.listing_window(listing, _today())[2],
        "location_approximate": location[2],
        "explanation": _spoken(explanation, language),
    }


class FarmerRequest(BaseModel):
    farmer_id: str = Field(min_length=1, max_length=64)


def _accept(db, booking: dict, accepted_by: str) -> dict:
    if not store.get_slots_for_booking(db, booking["id"]):
        raise HTTPException(status_code=409, detail="There is no pickup slot to accept yet")
    if pickups.offer_expired(booking, pickups.now_ist()):
        raise HTTPException(status_code=409, detail="This offer has expired -- please list again for a new slot")
    try:
        updated = store.update_booking_status(db, booking["id"], "booked",
                                              {"slot_accepted_at": pickups.now_ist().isoformat(), "accepted_by": accepted_by})
    except store.InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    locked = store.set_slots_status(db, booking["id"], "locked", locked=True)
    return {"booking": _booking_view(db, updated), "slots": locked, "pickup_window": pickups.window_label(locked[0])}


@app.post("/bookings/{booking_id}/accept")
def accept_booking(booking_id: str, req: FarmerRequest):
    """The farmer accepts the price and slot: the booking is confirmed and its
    slot locked. Later re-plans fit new work around it."""
    db = store.get_firestore_client()
    booking = store.get_booking(db, booking_id)
    if booking is None or booking.get("farmer_id") != req.farmer_id:
        raise HTTPException(status_code=404, detail="Booking not found")
    return _accept(db, booking, "farmer")


@app.post("/bookings/{booking_id}/cancel")
def cancel_booking(booking_id: str, req: FarmerRequest):
    db = store.get_firestore_client()
    booking = store.get_booking(db, booking_id)
    if booking is None or booking.get("farmer_id") != req.farmer_id:
        raise HTTPException(status_code=404, detail="Booking not found")
    try:
        updated = store.update_booking_status(db, booking_id, "cancelled", {"status_reason_code": "cancelled_by_farmer"})
    except store.InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    store.set_slots_status(db, booking_id, "cancelled", locked=False)
    pickups.plan_depot(db, booking["depot_id"])
    return {"booking": _booking_view(db, updated)}


@app.get("/farmers/{farmer_id}/bookings")
def farmer_bookings(farmer_id: str):
    """Everything the farmer's status cards need. Read-only."""
    db = store.get_firestore_client()
    depots = {d["id"]: d for d in store.get_depots(db)}
    bookings = [_booking_view(db, b, depots) for b in store.get_bookings_for_farmer(db, farmer_id)
                if b.get("status") not in ("cancelled",)]
    return {"farmer_id": farmer_id, "bookings": bookings}


@app.get("/bookings/{booking_id}/price-explanation")
def price_explanation(booking_id: str, language: Language = "Hindi"):
    """Why the farmer's price is what it is, in their language, from the
    procurement planner's own stated reason."""
    db = store.get_firestore_client()
    booking = store.get_booking(db, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    created = (booking.get("created_at") or _today().isoformat())[:10]
    row = store.get_posted_price(db, created, booking["district"]) or _posted_price(db, booking["district"])
    facts = {"district": booking["district"], "price_per_kg": booking["price_per_kg"], "reason": row["reason"]}
    text = explain_price(get_gemini_client(), facts, language)
    return {"explanation": text or row["reason"], "reason_code": row.get("reason_code"), "facts": facts}


@app.post("/farmers/{farmer_id}/no-burn-proof")
async def submit_no_burn_proof(farmer_id: str, district: str, claimed_date: str | None = None,
                               photo: UploadFile = File(...)):
    """A farmer's photo evidence that the field wasn't burned. Gemini reads
    the photo; the NASA FIRMS batch independently corroborates (or not);
    trust.py combines the two by a fixed rule."""
    db = store.get_firestore_client()
    client = get_gemini_client()
    district = district_from_text(district) or district
    photo_result = read_no_burn_proof(client, await photo.read(), mime_type=photo.content_type or "image/jpeg")
    if photo_result is None:
        raise HTTPException(status_code=503, detail="Could not read that photo right now -- please try again")
    field_condition = photo_result.get("field_condition")

    claimed_date = claimed_date or _today().isoformat()
    coverage = store.get_fire_data_coverage(db)
    if coverage is None or not (coverage["start_date"] <= claimed_date <= coverage["end_date"]):
        satellite = "no_data"
    else:
        satellite = "fire_detected" if store.get_fire_detections_near(db, district, claimed_date) else "no_fire_detected"

    farmer = store.get_farmer(db, farmer_id)
    scoring = score_no_burn_submission(farmer.get("trust_score") if farmer else None, field_condition, satellite)
    store.save_farmer_trust_score(db, farmer_id, scoring["new_score"])
    store.save_no_burn_proof(db, farmer_id, {
        "district": district, "claimed_date": claimed_date, "field_condition": field_condition,
        "satellite_corroboration": satellite, "previous_score": farmer.get("trust_score") if farmer else None,
        "new_score": scoring["new_score"], "disputed": scoring["disputed"], "note": photo_result.get("note"),
    })
    return {"trust_score": scoring["new_score"], "disputed": scoring["disputed"], "field_condition": field_condition,
            "satellite_corroboration": satellite, "note": photo_result.get("note")}


# ---------------------------------------------------------------------------
# Ops console: depots, pickups, inventory, plans, forecast
# ---------------------------------------------------------------------------

@app.get("/ops/summary")
def ops_summary():
    """What needs doing today, across all depots."""
    db = store.get_firestore_client()
    today = _today().isoformat()
    bookings = store.get_bookings(db)
    slots_today = [s for d in store.get_depots(db) for s in store.get_slots_for_depot(db, d["id"])
                   if s["date"] == today and s.get("status") in ("locked", "tentative")]
    by_status: dict[str, int] = {}
    for b in bookings:
        by_status[b.get("status", "offered")] = by_status.get(b.get("status", "offered"), 0) + 1
    procurement = store.get_plan(db, "procurement_current") or {}
    deliveries = store.get_plan(db, "deliveries_current") or {}
    return {
        "date": today, "bookings_by_status": by_status,
        "pickups_today": len([s for s in slots_today if s["status"] == "locked"]),
        "tentative_today": len([s for s in slots_today if s["status"] == "tentative"]),
        "on_partner_crews": len({s["booking_id"] for s in slots_today if s.get("partner")}),
        "needs_attention": [b["id"] for b in bookings if b.get("status") == "booked" and b.get("schedule_note")],
        "stock_t": round(sum(operations.depot_stock_t(db, d["id"]) for d in store.get_depots(db)), 1),
        "procurement_shortfall_t": procurement.get("shortfall_t"),
        "delivery_shortfall_t": deliveries.get("shortfall_t"),
    }


@app.get("/depots")
def list_depots():
    db = store.get_firestore_client()
    out = []
    for d in store.get_depots(db):
        crews = store.get_crews_for_depot(db, d["id"])
        out.append({**d, "crews": crews, "stock_t": operations.depot_stock_t(db, d["id"])})
    return {"depots": out}


def _farm(listing: dict, booking: dict) -> dict:
    location = pickups.listing_location(listing)
    return {
        "booking_id": booking["id"], "farmer_id": booking["farmer_id"], "district": booking.get("district"),
        "village": listing.get("village_or_district"), "contact": listing.get("contact"),
        "sowing_deadline": listing.get("sowing_deadline"), "crop_type": listing.get("crop_type"),
        "quality_grade": listing.get("quality_grade"), "kg": booking["kg"], "acres": booking.get("acres"),
        "price_per_kg": booking["price_per_kg"], "status": booking.get("status"),
        "lat": location[0] if location else None, "lon": location[1] if location else None,
        "location_approximate": location[2] if location else None,
    }


@app.get("/depots/{depot_id}/schedule")
def depot_schedule(depot_id: str):
    """Pickup Ops: one route sheet per crew per day, in visiting order, plus
    farms that can't be served and promises that need a person."""
    db = store.get_firestore_client()
    depot = store.get_depot(db, depot_id)
    if depot is None:
        raise HTTPException(status_code=404, detail="Depot not found")
    bookings = {b["id"]: b for b in store.get_bookings_for_depot(db, depot_id)}
    listings = {lid: doc for lid in {b["listing_id"] for b in bookings.values()} if (doc := store.get_listing(db, lid))}
    crews = {c["id"]: c for c in store.get_crews_for_depot(db, depot_id)}

    sheets: dict[tuple[str, str], list[dict]] = {}
    for slot in store.get_slots_for_depot(db, depot_id):
        booking = bookings.get(slot["booking_id"])
        if booking is None or booking.get("status") in ("cancelled", "expired"):
            continue
        sheets.setdefault((slot["date"], slot["crew_id"]), []).append(
            {**slot, "window": pickups.window_label(slot), **_farm(listings.get(booking["listing_id"], {}), booking)})
    route_sheets = [
        {"date": day, "crew_id": crew_id, "crew_name": crews.get(crew_id, {}).get("name", crew_id),
         "partner": crews.get(crew_id, {}).get("partner", False),
         "acres_per_day": crews.get(crew_id, {}).get("acres_per_day"),
         "stops": sorted(stops, key=lambda s: s["sequence"]), "acres": round(sum(s["acres"] for s in stops), 2)}
        for (day, crew_id), stops in sorted(sheets.items())
    ]
    unschedulable = [{**_farm(listings.get(b["listing_id"], {}), b), "reason": b.get("status_reason"),
                      "reason_code": b.get("status_reason_code")}
                     for b in bookings.values() if b.get("status") == "unschedulable"]
    attention = [{**_farm(listings.get(b["listing_id"], {}), b), "note": b["schedule_note"]}
                 for b in bookings.values() if b.get("status") == "booked" and b.get("schedule_note")]
    return {"depot": depot, "route_sheets": route_sheets, "unschedulable": unschedulable, "needs_attention": attention}


@app.post("/depots/{depot_id}/replan")
def replan_depot(depot_id: str):
    db = store.get_firestore_client()
    if store.get_depot(db, depot_id) is None:
        raise HTTPException(status_code=404, detail="Depot not found")
    expired = pickups.expire_stale_offers(db)
    return {**pickups.plan_depot(db, depot_id), "expired_offers": len(expired)}


class CrewRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    acres_per_day: float = Field(default=20.0, gt=0, le=80)
    partner: bool = False


@app.post("/depots/{depot_id}/crews")
def add_crew(depot_id: str, req: CrewRequest):
    """Adds a crew (ours or a hired partner) to a depot and re-plans it."""
    db = store.get_firestore_client()
    depot = store.get_depot(db, depot_id)
    if depot is None:
        raise HTTPException(status_code=404, detail="Depot not found")
    crew = store.save_crew(db, {"depot_id": depot_id, "name": req.name, "partner": req.partner,
                                "acres_per_day": req.acres_per_day, "depot_lat": depot["lat"], "depot_lon": depot["lon"],
                                "shift_start_min": 7 * 60, "shift_end_min": 18 * 60})
    return {"crew": crew, "plan": pickups.plan_depot(db, depot_id)}


@app.post("/ops/bookings/{booking_id}/accept")
def accept_on_behalf(booking_id: str):
    """Demo only: accept an offer for the farmer, so the collect-and-pay loop
    can be shown without a second phone. Recorded as accepted by ops."""
    db = store.get_firestore_client()
    booking = store.get_booking(db, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    return _accept(db, booking, "ops (demo)")


class CollectedRequest(BaseModel):
    collected_kg: float | None = Field(default=None, gt=0, le=MAX_QUANTITY_KG)


@app.post("/stops/{booking_id}/collected")
def stop_collected(booking_id: str, req: CollectedRequest):
    """The crew collected a farm: the farmer is paid the same day (simulated
    UPI) and the straw is added to the depot's stock."""
    db = store.get_firestore_client()
    booking = store.get_booking(db, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    if req.collected_kg is not None and req.collected_kg > booking["kg"] * 1.2:
        raise HTTPException(status_code=422, detail="Collected weight is more than 20% above the booked quantity")
    try:
        return pickups.complete_pickup(db, booking_id, req.collected_kg)
    except store.InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/inventory")
def inventory():
    db = store.get_firestore_client()
    out = []
    for d in store.get_depots(db):
        moves = store.get_inventory_moves(db, d["id"])
        inbound = sum(m["tonnes"] for m in moves if m["kind"] == "inbound")
        outbound = sum(m["tonnes"] for m in moves if m["kind"] == "outbound")
        out.append({"depot_id": d["id"], "name": d["name"], "capacity_t": d["capacity_t"],
                    "stock_t": round(inbound - outbound, 3), "inbound_t": round(inbound, 3), "outbound_t": round(outbound, 3),
                    "recent": sorted(moves, key=lambda m: m.get("created_at", ""), reverse=True)[:10]})
    return {"depots": out}


@app.get("/purchases")
def purchases(farmer_id: str | None = Query(None, max_length=64)):
    db = store.get_firestore_client()
    rows = [p for p in store.get_purchases(db) if not farmer_id or p["farmer_id"] == farmer_id]
    return {"purchases": sorted(rows, key=lambda p: p.get("created_at", ""), reverse=True),
            "total_inr": round(sum(p["amount_inr"] for p in rows), 2)}


@app.get("/plan/procurement")
def get_procurement_plan():
    db = store.get_firestore_client()
    return store.get_plan(db, "procurement_current") or operations.run_procurement(db)


@app.post("/plan/procurement")
def rerun_procurement():
    """Re-runs the procurement LP: new posted prices for today (existing
    bookings keep the price they were offered) and new district routing."""
    db = store.get_firestore_client()
    plan = operations.run_procurement(db)
    return {"plan": plan, "deliveries": operations.run_deliveries(db)}


@app.get("/plan/deliveries")
def get_delivery_plan():
    db = store.get_firestore_client()
    return {"plan": store.get_plan(db, "deliveries_current") or operations.run_deliveries(db),
            "deliveries": store.get_deliveries(db)}


@app.get("/forecast")
def forecast():
    """Supply: TimesFM's forecast of this season's harvest timing per district
    (from NASA FIRMS history) with the held-out backtests. Demand: published
    industry consumption, derived not trained. Straw volumes: APY crop data."""
    db = store.get_firestore_client()
    year = _today().year
    low, high = segment_totals()
    return {
        "supply_live": store.get_forecast(db, f"supply_live_{year}"),
        "backtests": [b for y in (year - 2, year - 1) if (b := store.get_forecast(db, f"supply_backtest_{y}"))],
        "district_straw": operations.district_straw_t(),
        "demand_segments": [{"key": s.key, "name": s.name, "annual_t_low": s.annual_t_low, "annual_t_high": s.annual_t_high,
                             "as_of": s.as_of, "note": s.note, "sources": list(s.sources)} for s in SEGMENTS],
        "demand_total_t": {"low": low, "high": high},
        "ex_situ_total_t": EX_SITU_TOTAL_T, "ex_situ_source": EX_SITU_SOURCE,
    }


# ---------------------------------------------------------------------------
# Customer portal: forward orders and quotes
# ---------------------------------------------------------------------------

@app.get("/customers")
def list_customers():
    db = store.get_firestore_client()
    return {"customers": store.get_customers(db)}


class OrderRequest(BaseModel):
    tonnes_per_month: float = Field(gt=0, le=20_000)
    months: int = Field(ge=1, le=12)
    start_month: date


def _order_months(req: OrderRequest) -> dict[str, float]:
    start = date(req.start_month.year, req.start_month.month, 1)
    return {operations.add_months(start, i).isoformat(): req.tonnes_per_month for i in range(req.months)}


def _customer_or_404(db, customer_id: str) -> dict:
    customer = store.get_customer(db, customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


@app.post("/customers/{customer_id}/quote")
def quote_customer(customer_id: str, req: OrderRequest):
    """A delivered price per tonne, built up from costs. Saves nothing."""
    db = store.get_firestore_client()
    customer = _customer_or_404(db, customer_id)
    start = date(req.start_month.year, req.start_month.month, 1)
    q = operations.quote_order(db, (customer["lat"], customer["lon"]), start, req.months)
    total_t = req.tonnes_per_month * req.months
    return {"quote": q, "total_t": total_t, "total_inr": round(total_t * q["price_per_t"], 2)}


@app.post("/customers/{customer_id}/orders")
def place_order(customer_id: str, req: OrderRequest):
    """A signed forward order: priced, saved, and folded into the next
    procurement and delivery plans."""
    db = store.get_firestore_client()
    customer = _customer_or_404(db, customer_id)
    start = date(req.start_month.year, req.start_month.month, 1)
    q = operations.quote_order(db, (customer["lat"], customer["lon"]), start, req.months)
    order = store.save_order(db, {
        "customer_id": customer_id, "product": "baled paddy straw", "tonnes_by_month": _order_months(req),
        "site": {"lat": customer["lat"], "lon": customer["lon"], "district": customer.get("district")},
        "quote": q, "total_t": req.tonnes_per_month * req.months,
    })
    operations.run_procurement(db)
    deliveries = operations.run_deliveries(db)
    return {"order": order, "delivery_plan": deliveries,
            "deliveries": store.get_deliveries(db, order["id"])}


@app.get("/customers/{customer_id}/orders")
def customer_orders(customer_id: str):
    db = store.get_firestore_client()
    _customer_or_404(db, customer_id)
    orders = store.get_orders(db, customer_id)
    plan = store.get_plan(db, "deliveries_current") or {}
    out = []
    for o in orders:
        short = [s for s in plan.get("shortfall", []) if s["order_id"] == o["id"]]
        out.append({**o, "deliveries": store.get_deliveries(db, o["id"]), "shortfall": short})
    return {"customer_id": customer_id, "orders": out}
