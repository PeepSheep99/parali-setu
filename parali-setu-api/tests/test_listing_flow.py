"""Speak-once, confirm-once flow: /listings/draft, /listings/{id}/confirm and
/matches/{id}/accept-slot, with Gemini, speech and Firestore mocked."""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import firestore_store as store  # noqa: E402
import main  # noqa: E402
import pickups  # noqa: E402
from phrases import confirm_summary  # noqa: E402

client = TestClient(main.app)


@pytest.fixture
def env(monkeypatch):
    state = {"drafts": {}, "listings": {}, "extracted": {}, "questions": 0}
    monkeypatch.setattr(store, "get_firestore_client", lambda: MagicMock())
    monkeypatch.setattr(main, "get_gemini_client", lambda: MagicMock())
    monkeypatch.setattr(main, "synthesize_speech", lambda text, lang: b"mp3")
    monkeypatch.setattr(main, "extract_listing", lambda c, text, lang: dict(state["extracted"]))

    def ask(c, missing, lang):
        state["questions"] += 1
        return "Kitne kille, aur kab tak khet khali chahiye?"
    monkeypatch.setattr(main, "follow_up_question", ask)

    def save_draft(db, draft):
        draft = {**draft, "id": draft.get("id") or f"draft{len(state['drafts']) + 1}"}
        state["drafts"][draft["id"]] = draft
        return draft
    monkeypatch.setattr(store, "save_draft", save_draft)
    monkeypatch.setattr(store, "get_draft", lambda db, did: state["drafts"].get(did))

    def save_listing(db, farmer_id, extracted, language):
        doc = {**extracted, "id": "listing1", "farmer_id": farmer_id, "quantity_remaining_kg": extracted["quantity_kg"]}
        state["listings"]["listing1"] = doc
        return doc
    monkeypatch.setattr(store, "save_listing", save_listing)
    return state


SANGRUR_TEXT = {"acres": 10, "crop_type": "rice_stubble", "village_or_district": "Sangrur"}


def test_one_question_covers_everything_missing_and_is_asked_only_once(env):
    env["extracted"] = {"acres": 10, "crop_type": "rice_stubble"}
    first = client.post("/listings/draft", data={"farmer_id": "f1", "language": "Punjabi", "text": "10 kille jhona"}).json()
    assert first["missing_fields"] == ["location", "sowing_deadline"]
    assert first["follow_up"]["text"] and first["follow_up"]["audio_base64"]
    assert first["confirm_summary"] is None
    assert first["fields"]["quantity_kg"] == 17500.0, "kg is derived in code from acres at 1.75 t/acre"

    env["extracted"] = {**SANGRUR_TEXT}   # still no sowing date in the answer
    second = client.post("/listings/draft", data={"farmer_id": "f1", "language": "Punjabi",
                                                  "draft_id": first["draft_id"], "text": "Sangrur"}).json()
    assert env["questions"] == 1, "never a second question"
    assert second["follow_up"] is None
    assert second["missing_fields"] == ["sowing_deadline"]
    assert second["confirm_summary"]["text"].startswith("ਤੁਸੀਂ ਦੱਸਿਆ")
    assert second["location_approximate"] is True


def test_complete_listing_goes_straight_to_the_confirm_card(env):
    env["extracted"] = {**SANGRUR_TEXT, "sowing_deadline": "2026-10-28"}
    body = client.post("/listings/draft", data={"farmer_id": "f1", "language": "Hindi", "text": "..."}).json()
    assert body["missing_fields"] == [] and body["follow_up"] is None
    assert "10 एकड़" in body["confirm_summary"]["text"] and "28/10/2026" in body["confirm_summary"]["text"]
    assert env["questions"] == 0


def test_draft_needs_something_to_understand(env):
    assert client.post("/listings/draft", data={"farmer_id": "f1"}).status_code == 422


def _confirm_env(monkeypatch, env, match_status="proposed", slots=True):
    env["drafts"]["d1"] = {"id": "d1", "farmer_id": "f1", "language": "Hindi",
                           "fields": {**SANGRUR_TEXT, "quantity_kg": 17500.0, "sowing_deadline": "2026-10-28"},
                           "quality": {"grade": "dry", "note": "pale"}}
    match = {"id": "m1", "listing_id": "listing1", "company_id": "c1", "farmer_id": "f1",
             "matched_kg": 17500.0, "price_agreed_per_kg": 1.0, "status": match_status}
    slot = {"id": "slot_m1_0", "date": "2026-10-22", "window_start_min": 540, "window_end_min": 720,
            "planned_start_min": 600}
    monkeypatch.setattr(main, "_run_global_solve", lambda db: [dict(match)])
    planned = []
    monkeypatch.setattr(pickups, "plan_companies", lambda db, ids, **kw: planned.append(set(ids)))
    monkeypatch.setattr(store, "get_match", lambda db, mid: dict(match))
    monkeypatch.setattr(store, "get_slots_for_match", lambda db, mid: [slot] if slots else [])
    monkeypatch.setattr(store, "get_company", lambda db, cid: {"name": "Sangrur Pellet Co-op (demo)"})
    monkeypatch.setattr(main, "explain_match", lambda c, m, lang: f"{m['company_name']} {m['pickup_window']}")
    return planned


def test_confirm_lists_matches_plans_and_offers_a_slot(monkeypatch, env):
    planned = _confirm_env(monkeypatch, env)
    body = client.post("/listings/d1/confirm", json={"farmer_id": "f1"}).json()
    assert body["status"] == "offered"
    assert planned == [{"c1"}], "pickups are planned for the buyer that got the match"
    offer = body["offers"][0]
    assert offer["company_name"] == "Sangrur Pellet Co-op (demo)"
    assert offer["pickup_window"] == "2026-10-22 09:00-12:00"
    assert body["payout_estimate_inr"] == 17500.0
    assert body["impact_if_collected"]["acres_cleared"] == 10.0
    assert "2026-10-22 09:00-12:00" in body["explanation"]["text"]
    assert env["listings"]["listing1"]["quality_grade"] == "dry"

    assert client.post("/listings/d1/confirm", json={"farmer_id": "f1"}).status_code == 409, "confirm only once"


def test_confirm_with_a_corrected_chip_rederives_weight(monkeypatch, env):
    _confirm_env(monkeypatch, env)
    client.post("/listings/d1/confirm", json={"farmer_id": "f1", "edits": {"acres": 4}})
    assert env["listings"]["listing1"]["quantity_kg"] == 7000.0
    assert env["listings"]["listing1"]["acres"] == 4


def test_confirm_reports_waitlist_honestly(monkeypatch, env):
    _confirm_env(monkeypatch, env, match_status="waitlisted", slots=False)
    body = client.post("/listings/d1/confirm", json={"farmer_id": "f1"}).json()
    assert body["status"] == "waitlisted"
    assert body["explanation"] is None


def test_accept_slot_locks_it(monkeypatch, env):
    _confirm_env(monkeypatch, env)
    transitions = []
    monkeypatch.setattr(store, "update_match_status", lambda db, mid, status, extra=None: (
        transitions.append(status), {"id": mid, "status": status})[1])
    monkeypatch.setattr(store, "set_slots_status", lambda db, mid, status, locked=None: [
        {"date": "2026-10-22", "window_start_min": 540, "window_end_min": 720, "status": status, "locked": locked}])

    body = client.post("/matches/m1/accept-slot", json={"farmer_id": "f1"}).json()
    assert transitions == ["scheduled"]
    assert body["slots"][0]["locked"] is True and body["pickup_window"] == "2026-10-22 09:00-12:00"

    assert client.post("/matches/m1/accept-slot", json={"farmer_id": "someone_else"}).status_code == 404


def test_accept_slot_needs_a_slot(monkeypatch, env):
    _confirm_env(monkeypatch, env, slots=False)
    assert client.post("/matches/m1/accept-slot", json={"farmer_id": "f1"}).status_code == 409


def test_confirm_summary_repeats_numbers_exactly():
    text = confirm_summary({"acres": 12.5, "crop_type": "wheat_stubble", "village_or_district": "Moga",
                            "sowing_deadline": "2026-11-02"}, "English")
    assert text == "You said: 12.5 acres, wheat stubble, in Moga, field to be cleared by 2/11/2026. Confirm if this is right."
