"""The three Gemini jobs in the farmer/company flow (PRD Section 8.1 /
8.2 / 12): extract a structured listing from natural language, parse a
negotiation counter-offer into a price delta, and explain a match back
in plain language. Every function returns structured data or plain
text -- never a price or quantity Gemini invented itself. solver.py
always produces the actual numbers; these functions only translate
language into solver inputs or solver outputs into language.
"""
from __future__ import annotations

import json
from datetime import date

from google import genai
from google.genai import types

from gemini_client import call_gemini

VALID_CROP_TYPES = ("rice_stubble", "wheat_stubble")
VALID_QUALITY_GRADES = ("dry", "wet", "mixed")
VALID_FIELD_CONDITIONS = ("unburned", "partially_burned", "burned", "inconclusive")


def extract_listing(client: genai.Client, raw_text: str, language: str, today: date | None = None) -> dict | None:
    """PRD 8.1.2 -- turn a farmer's spoken/typed listing into a structured
    record. Returns None if Gemini is unavailable or the response isn't
    valid JSON; callers must show a plain error, never guess a listing.

    `today` anchors relative dates like "by the 25th" -- found live
    (not hypothetical) that without an explicit anchor, Gemini resolved
    a bare day-of-month against the wrong year.
    """
    today = today or date.today()
    prompt = f"""You are extracting a structured crop-residue (stubble) listing
from a farmer's message. The message is in {language}. This message may be a
speech-to-text transcript and can contain recognition errors -- words that
don't quite fit grammatically, or a stray word that doesn't belong. Today's
date is {today.isoformat()}. Respond with ONLY a JSON object, no other text,
matching exactly this shape:

{{
  "quantity_kg": <number ONLY if the farmer stated a weight; convert quintals to kg by multiplying by 100 and tonnes by 1000; else null>,
  "acres": <number ONLY if the farmer stated an area in acres ("acre", "killa", "kille" all mean acre); else null>,
  "crop_type": <one of "rice_stubble" (paddy/jhona/dhaan) or "wheat_stubble">,
  "village_or_district": <string, as stated>,
  "ready_by": <ISO date string YYYY-MM-DD when the stubble is ready for pickup, or null>,
  "sowing_deadline": <ISO date string YYYY-MM-DD by which the field must be clear to sow the next crop, or null>,
  "contact": <string if a phone number or name was given, else null>
}}

Never convert between area and weight -- if only acres were stated,
quantity_kg is null, and if only a weight was stated, acres is null.

Strict rule for ready_by and sowing_deadline, since a wrong specific date is
worse than none: only fill one in if the message states an explicit day number
(e.g. "the 25th", "20 October") or an unambiguous relative timeframe (e.g.
"next week", "in 5 days") that you can resolve against today's date. If the
message only names a month with no day (e.g. a stray or garbled word near
"October" with no number), or is otherwise vague, return null -- do NOT guess,
round to, or infer any particular day of that month. A phrase like "25 tak
chakkni hai" (must be lifted by the 25th) is a sowing_deadline. The same
caution applies to every other field: if a word looks like a transcription
error or doesn't clearly state a value, use null rather than resolving it to a
specific guess.

Farmer's message: "{raw_text}"
"""
    text = call_gemini(client, prompt, json_mode=True)
    if text is None:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None

    if parsed.get("crop_type") not in VALID_CROP_TYPES:
        parsed["crop_type"] = None
    return parsed


FOLLOW_UP_FIELD_TEXT = {
    "quantity": "how many acres (or quintals) of stubble",
    "crop_type": "whether it is paddy or wheat stubble",
    "location": "which village and district the field is in",
    "sowing_deadline": "the date by which the field must be cleared for sowing",
}

# Used when Gemini can't phrase the question: the farmer still gets exactly
# one clear question in their language.
FALLBACK_FOLLOW_UPS = {
    "Hindi": {
        "quantity": "कितने एकड़ की पराली है?",
        "crop_type": "धान की पराली है या गेहूं की?",
        "location": "खेत किस गांव और ज़िले में है?",
        "sowing_deadline": "खेत किस तारीख तक खाली चाहिए?",
    },
    "Punjabi": {
        "quantity": "ਕਿੰਨੇ ਕਿੱਲੇ ਦੀ ਪਰਾਲੀ ਹੈ?",
        "crop_type": "ਝੋਨੇ ਦੀ ਪਰਾਲੀ ਹੈ ਜਾਂ ਕਣਕ ਦੀ?",
        "location": "ਖੇਤ ਕਿਹੜੇ ਪਿੰਡ ਅਤੇ ਜ਼ਿਲ੍ਹੇ ਵਿੱਚ ਹੈ?",
        "sowing_deadline": "ਖੇਤ ਕਿਸ ਤਾਰੀਖ ਤੱਕ ਖਾਲੀ ਚਾਹੀਦਾ ਹੈ?",
    },
    "English": {
        "quantity": "How many acres of stubble do you have?",
        "crop_type": "Is it paddy or wheat stubble?",
        "location": "Which village and district is the field in?",
        "sowing_deadline": "By what date must the field be cleared?",
    },
}


def follow_up_question(client: genai.Client, missing_fields: list[str], language: str) -> str:
    """One short spoken question that asks for every missing field at once.
    The farmer is asked at most one question per listing, so it has to
    cover everything. Falls back to fixed text if Gemini is unavailable."""
    asks = [FOLLOW_UP_FIELD_TEXT[f] for f in missing_fields if f in FOLLOW_UP_FIELD_TEXT]
    if not asks:
        return ""
    prompt = f"""A farmer is listing crop stubble for pickup by voice. Write ONE short,
polite question in {language}, in simple everyday words a farmer would use,
asking for: {"; ".join(asks)}. Ask for nothing else. Use the farmer's
everyday unit (in Punjabi, acres are "kille"). Plain text only, no markdown,
no asterisks, no greeting.
"""
    text = call_gemini(client, prompt, json_mode=False)
    if text and text.strip():
        return text.strip()
    fallback = FALLBACK_FOLLOW_UPS.get(language, FALLBACK_FOLLOW_UPS["English"])
    return " ".join(fallback[f] for f in missing_fields if f in fallback)


def read_stubble_quality(client: genai.Client, image_bytes: bytes, mime_type: str = "image/jpeg") -> dict | None:
    """PRD 8.1.3 -- optional multimodal perception signal, never a price
    input. Returns {"quality_grade": "dry"|"wet"|"mixed", "note": str} on
    success, or None if Gemini is unavailable -- callers must fall back
    to quality_grade="unknown" (self-reported crop_type only), never guess
    a grade. This is the one function in this file that takes an image
    instead of text, but the contract is identical: Gemini perceives,
    it never decides a number.
    """
    prompt_part = types.Part.from_text(text="""Look at this photo of harvested crop
residue (stubble) -- this could be cut stalks still standing/lying in the
field after harvest, or residue already gathered into a pile; either is a
valid photo. Respond with ONLY a JSON object:

{
  "quality_grade": <one of "dry", "wet", or "mixed" (visibly mixed with other
    debris/soil) -- your best visual read>,
  "note": <one short phrase explaining the read, e.g. "pale gold, no visible moisture">
}

If the image genuinely isn't crop residue/stubble at all (a different subject
entirely), or the photo is too unclear to make any reasonable call, respond
with {"quality_grade": null, "note": "not a usable photo"} instead of
guessing.
""")
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    text = call_gemini(client, [prompt_part, image_part], json_mode=True)
    if text is None:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None

    if parsed.get("quality_grade") not in VALID_QUALITY_GRADES:
        parsed["quality_grade"] = None
    return parsed


def read_no_burn_proof(client: genai.Client, image_bytes: bytes, mime_type: str = "image/jpeg") -> dict | None:
    """Feature 5 -- a farmer's photo evidence that their harvested field
    was NOT burned, same perception-only contract as read_stubble_quality:
    Gemini only reads what the photo shows, it never decides the trust
    score itself (that's solver.score_no_burn_submission's job, combined
    with Part A's real satellite corroboration).
    """
    prompt_part = types.Part.from_text(text="""Look at this photo of a
harvested field, submitted as evidence that crop residue was NOT burned after
harvest (sold instead). Respond with ONLY a JSON object:

{
  "field_condition": <one of "unburned" (clear/bare soil or gathered residue,
    no burn marks), "partially_burned" (some charred patches visible),
    "burned" (clearly and extensively charred/blackened), or "inconclusive">,
  "note": <one short phrase explaining the read>
}

If the image genuinely isn't a field at all, or is too unclear to make any
reasonable call, respond with {"field_condition": "inconclusive", "note":
"not a usable photo"} instead of guessing.
""")
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)

    text = call_gemini(client, [prompt_part, image_part], json_mode=True)
    if text is None:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None

    if parsed.get("field_condition") not in VALID_FIELD_CONDITIONS:
        parsed["field_condition"] = None
    return parsed


def explain_offer(client: genai.Client, offer: dict, language: str) -> str | None:
    """Narrate a pickup offer in the farmer's language. Every number comes
    from the planners and is repeated verbatim; Gemini adds no facts."""
    prompt = f"""Write a short, warm message in {language} (2-3 sentences) telling a
farmer that Parali Setu will buy their paddy straw. Use exactly these facts and
do not change or round any number:
- Price: {offer.get('price_per_kg')} rupees per kg (today's posted price in {offer.get('district')})
- Straw: {offer.get('kg')} kg
- Payment: {offer.get('payout_inr')} rupees, paid the same day the crew collects
- Pickup: {offer.get('pickup_window', 'to be confirmed')}
- The field is cleared free of charge.

Plain prose only, no markdown formatting, no asterisks.
"""
    return call_gemini(client, prompt, json_mode=False)


def explain_price(client: genai.Client, facts: dict, language: str) -> str | None:
    """Why today's price is what it is, from the procurement planner's own
    reason. Plain words, no jargon, in the farmer's language."""
    prompt = f"""In {language}, explain in two short sentences, in plain words a farmer
uses (no English words, no technical terms), why Parali Setu's price for paddy
straw in {facts.get('district')} today is {facts.get('price_per_kg')} rupees per kg.
Use only this reason, and keep the number exactly as written: {facts.get('reason')}
Also say the field is cleared for free and payment comes the same day.
Plain prose only, no markdown, no asterisks.
"""
    return call_gemini(client, prompt, json_mode=False)

