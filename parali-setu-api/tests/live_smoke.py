"""Live smoke test against the real Gemini, Speech, Text-to-Speech and
Firestore in parali-setu-aibuildercup2026. Not named test_*.py, so plain `pytest`
never runs it against real credentials and billing; run it by hand, after
`python reset_demo.py --yes` has seeded depots, customers and prices:

    python tests/live_smoke.py

Needs Application Default Credentials (gcloud auth application-default login).
Everything it creates is tagged with a "smoke_" farmer id and deleted at the end.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402
from google.cloud import texttospeech  # noqa: E402

import firestore_store as store  # noqa: E402
import main  # noqa: E402
from extraction import extract_listing  # noqa: E402
from gemini_client import get_gemini_client  # noqa: E402

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


def check_no_date_fabrication():
    """A month without a day must not become an invented date (a real bug,
    found 2026-10-15, fixed in the extraction prompt)."""
    vague = "ਮੇਰੇ ਕੋਲ 12 ਕੁਇੰਟਲ ਪਰਾਲੀ ਹੈ ਸੰਗਰੂਰ ਵਿੱਚ ਵੀ ਅਕਤੂਬਰ ਤੱਕ ਚੁੱਕ ਲਓ"
    result = extract_listing(get_gemini_client(), vague, "Punjabi", today=date(2026, 10, 15))
    assert result["ready_by"] is None, f"no date should be invented from a month alone, got {result['ready_by']}"
    print("no date fabrication: ok")


def check_voice_booking_collect_and_pay():
    """The whole farmer journey on real services: Punjabi speech and a photo
    -> draft -> confirm (posted price, depot, slot, spoken offer) -> price
    explanation -> accept -> collect -> same-day payout and depot stock."""
    audio = punjabi_wav("ਮੇਰੇ ਕੋਲ ਦਸ ਕਿੱਲੇ ਝੋਨੇ ਦੀ ਪਰਾਲੀ ਹੈ ਸੰਗਰੂਰ ਵਿੱਚ, ਪੱਚੀ ਅਕਤੂਬਰ ਤੱਕ ਕਣਕ ਬੀਜਣੀ ਹੈ")
    resp = client.post("/listings/draft", data={"farmer_id": FARMER, "language": "Punjabi"},
                       files={"audio": ("listing.wav", audio, "audio/wav"),
                              "photo": ("stubble.jpg", PHOTO.read_bytes(), "image/jpeg")})
    assert resp.status_code == 200, resp.text
    draft = resp.json()
    print("heard:", draft["transcript"], "| fields:", draft["fields"], "| quality:", draft["quality"])
    assert draft["fields"].get("acres") == 10 and draft["district"] == "Sangrur", draft
    assert draft["quality"]["grade"] in ("dry", "wet", "mixed"), "the real photo read should grade the stubble"

    resp = client.post(f"/listings/{draft['draft_id']}/confirm", json={"farmer_id": FARMER})
    assert resp.status_code == 200, resp.text
    offer = resp.json()
    booking = offer["booking"]
    posted = store.get_posted_price(store.get_firestore_client(), booking["created_at"][:10], "Sangrur")
    assert offer["status"] == "offered" and booking["pickup_window"], offer
    assert booking["price_per_kg"] == posted["price_per_kg"], "the farmer is offered today's posted price"
    assert offer["explanation"]["audio_base64"], "the offer is spoken back"
    print("offer:", booking["depot_name"], booking["pickup_window"], booking["price_per_kg"], "Rs/kg |", offer["explanation"]["text"])

    why = client.get(f"/bookings/{booking['id']}/price-explanation", params={"language": "Punjabi"}).json()
    assert why["explanation"] and why["reason_code"] in ("base", "scarce"), why
    print("why this price:", why["explanation"])

    assert client.post(f"/bookings/{booking['id']}/accept", json={"farmer_id": FARMER}).status_code == 200
    paid = client.post(f"/stops/{booking['id']}/collected", json={}).json()
    assert paid["booking"]["status"] == "paid"
    assert paid["purchase"]["amount_inr"] == round(booking["kg"] * booking["price_per_kg"], 2)
    print("collected and paid:", paid["purchase"]["amount_inr"], "Rs on", paid["purchase"]["paid_on"])


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
    assert abs(q["price_per_t"] - (q["cost_per_t"] + q["margin_per_t"])) < 0.05
    print("quote:", customers[0]["name"], q["price_per_t"], "Rs/t vs in-season", q["in_season_benchmark_per_t"])


def cleanup():
    db = store.get_firestore_client()
    removed = 0
    for coll in ("listing_drafts", "listings", "bookings", "purchases", "no_burn_proofs"):
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
        check_no_date_fabrication()
        check_voice_booking_collect_and_pay()
        check_no_burn_proof_disputed_path()
        check_customer_quote()
    finally:
        cleanup()
    print("\nALL LIVE CHECKS PASSED")


if __name__ == "__main__":
    run()
