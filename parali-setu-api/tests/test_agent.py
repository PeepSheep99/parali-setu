"""The talking agent with a scripted model: tools run for real against the
in-memory world, and the code-level guardrails (numbers, explicit yes,
cross-checks, fallback) are exercised without calling Gemini."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

import agent
import firestore_store as store
import main

TODAY = date(2026, 10, 17)


# ---- pure guardrails

def test_numbers_are_read_in_any_script_and_grouping():
    assert agent.numbers_in("₹17,500 और १७५०० और ੧੦ ਕਿੱਲੇ, 0.76") == {17500.0, 10.0, 0.76}
    tool = {"booking_id": "booking_fc851f2d86", "price_per_kg": 0.76, "payout_inr": 13300.0,
            "pickup_window": "2026-10-19 09:00-12:00"}
    assert agent.unsupported_numbers("price 0.76, you get 13,300 at 09:00", [], [tool]) == set()
    assert agent.unsupported_numbers("price 2 per kg", [], [tool]) == {2.0}, "digits inside an id license nothing"
    assert agent.unsupported_numbers("10 acres", ["ਦਸ ਕਿੱਲੇ, 10 ਕਿੱਲੇ"], []) == set(), "the farmer's own numbers are fine"


def test_cross_checks_flag_what_the_agent_must_ask_about():
    fields = {"acres": 10, "quantity_kg": 3000, "sowing_deadline": "2026-10-10", "ready_by": "2026-10-20",
              "village_or_district": "Atlantis"}
    codes = {w["code"] for w in agent.listing_warnings(fields, {"acres", "quantity_kg"}, TODAY)}
    assert codes == {"acres_weight_mismatch", "sowing_date_passed", "ready_after_sowing", "place_not_recognised"}
    derived = {"acres": 10, "quantity_kg": 17500.0, "village_or_district": "Sangrur"}
    assert agent.listing_warnings(derived, {"acres"}, TODAY) == [], "a weight we derived ourselves is not a mismatch"


@pytest.mark.parametrize("words,english,expected", [
    ("ਹਾਂ ਜੀ, ਕਰ ਦਿਓ", "Yes, do it", True),
    ("हाँ, बुक कर दो", None, True),
    ("ok", None, True),
    ("ਕੀ ਇਹ ਪੱਕਾ ਹੈ?", "Is it certain?", False),
    ("ਨਹੀਂ, ਹਾਲੇ ਨਹੀਂ", "No, not yet", False),
    ("ਮੈਂ ਸੋਚ ਕੇ ਦੱਸਾਂਗਾ", "I will think and tell you", False),
])
def test_only_the_farmers_own_yes_counts(words, english, expected):
    assert agent.farmer_affirmed(words, english) is expected


# ---- scripted conversations

class Script:
    """Plays the model: each step is either a list of tool calls or a
    function that builds the reply text from the latest tool results."""

    def __init__(self, steps):
        self.steps = list(steps)

    def __call__(self, client, contents, config):
        step = self.steps.pop(0)
        if callable(step):
            return [], step(_last_results(contents)), None
        return step, None, None


def _last_results(contents) -> dict:
    results = {}
    for content in contents:
        for part in content.parts or []:
            if part.function_response is not None:
                results[part.function_response.name] = part.function_response.response["result"]
    return results


@pytest.fixture
def chat(world, monkeypatch):
    def run(script, words, conversation_id=None, language="Punjabi"):
        monkeypatch.setattr(agent, "_generate", Script(script))
        return agent.take_turn(world, None, "farmer_a", language, words, f"(en) {words}", conversation_id)
    return run


SANGRUR_CALL = ("update_listing", {"acres": 10, "crop_type": "rice_stubble", "village_or_district": "Bahadurpur, Sangrur",
                                   "sowing_deadline": "2026-10-24", "farmer_name": "Gurmeet Singh",
                                   "contact": "98765 43210"})


def _offer_text(r):
    o = r["find_pickup_slot"]
    return f"ਅੱਜ ਦਾ ਭਾਅ ₹{o['price_per_kg']}, ਤੁਹਾਨੂੰ ₹{o['payout_inr']:,.0f} ਮਿਲਣਗੇ, ਪਿਕਅੱਪ {o['pickup_window']}. ਬੁੱਕ ਕਰਾਂ?"


def test_a_full_conversation_books_only_after_an_explicit_yes(chat, world):
    first = chat([[SANGRUR_CALL], [("find_pickup_slot", {})], _offer_text], "ਦਸ ਕਿੱਲੇ ਝੋਨਾ, ਬਹਾਦੁਰਪੁਰ ਸੰਗਰੂਰ, 24 ਤਰੀਕ ਤੱਕ ਕਣਕ")
    assert first["guardrails"]["fallback"] is False and first["guardrails"]["blocked_numbers"] == []
    offer = next(c for c in first["cards"] if c["type"] == "offer")
    assert offer["kg"] == 17500.0 and offer["payout_inr"] == round(17500 * offer["price_per_kg"], 2)
    assert store.get_booking(world, first["booking_id"])["status"] == "offered"

    # The farmer only asks a question; the model claims a yes anyway: refused.
    eager = chat([[("confirm_booking", {"farmer_said_yes": True})], lambda r: "ਜੀ, ਇਹ ਪੱਕਾ ਸਮਾਂ ਹੈ"], "ਕੀ ਇਹ ਪੱਕਾ ਹੈ?",
                 first["conversation_id"])
    assert eager["guardrails"]["tool_calls"][0]["ok"] is False
    assert store.get_booking(world, first["booking_id"])["status"] == "offered"
    second = chat([[("confirm_booking", {"farmer_said_yes": True})],
                   lambda r: f"ਬੁੱਕ ਹੋ ਗਿਆ: {r['confirm_booking']['pickup_window']}"], "ਹਾਂ ਜੀ, ਕਰ ਦਿਓ",
                  first["conversation_id"])
    assert store.get_booking(world, first["booking_id"])["status"] == "booked"
    assert any(c["type"] == "booked" for c in second["cards"])
    turns = store.get_conversation(world, first["conversation_id"])["turns"]
    assert turns[0]["english"].startswith("(en)") and len(turns) == 6
    assert store.get_conversation(world, first["conversation_id"])["fields"]["acres"] == 10


def test_confirming_in_the_same_turn_as_the_offer_is_refused(chat, world):
    result = chat([[SANGRUR_CALL], [("find_pickup_slot", {})], [("confirm_booking", {"farmer_said_yes": True})],
                   _offer_text], "ਦਸ ਕਿੱਲੇ ਝੋਨਾ ਸੰਗਰੂਰ, 24 ਤਰੀਕ ਤੱਕ, ਬੁੱਕ ਕਰ ਦਿਓ")
    confirm = next(c for c in result["guardrails"]["tool_calls"] if c["name"] == "confirm_booking")
    assert confirm["ok"] is False
    assert store.get_booking(world, result["booking_id"])["status"] == "offered"


def test_an_invented_number_is_blocked_then_replaced_by_the_template(chat):
    result = chat([[SANGRUR_CALL], [("find_pickup_slot", {})], lambda r: "ਭਾਅ ₹77 ਪ੍ਰਤੀ ਕਿਲੋ ਹੈ",
                   lambda r: "ਭਾਅ ₹78 ਪ੍ਰਤੀ ਕਿਲੋ ਹੈ"], "ਦਸ ਕਿੱਲੇ ਝੋਨਾ ਸੰਗਰੂਰ, 24 ਤਰੀਕ ਤੱਕ")
    g = result["guardrails"]
    assert g["blocked_numbers"] == [77.0] and g["regenerated"] and g["fallback"]
    offer = next(c for c in result["cards"] if c["type"] == "offer")
    assert f"₹{offer['price_per_kg']:g}" in result["reply"] and offer["pickup_window_spoken"] in result["reply"]


def test_a_corrected_reply_passes_after_one_regeneration(chat):
    result = chat([[SANGRUR_CALL], [("find_pickup_slot", {})], lambda r: "ਭਾਅ ₹77 ਹੈ", _offer_text],
                  "ਦਸ ਕਿੱਲੇ ਝੋਨਾ ਸੰਗਰੂਰ, 24 ਤਰੀਕ ਤੱਕ")
    assert result["guardrails"]["regenerated"] and not result["guardrails"]["fallback"]


def test_missing_details_and_mismatches_come_back_as_questions(chat):
    result = chat([[("update_listing", {"acres": 10, "quantity_kg": 2000})],
                   lambda r: "ਦਸ ਕਿੱਲਿਆਂ ਵਿੱਚ ਆਮ ਤੌਰ ਤੇ 17500 ਕਿਲੋ ਹੁੰਦੀ ਹੈ, ਤੁਸੀਂ 2000 ਕਿਹਾ। ਕਿਹੜਾ ਸਹੀ ਹੈ?"],
                  "10 ਕਿੱਲੇ, 2000 ਕਿਲੋ ਪਰਾਲੀ")
    draft = next(c for c in result["cards"] if c["type"] == "draft")
    assert {w["code"] for w in draft["warnings"]} == {"acres_weight_mismatch"}
    assert set(draft["missing_fields"]) == {"crop_type", "location", "sowing_deadline", "name", "phone"}
    assert result["guardrails"]["fallback"] is False, "17500 came from the tool, so the reply may say it"


def test_booking_needs_complete_details_and_valid_dates(chat):
    result = chat([[("find_pickup_slot", {})], lambda r: "ਪਹਿਲਾਂ ਦੱਸੋ"], "ਪਿਕਅੱਪ ਚਾਹੀਦਾ")
    assert result["guardrails"]["tool_calls"][0]["ok"] is False and result["booking_id"] is None


def test_when_the_model_is_unavailable_the_farmer_still_gets_an_answer(world, monkeypatch):
    monkeypatch.setattr(agent, "_generate", lambda c, contents, config: ([], None, None))
    result = agent.take_turn(world, None, "farmer_b", "Hindi", "नमस्ते", "hello")
    assert result["guardrails"]["fallback"] and result["reply"].startswith("नमस्ते")


def test_a_conversation_belongs_to_one_farmer(chat, world):
    first = chat([lambda r: "ਸਤ ਸ੍ਰੀ ਅਕਾਲ"], "ਸਤ ਸ੍ਰੀ ਅਕਾਲ")
    with pytest.raises(PermissionError):
        agent.take_turn(world, None, "someone_else", "Punjabi", "hi", "hi", first["conversation_id"])


# ---- over HTTP

def test_agent_turn_endpoint_speaks_and_returns_cards(world, monkeypatch):
    monkeypatch.setattr(main, "get_gemini_client", lambda: None)
    monkeypatch.setattr(main, "synthesize_speech", lambda text, lang: b"mp3")
    monkeypatch.setattr(agent, "to_english", lambda c, text, lang: f"(en) {text}")
    monkeypatch.setattr(agent, "_generate", Script([[("get_todays_price", {"district": "ਸੰਗਰੂਰ"})],
                                                    lambda r: f"ਅੱਜ ਦਾ ਭਾਅ ₹{r['get_todays_price']['price_per_kg']} ਹੈ"]))
    client = TestClient(main.app)
    body = client.post("/agent/turn", data={"farmer_id": "farmer_c", "language": "Punjabi", "text": "ਅੱਜ ਦਾ ਭਾਅ?"}).json()
    assert body["reply"]["audio_base64"] and body["heard"]["english"] == "(en) ਅੱਜ ਦਾ ਭਾਅ?"
    assert body["cards"][0]["type"] == "price" and body["cards"][0]["district"] == "Sangrur"
    conv = client.get(f"/agent/conversations/{body['conversation_id']}").json()
    assert conv["turns"][1]["guardrails"]["tool_calls"][0]["name"] == "get_todays_price"
    assert client.post("/agent/turn", data={"farmer_id": "farmer_c"}).status_code == 422
    bad = client.post("/agent/turn", data={"farmer_id": "farmer_c"}, files={"audio": ("x.txt", b"hi", "text/plain")})
    assert bad.status_code == 422


def test_a_withdrawn_weight_is_cleared_and_a_mismatch_blocks_booking(chat, world):
    first = chat([[("update_listing", {"acres": 8, "quantity_kg": 3000, "crop_type": "rice_stubble",
                                       "village_or_district": "Patiala", "sowing_deadline": "2026-10-22", "farmer_name": "Gurmeet", "contact": "9876543210"})],
                  [("find_pickup_slot", {})], lambda r: "ਪਹਿਲਾਂ ਵਜ਼ਨ ਦੱਸੋ"], "8 ਕਿੱਲੇ, 3000 ਕਿਲੋ, ਪਟਿਆਲਾ, 22 ਤਰੀਕ")
    refused = next(c for c in first["guardrails"]["tool_calls"] if c["name"] == "find_pickup_slot")
    assert refused["ok"] is False and first["booking_id"] is None, "no booking while acres and weight disagree"

    second = chat([[("update_listing", {"clear_fields": ["quantity_kg"]})], [("find_pickup_slot", {})], _offer_text],
                  "8 ਕਿੱਲੇ ਹੀ ਸਹੀ ਹੈ, ਵਜ਼ਨ ਨਹੀਂ ਪਤਾ", first["conversation_id"])
    offer = next(c for c in second["cards"] if c["type"] == "offer")
    assert offer["kg"] == 14000.0, "weight re-derived from 8 acres at 1.75 t/acre"
    assert not offer["pickup_window_spoken"][0].isdigit(), "the window is said as a day and time, not an ISO date"


@pytest.mark.parametrize("reply, farmer, expected", [
    ("आज का तय सरकारी भाव 0.6 रुपये है", ["10 एकड़ धान"], ["government"]),
    ("You can trust our same-day payment without worry", ["10 acres"], ["trust"]),
    ("ਇਹ ਸਰਕਾਰੀ ਯੋਜਨਾ ਹੈ", ["ਦਸ ਕਿੱਲੇ"], ["government", "scheme"]),
    ("No, we are a private company, not a government scheme", ["Is this a government scheme?"], []),
    ("ਭਾਅ ਪ੍ਰਤੀ ਕਿੱਲੋ ਹੈ", ["ਦਸ ਕਿੱਲੇ"], []),
])
def test_forbidden_claims(reply, farmer, expected):
    assert agent.forbidden_claims(reply, farmer) == expected


def test_a_reply_that_calls_the_rate_government_is_regenerated(chat):
    result = chat([[SANGRUR_CALL], [("find_pickup_slot", {})], lambda r: "ਸਰਕਾਰੀ ਭਾਅ ਹੈ", _offer_text],
                  "ਦਸ ਕਿੱਲੇ ਝੋਨਾ ਸੰਗਰੂਰ, 24 ਤਰੀਕ ਤੱਕ")
    g = result["guardrails"]
    assert g["blocked_claims"] == ["government"] and g["regenerated"] and not g["fallback"]


def test_name_and_a_valid_mobile_are_required_before_an_offer(chat):
    no_contact = ("update_listing", {"acres": 10, "crop_type": "rice_stubble", "village_or_district": "Sangrur",
                                     "sowing_deadline": "2026-10-24", "contact": "12345"})
    result = chat([[no_contact], [("find_pickup_slot", {})], lambda r: "ਨਾਮ ਅਤੇ ਮੋਬਾਈਲ ਨੰਬਰ ਦੱਸੋ"], "ਦਸ ਕਿੱਲੇ ਸੰਗਰੂਰ")
    assert result["missing_fields"] == ["name", "phone"]
    assert not any(c["type"] == "offer" for c in result["cards"])


def test_the_offer_reads_back_the_farm_and_the_booking_gets_a_code(chat, world):
    first = chat([[SANGRUR_CALL], [("find_pickup_slot", {})], _offer_text], "ਦਸ ਕਿੱਲੇ ਝੋਨਾ ਸੰਗਰੂਰ, 24 ਤਰੀਕ ਤੱਕ")
    offer = next(c for c in first["cards"] if c["type"] == "offer")
    assert offer["farm"]["name"] == "Gurmeet Singh" and offer["farm"]["phone"] == "+91 ******3210"
    assert offer["farm"]["location"] == "demo location"
    fields = store.get_conversation(world, first["conversation_id"])["fields"]
    assert fields["contact"] == "+919876543210" and fields["location_source"] == "demo"
    second = chat([[("confirm_booking", {"farmer_said_yes": True})], lambda r: "ਬੁੱਕ ਹੋ ਗਿਆ"], "ਹਾਂ ਜੀ, ਕਰ ਦਿਓ",
                  first["conversation_id"])
    booked = next(c for c in second["cards"] if c["type"] == "booked")
    assert booked["booking_code"].startswith("PS-") and len(booked["booking_code"]) == 7 and booked["sms"] == "simulated"


def test_service_terms_answer_the_questions_farmers_ask(chat):
    result = chat([[("get_service_terms", {})], lambda r: "ਪੈਸੇ ਉਸੇ ਦਿਨ ਡਿਜੀਟਲ ਟ੍ਰਾਂਸਫਰ ਨਾਲ ਮਿਲਣਗੇ, ਇਸ ਡੈਮੋ ਵਿੱਚ ਅਸਲੀ ਪੈਸੇ ਨਹੀਂ"],
                  "ਪੈਸੇ ਕਿਵੇਂ ਮਿਲਣਗੇ? ਟਰੱਕ ਨਾ ਆਇਆ ਤਾਂ?")
    assert result["guardrails"]["tool_calls"][0] == {"name": "get_service_terms", "args": {}, "ok": True}
    terms = agent.SERVICE_TERMS
    assert "partner crew" in terms["if_crew_does_not_come"] and "simulated" in terms["payment"]
    assert not agent.forbidden_claims(" ".join(str(v) for v in terms.values()), []), "our own answers pass our own guardrail"
    assert not agent.numbers_in(" ".join(str(v) for v in terms.values() if isinstance(v, str)))


def test_a_very_close_sowing_date_is_flagged_and_unserved_places_list_the_districts():
    w = agent.listing_warnings({"sowing_deadline": "2026-10-19", "village_or_district": "Amritsar"}, set(), TODAY)
    codes = {x["code"]: x for x in w}
    assert "sowing_very_soon" in codes and "Sangrur" in codes["place_not_recognised"]["served_districts"]
