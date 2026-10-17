"""Live smoke test against the real Gemini, Speech, Text-to-Speech and
Firestore in parali-setu-aibuildercup-2026. Not named test_*.py, so plain `pytest`
never runs it against real credentials and billing; run it by hand, after
`python reset_demo.py --yes` has seeded depots, customers and prices:

    python tests/live_smoke.py

Needs Application Default Credentials (gcloud auth application-default login).
Everything it creates is tagged with a "smoke_" farmer id and deleted at the end.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from google.cloud import texttospeech  # noqa: E402

import firestore_store as store  # noqa: E402
import main  # noqa: E402

client = TestClient(main.app)
PHOTO = Path(__file__).resolve().parent.parent / "seed" / "reference_photos" / "paddy_stubble_coorg_dry_example.jpg"
FARMER = "smoke_farmer_voice"


def punjabi_wav(text: str) -> bytes:
    tts = texttospeech.TextToSpeechClient()
    return tts.synthesize_speech(
        input=texttospeech.SynthesisInput(text=text),
        voice=texttospeech.VoiceSelectionParams(language_code="pa-IN", name="pa-IN-Chirp3-HD-Achernar"),
        audio_config=texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.LINEAR16, sample_rate_hertz=16000),
    ).audio_content


def turn(conversation_id, **form):
    data = {"farmer_id": FARMER, "speak": "false", **({"conversation_id": conversation_id} if conversation_id else {})}
    files = form.pop("files", None)
    resp = client.post("/agent/turn", data={**data, **form}, files=files)
    assert resp.status_code == 200, resp.text
    return resp.json()


def check_voice_booking_verify_collect_and_pay():
    """The whole farmer journey on real services: Punjabi speech and a photo,
    no language chosen -> the agent asks for name and phone -> an offer at
    today's posted price with a slot -> the farmer's yes -> our team verifies
    -> collect -> same-day payout and depot stock."""
    audio = punjabi_wav("ਮੇਰੇ ਕੋਲ ਦਸ ਕਿੱਲੇ ਝੋਨੇ ਦੀ ਪਰਾਲੀ ਹੈ ਸੰਗਰੂਰ ਵਿੱਚ, ਪੱਚੀ ਅਕਤੂਬਰ ਤੱਕ ਕਣਕ ਬੀਜਣੀ ਹੈ")
    first = turn(None, files={"audio": ("speech.wav", audio, "audio/wav"),
                              "photo": ("stubble.jpg", PHOTO.read_bytes(), "image/jpeg")})
    print("heard:", first["heard"]["text"], "|", first["language"], "|", first["reply"]["text"])
    assert first["language"] == "Punjabi" and first["fields"].get("acres") == 10, first["fields"]
    assert {"name", "phone"} <= set(first["missing_fields"]), "the agent asks who and how to reach them"

    second = turn(first["conversation_id"], text="ਮੇਰਾ ਨਾਮ ਗੁਰਮੀਤ ਸਿੰਘ ਹੈ, ਨੰਬਰ 9876543210")
    offer = next((c for c in second["cards"] if c["type"] == "offer"), None)
    assert offer, second
    posted = store.get_posted_price(store.get_firestore_client(), main._today().isoformat(), "Sangrur")
    assert offer["price_per_kg"] == posted["price_per_kg"], "the farmer is offered today's posted price"
    print("offer:", offer["depot"], offer["pickup_window"], offer["price_per_kg"], "Rs/kg |", second["reply"]["text"])

    third = turn(first["conversation_id"], text="ਹਾਂ ਜੀ, ਬੁੱਕ ਕਰ ਦਿਓ")
    booked = next((c for c in third["cards"] if c["type"] == "booked"), None)
    assert booked and booked["booking_code"].startswith("PS-"), third
    booking_id = offer["booking_id"]
    assert client.post(f"/stops/{booking_id}/collected", json={}).status_code == 409, "no crew before the call"
    assert client.post(f"/ops/bookings/{booking_id}/verify", json={"notes": "smoke test"}).status_code == 200
    paid = client.post(f"/stops/{booking_id}/collected", json={}).json()
    assert paid["booking"]["status"] == "paid"
    assert paid["purchase"]["amount_inr"] == round(offer["kg"] * offer["price_per_kg"], 2)
    print("verified, collected and paid:", paid["purchase"]["amount_inr"], "Rs on", paid["purchase"]["paid_on"])


def check_no_burn_proof_disputed_path():
    """A photo claiming 'unburned' where the satellites saw fire that day must
    come back disputed, not given full credit."""
    db = store.get_firestore_client()
    assert store.get_fire_data_coverage(db), "run fetch_fire_data.py first"
    detections = [d.to_dict() for d in db.collection("fire_detections").stream() if d.id != "_meta"]
    assert detections, "the fire batch has no detections; widen its lookback"
    sample = detections[0]
    resp = client.post("/farmers/smoke_farmer_proof/no-burn-proof",
                       params={"district": sample["district_guess"], "claimed_date": sample["detected_at"]},
                       files={"photo": ("field.jpg", PHOTO.read_bytes(), "image/jpeg")})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["satellite_corroboration"] == "fire_detected", body
    if body["field_condition"] == "unburned":
        assert body["disputed"] is True
    print("no-burn proof:", body)


def check_customer_quote():
    customers = client.get("/customers").json()["customers"]
    assert customers, "run reset_demo.py first"
    quote = client.post(f"/customers/{customers[0]['id']}/quote",
                        json={"tonnes_per_month": 100, "months": 6, "start_month": "2026-12-01"}).json()
    q = quote["quote"]
    assert q["price_per_t"] == q["cost_per_t"] + q["margin_per_t"]
    assert quote["commit"]["asked_t"] == 600
    print("quote:", customers[0]["name"], q["price_per_t"], "Rs/t vs in-season", q["in_season_benchmark_per_t"],
          "| can commit", quote["commit"]["committable_t"], "t")


def cleanup():
    db = store.get_firestore_client()
    removed = 0
    for coll in ("listings", "bookings", "purchases", "no_burn_proofs", "conversations"):
        for d in db.collection(coll).stream():
            if not str(d.to_dict().get("farmer_id", "")).startswith("smoke_"):
                continue
            if coll == "bookings":
                for related in ("pickup_slots", "inventory_moves"):
                    for r in db.collection(related).where("booking_id", "==", d.id).stream():
                        r.reference.delete()
            d.reference.delete()
            removed += 1
    db.collection("farmers").document("smoke_farmer_proof").delete()
    print(f"cleaned up {removed} smoke documents")


def run():
    assert client.get("/health").status_code == 200
    try:
        check_voice_booking_verify_collect_and_pay()
        check_no_burn_proof_disputed_path()
        check_customer_quote()
    finally:
        cleanup()
    print("\nALL LIVE CHECKS PASSED")


if __name__ == "__main__":
    run()
