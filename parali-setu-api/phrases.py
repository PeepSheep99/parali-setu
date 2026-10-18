"""Fixed, deterministic phrases for the farmer's agent: the fallback reply
built only from tool results, the trilingual greeting, and pickup windows the
way a person says them. Templated rather than generated, so they never
round, translate or reinterpret a figure.
"""
from __future__ import annotations

from datetime import date

def _fmt_number(value: float) -> str:
    return f"{value:g}"


# The talking agent's fallback, used when Gemini is unavailable or its reply
# fails the numbers check. Built only from tool results.
AGENT_FALLBACK = {
    "Hindi": {
        "booked": "आपकी पिकअप बुक हो गई: {window}. पराली उठते ही उसी दिन ₹{payout} मिलेंगे।",
        "offer": "आज का भाव ₹{price} प्रति किलो है। आपको ₹{payout} मिलेंगे, पिकअप {window}. क्या बुक कर दूं?",
        "held": "आपका ऑफ़र वही है: ₹{price} प्रति किलो, आज सबके लिए एक ही भाव, मोलभाव से नहीं बदलता। आपको उसी दिन ₹{payout} मिलेंगे, पिकअप {window}. क्या बुक कर दूं?",
        "reminder": "आपका ऑफ़र वही है: पिकअप {window}, उसी दिन ₹{payout}। क्या बुक कर दूं?",
        "price": "{district} में आज का भाव ₹{price} प्रति किलो है। खेत मुफ्त में साफ़ होगा, पैसे उसी दिन।",
        "missing": "कृपया बताइए: {items}.",
        "start": "नमस्ते! बताइए कितने एकड़ धान है, कौन सा गांव, और गेहूं कब बोनी है।",
        "items": {"quantity": "कितने एकड़", "crop_type": "कौन सी फसल", "location": "गांव या ज़िला",
                  "sowing_deadline": "गेहूं की बुवाई की तारीख", "name": "आपका नाम", "phone": "मोबाइल नंबर"},
    },
    "Punjabi": {
        "booked": "ਤੁਹਾਡਾ ਪਿਕਅੱਪ ਬੁੱਕ ਹੋ ਗਿਆ: {window}. ਪਰਾਲੀ ਚੁੱਕਦੇ ਹੀ ਉਸੇ ਦਿਨ ₹{payout} ਮਿਲਣਗੇ।",
        "offer": "ਅੱਜ ਦਾ ਭਾਅ ₹{price} ਪ੍ਰਤੀ ਕਿਲੋ ਹੈ। ਤੁਹਾਨੂੰ ₹{payout} ਮਿਲਣਗੇ, ਪਿਕਅੱਪ {window}. ਕੀ ਬੁੱਕ ਕਰ ਦਿਆਂ?",
        "held": "ਤੁਹਾਡੀ ਪੇਸ਼ਕਸ਼ ਉਹੀ ਹੈ: ₹{price} ਪ੍ਰਤੀ ਕਿਲੋ, ਅੱਜ ਸਭ ਲਈ ਇੱਕੋ ਭਾਅ, ਮੋਲ-ਭਾਅ ਨਾਲ ਨਹੀਂ ਬਦਲਦਾ। ਤੁਹਾਨੂੰ ਉਸੇ ਦਿਨ ₹{payout} ਮਿਲਣਗੇ, ਪਿਕਅੱਪ {window}. ਕੀ ਬੁੱਕ ਕਰ ਦਿਆਂ?",
        "reminder": "ਤੁਹਾਡੀ ਪੇਸ਼ਕਸ਼ ਉਹੀ ਹੈ: ਪਿਕਅੱਪ {window}, ਉਸੇ ਦਿਨ ₹{payout}। ਕੀ ਬੁੱਕ ਕਰ ਦਿਆਂ?",
        "price": "{district} ਵਿੱਚ ਅੱਜ ਦਾ ਭਾਅ ₹{price} ਪ੍ਰਤੀ ਕਿਲੋ ਹੈ। ਖੇਤ ਮੁਫ਼ਤ ਸਾਫ਼ ਹੋਵੇਗਾ, ਪੈਸੇ ਉਸੇ ਦਿਨ।",
        "missing": "ਕਿਰਪਾ ਕਰਕੇ ਦੱਸੋ: {items}.",
        "start": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ! ਦੱਸੋ ਕਿੰਨੇ ਕਿੱਲੇ ਝੋਨਾ ਹੈ, ਕਿਹੜਾ ਪਿੰਡ, ਅਤੇ ਕਣਕ ਕਦੋਂ ਬੀਜਣੀ ਹੈ।",
        "items": {"quantity": "ਕਿੰਨੇ ਕਿੱਲੇ", "crop_type": "ਕਿਹੜੀ ਫ਼ਸਲ", "location": "ਪਿੰਡ ਜਾਂ ਜ਼ਿਲ੍ਹਾ",
                  "sowing_deadline": "ਕਣਕ ਦੀ ਬਿਜਾਈ ਦੀ ਤਾਰੀਖ", "name": "ਤੁਹਾਡਾ ਨਾਮ", "phone": "ਮੋਬਾਈਲ ਨੰਬਰ"},
    },
    "English": {
        "booked": "Your pickup is booked: {window}. You get Rs {payout} the same day we collect.",
        "offer": "Today's price is Rs {price} per kg. You get Rs {payout}, pickup {window}. Shall I book it?",
        "held": "Your offer stands: Rs {price} per kg, the same price for every farmer today, so it doesn't change with bargaining. You get Rs {payout} the same day, pickup {window}. Shall I book it?",
        "reminder": "Your offer stands: pickup {window}, Rs {payout} the same day. Shall I book it?",
        "price": "Today's price in {district} is Rs {price} per kg. We clear the field free and pay the same day.",
        "missing": "Please tell me: {items}.",
        "start": "Hello! Tell me how many acres of paddy, your village, and when you sow wheat.",
        "items": {"quantity": "how many acres", "crop_type": "which crop", "location": "village or district",
                  "sowing_deadline": "your wheat sowing date", "name": "your name", "phone": "your mobile number"},
    },
}


def offer_reminder(offer: dict, language: str) -> str:
    """One sentence restating an open offer's pickup time and payout, added
    when a reply after the offer doesn't mention it."""
    t = AGENT_FALLBACK.get(language, AGENT_FALLBACK["English"])
    return t["reminder"].format(window=offer.get("pickup_window_spoken") or offer["pickup_window"],
                                payout=_fmt_number(offer["payout_inr"]))


def agent_fallback(cards: list[dict], fields: dict, language: str, conv: dict | None = None) -> str:
    """This turn's cards first; with none (a question, some bargaining), what
    the conversation already holds, so a dropped reply never restarts a
    farmer who has a booking or an offer."""
    t = AGENT_FALLBACK.get(language, AGENT_FALLBACK["English"])
    conv = conv or {}
    last = {c["type"]: c for c in cards}
    if "booked" in last:
        c = last["booked"]
        return t["booked"].format(window=c.get("pickup_window_spoken") or c["pickup_window"], payout=_fmt_number(c["payout_inr"]))
    if "offer" in last:
        c = last["offer"]
        return t["offer"].format(price=_fmt_number(c["price_per_kg"]), payout=_fmt_number(c["payout_inr"]),
                                 window=c.get("pickup_window_spoken") or c["pickup_window"])
    if "draft" in last and last["draft"]["missing_fields"]:
        items = ", ".join(t["items"][m] for m in last["draft"]["missing_fields"] if m in t["items"])
        return t["missing"].format(items=items)
    if "price" in last:
        c = last["price"]
        return t["price"].format(district=c["district"], price=_fmt_number(c["price_per_kg"]))
    if conv.get("booked_card"):
        c = conv["booked_card"]
        return t["booked"].format(window=c.get("pickup_window_spoken") or c["pickup_window"], payout=_fmt_number(c["payout_inr"]))
    if conv.get("offer_card"):
        c = conv["offer_card"]
        return t["held"].format(price=_fmt_number(c["price_per_kg"]), payout=_fmt_number(c["payout_inr"]),
                                window=c.get("pickup_window_spoken") or c["pickup_window"])
    if fields:
        from pickups import agent_missing_fields
        missing = [m for m in agent_missing_fields(fields) if m in t["items"]]
        if missing:
            return t["missing"].format(items=", ".join(t["items"][m] for m in missing))
    return t["start"]


# Pickup windows the way a person says them, e.g. "Saturday 17 October,
# 10 am to 1 pm". The agent reads this, never the raw "2026-10-17 10:00-13:00".
MONTHS = {
    "Hindi": ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"],
    "Punjabi": ["ਜਨਵਰੀ", "ਫ਼ਰਵਰੀ", "ਮਾਰਚ", "ਅਪ੍ਰੈਲ", "ਮਈ", "ਜੂਨ", "ਜੁਲਾਈ", "ਅਗਸਤ", "ਸਤੰਬਰ", "ਅਕਤੂਬਰ", "ਨਵੰਬਰ", "ਦਸੰਬਰ"],
    "English": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                "November", "December"],
}
WEEKDAYS = {   # Monday first, as date.weekday()
    "Hindi": ["सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार"],
    "Punjabi": ["ਸੋਮਵਾਰ", "ਮੰਗਲਵਾਰ", "ਬੁੱਧਵਾਰ", "ਵੀਰਵਾਰ", "ਸ਼ੁੱਕਰਵਾਰ", "ਸ਼ਨੀਵਾਰ", "ਐਤਵਾਰ"],
    "English": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
}
DAY_PARTS = {   # (before noon, noon to 4 pm, from 4 pm)
    "Hindi": ("सुबह", "दोपहर", "शाम"),
    "Punjabi": ("ਸਵੇਰੇ", "ਦੁਪਹਿਰ", "ਸ਼ਾਮ"),
}
WINDOW_TEMPLATE = {
    "Hindi": "{weekday}, {day} {month}, {start} से {end} बजे",
    "Punjabi": "{weekday}, {day} {month}, {start} ਤੋਂ {end} ਵਜੇ",
    "English": "{weekday} {day} {month}, {start} to {end}",
}


def _clock(minutes: int, language: str) -> str:
    hour = (minutes // 60) % 24
    h12 = hour % 12 or 12
    mins = f":{minutes % 60:02d}" if minutes % 60 else ""
    if language == "English":
        return f"{h12}{mins} {'am' if hour < 12 else 'pm'}"
    part = DAY_PARTS[language][0 if hour < 12 else 1 if hour < 16 else 2]
    return f"{part} {h12}{mins}"


def window_words(day: str, start_min: int, end_min: int, language: str) -> str:
    language = language if language in WINDOW_TEMPLATE else "English"
    d = date.fromisoformat(day[:10])
    return WINDOW_TEMPLATE[language].format(
        weekday=WEEKDAYS[language][d.weekday()], day=d.day, month=MONTHS[language][d.month - 1],
        start=_clock(start_min, language), end=_clock(end_min, language))
