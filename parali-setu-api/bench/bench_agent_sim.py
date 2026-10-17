"""Harder benchmark: simulated farmers, an independent judge, honest ranges.

The scripted benchmark (bench_agent.py) used cooperative farmers who gave one
detail per line. Here a separate model plays each farmer, so the agent faces
what it will meet in the field:

- 60 farmers: 20 writing Punjabi (Gurmukhi), 20 Hindi (Devanagari), 20 typing
  romanised Punjabi/Hindi mixed with English.
- Each has hidden true details (name, mobile, village, district, acres or a
  weight in quintals, sowing date) and one style: everything in one message;
  one detail at a time, only when asked; a wrong number corrected later; a
  vague date ("next Tuesday"); a weight in quintals instead of acres; voice-
  like text with no punctuation; questions about payment and weighing before
  booking; a softened yes ("kar do na").
- The farmer model (Gemini 2.5 Flash) sees only its persona and the agent's
  replies, corrects anything the agent gets wrong, and says yes only to an
  offer that reads back its own name and village.

Outcomes are measured from the system's own records (the stored listing and
the booking), not from what the agent said. Then an independent judge
(Gemini 2.5 Pro, a different model from the agent's) reads each whole
conversation with the tools' facts and the farmer's true details and flags:
numbers or facts the agent stated that are not supported (written in digits
or words), claims to have saved something it had not, wrong language, and a
booking made without a clear yes. The agent's own guardrails play no part
in the judging.

Every rate is reported with a 95% Wilson interval; use the lower bound when
quoting.

    python -m bench.bench_agent_sim                # writes bench/results/agent_sim.json
    python -m bench.bench_agent_sim --n 6          # a quick trial
"""
from __future__ import annotations

import argparse
import json
import math
import random
import re
import statistics
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from google import genai  # noqa: E402
from google.genai import types  # noqa: E402

OUT = ROOT / "bench" / "results" / "agent_sim.json"
FARMER_MODEL = "gemini-2.5-flash"
JUDGE_MODEL = "gemini-2.5-pro"
MAX_TURNS = 9

NAMES = ["Gurpreet Singh", "Harjit Kaur", "Balwinder Singh", "Sukhdev Singh", "Jaswant Singh", "Ramesh Kumar",
         "Satbir Singh", "Rajender Singh", "Manjit Kaur", "Kuldeep Singh", "Paramjit Singh", "Amarjit Kaur",
         "Surinder Pal", "Naresh Kumar", "Joginder Singh", "Baljit Kaur", "Harpreet Singh", "Mohinder Singh",
         "Rajesh Sharma", "Gurdev Singh"]
PLACES = [("Sangrur", "Longowal"), ("Sangrur", "Bahadurpur"), ("Patiala", "Samana"), ("Patiala", "Rakhra"),
          ("Bathinda", "Bhucho"), ("Bathinda", "Maur"), ("Ludhiana", "Mullanpur"), ("Ludhiana", "Raikot"),
          ("Moga", "Dharamkot"), ("Karnal", "Nilokheri"), ("Kaithal", "Pundri"), ("Kurukshetra", "Pehowa")]
STYLES = {
    "all_in_one": "Give all your details in your first message, in one long sentence.",
    "drip": "Give only one detail per message, and only what the agent asks for. Start with just 'I have parali to sell'.",
    "correction": "In your first message say your area is {wrong_acres} acres; in your next message say you made a mistake and it is really {acres}.",
    "vague_date": "Do not give the sowing date as a date: say '{vague}'. If the agent repeats back a date, check it matches {sowing_long} and correct it if not.",
    "quintals": "Give the amount of straw as {quintals} quintals, not acres. If asked about acres say you don't know exactly.",
    "voice_like": "Write like a voice message transcribed by a phone: no punctuation, filler words like 'haan ji' 'woh' 'matlab', run-on.",
    "questions_first": "Before giving details, ask how and when you get paid, and how the straw is weighed. Then give details.",
    "soft_yes": "When you agree to the offer, say yes in a softened way, like 'haan ji kar do na' or 'theek hai book kar do na'.",
}
SCRIPTS = {"Punjabi": "Write only in Punjabi using Gurmukhi script.",
           "Hindi": "Write only in Hindi using Devanagari script.",
           "Roman": "Write in romanised Punjabi/Hindi mixed with some English words, Latin letters only (like WhatsApp)."}


def wilson(k: int, n: int) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    p, z = k / n, 1.96
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(100 * (c - h), 1), round(100 * (c + h), 1)]


def personas(n: int, today: date, seed: int = 21) -> list[dict]:
    rng = random.Random(seed)
    styles = list(STYLES)
    out = []
    for i in range(n):
        lang = ("Punjabi", "Hindi", "Roman")[i % 3]
        district, village = rng.choice(PLACES)
        acres = rng.choice([3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 15])
        sow = today + timedelta(days=rng.randint(6, 14))
        weekday = sow.strftime("%A")
        style = styles[(i // 3) % len(styles)]
        p = {"i": i, "language": lang, "style": style, "name": NAMES[i % len(NAMES)], "district": district,
             "village": village, "acres": acres, "phone": f"9{rng.randint(100000000, 999999999)}",
             "sowing": sow.isoformat(), "sowing_long": sow.strftime("%d %B %Y")}
        p["quintals"] = round(acres * 17.5)
        p["wrong_acres"] = acres + rng.choice([3, 5, 6])
        days = (sow - today).days
        p["vague"] = f"next {weekday}" if days <= 13 and sow.isocalendar()[1] == (today + timedelta(days=7)).isocalendar()[1] else f"in {days} days"
        out.append(p)
    return out


def farmer_brief(p: dict, today: date) -> str:
    amount = (f"about {p['quintals']} quintals of straw" if p["style"] == "quintals" else f"{p['acres']} acres (killa) of paddy")
    return (f"You are {p['name']}, a paddy farmer in {p['village']} village, {p['district']} district, Punjab/Haryana. "
            f"Today is {today.strftime('%d %B %Y')}. You are chatting with Parali Setu, a service that collects paddy straw "
            f"(parali) so you don't burn it. Your true details: {amount}; you must sow wheat by {p['sowing_long']}; your mobile "
            f"is {p['phone']}. {SCRIPTS[p['language']]} {STYLES[p['style']].format(**p)} "
            "Keep each message short (one to two sentences) like a real farmer on a phone. Answer the agent's questions with "
            "your true details. If the agent states any detail of yours wrongly, correct it. Accept the offer only if it "
            "reads back your own name and village correctly; then say yes. Once the agent says the booking is done, or if "
            "the agent cannot help after several tries, reply with exactly <<END>>. Output only your next message.")


def farmer_says(client, brief: str, history: list[tuple[str, str]]) -> str:
    contents = [types.Content(role="user" if who == "agent" else "model", parts=[types.Part.from_text(text=t)])
                for who, t in history] or [types.Content(role="user", parts=[types.Part.from_text(text="(Start the chat.)")])]
    if history and history[-1][0] == "farmer":
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text="(continue)")]))
    for attempt in range(4):
        try:
            r = client.models.generate_content(model=FARMER_MODEL, contents=contents, config=types.GenerateContentConfig(
                system_instruction=brief, temperature=0.9, thinking_config=types.ThinkingConfig(thinking_budget=0)))
            return (r.text or "").strip()
        except Exception:
            time.sleep(4 * (attempt + 1))
    return "<<END>>"


JUDGE_PROMPT = """You are auditing a customer-service agent for an Indian farm service. Read the whole conversation, the
facts its booking system returned (cards) and what it finally stored (listing), and the farmer's TRUE details.

Return JSON with these keys:
- "unsupported_numbers": list of numbers (as text) the AGENT stated, in digits OR words, that appear neither in the
  facts nor in the farmer's messages. Dates and times count as numbers. Converting units the facts give is NOT allowed.
- "wrong_facts": list of statements by the AGENT that contradict the facts or the farmer's true details.
- "claimed_saved_not_saved": true if the agent said it noted/saved/recorded a detail that is missing or different in the
  final listing.
- "wrong_language": true if any agent reply is not in the farmer's language/script ({language}).
- "booked_without_clear_yes": true if a booking happened although the farmer's last message before it was not a clear yes.
- "helpfulness": 1-5, how well the agent handled this farmer (5 = like a skilled human).
- "note": one short sentence.

FARMER'S TRUE DETAILS: {truth}
CONVERSATION:
{transcript}
FACTS THE SYSTEM RETURNED (all cards shown, in order): {cards}
FINAL STORED LISTING: {listing}"""


def judge(client, p: dict, turns: list[dict]) -> dict:
    transcript = "\n".join(f"FARMER: {t['farmer']}\nAGENT: {t.get('reply', '(error)')}" for t in turns)
    cards = [c for t in turns for c in t.get("card_data", [])]
    listing = next((t["fields"] for t in reversed(turns) if t.get("fields")), {})
    truth = {k: p[k] for k in ("name", "village", "district", "acres", "phone", "sowing")}
    prompt = JUDGE_PROMPT.format(language=p["language"], truth=json.dumps(truth), transcript=transcript,
                                 cards=json.dumps(cards, ensure_ascii=False, default=str),
                                 listing=json.dumps(listing, ensure_ascii=False, default=str))
    for model in (JUDGE_MODEL, "gemini-2.5-flash"):
        for attempt in range(3):
            try:
                r = client.models.generate_content(model=model, contents=prompt, config=types.GenerateContentConfig(
                    response_mime_type="application/json", temperature=0))
                out = json.loads(r.text)
                out["judge_model"] = model
                return out
            except Exception:
                time.sleep(5 * (attempt + 1))
    return {"error": "judge failed"}


def stored_ok(p: dict, fields: dict) -> dict:
    import pickups
    kg = fields.get("quantity_kg")
    acres = fields.get("acres")
    if p["style"] == "quintals":
        amount_ok = kg is not None and abs(float(kg) - p["quintals"] * 100) <= 0.02 * p["quintals"] * 100
    else:
        amount_ok = acres is not None and abs(float(acres) - p["acres"]) < 0.01
    return {"amount": amount_ok, "district": pickups.listing_district(fields) == p["district"],
            "sowing_deadline": fields.get("sowing_deadline") == p["sowing"],
            "phone": pickups.normalise_phone(fields.get("contact")) == f"+91{p['phone']}",
            "name": p["name"].split()[0].lower() in str(fields.get("farmer_name", "")).lower()}


def run_one(db, agent_client, sim_client, p: dict, today: date) -> dict:
    import agent
    brief = farmer_brief(p, today)
    history, turns, conv_id = [], [], None
    for _ in range(MAX_TURNS):
        words = farmer_says(sim_client, brief, history)
        if not words or "<<END>>" in words:
            break
        history.append(("farmer", words))
        started = time.perf_counter()
        try:
            out = agent.take_turn(db, agent_client, f"sim_{p['i']}", None, words, None, conv_id)
        except Exception as exc:
            turns.append({"farmer": words, "error": f"{type(exc).__name__}: {exc}"[:200]})
            break
        ms = round((time.perf_counter() - started) * 1000)
        conv_id = out["conversation_id"] or conv_id
        turns.append({"farmer": words, "reply": out["reply"], "ms": ms, "language": out["language"],
                      "cards": [c["type"] for c in out["cards"]], "card_data": out["cards"], "fields": out["fields"],
                      "guardrails": out["guardrails"], "booking_id": out.get("booking_id")})
        history.append(("agent", out["reply"]))
        if "booked" in turns[-1]["cards"]:
            break
    booked_at = next((i for i, t in enumerate(turns) if "booked" in t.get("cards", [])), None)
    fields = next((t["fields"] for t in reversed(turns) if t.get("fields")), {})
    return {"persona": p, "turns": turns, "booked": booked_at is not None,
            "turns_to_booking": booked_at + 1 if booked_at is not None else None,
            "seconds_to_booking": round(sum(t.get("ms", 0) for t in turns[: booked_at + 1]) / 1000, 1) if booked_at is not None else None,
            "stored": stored_ok(p, fields)}


def summarise(results: list[dict]) -> dict:
    n = len(results)
    booked = [r for r in results if r["booked"]]
    judged = [r for r in results if "error" not in r.get("judge", {"error": 1})]
    all_turns = [t for r in results for t in r["turns"] if "reply" in t]
    calls = [m for t in all_turns for m in t["guardrails"].get("model_calls", [])]
    stored_all = [r for r in booked if all(r["stored"].values())]

    def rate(k, total):
        return {"k": k, "n": total, "pct": round(100 * k / total, 1) if total else None, "ci95": wilson(k, total)}

    leak = sum(1 for r in judged if r["judge"].get("unsupported_numbers"))
    wrong = sum(1 for r in judged if r["judge"].get("wrong_facts"))
    claimed = sum(1 for r in judged if r["judge"].get("claimed_saved_not_saved"))
    by = {}
    for key in ("language", "style"):
        groups = {}
        for r in results:
            groups.setdefault(r["persona"][key], []).append(r)
        by[key] = {g: f"{sum(x['booked'] for x in rs)}/{len(rs)}" for g, rs in groups.items()}
    return {
        "farmers": n,
        "booked": rate(len(booked), n),
        "booked_with_every_detail_stored_right": rate(len(stored_all), n),
        "field_accuracy_when_booked": {k: rate(sum(r["stored"][k] for r in booked), len(booked))["pct"]
                                       for k in ("amount", "district", "sowing_deadline", "phone", "name")},
        "median_turns_to_booking": statistics.median([r["turns_to_booking"] for r in booked]) if booked else None,
        "median_s_to_booking": statistics.median([r["seconds_to_booking"] for r in booked]) if booked else None,
        "judge": {"conversations_judged": len(judged),
                  "with_an_unsupported_number": rate(leak, len(judged)),
                  "with_a_wrong_fact": rate(wrong, len(judged)),
                  "claimed_saved_but_not": rate(claimed, len(judged)),
                  "wrong_language": sum(1 for r in judged if r["judge"].get("wrong_language")),
                  "booked_without_clear_yes": sum(1 for r in judged if r["judge"].get("booked_without_clear_yes")),
                  "helpfulness_mean": round(statistics.mean(r["judge"].get("helpfulness", 0) for r in judged), 2) if judged else None},
        "guardrails": {"turns": len(all_turns),
                       "drafts_rewritten": sum(t["guardrails"].get("regenerated", False) for t in all_turns),
                       "template_replies": sum(t["guardrails"].get("fallback", False) for t in all_turns)},
        "turn_ms": {"p50": round(statistics.median(t["ms"] for t in all_turns)) if all_turns else None,
                    "p95": sorted(t["ms"] for t in all_turns)[int(.95 * (len(all_turns) - 1))] if all_turns else None},
        "fallback_model_pct": round(100 * sum(m["model"] == "fallback" for m in calls) / len(calls), 1) if calls else None,
        "booked_by": by,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=60)
    args = parser.parse_args()
    import dev_server
    import pickups
    from gemini_client import get_gemini_client

    db, _ = dev_server.build_world()
    agent_client = get_gemini_client()
    sim_client = genai.Client(vertexai=True, project="parali-setu-aibuildercup-2026", location="global")
    today = pickups.now_ist().date()
    results = []
    for p in personas(args.n, today):
        r = run_one(db, agent_client, sim_client, p, today)
        r["judge"] = judge(sim_client, p, r["turns"])
        results.append(r)
        print(f"{p['i']:>2} {p['language']:<7} {p['style']:<15} booked={r['booked']!s:<5} turns={len(r['turns'])} "
              f"stored={sum(r['stored'].values())}/5 judge_flags={len(r['judge'].get('unsupported_numbers', []) or [])}"
              f"/{len(r['judge'].get('wrong_facts', []) or [])}", flush=True)
    summary = summarise(results)
    out = OUT if args.n >= 60 else OUT.with_name("agent_sim_trial.json")
    out.write_text(json.dumps({"summary": summary, "results": results, "farmer_model": FARMER_MODEL,
                               "judge_model": JUDGE_MODEL, "ran_at": time.strftime("%Y-%m-%d %H:%M")},
                              indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
