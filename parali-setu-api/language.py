"""Which language the farmer is speaking, decided in code from what they said.

The pickup page has no language step: a farmer just talks or types, and the
agent replies in the same language. Gurmukhi script means Punjabi and
Devanagari means Hindi. Latin script is English unless it reads as romanised
Punjabi or Hindi ("mere kol 10 kille jhona"), which a short list of everyday
farm words catches. Any other script (Bengali, Urdu, Tamil...) is a language we
don't serve yet, and the farmer is told which ones we do.
"""
from __future__ import annotations

import re

SUPPORTED = ("Punjabi", "Hindi", "English")
UNSUPPORTED = "unsupported"

_GURMUKHI = re.compile(r"[਀-੿]")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LATIN = re.compile(r"[A-Za-z]")
# Bengali, Gujarati, Odia, Tamil, Telugu, Kannada, Malayalam, Sinhala, Arabic/Urdu
_OTHER = re.compile(r"[ঀ-৿઀-෿؀-ۿ]")
_WORD = re.compile(r"[a-z]+")

# Words a Punjabi or Hindi speaker types in Latin letters. Kept to words that
# are not also common English, so "I have 10 acres" stays English.
_ROMAN_PUNJABI = {"kille", "killa", "killey", "jhona", "jhone", "kanak", "mere", "kol", "sanu", "tuhanu", "mainu",
                  "tusi", "asi", "kithe", "kado", "kinne", "hega", "pind", "parali", "bijai", "chahidi", "karo",
                  "dasso", "ji", "haanji", "nahi", "nahin", "mera", "naam", "nu", "karni", "sadda", "saada"}
_ROMAN_HINDI = {"mere", "paas", "hai", "hain", "ekad", "ekar", "dhaan", "dhan", "gehun", "gehu", "gaon", "gaanv",
                "kitne", "kab", "tak", "bona", "bowai", "chahiye", "karna", "kijiye", "nahi", "nahin", "haan",
                "ji", "kya", "aap", "hum", "parali", "zila", "mera", "naam", "hamara", "mujhe"}
# Words that tip a romanised message one way when both lists match.
_PUNJABI_ONLY = {"kille", "killa", "killey", "jhona", "jhone", "kanak", "kol", "sanu", "tuhanu", "mainu", "tusi",
                 "asi", "kithe", "kado", "kinne", "hega", "pind", "chahidi", "dasso", "haanji"}
_HINDI_ONLY = {"paas", "ekad", "ekar", "dhaan", "gehun", "gehu", "gaon", "gaanv", "kitne", "kab", "bona", "bowai",
               "chahiye", "kijiye", "kya", "aap", "hum", "zila"}


# Everyday English words. A Latin-script message with fewer than two of these
# and no romanised cue words ("mera naam Gurpreet, number 98...") is not
# evidence of English: it is a name and a number, in whatever language the
# farmer has been speaking.
_ENGLISH = {"i", "my", "me", "is", "am", "are", "the", "a", "an", "have", "has", "please", "yes", "no", "what", "when",
            "how", "where", "will", "you", "we", "it", "to", "of", "in", "and", "by", "for", "can", "do", "want",
            "need", "name", "acres", "village", "sow", "sowing", "wheat", "book", "paid", "pay", "straw", "this", "that"}


def detect(text: str | None) -> str | None:
    """'Punjabi', 'Hindi', 'English', UNSUPPORTED, or None when the text has
    no letters to go on (only numbers, say), so the conversation's last
    language carries on."""
    return detect_with_confidence(text)[0]


def detect_with_confidence(text: str | None) -> tuple[str | None, bool]:
    """(language, decisive). Not decisive when romanised text could be either
    Punjabi or Hindi, or when Latin text has too little English in it to call
    it English. The agent then keeps the conversation's language instead of
    switching a Punjabi farmer to English because they typed their name."""
    if not text:
        return None, False
    pa, hi = len(_GURMUKHI.findall(text)), len(_DEVANAGARI.findall(text))
    other, latin = len(_OTHER.findall(text)), len(_LATIN.findall(text))
    if pa or hi:
        return ("Punjabi" if pa >= hi else "Hindi"), True
    if other and other >= latin:
        return UNSUPPORTED, True
    if not latin:
        return None, False
    words = set(_WORD.findall(text.lower()))
    pa_hits, hi_hits = len(words & _ROMAN_PUNJABI), len(words & _ROMAN_HINDI)
    if max(pa_hits, hi_hits) < 2:
        return "English", len(words & _ENGLISH) >= 2 and not (pa_hits or hi_hits)
    pa_only, hi_only = len(words & _PUNJABI_ONLY), len(words & _HINDI_ONLY)
    if pa_only != hi_only:
        return ("Punjabi" if pa_only > hi_only else "Hindi"), True
    return ("Punjabi" if pa_hits >= hi_hits else "Hindi"), False


# Said in all three when a farmer uses a language we don't serve yet. Spoken in
# English only (the one voice that can read the whole line).
UNSUPPORTED_REPLY = ("ਮੈਂ ਪੰਜਾਬੀ, ਹਿੰਦੀ ਜਾਂ ਅੰਗਰੇਜ਼ੀ ਵਿੱਚ ਗੱਲ ਕਰ ਸਕਦਾ ਹਾਂ। "
                     "मैं पंजाबी, हिंदी या अंग्रेज़ी में बात कर सकता हूँ। "
                     "I can talk in Punjabi, Hindi or English.")
UNSUPPORTED_SPOKEN = "I can talk in Punjabi, Hindi or English. Please say that again in one of them."
