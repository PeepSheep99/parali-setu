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
