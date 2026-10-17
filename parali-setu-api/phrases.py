"""Fixed, deterministic phrases read back to farmers.

The confirm card repeats the farmer's own numbers, so it is templated rather
than generated: a read-back must never round, translate or reinterpret a
figure. Gemini is used for questions and explanations, not for this.
"""
from __future__ import annotations

from datetime import date

CROP_NAMES = {
    "Hindi": {"rice_stubble": "धान की पराली", "wheat_stubble": "गेहूं का भूसा"},
    "Punjabi": {"rice_stubble": "ਝੋਨੇ ਦੀ ਪਰਾਲੀ", "wheat_stubble": "ਕਣਕ ਦਾ ਨਾੜ"},
    "English": {"rice_stubble": "paddy stubble", "wheat_stubble": "wheat stubble"},
}

TEMPLATES = {
    "Hindi": {
        "lead": "आपने बताया:",
        "amount": "{acres} एकड़",
        "place": "{place} में",
        "sowing": "खेत {date} तक खाली करना है",
        "close": "सही है तो पुष्टि करें।",
        "unknown": "पता नहीं",
    },
    "Punjabi": {
        "lead": "ਤੁਸੀਂ ਦੱਸਿਆ:",
        "amount": "{acres} ਕਿੱਲੇ",
        "place": "{place} ਵਿੱਚ",
        "sowing": "ਖੇਤ {date} ਤੱਕ ਖਾਲੀ ਕਰਨਾ ਹੈ",
        "close": "ਠੀਕ ਹੈ ਤਾਂ ਪੁਸ਼ਟੀ ਕਰੋ।",
        "unknown": "ਪਤਾ ਨਹੀਂ",
    },
    "English": {
        "lead": "You said:",
        "amount": "{acres} acres",
        "place": "in {place}",
        "sowing": "field to be cleared by {date}",
        "close": "Confirm if this is right.",
        "unknown": "not given",
    },
}


def _fmt_number(value: float) -> str:
    return f"{value:g}"


def _fmt_date(value) -> str | None:
    try:
        d = date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None
    return f"{d.day}/{d.month}/{d.year}"


def confirm_summary(fields: dict, language: str) -> str:
    t = TEMPLATES.get(language, TEMPLATES["English"])
    crops = CROP_NAMES.get(language, CROP_NAMES["English"])
    parts = []
    if fields.get("acres"):
        parts.append(t["amount"].format(acres=_fmt_number(fields["acres"])))
    parts.append(crops.get(fields.get("crop_type"), t["unknown"]))
    if fields.get("village_or_district"):
        parts.append(t["place"].format(place=fields["village_or_district"]))
    sowing = _fmt_date(fields.get("sowing_deadline"))
    if sowing:
        parts.append(t["sowing"].format(date=sowing))
    return f"{t['lead']} {', '.join(parts)}. {t['close']}"


# The talking agent's fallback, used when Gemini is unavailable or its reply
# fails the numbers check. Built only from tool results.
AGENT_FALLBACK = {
    "Hindi": {
        "booked": "आपकी पिकअप बुक हो गई: {window}. पराली उठते ही उसी दिन ₹{payout} मिलेंगे।",
        "offer": "आज का भाव ₹{price} प्रति किलो है। आपको ₹{payout} मिलेंगे, पिकअप {window}. क्या बुक कर दूं?",
        "price": "{district} में आज का भाव ₹{price} प्रति किलो है। खेत मुफ्त में साफ़ होगा, पैसे उसी दिन।",
        "missing": "कृपया बताइए: {items}.",
        "start": "नमस्ते! बताइए कितने एकड़ धान है, कौन सा गांव, और गेहूं कब बोनी है।",
        "items": {"quantity": "कितने एकड़", "crop_type": "कौन सी फसल", "location": "गांव या ज़िला",
                  "sowing_deadline": "गेहूं की बुवाई की तारीख"},
    },
    "Punjabi": {
        "booked": "ਤੁਹਾਡਾ ਪਿਕਅੱਪ ਬੁੱਕ ਹੋ ਗਿਆ: {window}. ਪਰਾਲੀ ਚੁੱਕਦੇ ਹੀ ਉਸੇ ਦਿਨ ₹{payout} ਮਿਲਣਗੇ।",
        "offer": "ਅੱਜ ਦਾ ਭਾਅ ₹{price} ਪ੍ਰਤੀ ਕਿਲੋ ਹੈ। ਤੁਹਾਨੂੰ ₹{payout} ਮਿਲਣਗੇ, ਪਿਕਅੱਪ {window}. ਕੀ ਬੁੱਕ ਕਰ ਦਿਆਂ?",
        "price": "{district} ਵਿੱਚ ਅੱਜ ਦਾ ਭਾਅ ₹{price} ਪ੍ਰਤੀ ਕਿਲੋ ਹੈ। ਖੇਤ ਮੁਫ਼ਤ ਸਾਫ਼ ਹੋਵੇਗਾ, ਪੈਸੇ ਉਸੇ ਦਿਨ।",
        "missing": "ਕਿਰਪਾ ਕਰਕੇ ਦੱਸੋ: {items}.",
        "start": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ! ਦੱਸੋ ਕਿੰਨੇ ਕਿੱਲੇ ਝੋਨਾ ਹੈ, ਕਿਹੜਾ ਪਿੰਡ, ਅਤੇ ਕਣਕ ਕਦੋਂ ਬੀਜਣੀ ਹੈ।",
        "items": {"quantity": "ਕਿੰਨੇ ਕਿੱਲੇ", "crop_type": "ਕਿਹੜੀ ਫ਼ਸਲ", "location": "ਪਿੰਡ ਜਾਂ ਜ਼ਿਲ੍ਹਾ",
                  "sowing_deadline": "ਕਣਕ ਦੀ ਬਿਜਾਈ ਦੀ ਤਾਰੀਖ"},
    },
    "English": {
        "booked": "Your pickup is booked: {window}. You get Rs {payout} the same day we collect.",
        "offer": "Today's price is Rs {price} per kg. You get Rs {payout}, pickup {window}. Shall I book it?",
        "price": "Today's price in {district} is Rs {price} per kg. We clear the field free and pay the same day.",
        "missing": "Please tell me: {items}.",
        "start": "Hello! Tell me how many acres of paddy, your village, and when you sow wheat.",
        "items": {"quantity": "how many acres", "crop_type": "which crop", "location": "village or district",
                  "sowing_deadline": "your wheat sowing date"},
    },
}


def agent_fallback(cards: list[dict], fields: dict, language: str) -> str:
    t = AGENT_FALLBACK.get(language, AGENT_FALLBACK["English"])
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
