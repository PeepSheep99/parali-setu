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
import logging
import os
import time
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal

import asyncio
import json

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import agent
import costs
import firestore_store as store
import live
import operations
import pickups
import ratelimit
from extraction import read_no_burn_proof, read_stubble_quality
from forecast.demand_segments import EX_SITU_SOURCE, EX_SITU_TOTAL_T, SEGMENTS, segment_totals
from geo import demo_farm_location, district_from_text
from gemini_client import get_gemini_client
from impact import impact_for_kg, punjab_scenario
from scheduler import STRAW_T_PER_ACRE
from speech import synthesize_speech, transcribe_audio
from trust import score_no_burn_submission

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
for noisy in ("httpx", "httpcore", "google_genai", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
log = logging.getLogger("parali.api")
app = FastAPI(title="Parali Setu API")

# Only our own Firebase Hosting site (and local development) may call the
# API from a browser. Override with a comma-separated ALLOWED_ORIGINS.
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get(
        "ALLOWED_ORIGINS",
        "https://parali-setu-aibuildercup-2026.web.app,https://parali-setu-aibuildercup-2026.firebaseapp.com,http://localhost:8000,http://127.0.0.1:8000",
    ).split(",")
    if o.strip()
]
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["*"])
app.middleware("http")(ratelimit.limit_middleware)   # caps on the endpoints that call Gemini or speech

Language = Literal["Hindi", "Punjabi", "English"]
MAX_QUANTITY_KG = 10_000_000.0


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------



def _today() -> date:
    return pickups.now_ist().date()


def _spoken(text: str | None, language: str, say: str | None = None) -> dict | None:
    if not text:
        return None
    audio = synthesize_speech(say or text, language)
    return {"text": text, "audio_base64": base64.b64encode(audio).decode("ascii") if audio else None}


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
    for b in store.get_bookings(db, ("booked", "verified", "collected", "paid")):
        if b["status"] in ("booked", "verified"):
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

class FarmerRequest(BaseModel):
    farmer_id: str = Field(min_length=1, max_length=64)


def _accept(db, booking: dict, accepted_by: str) -> dict:
    try:
        return pickups.accept_booking(db, booking, accepted_by)
    except pickups.BookingError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


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
    return {"booking": pickups.booking_view(db, updated)}


@app.get("/farmers/{farmer_id}/bookings")
def farmer_bookings(farmer_id: str):
    """Everything the farmer's status cards need. Offers nobody accepted in time lapse first."""
    db = store.get_firestore_client()
    pickups.expire_stale_offers(db)
    depots = {d["id"]: d for d in store.get_depots(db)}
    bookings = [pickups.booking_view(db, b, depots) for b in store.get_bookings_for_farmer(db, farmer_id)
                if b.get("status") not in ("cancelled",)]
    return {"farmer_id": farmer_id, "bookings": bookings}


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
# Farmer: the talking agent (Gemini function calling, guardrails in code)
# ---------------------------------------------------------------------------

AUDIO_TYPES = {"audio/wav", "audio/x-wav", "audio/wave", "audio/webm", "audio/ogg", "audio/mpeg", "audio/mp3"}


class LocateRequest(BaseModel):
    farmer_id: str = Field(..., min_length=1, max_length=64)
    conversation_id: str | None = Field(None, max_length=64)
    village_or_district: str | None = Field(None, max_length=120)


@app.post("/demo/locate")
def demo_locate(req: LocateRequest):
    """"Detect my location" for the prototype. It deliberately does not use the
    device: a judge opening the demo from outside Punjab would get a farm that
    no depot reaches. It returns a demo farm near the named district (Sangrur
    when none is known) and, given a conversation, records it as the farm."""
    db = store.get_firestore_client()
    district = district_from_text(req.village_or_district)
    conv = store.get_conversation(db, req.conversation_id) if req.conversation_id else None
    if conv is not None and conv["farmer_id"] != req.farmer_id:
        raise HTTPException(403, "That conversation belongs to someone else")
    if district is None and conv is not None:
        district = pickups.listing_district(conv.get("fields") or {})
    lat, lon, name = demo_farm_location(district, req.farmer_id)
    if conv is not None:
        fields = conv.setdefault("fields", {})
        fields.update({"lat": lat, "lon": lon, "location_source": "demo"})
        fields.setdefault("village_or_district", req.village_or_district or name)
        store.save_conversation(db, conv)
    return {"lat": lat, "lon": lon, "district": name, "source": "demo",
            "label": f"Demo farm near {name}, Punjab (the prototype does not use your real location)"}


@app.post("/agent/turn")
async def agent_turn(
    farmer_id: str = Form(..., min_length=1, max_length=64),
    language: Language | None = Form(None),     # only a hint: the reply follows what the farmer says
    conversation_id: str | None = Form(None, max_length=64),
    text: str | None = Form(None, max_length=600),
    audio: UploadFile | None = File(None),
    photo: UploadFile | None = File(None),
    speak: bool = Form(True),
):
    """One turn of the farmer's conversation: voice or text in, the agent's
    spoken reply and any cards (price, offer, booking) out. Every number on a
    card comes from a tool; the reply is checked so it says no others."""
    db = store.get_firestore_client()
    client = get_gemini_client()
    audio_bytes = await audio.read() if audio is not None else None
    if audio_bytes is not None:
        mime = (audio.content_type or "audio/wav").split(";")[0]
        if mime not in AUDIO_TYPES or len(audio_bytes) > 5_000_000:
            raise HTTPException(status_code=422, detail="Send a short recording (WAV, WebM, OGG or MP3)")
    elif not (text and text.strip()):
        raise HTTPException(status_code=422, detail="Say or type something")

    def stt(data: bytes) -> str:
        fmt, rate = ("linear16", 16000) if "wav" in (audio.content_type or "") else ("webm_opus", 48000)
        words = transcribe_audio(data, language or "Punjabi", sample_rate_hertz=rate, audio_format=fmt)
        if words is None:
            raise HTTPException(status_code=422, detail="Could not hear that clearly -- please try again or type it")
        return words

    # The model, speech and Firestore calls block, so they run in worker threads:
    # one farmer's slow turn must not hold up everyone else's requests.
    started = time.perf_counter()
    words, english = await run_in_threadpool(
        agent.understand, client, language, (text or "").strip() or None, audio_bytes,
        (audio.content_type or "").split(";")[0] if audio else None, stt)
    heard_at = time.perf_counter()
    quality = None
    if photo is not None:
        read = await run_in_threadpool(read_stubble_quality, client, await photo.read(),
                                       mime_type=photo.content_type or "image/jpeg")
        if read and read.get("quality_grade"):
            quality = {"grade": read["quality_grade"], "note": read.get("note")}
    try:
        result = await run_in_threadpool(agent.take_turn, db, client, farmer_id, language, words, english,
                                         conversation_id, quality)
    except PermissionError:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except OverflowError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    turn_done = time.perf_counter()
    spoken_text = result.pop("speak_text", None) or result["reply"]
    if speak:
        result["reply"] = await run_in_threadpool(_spoken, result["reply"], result["language"], spoken_text)
    else:
        result["reply"] = {"text": result["reply"], "audio_base64": None, "speak_text": spoken_text}
    if quality:
        result["quality"] = quality
    log.info("agent turn: understand %.1fs, agent %.1fs, speech %.1fs", heard_at - started, turn_done - heard_at,
             time.perf_counter() - turn_done)
    return result


@app.websocket("/agent/live")
async def agent_live(ws: WebSocket):
    """Live mode: the phone streams 16 kHz PCM; captions come back as the
    farmer speaks; the final transcript is one guarded agent turn.

    Protocol: client sends {"farmer_id", "language", "conversation_id"?} as
    text, then binary audio frames, then {"type": "end"}. Server sends
    {"type": "caption", "text", "final"} events, then {"type": "reply", ...}
    (the same body as /agent/turn) or {"type": "error", "detail"}, and closes."""
    origin = ws.headers.get("origin")
    if origin and origin not in ALLOWED_ORIGINS:
        await ws.close(code=1008)
        return
    forwarded = ws.headers.get("x-forwarded-for", "")
    if ratelimit.check(forwarded.split(",")[0].strip() if forwarded else (ws.client.host if ws.client else "unknown")):
        await ws.close(code=1013)          # try again later
        return
    await ws.accept()
    try:
        start = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=10))
        farmer_id = str(start.get("farmer_id", ""))[:64]
        language = start.get("language") if start.get("language") in live.LANGUAGE_CODES else None   # a hint only
        conversation_id = (str(start["conversation_id"])[:64] if start.get("conversation_id") else None)
        if not farmer_id:
            raise ValueError("farmer_id is required")
    except (asyncio.TimeoutError, ValueError, json.JSONDecodeError, WebSocketDisconnect):
        await ws.close(code=1008)
        return

    final_parts: list[str] = []
    try:
        async with live.open_session(language) as session:
            async def pump_audio():
                received = 0
                while True:
                    msg = await ws.receive()
                    if msg.get("type") == "websocket.disconnect":
                        raise WebSocketDisconnect()
                    if msg.get("bytes"):
                        received += len(msg["bytes"])
                        if received > live.MAX_AUDIO_SECONDS * live.SAMPLE_RATE * 2:
                            break
                        await session.send_realtime_input(audio=live.audio_blob(msg["bytes"]))
                    elif msg.get("text") and json.loads(msg["text"]).get("type") == "end":
                        break
                await session.send_realtime_input(audio_stream_end=True)

            async def pump_captions():
                async for message in session.receive():
                    for event in live.caption_events(message):
                        if event["type"] == "caption":
                            if event["final"]:
                                final_parts.append(event["text"])
                            await ws.send_json(event)
                        elif event["type"] == "done":
                            return

            sender = asyncio.create_task(pump_audio())
            await asyncio.wait_for(pump_captions(), timeout=live.MAX_SESSION_SECONDS)
            sender.cancel()
    except WebSocketDisconnect:
        return
    except Exception as exc:   # the live service failed: tell the phone so it can fall back to recording
        await ws.send_json({"type": "error", "detail": f"Live listening is unavailable right now ({type(exc).__name__}). Please tap to record instead."})
        await ws.close()
        return

    words = " ".join(final_parts).strip()
    if not words:
        await ws.send_json({"type": "error", "detail": "Could not hear that clearly -- please try again or type it"})
        await ws.close()
        return
    db = store.get_firestore_client()
    client = get_gemini_client()
    try:
        result = await run_in_threadpool(agent.take_turn, db, client, farmer_id, language, words, None, conversation_id)
        spoken_text = result.pop("speak_text", None) or result["reply"]
        result["reply"] = await run_in_threadpool(_spoken, result["reply"], result["language"], spoken_text)
        await ws.send_json({"type": "reply", **result})
    except PermissionError:
        await ws.send_json({"type": "error", "detail": "Conversation not found"})
    except OverflowError as exc:
        await ws.send_json({"type": "error", "detail": str(exc)})
    await ws.close()


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=700)
    language: Language


@app.post("/speech")
def speech(req: SpeechRequest):
    """The reply read aloud. The phone shows the agent's text first and fetches
    this alongside, so the farmer is never waiting on speech to see an answer."""
    audio = synthesize_speech(req.text, req.language)
    if not audio:
        raise HTTPException(status_code=503, detail="Speech is unavailable right now")
    return {"audio_base64": base64.b64encode(audio).decode("ascii")}


@app.get("/agent/conversations/{conversation_id}")
def agent_conversation(conversation_id: str):
    """A conversation as ops sees it: each turn in the farmer's words and in
    English, the structured listing, and what the guardrails did."""
    db = store.get_firestore_client()
    conv = store.get_conversation(db, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


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
        "needs_attention": [b["id"] for b in bookings if b.get("status") in ("booked", "verified") and b.get("schedule_note")],
        "verify_queue": len([b for b in bookings if b.get("status") == "booked"]),
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
        "farmer_name": listing.get("farmer_name"),
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
                 for b in bookings.values() if b.get("status") in ("booked", "verified") and b.get("schedule_note")]
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
    """Adds a crew (ours or an on-call) to a depot and re-plans it."""
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


class VerifyRequest(BaseModel):
    checks: dict[str, bool] | None = None
    notes: str | None = Field(default=None, max_length=500)


@app.post("/ops/bookings/{booking_id}/verify")
def verify_booking(booking_id: str, req: VerifyRequest):
    """Our team called the farmer and confirmed phone, location, acres and
    price (simulated call in the prototype): the pickup can now be dispatched."""
    db = store.get_firestore_client()
    booking = store.get_booking(db, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    try:
        updated = pickups.verify_booking(db, booking, by="ops", checks=req.checks, notes=req.notes)
    except pickups.BookingError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"booking": pickups.booking_view(db, updated)}


class FlagRequest(BaseModel):
    notes: str = Field(min_length=3, max_length=500)


@app.post("/ops/bookings/{booking_id}/needs-change")
def flag_booking(booking_id: str, req: FlagRequest):
    db = store.get_firestore_client()
    booking = store.get_booking(db, booking_id)
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found")
    try:
        updated = pickups.flag_booking(db, booking, by="ops", notes=req.notes)
    except pickups.BookingError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"booking": pickups.booking_view(db, updated)}


@app.post("/ops/verify-all")
def verify_all():
    """Demo shortcut: confirm every booked pickup at once."""
    db = store.get_firestore_client()
    done = [pickups.verify_booking(db, b, by="ops (demo, all at once)")["id"] for b in store.get_bookings(db, ("booked",))]
    return {"verified": len(done)}


@app.get("/ops/dispatch")
def dispatch(day: date | None = None):
    """Who goes out on `day` (default tomorrow): each depot's crews with their
    stops in order, which crews are on-call hires and what they cost, which
    vehicles stay idle; the calls still to make; whether our crews cover the
    forecast for the next two weeks; and the few things that need a person."""
    db = store.get_firestore_client()
    today = _today()
    day = day or today + timedelta(days=1)
    depots_out, queue, exceptions = [], [], []
    premium = costs.PARTNER_COLLECTION_PER_T_INR - costs.OWN_COLLECTION_PER_T_INR
    for depot in store.get_depots(db):
        crews = store.get_crews_for_depot(db, depot["id"])
        bookings = {b["id"]: b for b in store.get_bookings_for_depot(db, depot["id"])}
        listings = {lid: doc for lid in {b["listing_id"] for b in bookings.values()} if (doc := store.get_listing(db, lid))}
        slots = store.get_slots_for_depot(db, depot["id"])
        by_crew: dict[str, list[dict]] = {}
        for slot in slots:
            booking = bookings.get(slot["booking_id"])
            if slot["date"] != day.isoformat() or booking is None or booking.get("status") not in ("offered", "booked", "verified"):
                continue
            by_crew.setdefault(slot["crew_id"], []).append({
                **_farm(listings.get(booking["listing_id"], {}), booking), "acres": slot["acres"],
                "window": pickups.window_label(slot), "window_start_min": slot["window_start_min"],
                "window_end_min": slot["window_end_min"], "planned_start_min": slot.get("planned_start_min"),
                "planned_end_min": slot.get("planned_end_min"),
                "farmer_name": listings.get(booking["listing_id"], {}).get("farmer_name"),
                "sequence": slot["sequence"], "booking_code": pickups.booking_code(booking["id"]),
                "dispatch": {"verified": "ready", "booked": "call first", "offered": "awaiting farmer"}[booking["status"]]})
        rows = []
        for crew in crews:
            stops = sorted(by_crew.get(crew["id"], []), key=lambda s: s["sequence"])
            if crew.get("partner") and not stops:
                continue          # an on-call crew we don't need is not hired
            acres = round(sum(s["acres"] for s in stops), 1)
            rows.append({"crew_id": crew["id"], "name": crew["name"], "on_call": bool(crew.get("partner")),
                         "acres": acres, "acres_per_day": crew.get("acres_per_day", 20.0), "stops": stops,
                         "start_min": min((s["window_start_min"] for s in stops), default=None),
                         "hire_cost_inr": round(acres * STRAW_T_PER_ACRE * premium) if crew.get("partner") else 0})
        own = [r for r in rows if not r["on_call"]]
        depots_out.append({"depot_id": depot["id"], "name": depot["name"], "crews": rows,
                           "own_crews_out": len([r for r in own if r["stops"]]), "own_crews_idle": len([r for r in own if not r["stops"]]),
                           "oncall_hired": len([r for r in rows if r["on_call"]]),
                           "hire_cost_inr": sum(r["hire_cost_inr"] for r in rows),
                           "farms": sum(len(r["stops"]) for r in rows), "acres": round(sum(r["acres"] for r in rows), 1)})
        first_slot = {}
        for slot in slots:
            key = (slot["date"], slot["window_start_min"])
            if slot["booking_id"] not in first_slot or key < first_slot[slot["booking_id"]]:
                first_slot[slot["booking_id"]] = key
        for b in bookings.values():
            farm = _farm(listings.get(b["listing_id"], {}), b)
            if b.get("status") == "booked":
                when = first_slot.get(b["id"])
                queue.append({**farm, "booking_code": pickups.booking_code(b["id"]), "depot_name": depot["name"],
                              "pickup_date": when[0] if when else None, "pickup_start_min": when[1] if when else None,
                              "verification": b.get("verification") or {"status": "pending"},
                              "farmer_name": listings.get(b["listing_id"], {}).get("farmer_name")})
            elif b.get("status") == "unschedulable":
                exceptions.append({"kind": "no_slot", "depot_name": depot["name"], **farm, "reason": b.get("status_reason")})
            if b.get("status") in ("booked", "verified") and b.get("schedule_note"):
                exceptions.append({"kind": "promise_at_risk", "depot_name": depot["name"], **farm, "reason": b["schedule_note"]})
    queue.sort(key=lambda q: (q["pickup_date"] or "9999", q["pickup_start_min"] or 0))
    procurement = store.get_plan(db, "procurement_current") or {}
    deliveries = store.get_plan(db, "deliveries_current") or {}
    if procurement.get("shortfall_t"):
        exceptions.append({"kind": "orders_short_of_straw", "tonnes": procurement["shortfall_t"]})
    if deliveries.get("shortfall_t"):
        exceptions.append({"kind": "deliveries_short", "tonnes": deliveries["shortfall_t"],
                           "orders": sorted({s["order_id"] for s in deliveries.get("shortfall", [])})})
    return {"date": day.isoformat(), "today": today.isoformat(), "depots": depots_out, "verify_queue": queue,
            "readiness": operations.readiness(db, today, 21), "exceptions": exceptions}


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


@lru_cache(maxsize=1)
def _fire_seasons() -> list[dict]:
    """Paddy-season (Sep-Dec) satellite fire detections per year for Punjab
    and Haryana, from the NASA FIRMS history in forecast/data."""
    import csv
    path = Path(__file__).resolve().parent / "forecast" / "data" / "fires_daily.csv"
    seasons: dict[int, dict] = {}
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            year = int(row["date"][:4])
            season = seasons.setdefault(year, {"year": year, "Punjab": 0, "Haryana": 0, "last_date": row["date"]})
            season[row["state"]] = season.get(row["state"], 0) + int(row["fire_pixels"])
            season["last_date"] = max(season["last_date"], row["date"])
    return [{**s, "total": s["Punjab"] + s["Haryana"], "partial": s["last_date"] < f"{s['year']}-12-01"}
            for s in sorted(seasons.values(), key=lambda s: s["year"]) if s["year"] >= 2002]


@app.get("/fires/history")
def fire_history():
    """25 paddy seasons of satellite fire detections (NASA FIRMS via Earth
    Engine), counted per day within official district boundaries."""
    return {"source": "NASA FIRMS via Google Earth Engine; FAO GAUL 2025 district boundaries; Sep-Dec each year",
            "seasons": _fire_seasons()}


@app.get("/costs")
def cost_model():
    """The cost model behind posted prices and customer quotes, each figure
    marked as sourced or as our working assumption."""
    import costs
    return {"items": [
        {"key": "farm_gate_base", "label": "Base farm-gate price", "value": costs.FARM_GATE_BASE_PER_KG, "unit": "Rs/kg",
         "kind": "decision", "note": f"posted prices stay within Rs {costs.FARM_GATE_MIN_PER_KG}-{costs.FARM_GATE_MAX_PER_KG}/kg"},
        {"key": "shadow_share", "label": "Share of shadow price passed to farmers", "value": costs.SHADOW_PRICE_SHARE,
         "unit": "", "kind": "decision", "note": "how much of a scarce district's marginal value goes into its price"},
        {"key": "hired_baling", "label": "What farmers pay hired balers", "value": list(costs.HIRED_BALING_PER_T_INR),
         "unit": "Rs/t", "kind": "sourced", "note": "Rs 2,500-4,000 per acre (Tribune) at 1.75 t/acre"},
        {"key": "own_collection", "label": "Our crews' collection cost", "value": costs.OWN_COLLECTION_PER_T_INR,
         "unit": "Rs/t", "kind": "assumption", "note": "below the hired rate because routes are planned densely"},
        {"key": "partner_collection", "label": "On-call crew cost", "value": costs.PARTNER_COLLECTION_PER_T_INR,
         "unit": "Rs/t", "kind": "assumption", "note": "low end of the hired rate"},
        {"key": "haul", "label": "Truck freight", "value": costs.HAUL_PER_T_KM_INR, "unit": "Rs/t-km", "kind": "assumption",
         "note": "road distance = straight line x 1.3"},
        {"key": "storage", "label": "Storage", "value": costs.STORAGE_PER_T_MONTH_INR, "unit": "Rs/t/month",
         "kind": "assumption", "note": "covered bale stack with fire watch"},
        {"key": "benchmark", "label": "In-season delivered price at plants", "value": costs.IN_SEASON_DELIVERED_PER_T_INR,
         "unit": "Rs/t", "kind": "sourced", "note": "about Rs 169 per quintal (Tribune)"},
        {"key": "margin", "label": "Our margin on quotes", "value": costs.DEFAULT_MARGIN_PCT, "unit": "%", "kind": "decision",
         "note": "added to delivered cost"},
    ]}


OPERATING_DISTRICTS = ("Sangrur", "Patiala", "Bathinda", "Ludhiana", "Moga", "Karnal", "Kaithal", "Kurukshetra")


def _season_start(year: int) -> date:
    """The first Monday on or after 1 September: week 0 of a paddy season."""
    first = date(year, 9, 1)
    return first + timedelta(days=(7 - first.weekday()) % 7)


@lru_cache(maxsize=1)
def _weekly_fires() -> dict[tuple[int, str], dict[int, int]]:
    """(season, district) -> {week of season: fire detections}, from the
    NASA FIRMS history in forecast/data (Sep-Dec)."""
    import csv
    path = Path(__file__).resolve().parent / "forecast" / "data" / "fires_daily.csv"
    out: dict[tuple[int, str], dict[int, int]] = {}
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            day = date.fromisoformat(row["date"])
            week = (day - _season_start(day.year)).days // 7
            if 0 <= week < 18:
                bucket = out.setdefault((day.year, row["district"]), {})
                bucket[week] = bucket.get(week, 0) + int(row["fire_pixels"])
    return out


@app.get("/forecast/seasons")
def forecast_seasons(district: str | None = None, back: int = Query(3, ge=1, le=10)):
    """Weekly fire detections for this season and the last `back` seasons,
    aligned by week of season, for one district or our eight; plus the
    TimesFM forecast for the rest of this season on the same weeks."""
    db = store.get_firestore_client()
    year = _today().year
    names = [district] if district else list(OPERATING_DISTRICTS)
    weekly = _weekly_fires()
    seasons = []
    for y in range(year - back, year + 1):
        weeks: dict[int, int] = {}
        for name in names:
            for w, n in weekly.get((y, name), {}).items():
                weeks[w] = weeks.get(w, 0) + n
        seasons.append({"year": y, "weeks": [{"week": w, "fires": weeks[w]} for w in sorted(weeks)]})
    live = store.get_forecast(db, f"supply_live_{year}") or {}
    start = _season_start(year)
    fc: dict[int, dict] = {}
    for name in names:
        for row in (live.get("districts") or {}).get(name, []):
            w = (date.fromisoformat(row["week"]) - start).days // 7
            cell = fc.setdefault(w, {"week": w, "week_start": row["week"], "fires": 0.0, "low": 0.0, "high": 0.0})
            cell["fires"] += row["fire_pixels"]; cell["low"] += row["low"]; cell["high"] += row["high"]
    per_district = {name: [{"week": (date.fromisoformat(r["week"]) - start).days // 7, "fires": r["fire_pixels"]}
                           for r in (live.get("districts") or {}).get(name, [])] for name in OPERATING_DISTRICTS}
    return {"districts": names, "season_start": start.isoformat(), "today_week": (_today() - start).days // 7,
            "seasons": seasons, "forecast": [fc[w] for w in sorted(fc)], "forecast_by_district": per_district,
            "model": live.get("model"), "context_end": live.get("context_end")}


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
    allow_partial: bool = False     # accept a smaller delivery plan when we cannot fill the whole order


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
    can = operations.committable(db, (customer["lat"], customer["lon"]), _order_months(req), q["price_per_t"])
    return {"quote": q, "total_t": total_t, "total_inr": round(total_t * q["price_per_t"], 2), "commit": can}


@app.post("/customers/{customer_id}/orders")
def place_order(customer_id: str, req: OrderRequest):
    """A signed forward order: priced, saved, and folded into the next
    procurement and delivery plans."""
    db = store.get_firestore_client()
    customer = _customer_or_404(db, customer_id)
    start = date(req.start_month.year, req.start_month.month, 1)
    q = operations.quote_order(db, (customer["lat"], customer["lon"]), start, req.months)
    can = operations.committable(db, (customer["lat"], customer["lon"]), _order_months(req), q["price_per_t"])
    if not can["can_fill"] and not req.allow_partial:
        raise HTTPException(status_code=409, detail={
            "message": "We cannot fill this whole order. Order what we can commit, or accept a partial plan.",
            "commit": can})
    order = store.save_order(db, {
        "customer_id": customer_id, "product": "baled paddy straw", "tonnes_by_month": _order_months(req),
        "site": {"lat": customer["lat"], "lon": customer["lon"], "district": customer.get("district")},
        "quote": q, "total_t": req.tonnes_per_month * req.months,
    })
    order = store.save_order(db, {**order, "order_code": operations.order_code(order["id"])})
    operations.run_procurement(db)
    deliveries = operations.run_deliveries(db)
    return {"order": order, "delivery_plan": deliveries,
            "deliveries": store.get_deliveries(db, order["id"])}


@app.post("/customers/{customer_id}/orders/{order_id}/cancel")
def cancel_order(customer_id: str, order_id: str):
    """Cancels a forward order and re-plans so its stock goes to the next in the queue."""
    db = store.get_firestore_client()
    _customer_or_404(db, customer_id)
    order = next((o for o in store.get_orders(db, customer_id) if o["id"] == order_id), None)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("status") == "cancelled":
        raise HTTPException(status_code=409, detail="This order is already cancelled")
    order = store.update_order_status(db, order_id, "cancelled")
    operations.run_procurement(db)
    return {"order": order, "delivery_plan": operations.run_deliveries(db)}


@app.get("/customers/{customer_id}/orders")
def customer_orders(customer_id: str):
    db = store.get_firestore_client()
    _customer_or_404(db, customer_id)
    orders = store.get_orders(db, customer_id)
    plan = store.get_plan(db, "deliveries_current") or {}
    out = []
    for o in orders:
        short = [s for s in plan.get("shortfall", []) if s["order_id"] == o["id"]]
        out.append({**o, "order_code": o.get("order_code") or operations.order_code(o["id"]),
                    "deliveries": store.get_deliveries(db, o["id"]), "shortfall": short})
    return {"customer_id": customer_id, "orders": out}
