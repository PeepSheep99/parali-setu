"""The farmer's talking agent: Gemini on Vertex AI with function calling.

The farmer talks freely, in Punjabi, Hindi or English. Gemini understands,
asks follow-up and cross-checking questions, and acts only through the tools
below. Every number the farmer hears comes from a tool -- the posted price
(procurement LP), the pickup slot (routing), the payout (price x kg) -- never
from the model. The guardrails are enforced in code, not only asked for in
the prompt:

- Numbers: each number in a reply must appear in a tool result or in the
  farmer's own words; otherwise the reply is regenerated once, then
  replaced by a deterministic template.
- Booking: confirm_booking runs only after an offer was shown in an earlier
  turn and the farmer's own latest words say yes (checked in code, in their
  language and in English; a question or a "no" is never a yes). Cancelling
  needs the same yes.
- Cross-checks: acres against tonnes, harvest date against sowing date, a
  sowing date already past -- returned as warnings the agent must resolve.
- Scope and size: a fixed reply language, at most MAX_TOOL_STEPS tool calls
  per turn, bounded input length; off-topic requests are declined.

Each turn stores the farmer's words and an English rendering, so ops and
inventory work from one normalised record whatever language was spoken.
"""
from __future__ import annotations

import json
import threading
import time
import os
import logging
import re
from datetime import date

from google import genai
from google.genai import types

import firestore_store as store
import operations
import pickups
from extraction import to_english, understand_audio
from gemini_client import GEMINI_MODEL, PROJECT_ID, REQUEST_HTTP_OPTIONS
from geo import DISTRICT_COORDS, district_from_text, demo_farm_location
from impact import impact_for_kg
from phrases import window_words
from scheduler import STRAW_T_PER_ACRE

MAX_TOOL_STEPS = 5
MAX_TURNS = 40
ACRE_WEIGHT_TOLERANCE = 0.4   # stated kg may differ from acres x 1.75 t by this share before we ask

SYSTEM_PROMPT = """You are Parali Setu's assistant for paddy farmers in Punjab and Haryana.
Parali Setu buys paddy straw (parali): our crew clears the field for free before
the farmer sows wheat, and pays today's posted price the same day it collects.

Rules you must follow:
1. Reply only in {language}. Use one to three short sentences and the plain words a
   farmer uses. Be warm and respectful. No lists, no markdown.
2. Never state a price, weight, area, date, time, money amount or pickup slot unless
   it came from a tool result or the farmer said it. Never estimate or calculate.
   Repeat numbers exactly as the tools give them.
3. Record what the farmer tells you with update_listing, using only what they said.
   "Killa"/"kille" means acre. Never convert acres to weight yourself. If the farmer
   corrects or withdraws a detail, pass it in clear_fields.
4. If update_listing returns warnings, ask one short question that resolves them.
5. If details are missing, ask for all of them together in one short question. Besides the
   straw details we always need the farmer's name and mobile number (and a village or district).
6. When nothing is missing, call find_pickup_slot. Then tell the farmer the price per
   kg, what they will be paid, and the pickup time, and ask if they agree. Say the
   pickup time using pickup_window_spoken exactly as given, never the raw date. Also read back
   the farmer's name and village from the offer's farm details and ask if they are right.
7. Call confirm_booking only after the farmer clearly says yes to that offer.
8. Talk only about selling paddy straw, pickup, payment, and not burning. Politely
   decline anything else (politics, loans, medicine, other businesses) in one sentence
   and bring the talk back to their straw.
9. Never promise anything a tool did not return: no subsidies, no other prices.
   When the farmer asks how payment works, how the straw is weighed, what happens if the
   crew does not come, who we are or how the price is set, call get_service_terms and answer
   that question first, in plain words, before going back to booking. Ask them to book at
   most once in a reply.
10. Parali Setu is a private company, not the government and not a government scheme. Never
    call the price "government" or "official". Payments in this prototype are simulated: never
    ask the farmer to trust us, never say "without worry", and never guarantee anything.

Today's date is {today}. What we already know in this conversation:
{facts}"""

LISTING_KEYS_FOR_SCHEMA = ("acres", "quantity_kg", "crop_type", "village_or_district", "ready_by", "sowing_deadline",
                           "contact", "farmer_name")

TOOLS = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="get_todays_price",
        description="Today's posted farm-gate price for paddy straw in a district, and the reason for it.",
        parameters_json_schema={"type": "object", "properties": {
            "district": {"type": "string", "description": "District name as the farmer said it"}},
            "required": ["district"]},
    ),
    types.FunctionDeclaration(
        name="update_listing",
        description="Record details of the farmer's straw that they stated. Only pass what was said.",
        parameters_json_schema={"type": "object", "properties": {
            "acres": {"type": "number", "description": "Area in acres (killa)"},
            "quantity_kg": {"type": "number", "description": "Weight in kg, only if the farmer stated a weight"},
            "crop_type": {"type": "string", "enum": ["rice_stubble", "wheat_stubble"]},
            "village_or_district": {"type": "string"},
            "ready_by": {"type": "string", "description": "YYYY-MM-DD when the straw is ready"},
            "sowing_deadline": {"type": "string", "description": "YYYY-MM-DD by which the field must be clear"},
            "contact": {"type": "string", "description": "Mobile phone number, only if the farmer gave one"},
            "farmer_name": {"type": "string", "description": "The farmer's own name, only if they said it"},
            "clear_fields": {"type": "array", "items": {"type": "string", "enum": list(LISTING_KEYS_FOR_SCHEMA)},
                             "description": "Details the farmer corrected or withdrew, e.g. a weight they are not sure of"}}},
    ),
    types.FunctionDeclaration(
        name="find_pickup_slot",
        description="When all details are known: price the straw at today's posted price and plan a pickup slot. Returns the offer.",
        parameters_json_schema={"type": "object", "properties": {}},
    ),
    types.FunctionDeclaration(
        name="confirm_booking",
        description="Book the offered pickup. Only after the farmer clearly said yes to the offer.",
        parameters_json_schema={"type": "object", "properties": {
            "farmer_said_yes": {"type": "boolean"}}, "required": ["farmer_said_yes"]},
    ),
    types.FunctionDeclaration(
        name="get_service_terms",
        description="How Parali Setu works: payment, weighing, what happens if our crew does not come, who we are, how the price is set. Call it whenever the farmer asks about any of these.",
        parameters_json_schema={"type": "object", "properties": {}},
    ),
    types.FunctionDeclaration(
        name="my_bookings",
        description="The farmer's pickups and payments so far.",
        parameters_json_schema={"type": "object", "properties": {}},
    ),
    types.FunctionDeclaration(
        name="cancel_booking",
        description="Cancel one of the farmer's pickups. Only after the farmer clearly asked to cancel.",
        parameters_json_schema={"type": "object", "properties": {
            "booking_id": {"type": "string"}, "farmer_said_yes": {"type": "boolean"}},
            "required": ["booking_id", "farmer_said_yes"]},
    ),
])

# Fixed, prototype-honest answers to the questions farmers ask before they book.
# No digits here: the number guardrail only lets through numbers a tool returned.
SERVICE_TERMS = {
    "who_we_are": "Parali Setu is a private company. This is a demo prototype.",
    "price": "One posted price per district per day, set by our planner from how much straw we need and how much we expect. There is no bargaining, and the price you are offered does not change during the day.",
    "payment": "In this prototype payment is a simulated UPI transfer on the day our crew collects. No real money moves.",
    "weighing": "The straw is weighed on a weighbridge at the depot and you are paid for the weighed kilograms. The weight in the offer is an estimate from your area.",
    "if_crew_does_not_come": "If our own crew cannot come, a partner crew is booked before your sowing date, our team is alerted, and you can cancel for free at any time before collection.",
    "field_cleared_free": True,
}

LISTING_KEYS = ("acres", "quantity_kg", "crop_type", "village_or_district", "ready_by", "sowing_deadline", "contact",
                "farmer_name")

# ---- guardrail: numbers ---------------------------------------------------

_INDIC_DIGITS = str.maketrans("०१२३४५६७८९੦੧੨੩੪੫੬੭੮੯", "01234567890123456789")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def numbers_in(text: str) -> set[float]:
    """Every number written in a text, Indian digit grouping and Devanagari
    or Gurmukhi digits included ("17,500", "१७५००" and "17500" are equal)."""
    out = set()
    for raw in _NUMBER.findall((text or "").translate(_INDIC_DIGITS)):
        cleaned = raw.replace(",", "")
        try:
            out.add(round(float(cleaned), 2))
        except ValueError:
            continue
    return out


def numbers_in_values(obj, key: str = "") -> set[float]:
    """Numbers the tools actually returned: every numeric value and every
    number written inside a string value, skipping identifiers (a random id
    like "booking_fc851f2d86" must not license the numbers 851, 2 or 86)."""
    if key == "id" or key.endswith("_id") or key.endswith("_ids"):
        return set()
    if isinstance(obj, bool):
        return set()
    if isinstance(obj, (int, float)):
        return {round(float(obj), 2)}
    if isinstance(obj, str):
        return numbers_in(obj)
    if isinstance(obj, dict):
        out: set[float] = set()
        for k, v in obj.items():
            out |= numbers_in_values(v, str(k))
        return out
    if isinstance(obj, (list, tuple)):
        out = set()
        for v in obj:
            out |= numbers_in_values(v, key)
        return out
    return set()


def unsupported_numbers(reply: str, farmer_texts: list[str], tool_values: list) -> set[float]:
    """Numbers in a reply that neither the farmer said nor a tool returned."""
    allowed: set[float] = set()
    for t in farmer_texts:
        allowed |= numbers_in(t)
    for v in tool_values:
        allowed |= numbers_in_values(v)
    return {n for n in numbers_in(reply) if n not in allowed}


# ---- guardrail: claims we must never make ----------------------------------------

# Parali Setu is a private prototype with simulated payments. A reply must not
# pass the rate off as government's, offer subsidies or ask to be trusted. A term
# the farmer used themselves is let through so the agent can answer "is this a
# government scheme?" (it may say no).
_FORBIDDEN_CLAIMS = {
    "government": re.compile(r"(government|govt|official rate|सरकारी|सरकार|ਸਰਕਾਰੀ|ਸਰਕਾਰ)", re.IGNORECASE),
    "scheme": re.compile(r"(scheme|subsid\w*|योजना|सब्सिडी|ਯੋਜਨਾ|ਸਬਸਿਡੀ)", re.IGNORECASE),
    "trust": re.compile(r"(\btrust\b|without (any )?(worry|doubt)|भरोसा|बिना चिंता|चिंता मत|ਭਰੋਸਾ|ਬਿਨਾਂ ਚਿੰਤਾ|ਚਿੰਤਾ ਨਾ)",
                        re.IGNORECASE),
}


def forbidden_claims(reply: str, farmer_texts: list[str]) -> list[str]:
    said = " ".join(farmer_texts)
    return [name for name, pattern in _FORBIDDEN_CLAIMS.items() if pattern.search(reply) and not pattern.search(said)]


# ---- guardrail: an explicit yes ------------------------------------------------

# Latin-script words use \b; for Devanagari and Gurmukhi, whose vowel signs
# break \b, short words are matched only when standing alone.
_YES_WORDS = re.compile(
    r"(\b(yes|ok|okay|sure|go ahead|book it|confirm\w*|agree\w*|haan?|hanji|theek|thik|kar do|kar de|kar dijiye)\b"
    r"|हाँ|हां|ठीक|कर दो|कर दीजिए|बुक कर|ਹਾਂ|ਠੀਕ|ਕਰ ਦਿਓ|ਕਰ ਦਿਉ|ਬੁੱਕ ਕਰ)",
    re.IGNORECASE)
_NO_WORDS = re.compile(r"(\b(no|not|don'?t|nahi|nahin|na)\b|नहीं|(?<!\S)मत(?!\S)|ਨਹੀਂ|(?<!\S)ਨਾ(?!\S))", re.IGNORECASE)


def farmer_affirmed(words: str, english: str | None) -> bool:
    """True only if the farmer's own latest words say yes: an affirmative word
    in their language or the English rendering, no negation, not a question.
    The model's claim that the farmer agreed is never enough on its own."""
    texts = [t for t in (words, english) if t]
    if any(t.strip().endswith("?") for t in texts):
        return False
    if any(_NO_WORDS.search(t) for t in texts):
        return False
    return any(_YES_WORDS.search(t) for t in texts)


# ---- listing checks --------------------------------------------------------

def listing_warnings(fields: dict, stated: set[str], today: date) -> list[dict]:
    """Things to ask the farmer about before booking, decided in code."""
    warnings = []
    if {"acres", "quantity_kg"} <= stated and fields.get("acres") and fields.get("quantity_kg"):
        expected = fields["acres"] * STRAW_T_PER_ACRE * 1000
        if abs(fields["quantity_kg"] - expected) > ACRE_WEIGHT_TOLERANCE * expected:
            warnings.append({"code": "acres_weight_mismatch", "acres": fields["acres"],
                             "stated_kg": fields["quantity_kg"], "usual_kg_for_that_area": round(expected)})
    sowing, ready = fields.get("sowing_deadline"), fields.get("ready_by")
    if sowing and sowing < today.isoformat():
        warnings.append({"code": "sowing_date_passed", "sowing_deadline": sowing})
    if sowing and ready and ready > sowing:
        warnings.append({"code": "ready_after_sowing", "ready_by": ready, "sowing_deadline": sowing})
    if sowing and sowing >= today.isoformat() and (date.fromisoformat(sowing) - today).days <= 2:
        warnings.append({"code": "sowing_very_soon", "sowing_deadline": sowing})
    if fields.get("village_or_district") and pickups.listing_district(fields) is None:
        warnings.append({"code": "place_not_recognised", "village_or_district": fields["village_or_district"],
                         "served_districts": sorted(DISTRICT_COORDS)})
    return warnings


def _valid_date(value) -> str | None:
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


# ---- tools ------------------------------------------------------------------

class Turn:
    """One farmer turn: the conversation state, the tool results so far and
    the cards the app will show."""

    def __init__(self, db, conversation: dict, words: str = "", english: str | None = None):
        self.db, self.conv = db, conversation
        self.words, self.english = words, english
        self.tool_results: list[dict] = []
        self.cards: list[dict] = []
        self.index = len([t for t in conversation.get("turns", []) if t["role"] == "user"])

    def run_tool(self, name: str, args: dict) -> dict:
        handler = getattr(self, f"tool_{name}", None)
        result = handler(**(args or {})) if handler else {"error": "unknown_tool"}
        self.tool_results.append(result)
        self.conv.setdefault("facts", {})[name] = result
        return result

    def tool_get_todays_price(self, district: str = "") -> dict:
        name = district_from_text(district)
        if name is None:
            return {"error": "district_not_served", "district": district}
        row = store.get_posted_price(self.db, pickups.now_ist().date().isoformat(), name)
        if row is None:
            operations.run_procurement(self.db)
            row = store.get_posted_price(self.db, pickups.now_ist().date().isoformat(), name)
        result = {"district": name, "price_per_kg": row["price_per_kg"], "reason": row["reason"],
                  "field_cleared_free": True, "paid_same_day": True}
        self.cards.append({"type": "price", **result})
        return result

    def tool_update_listing(self, **kwargs) -> dict:
        fields = dict(self.conv.get("fields") or {})
        stated = set(self.conv.get("stated") or [])
        for key in kwargs.get("clear_fields") or []:
            if key in LISTING_KEYS:
                fields.pop(key, None)
                stated.discard(key)
        if "quantity_kg" not in stated and "acres" in stated:
            fields.pop("quantity_kg", None)
        rejected = []
        for key in LISTING_KEYS:
            value = kwargs.get(key)
            if value in (None, ""):
                continue
            if key in ("ready_by", "sowing_deadline"):
                value = _valid_date(value)
                if value is None:
                    continue
            if key == "contact":
                value = pickups.normalise_phone(value)
                if value is None:
                    rejected.append("contact")
                    continue
            if key in ("acres", "quantity_kg"):
                value = float(value)
                if not 0 < value <= (1000 if key == "acres" else 10_000_000):
                    continue
            fields[key] = value
            stated.add(key)
        if "acres" in stated and "quantity_kg" not in stated:
            fields.pop("quantity_kg", None)       # re-derive weight from area in code
        fields = pickups.complete_quantities(fields)
        self.conv["fields"], self.conv["stated"] = fields, sorted(stated)
        result = {"fields": fields, "district": pickups.listing_district(fields),
                  "missing_fields": pickups.agent_missing_fields(fields),
                  "warnings": listing_warnings(fields, stated, pickups.now_ist().date())}
        if rejected:
            result["not_a_valid_mobile_number"] = True
        self.cards.append({"type": "draft", **result})
        return result

    def tool_find_pickup_slot(self) -> dict:
        fields = self.conv.get("fields") or {}
        missing = pickups.agent_missing_fields(fields)
        if missing:
            return {"error": "missing_details", "missing_fields": missing}
        warnings = listing_warnings(fields, set(self.conv.get("stated") or []), pickups.now_ist().date())
        blocking = [w for w in warnings if w["code"] in ("sowing_date_passed", "ready_after_sowing", "acres_weight_mismatch")]
        if blocking:
            return {"error": "resolve_with_farmer_first", "warnings": blocking}
        replaced = pickups.replace_open_offers(self.db, self.conv["farmer_id"])
        if fields.get("lat") is None:     # prototype: "detect my location" is a demo farm, see geo.demo_farm_location
            lat, lon, _ = demo_farm_location(pickups.listing_district(fields), self.conv["farmer_id"])
            fields = {**fields, "lat": lat, "lon": lon, "location_source": "demo"}
            self.conv["fields"] = fields
        district = pickups.listing_district(fields)
        listing = store.save_listing(self.db, self.conv["farmer_id"], {
            **fields, "district": district, "quality_grade": (self.conv.get("quality") or {}).get("grade", "unknown"),
            "conversation_id": self.conv["id"]}, self.conv["language"])
        booking, price = operations.book_listing(self.db, listing)
        if booking is None:
            return {"error": "out_of_area", "district": district, "served_districts": sorted(DISTRICT_COORDS)}
        pickups.plan_depots(self.db, {*replaced, booking["depot_id"]})
        view = pickups.booking_view(self.db, store.get_booking(self.db, booking["id"]))
        self.conv["booking_id"], self.conv["offer_turn"] = view["id"], self.index
        if view["status"] != "offered" or not view["pickup_window"]:
            return {"error": "no_slot", "reason_code": view.get("status_reason_code")}
        slot = view["slots"][0]
        offer = {"booking_id": view["id"], "price_per_kg": view["price_per_kg"], "kg": view["kg"],
                 "payout_inr": view["payout_estimate_inr"], "pickup_window": view["pickup_window"],
                 "pickup_window_spoken": window_words(slot["date"], slot["window_start_min"], slot["window_end_min"],
                                                      self.conv["language"]),
                 "depot": view["depot_name"], "offer_valid_until": view["offer_expires_at"],
                 "field_cleared_free": True, "paid_same_day": True,
                 "farm": {"name": fields.get("farmer_name"), "phone": pickups.mask_phone(fields.get("contact")),
                          "village": fields.get("village_or_district"), "acres": fields.get("acres"),
                          "location": "demo location" if fields.get("location_source") == "demo" else None}}
        self.cards.append({"type": "offer", **offer, "impact": impact_for_kg(view["kg"]),
                           "partner_crew": view["partner_crew"]})
        return offer

    def _farmer_replied_since_offer(self) -> bool:
        return self.conv.get("offer_turn") is not None and self.index > self.conv["offer_turn"]

    def tool_confirm_booking(self, farmer_said_yes: bool = False) -> dict:
        booking_id = self.conv.get("booking_id")
        if not booking_id:
            return {"error": "no_offer_yet"}
        if not (farmer_said_yes and self._farmer_replied_since_offer() and farmer_affirmed(self.words, self.english)):
            return {"error": "needs_explicit_yes_to_the_offer"}
        booking = store.get_booking(self.db, booking_id)
        try:
            result = pickups.accept_booking(self.db, booking, accepted_by="farmer (agent)")
        except pickups.BookingError as exc:
            return {"error": "cannot_book", "detail": str(exc)}
        slot = result["slots"][0]
        booked = {"booking_id": booking_id, "status": "booked", "pickup_window": result["pickup_window"],
                  "pickup_window_spoken": window_words(slot["date"], slot["window_start_min"], slot["window_end_min"],
                                                       self.conv["language"]),
                  "payout_inr": result["booking"]["payout_estimate_inr"],
                  "booking_code": result["booking"]["booking_code"], "depot": result["booking"]["depot_name"],
                  "sms": "simulated"}
        self.cards.append({"type": "booked", **booked})
        return booked

    def tool_get_service_terms(self) -> dict:
        return dict(SERVICE_TERMS)

    def tool_my_bookings(self) -> dict:
        views = [pickups.booking_view(self.db, b) for b in store.get_bookings_for_farmer(self.db, self.conv["farmer_id"])
                 if b.get("status") not in ("cancelled", "expired")]
        rows = [{"booking_id": v["id"], "status": v["status"], "pickup_window": v["pickup_window"],
                 "kg": v["kg"], "price_per_kg": v["price_per_kg"], "paid_inr": v.get("payout_inr")} for v in views]
        self.cards.append({"type": "bookings", "bookings": rows})
        return {"bookings": rows}

    def tool_cancel_booking(self, booking_id: str = "", farmer_said_yes: bool = False) -> dict:
        booking = store.get_booking(self.db, booking_id)
        if booking is None or booking["farmer_id"] != self.conv["farmer_id"]:
            return {"error": "not_found"}
        if not (farmer_said_yes and farmer_affirmed(self.words, self.english)):
            return {"error": "needs_explicit_yes"}
        try:
            store.update_booking_status(self.db, booking_id, "cancelled", {"status_reason_code": "cancelled_by_farmer"})
        except store.InvalidTransition as exc:
            return {"error": "cannot_cancel", "detail": str(exc)}
        store.set_slots_status(self.db, booking_id, "cancelled", locked=False)
        pickups.plan_depot(self.db, booking["depot_id"])
        return {"booking_id": booking_id, "status": "cancelled"}


# ---- model calls --------------------------------------------------------------

# Gemini 3 on the global endpoint has a tight per-minute quota. On a 429 the agent
# waits a moment and retries, then falls back to gemini-2.5-flash in Mumbai, which
# has its own quota, so a busy minute slows a farmer down instead of dropping the
# conversation to a template.
FALLBACK_MODEL = os.environ.get("AGENT_FALLBACK_MODEL", "gemini-2.5-flash")
FALLBACK_LOCATION = os.environ.get("AGENT_FALLBACK_LOCATION", "asia-south1")
_fallback_client = None
# Once the fallback model answers a step, the rest of that turn stays on it: the
# two models sign function calls differently, so mixing them mid-turn is rejected.
_turn_model = threading.local()


def _fallback():
    global _fallback_client
    if _fallback_client is None:
        _fallback_client = genai.Client(vertexai=True, project=PROJECT_ID, location=FALLBACK_LOCATION,
                                        http_options=REQUEST_HTTP_OPTIONS)
    return _fallback_client


def _generate(client, contents: list, config: types.GenerateContentConfig):
    """One model step. Returns (function_calls, text, model_content). A thin
    seam so tests can script the model."""
    log = logging.getLogger("parali.agent")
    steps = (("fallback", 0),) if getattr(_turn_model, "fallback", False) else (("primary", 0), ("primary retry", 2.0), ("fallback", 0))
    for label, wait in steps:
        if wait:
            time.sleep(wait)
        try:
            if label == "fallback":
                response = _fallback().models.generate_content(model=FALLBACK_MODEL, contents=contents, config=config)
            else:
                response = client.models.generate_content(model=GEMINI_MODEL, contents=contents, config=config)
        except Exception as exc:   # rate-limited or unavailable: try the next way, else the caller uses a template
            log.warning("model call failed (%s): %s: %s", label, type(exc).__name__, str(exc)[:200])
            continue
        if label == "fallback":
            _turn_model.fallback = True
        calls = [(c.name, dict(c.args or {})) for c in (response.function_calls or [])]
        content = response.candidates[0].content if response.candidates else None
        return calls, (response.text if not calls else None), content
    return [], None, None


def _facts_summary(conv: dict) -> str:
    facts = {k: v for k, v in (conv.get("facts") or {}).items()}
    return json.dumps({"listing": conv.get("fields") or {}, "tool_results": facts}, ensure_ascii=False, default=str)


def _history(conv: dict) -> list[types.Content]:
    contents = []
    for t in conv.get("turns", [])[-12:]:
        contents.append(types.Content(role="user" if t["role"] == "user" else "model",
                                      parts=[types.Part.from_text(text=t["text"])]))
    return contents


def fallback_reply(turn: Turn, language: str) -> str:
    """A deterministic reply when the model's text can't be used: built only
    from tool results, in the farmer's language."""
    from phrases import agent_fallback
    return agent_fallback(turn.cards, turn.conv.get("fields") or {}, language)


def respond(client, turn: Turn, user_text: str) -> tuple[str, dict]:
    """Runs the tool loop for one farmer turn and returns (reply, guardrail
    report)."""
    conv = turn.conv
    _turn_model.fallback = False
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_PROMPT.format(language=conv["language"], today=pickups.now_ist().date().isoformat(),
                                                facts=_facts_summary(conv)),
        tools=[TOOLS], temperature=0.2,
        thinking_config=types.ThinkingConfig(thinking_budget=0),   # ~2 s per call instead of 5+; the guardrails live in code
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    contents = _history(conv) + [types.Content(role="user", parts=[types.Part.from_text(text=user_text)])]
    report = {"tool_calls": [], "regenerated": False, "fallback": False, "blocked_numbers": [],
              "blocked_claims": []}
    text = None
    for _ in range(MAX_TOOL_STEPS):
        calls, text, model_content = _generate(client, contents, config)
        if not calls:
            break
        if model_content is not None:
            contents.append(model_content)
        responses = []
        for name, args in calls:
            result = turn.run_tool(name, args)
            report["tool_calls"].append({"name": name, "args": args, "ok": "error" not in result})
            responses.append(types.Part.from_function_response(name=name, response={"result": result}))
        contents.append(types.Content(role="user", parts=responses))
        text = None

    farmer_texts = [user_text, *[t["text"] for t in conv.get("turns", []) if t["role"] == "user"]]
    tool_values = [*turn.tool_results, conv.get("facts") or {}, conv.get("fields") or {},
                   pickups.now_ist().date().isoformat()]
    bad = unsupported_numbers(text or "", farmer_texts, tool_values)
    claims = forbidden_claims(text or "", farmer_texts)
    if text and (bad or claims):
        report["blocked_numbers"] = sorted(bad)
        report["blocked_claims"] = claims
        report["regenerated"] = True
        problems = []
        if bad:
            problems.append(f"these numbers, which no tool returned and the farmer did not say: {sorted(bad)}")
        if claims:
            problems.append("any talk of government, schemes, subsidies or asking to be trusted "
                            f"({', '.join(claims)}); we are a private company and payments are simulated")
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=(
            "Rewrite your last reply without " + " and without ".join(problems) +
            ". Use only numbers from the tool results."))]))
        _, text, _ = _generate(client, contents, config)
        if text and (unsupported_numbers(text, farmer_texts, tool_values) or forbidden_claims(text, farmer_texts)):
            text = None
    if not text:
        report["fallback"] = True
        text = fallback_reply(turn, conv["language"])
    return text.strip(), report


def understand(client, language: str, text: str | None, audio: bytes | None, mime: str | None,
               transcribe_fallback) -> tuple[str, str | None]:
    """(farmer's words, English rendering). Gemini hears audio directly;
    Cloud Speech-to-Text is the fallback."""
    if audio:
        heard = understand_audio(client, audio, mime or "audio/wav", language)
        if heard:
            return heard["transcript"], heard.get("english")
        words = transcribe_fallback(audio)
        return words, to_english(client, words, language)
    if language == "English":
        return text, text            # already English: no translation call
    return text, to_english(client, text, language)


def take_turn(db, client, farmer_id: str, language: str, words: str, english: str | None,
              conversation_id: str | None = None, quality: dict | None = None) -> dict:
    """Loads or starts the conversation, runs one turn, saves it."""
    conv = store.get_conversation(db, conversation_id) if conversation_id else None
    if conv is not None and conv["farmer_id"] != farmer_id:
        raise PermissionError("conversation belongs to another farmer")
    if conv is None:
        conv = store.save_conversation(db, {"farmer_id": farmer_id, "language": language, "turns": [],
                                            "fields": {}, "facts": {}})
    if len([t for t in conv["turns"] if t["role"] == "user"]) >= MAX_TURNS:
        raise OverflowError("conversation is too long; please start again")
    conv["language"] = language
    if quality:
        conv["quality"] = quality
    turn = Turn(db, conv, words, english)
    reply, report = respond(client, turn, words)
    now = pickups.now_ist().isoformat()
    conv["turns"] = conv.get("turns", []) + [
        {"role": "user", "text": words, "english": english, "at": now},
        {"role": "model", "text": reply, "at": now, "guardrails": report},
    ]
    store.save_conversation(db, conv)
    return {"conversation_id": conv["id"], "heard": {"text": words, "english": english}, "reply": reply,
            "cards": turn.cards, "fields": conv.get("fields") or {},
            "missing_fields": pickups.agent_missing_fields(conv.get("fields") or {}),
            "booking_id": conv.get("booking_id"), "guardrails": report}
