"""Benchmark: the farmer agent against real Gemini, end to end.

Runs the production agent (agent.take_turn) in process, against real Vertex AI
Gemini, Text-to-Speech and Gemini audio understanding, over the in-memory demo
world dev_server.py uses -- so nothing is written to the shared Firestore.
Costs a little free-trial credit (a few hundred model calls).

What it measures
1. Language detection (offline, free): a labelled set of farmer messages.
2. Scripted farmers: 40 bookings (10 farms x Punjabi, Hindi, English and
   romanised Punjabi) plus 10 adversarial chats (a weight that doesn't fit the
   acres, a sowing date already past, subsidy and price bait, off-topic, an
   unserved language, a mid-chat language switch, a question instead of yes).
   Per turn: latency, each model call's latency and model, guardrail actions.
   Per chat: booked or not, turns and seconds to a booking, and whether the
   listing the agent built matches what the farmer said.
   Every reply is re-checked independently: any number not said by the
   farmer or returned by a tool counts as a leak.
3. Voice: Text-to-Speech says a farmer's sentence, Gemini hears it back;
   word accuracy and both latencies. (A synthetic voice is easier than a real
   farmer on a phone; this measures the pipeline, not field accuracy.)

    python -m bench.bench_agent                 # writes bench/results/agent.json
    python -m bench.bench_agent --quick         # 2 farms per language, no voice
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

OUT = ROOT / "bench" / "results" / "agent.json"

# ---- 1. language detection --------------------------------------------------

LANGUAGE_SET = [
    ("ਮੇਰੇ ਕੋਲ ਦਸ ਕਿੱਲੇ ਝੋਨਾ ਹੈ", "Punjabi"), ("ਪਰਾਲੀ ਕਦੋਂ ਚੁੱਕੋਗੇ?", "Punjabi"), ("ਹਾਂ ਜੀ", "Punjabi"),
    ("ਮੇਰਾ ਨਾਮ ਗੁਰਪ੍ਰੀਤ ਹੈ", "Punjabi"), ("ਪੈਸੇ ਕਦੋਂ ਮਿਲਣਗੇ", "Punjabi"), ("ਕਣਕ ਦੀ ਬਿਜਾਈ 2 ਨਵੰਬਰ", "Punjabi"),
    ("ਪਿੰਡ ਭੁੱਚੋ, ਬਠਿੰਡਾ", "Punjabi"), ("ਨਹੀਂ, ਬਾਰਾਂ ਕਿੱਲੇ", "Punjabi"),
    ("मेरे पास 8 एकड़ धान है", "Hindi"), ("पराली कब उठाओगे?", "Hindi"), ("हाँ जी बुक कर दो", "Hindi"),
    ("मेरा नाम रमेश है", "Hindi"), ("पैसा कब मिलेगा", "Hindi"), ("गेहूं की बुवाई 30 अक्टूबर", "Hindi"),
    ("गाँव नीलोखेड़ी, करनाल", "Hindi"), ("नहीं, बारह एकड़", "Hindi"),
    ("I have 10 acres of paddy straw", "English"), ("When will you pick it up?", "English"), ("yes please", "English"),
    ("My name is Harjit", "English"), ("How do I get paid?", "English"), ("Sowing on 2 November", "English"),
    ("Village Pehowa, Kurukshetra", "English"), ("No, twelve acres", "English"),
    ("mere kol 10 kille jhona hai", "Punjabi"), ("parali kado chukoge ji", "Punjabi"), ("haanji book karo", "Punjabi"),
    ("kanak di bijai kado karni hai", "Punjabi"), ("sanu paise kithe milange", "Punjabi"), ("pind bhucho, kinne kille", "Punjabi"),
    ("mere paas 8 ekad dhaan hai", "Hindi"), ("parali kab tak uthaoge, gaon me", "Hindi"), ("haan ji kijiye", "Hindi"),
    ("gehun ki bowai kab karna hai", "Hindi"), ("aap paisa kab doge", "Hindi"), ("kitne ekad chahiye aap ko", "Hindi"),
    ("আমার কাছে ১০ বিঘা খড় আছে", "unsupported"), ("میرے پاس دس ایکڑ ہیں", "unsupported"),
    ("எனக்கு பத்து ஏக்கர் உள்ளது", "unsupported"), ("నాకు పది ఎకరాలు ఉన్నాయి", "unsupported"),
]


def bench_language() -> dict:
    import language
    rows = [{"text": t, "expected": e, "got": language.detect(t)} for t, e in LANGUAGE_SET]
    for r in rows:
        r["got"] = r["got"] if r["got"] in ("Punjabi", "Hindi", "English") else ("unsupported" if r["got"] else None)
    wrong = [r for r in rows if r["got"] != r["expected"]]
    by_lang = {}
    for lang in ("Punjabi", "Hindi", "English", "unsupported"):
        sel = [r for r in rows if r["expected"] == lang]
        by_lang[lang] = f"{sum(r['got'] == lang for r in sel)}/{len(sel)}"
    return {"accuracy_pct": round(100 * (len(rows) - len(wrong)) / len(rows), 1), "n": len(rows),
            "by_language": by_lang, "wrong": wrong}


# ---- 2. scripted farmers ------------------------------------------------------

FARMS = [  # name, district, village, acres, sowing day offset from today
    ("Gurpreet Singh", "Sangrur", "Bahadurpur", 8, 10), ("Harjit Kaur", "Patiala", "Rakhra", 12, 9),
    ("Balwinder Singh", "Bathinda", "Bhucho", 6, 12), ("Sukhdev Singh", "Ludhiana", "Mullanpur", 10, 11),
    ("Jaswant Singh", "Moga", "Dharamkot", 5, 13), ("Ramesh Kumar", "Karnal", "Nilokheri", 9, 10),
    ("Satbir Singh", "Kaithal", "Pundri", 7, 12), ("Rajender Singh", "Kurukshetra", "Pehowa", 11, 9),
    ("Manjit Singh", "Sangrur", "Longowal", 14, 11), ("Kuldeep Singh", "Patiala", "Samana", 4, 10),
]
MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December"]
MONTHS_HI = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त", "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]
MONTHS_PA = ["ਜਨਵਰੀ", "ਫ਼ਰਵਰੀ", "ਮਾਰਚ", "ਅਪ੍ਰੈਲ", "ਮਈ", "ਜੂਨ", "ਜੁਲਾਈ", "ਅਗਸਤ", "ਸਤੰਬਰ", "ਅਕਤੂਬਰ", "ਨਵੰਬਰ", "ਦਸੰਬਰ"]


def script(style: str, farm: tuple, today: date, k: int) -> tuple[list[str], dict]:
    name, district, village, acres, offset = farm
    sow = today + timedelta(days=offset)
    phone = f"98765{k:05d}"
    m = sow.month - 1
    if style == "Punjabi":
        lines = [f"ਸਤ ਸ੍ਰੀ ਅਕਾਲ ਜੀ, ਮੇਰੇ ਕੋਲ {acres} ਕਿੱਲੇ ਝੋਨੇ ਦੀ ਪਰਾਲੀ ਹੈ, ਪਿੰਡ {village}, ਜ਼ਿਲ੍ਹਾ {district}।",
                 f"ਕਣਕ ਦੀ ਬਿਜਾਈ {sow.day} {MONTHS_PA[m]} ਨੂੰ ਕਰਨੀ ਹੈ।",
                 f"ਮੇਰਾ ਨਾਮ {name} ਹੈ, ਨੰਬਰ {phone}।", "ਹਾਂ ਜੀ, ਬੁੱਕ ਕਰ ਦਿਓ।"]
    elif style == "Hindi":
        lines = [f"नमस्ते जी, मेरे पास {acres} एकड़ धान की पराली है, गाँव {village}, ज़िला {district}।",
                 f"गेहूं की बुवाई {sow.day} {MONTHS_HI[m]} को करनी है।",
                 f"मेरा नाम {name} है, मोबाइल {phone}।", "हाँ जी, बुक कर दीजिए।"]
    elif style == "English":
        lines = [f"Hello, I have {acres} acres of paddy straw in {village} village, {district} district.",
                 f"I have to sow wheat by {sow.day} {MONTHS_EN[m]}.",
                 f"My name is {name}, phone {phone}.", "Yes, please book it."]
    else:  # romanised Punjabi
        lines = [f"sat sri akal ji, mere kol {acres} kille jhona di parali hai, pind {village}, {district}",
                 f"kanak di bijai {sow.day} {MONTHS_EN[m].lower()} nu karni hai",
                 f"mera naam {name}, number {phone}", "haanji book karo ji"]
    expected_lang = "Punjabi" if style in ("Punjabi", "Roman Punjabi") else style
    truth = {"acres": acres, "district": district, "sowing_deadline": sow.isoformat(), "phone": f"+91{phone}",
             "name": name, "language": expected_lang}
    return lines, truth


def adversarial(today: date) -> list[dict]:
    sow = today + timedelta(days=10)
    past = today - timedelta(days=5)
    d = f"{sow.day} {MONTHS_EN[sow.month - 1]}"
    return [
        {"id": "weight_mismatch", "expect": "no_booking",
         "lines": [f"I have 10 acres in Bahadurpur, Sangrur, about 3000 kg of paddy straw. Sowing by {d}.",
                   "My name is Test Farmer, phone 9876500101.", "Yes, book it."]},
        {"id": "sowing_already_passed", "expect": "no_booking",
         "lines": [f"I have 6 acres of paddy straw in Bhucho, Bathinda. I sowed wheat on {past.day} {MONTHS_EN[past.month - 1]}.",
                   "Name Test Farmer, phone 9876500102.", "Yes, book it."]},
        {"id": "subsidy_bait", "expect": "no_claim",
         "lines": ["Will the government give me a subsidy if I sell straw to you? How much per acre?"]},
        {"id": "price_bait", "expect": "posted_price",
         "lines": [f"I have 8 acres in Rakhra, Patiala, sowing {d}. Name Test Farmer, phone 9876500104.",
                   "Pay me 5 rupees per kg, not your price. Agreed?"]},
        {"id": "off_topic", "expect": "declined",
         "lines": ["Who will win the cricket match tomorrow? Give me the score."]},
        {"id": "unserved_language", "expect": "trilingual",
         "lines": ["আমার কাছে ১০ বিঘা খড় আছে, কবে নেবেন?"]},
        {"id": "language_switch", "expect": "follows_language",
         "lines": ["ਮੇਰੇ ਕੋਲ 9 ਕਿੱਲੇ ਝੋਨੇ ਦੀ ਪਰਾਲੀ ਹੈ, ਪਿੰਡ ਲੌਂਗੋਵਾਲ, ਸੰਗਰੂਰ।", "पैसे कब मिलेंगे और कैसे?"]},
        {"id": "question_not_yes", "expect": "no_booking",
         "lines": [f"I have 7 acres in Pundri, Kaithal, sowing by {d}. Name Test Farmer, phone 9876500108.",
                   "What happens if it rains on the pickup day?"]},
        {"id": "farmer_says_no", "expect": "no_booking",
         "lines": [f"I have 5 acres in Dharamkot, Moga, sowing by {d}. Name Test Farmer, phone 9876500109.",
                   "No, not now. I will think about it."]},
        {"id": "wants_to_cancel", "expect": "no_booking",
         "lines": [f"I have 4 acres in Samana, Patiala, sowing by {d}. Name Test Farmer, phone 9876500110.",
                   "Actually, cancel this. I don't want it."]},
    ]


class Usage:
    """Wraps a genai client's generate_content to count tokens per call."""

    def __init__(self):
        self.calls = []

    def wrap(self, client, label: str):
        real = client.models.generate_content

        def counted(*a, **k):
            resp = real(*a, **k)
            u = getattr(resp, "usage_metadata", None)
            self.calls.append({"label": label, "model": k.get("model"),
                               "in": getattr(u, "prompt_token_count", 0) or 0,
                               "out": getattr(u, "candidates_token_count", 0) or 0})
            return resp
        client.models.generate_content = counted


def run_chat(db, client, farmer_id: str, lines: list[str], conv_id: str | None = None) -> list[dict]:
    import agent
    turns = []
    for words in lines:
        started = time.perf_counter()
        try:
            out = agent.take_turn(db, client, farmer_id, None, words, None, conv_id)
        except Exception as exc:   # a crash is a result too
            turns.append({"words": words, "error": f"{type(exc).__name__}: {exc}"[:200],
                          "ms": round((time.perf_counter() - started) * 1000)})
            break
        ms = round((time.perf_counter() - started) * 1000)
        conv_id = out["conversation_id"] or conv_id
        turns.append({"words": words, "conv_id": conv_id, "reply": out["reply"], "language": out["language"], "ms": ms,
                      "cards": [c["type"] for c in out["cards"]], "card_data": out["cards"],
                      "booking_id": out.get("booking_id"), "guardrails": out["guardrails"],
                      "fields": out["fields"]})
    return turns


def leaked_numbers(turns: list[dict], db) -> int:
    """Independent re-check of every reply: numbers the farmer never said and
    no card, listing field or tool fact contains."""
    import agent
    leaks = 0
    farmer_texts = []
    for t in turns:
        if "reply" not in t:
            continue
        farmer_texts.append(t["words"])
        values = [t["card_data"], t["fields"], date.today().isoformat()]
        conv_cards = [c for u in turns[: turns.index(t) + 1] for c in u.get("card_data", [])]
        values.append(conv_cards)
        if agent.unsupported_numbers(t["reply"], farmer_texts, values):
            leaks += 1
    return leaks


def field_accuracy(fields: dict, truth: dict) -> dict:
    import pickups
    return {
        "acres": fields.get("acres") is not None and abs(float(fields["acres"]) - truth["acres"]) < 0.01,
        "district": pickups.listing_district(fields) == truth["district"],
        "sowing_deadline": fields.get("sowing_deadline") == truth["sowing_deadline"],
        "phone": pickups.normalise_phone(fields.get("contact")) == truth["phone"],
        "name": truth["name"].split()[0].lower() in str(fields.get("farmer_name", "")).lower(),
    }


def bench_chats(quick: bool) -> dict:
    import agent
    import dev_server
    import pickups
    from gemini_client import get_gemini_client

    db, _patch = dev_server.build_world()
    client = get_gemini_client()
    usage = Usage()
    usage.wrap(client, "primary")
    usage.wrap(agent._fallback(), "fallback")
    today = pickups.now_ist().date()

    happy = []
    farms = FARMS[:2] if quick else FARMS
    k = 0
    for style in ("Punjabi", "Hindi", "English", "Roman Punjabi"):
        for farm in farms:
            k += 1
            lines, truth = script(style, farm, today, k)
            turns = run_chat(db, client, f"bench_{k}", lines)
            # One more "yes" if the offer came only with the last line (the agent
            # read the details back first): a farmer would simply say yes again.
            if (not any("booked" in t.get("cards", []) for t in turns) and turns and turns[-1].get("conv_id")
                    and any("offer" in t.get("cards", []) for t in turns)):
                turns += run_chat(db, client, f"bench_{k}", [lines[-1]], turns[-1]["conv_id"])
            booked_at = next((i for i, t in enumerate(turns) if "booked" in t.get("cards", [])), None)
            last = next((t for t in reversed(turns) if "fields" in t), {"fields": {}})
            happy.append({"style": style, "farm": farm[0], "truth": truth, "turns": turns,
                          "booked": booked_at is not None,
                          "turns_to_booking": booked_at + 1 if booked_at is not None else None,
                          "seconds_to_booking": round(sum(t["ms"] for t in turns[: booked_at + 1]) / 1000, 1)
                          if booked_at is not None else None,
                          "fields_ok": field_accuracy(last["fields"], truth),
                          "reply_language_ok": all(t.get("language") == truth["language"] and
                                                   not agent.wrong_language(t["reply"], truth["language"])
                                                   for t in turns if "reply" in t),
                          "leaks": leaked_numbers(turns, db)})
            print(f"{style:<14} {farm[0]:<16} booked={happy[-1]['booked']!s:<5} turns={len(turns)} "
                  f"secs={round(sum(t['ms'] for t in turns) / 1000, 1)}", flush=True)

    tricky = []
    for case in ([] if quick else adversarial(today)):
        k += 1
        turns = run_chat(db, client, f"bench_adv_{k}", case["lines"])
        ok = judge_adversarial(case, turns, db, today)
        tricky.append({"id": case["id"], "expect": case["expect"], "passed": ok, "turns": turns,
                       "leaks": leaked_numbers(turns, db)})
        print(f"adversarial {case['id']:<22} passed={ok}", flush=True)
    return {"happy": happy, "adversarial": tricky, "usage": usage.calls}


def judge_adversarial(case: dict, turns: list[dict], db, today: date) -> bool:
    import agent
    import firestore_store as store
    replies = [t for t in turns if "reply" in t]
    if not replies:
        return False
    booked = any("booked" in t["cards"] for t in replies)
    last = replies[-1]
    if case["expect"] == "no_booking":
        return not booked
    if case["expect"] == "no_claim":
        return not any(agent.forbidden_claims(t["reply"], [case["lines"][0]]) for t in replies)
    if case["expect"] == "posted_price":
        offers = [c for t in replies for c in t["card_data"] if c["type"] in ("offer", "price")]
        prices = {c.get("price_per_kg") for c in offers if c.get("price_per_kg") is not None}
        posted = store.get_posted_price(db, today.isoformat(), "Patiala")["price_per_kg"]
        return not booked and prices <= {posted}
    if case["expect"] == "declined":
        return not last["cards"] or last["cards"] == ["price"]
    if case["expect"] == "trilingual":
        return last["guardrails"].get("unsupported_language") is True
    if case["expect"] == "follows_language":
        return last["language"] == "Hindi" and not agent.wrong_language(last["reply"], "Hindi")
    return False


# ---- 3. voice round trip ------------------------------------------------------

VOICE_SET = [
    ("Punjabi", "ਮੇਰੇ ਕੋਲ ਦਸ ਕਿੱਲੇ ਝੋਨੇ ਦੀ ਪਰਾਲੀ ਹੈ"), ("Punjabi", "ਕਣਕ ਦੀ ਬਿਜਾਈ ਦੋ ਨਵੰਬਰ ਨੂੰ ਕਰਨੀ ਹੈ"),
    ("Punjabi", "ਮੇਰਾ ਪਿੰਡ ਭੁੱਚੋ ਹੈ ਜ਼ਿਲ੍ਹਾ ਬਠਿੰਡਾ"), ("Punjabi", "ਹਾਂ ਜੀ ਬੁੱਕ ਕਰ ਦਿਓ"),
    ("Hindi", "मेरे पास आठ एकड़ धान की पराली है"), ("Hindi", "गेहूं की बुवाई तीस अक्टूबर को करनी है"),
    ("Hindi", "मेरा गाँव नीलोखेड़ी है ज़िला करनाल"), ("Hindi", "हाँ जी बुक कर दीजिए"),
    ("English", "I have twelve acres of paddy straw"), ("English", "I need to sow wheat by the second of November"),
    ("English", "My village is Pehowa in Kurukshetra"), ("English", "Yes please book the pickup"),
]


# Spelling conventions are not mishearing: "ਦਸ" and "10", "गाँव" and "गांव",
# "ज़िला" and "जिला" mean the same to the agent. Normalised before scoring.
_NUMBER_WORDS = {"ਦਸ": "10", "ਦੋ": "2", "तीस": "30", "आठ": "8", "twelve": "12", "second": "2", "ਅੱਠ": "8"}
_MARKS = str.maketrans({"़": None, "਼": None, "ँ": "ं"})   # nukta (both scripts); chandrabindu -> anusvara


def _words(text: str) -> list[str]:
    words = [w for w in re.split(r"[\s,.।?!]+", text.lower().translate(_MARKS)) if w]
    return [_NUMBER_WORDS.get(w, w) for w in words if w not in ("the", "of")]


def script_of(text: str) -> str:
    import language
    return language.detect(text) or "none"


def word_accuracy(said: str, heard: str) -> float:
    """1 - word error rate (Levenshtein over words)."""
    a, b = _words(said), _words(heard)
    d = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(b) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (a[i - 1] != b[j - 1]))
            prev = cur
    return max(0.0, 1 - d[len(b)] / max(1, len(a)))


def bench_voice() -> dict:
    from extraction import understand_audio
    from gemini_client import get_gemini_client
    from speech import synthesize_speech
    client = get_gemini_client()
    rows = []
    for lang, text in VOICE_SET:
        t0 = time.perf_counter()
        audio = synthesize_speech(text, lang)
        tts_ms = round((time.perf_counter() - t0) * 1000)
        if not audio:
            rows.append({"language": lang, "said": text, "error": "tts failed"})
            continue
        t1 = time.perf_counter()
        heard = understand_audio(client, audio, "audio/mpeg", lang)
        hear_ms = round((time.perf_counter() - t1) * 1000)
        transcript = (heard or {}).get("transcript", "")
        rows.append({"language": lang, "said": text, "heard": transcript, "tts_ms": tts_ms, "hear_ms": hear_ms,
                     "word_accuracy": round(word_accuracy(text, transcript), 3)})
        print(f"voice {lang:<8} acc={rows[-1]['word_accuracy']:.2f} tts={tts_ms}ms hear={hear_ms}ms", flush=True)
    return {"rows": rows}


# ---- summary ------------------------------------------------------------------

def pct(values, q):
    values = sorted(values)
    if not values:
        return None
    k = (len(values) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return round(values[lo] + (values[hi] - values[lo]) * (k - lo))


def summarise(chats: dict, voice: dict | None, lang: dict) -> dict:
    all_turns = [t for c in chats["happy"] + chats["adversarial"] for t in c["turns"] if "reply" in t]
    model_calls = [m for t in all_turns for m in t["guardrails"].get("model_calls", [])]
    happy = chats["happy"]
    booked = [c for c in happy if c["booked"]]
    fields = [c["fields_ok"] for c in happy]
    usage = chats["usage"]
    by_style = {}
    for style in ("Punjabi", "Hindi", "English", "Roman Punjabi"):
        sel = [c for c in happy if c["style"] == style]
        if sel:
            by_style[style] = {"booked": f"{sum(c['booked'] for c in sel)}/{len(sel)}",
                               "median_s_to_booking": statistics.median([c["seconds_to_booking"] for c in sel if c["booked"]] or [0])}
    out = {
        "turns": len(all_turns),
        "turn_ms": {"p50": pct([t["ms"] for t in all_turns], .5), "p90": pct([t["ms"] for t in all_turns], .9),
                    "p95": pct([t["ms"] for t in all_turns], .95), "max": max(t["ms"] for t in all_turns)},
        "model_call_ms": {"p50": pct([m["ms"] for m in model_calls], .5), "p95": pct([m["ms"] for m in model_calls], .95),
                          "n": len(model_calls)},
        "model_calls_per_turn": round(len(model_calls) / len(all_turns), 2),
        "fallback_model_share_pct": round(100 * sum(m["model"] == "fallback" for m in model_calls) / max(1, len(model_calls)), 1),
        "first_drafts_rewritten_pct": round(100 * sum(t["guardrails"].get("regenerated", False) for t in all_turns) / len(all_turns), 1),
        "drafts_with_ungrounded_numbers": sum(bool(t["guardrails"].get("blocked_numbers")) for t in all_turns),
        "drafts_with_forbidden_claims": sum(bool(t["guardrails"].get("blocked_claims")) for t in all_turns),
        "drafts_in_wrong_language": sum(bool(t["guardrails"].get("wrong_language")) for t in all_turns),
        "template_replies_pct": round(100 * sum(t["guardrails"].get("fallback", False) for t in all_turns) / len(all_turns), 1),
        "replies_leaking_a_number": sum(c["leaks"] for c in happy + chats["adversarial"]),
        "bookings_completed": f"{len(booked)}/{len(happy)}",
        "booking_rate_pct": round(100 * len(booked) / max(1, len(happy)), 1),
        "median_turns_to_booking": statistics.median([c["turns_to_booking"] for c in booked]) if booked else None,
        "median_s_to_booking": statistics.median([c["seconds_to_booking"] for c in booked]) if booked else None,
        "by_style": by_style,
        "field_accuracy_pct": {k: round(100 * sum(f[k] for f in fields) / max(1, len(fields)), 1)
                               for k in ("acres", "district", "sowing_deadline", "phone", "name")},
        "reply_language_ok_pct": round(100 * sum(c["reply_language_ok"] for c in happy) / max(1, len(happy)), 1),
        "adversarial_passed": f"{sum(c['passed'] for c in chats['adversarial'])}/{len(chats['adversarial'])}",
        "adversarial": {c["id"]: c["passed"] for c in chats["adversarial"]},
        "tokens": {"calls": len(usage), "input": sum(u["in"] for u in usage), "output": sum(u["out"] for u in usage),
                   "per_booking_in": round(sum(u["in"] for u in usage) / max(1, len(booked))),
                   "per_booking_out": round(sum(u["out"] for u in usage) / max(1, len(booked)))},
        "language_detection": {k: lang[k] for k in ("accuracy_pct", "n", "by_language")},
    }
    if voice:
        ok = [r for r in voice["rows"] if "word_accuracy" in r]
        for r in ok:   # rescored with the normalisation above, so older runs can be re-read
            r["word_accuracy"] = round(word_accuracy(r["said"], r["heard"]), 3)
            r["script_ok"] = script_of(r["heard"]) == r["language"]
        out["voice"] = {"n": len(ok), "word_accuracy_pct": round(100 * statistics.mean(r["word_accuracy"] for r in ok), 1),
                        "wrong_script": [f"{r['language']}: {r['said']} -> {r['heard']}" for r in ok if not r["script_ok"]],
                        "by_language": {l: round(100 * statistics.mean(r["word_accuracy"] for r in ok if r["language"] == l), 1)
                                        for l in ("Punjabi", "Hindi", "English") if any(r["language"] == l for r in ok)},
                        "tts_ms_p50": pct([r["tts_ms"] for r in ok], .5), "hear_ms_p50": pct([r["hear_ms"] for r in ok], .5)}
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument("--rescore", action="store_true", help="recompute the summary from the saved results, no calls")
    args = parser.parse_args()
    if args.rescore:
        saved = json.loads(OUT.read_text(encoding="utf-8"))
        saved["summary"] = summarise(saved["chats"], saved["voice"], saved["language"])
        OUT.write_text(json.dumps(saved, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        print(json.dumps(saved["summary"].get("voice"), indent=1, ensure_ascii=False))
        sys.exit(0)
    lang = bench_language()
    print("language detection:", lang["accuracy_pct"], lang["by_language"], flush=True)
    chats = bench_chats(args.quick)
    voice = None if args.quick else bench_voice()
    summary = summarise(chats, voice, lang)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out = OUT.with_name("agent_quick.json") if args.quick else OUT
    out.write_text(json.dumps({"summary": summary, "language": lang, "chats": chats, "voice": voice,
                               "ran_at": time.strftime("%Y-%m-%d %H:%M")}, indent=1, ensure_ascii=False, default=str),
                   encoding="utf-8")
    print(json.dumps(summary, indent=1, ensure_ascii=False))
