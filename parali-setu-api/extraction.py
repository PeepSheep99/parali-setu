"""Gemini perception jobs for the farmer's agent: hear a recording, read a
photo of the straw or of the cleared field, and render the farmer's words in
English for our records. Every function returns structured data or plain
text, never a price or quantity Gemini invented: numbers come from the
planners, and the agent's own replies are checked in agent.py.
"""
from __future__ import annotations

import json

from google import genai
from google.genai import types

from gemini_client import call_gemini

VALID_QUALITY_GRADES = ("dry", "wet", "mixed")
VALID_FIELD_CONDITIONS = ("unburned", "partially_burned", "burned", "inconclusive")


def read_stubble_quality(client: genai.Client, image_bytes: bytes, mime_type: str = "image/jpeg") -> dict | None:
    """An optional perception signal, never a price
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
    """A farmer's photo evidence that their harvested field
    was NOT burned, same perception-only contract as read_stubble_quality:
    Gemini only reads what the photo shows, it never decides the trust
    score itself (that is trust.score_no_burn_submission's job, combined
    with the satellite fire data for the district).
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


def understand_audio(client: genai.Client, audio_bytes: bytes, mime_type: str, language: str) -> dict | None:
    """Gemini listens to the farmer directly (no separate speech-to-text) and
    returns {"transcript": exactly what was said, in its own script,
    "english": a faithful English rendering for ops and inventory}. None if
    Gemini is unavailable or hears nothing, so the caller can fall back to
    Cloud Speech-to-Text."""
    prompt = types.Part.from_text(text=f"""This is a farmer in Punjab or Haryana speaking Punjabi, Hindi or
English (they may mix them; {language} is only a guess). Write the transcript in the script of the
language they actually spoke: Gurmukhi for Punjabi, Devanagari for Hindi, Latin for English.
Respond with ONLY a JSON object:
{{"transcript": <exactly what they said, in the script of the language they spoke>,
  "english": <a faithful English translation; keep every number, place and date exactly>}}
If there is no intelligible speech, respond {{"transcript": null, "english": null}}.""")
    text = call_gemini(client, [prompt, types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)], json_mode=True)
    if text is None:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if parsed.get("transcript") else None


def to_english(client: genai.Client, text: str, language: str) -> str | None:
    """A faithful English rendering of a farmer's message for ops and
    inventory records. Numbers, places and dates are kept exactly."""
    if language == "English":
        return text
    prompt = f"""Translate this {language} message from a farmer into plain English.
Keep every number, place name and date exactly as given. Reply with the translation only.

{text}"""
    return call_gemini(client, prompt, json_mode=False)
