"""Mocked tests for extraction.py's Gemini jobs -- fast, no real
API calls. These were each also live-verified once by hand against the
real Vertex AI endpoint (extract_listing's date-anchoring and the
Punjabi narration were both fixed after that live check caught real
bugs a mock never would have) -- see PRD docs/PARALI_SETU_PRD.md
Section 13 for why a live check still matters even with these in place.
"""
import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extraction import explain_offer, explain_price, extract_listing, read_stubble_quality  # noqa: E402


def make_fake_client(response_text):
    client = MagicMock()
    client.models.generate_content.return_value = MagicMock(text=response_text)
    return client


def test_extract_listing_parses_valid_json():
    client = make_fake_client(json.dumps({
        "quantity_kg": 800, "crop_type": "rice_stubble",
        "village_or_district": "Sangrur", "ready_by": "2026-10-25", "contact": None,
    }))
    result = extract_listing(client, "8 quintal rice stubble in Sangrur", "Hindi", today=date(2026, 10, 14))
    assert result["quantity_kg"] == 800
    assert result["crop_type"] == "rice_stubble"


def test_extract_listing_rejects_invalid_crop_type_rather_than_trust_it():
    client = make_fake_client(json.dumps({
        "quantity_kg": 800, "crop_type": "cotton_stubble",  # not a valid type
        "village_or_district": "Sangrur", "ready_by": None, "contact": None,
    }))
    result = extract_listing(client, "...", "Hindi", today=date(2026, 10, 14))
    assert result["crop_type"] is None


def test_extract_listing_returns_none_on_gemini_unavailable():
    client = MagicMock()
    client.models.generate_content.side_effect = Exception("unreachable")
    try:
        extract_listing(client, "...", "Hindi", today=date(2026, 10, 14))
        assert False, "expected the underlying exception to propagate from call_gemini"
    except Exception:
        pass


def test_extract_listing_returns_none_on_malformed_json():
    client = make_fake_client("not valid json")
    result = extract_listing(client, "...", "Hindi", today=date(2026, 10, 14))
    assert result is None


def test_read_stubble_quality_parses_valid_grade():
    client = make_fake_client(json.dumps({"quality_grade": "dry", "note": "pale, no moisture"}))
    result = read_stubble_quality(client, b"fake-image-bytes", mime_type="image/jpeg")
    assert result["quality_grade"] == "dry"


def test_read_stubble_quality_rejects_invalid_grade_rather_than_trust_it():
    client = make_fake_client(json.dumps({"quality_grade": "excellent", "note": "..."}))  # not a real grade
    result = read_stubble_quality(client, b"fake-image-bytes")
    assert result["quality_grade"] is None


def test_read_stubble_quality_null_grade_passes_through():
    """Confirmed live 2026-10-15: Gemini correctly returns a null grade
    for an unusable/off-subject photo rather than guessing one -- this
    test locks in that None must survive untouched, not get coerced."""
    client = make_fake_client(json.dumps({"quality_grade": None, "note": "not a usable photo"}))
    result = read_stubble_quality(client, b"fake-image-bytes")
    assert result["quality_grade"] is None
    assert result["note"] == "not a usable photo"


def test_read_stubble_quality_returns_none_on_gemini_unavailable():
    client = MagicMock()
    client.models.generate_content.side_effect = Exception("unreachable")
    try:
        read_stubble_quality(client, b"fake-image-bytes")
        assert False, "expected the underlying exception to propagate from call_gemini"
    except Exception:
        pass


def test_offer_narration_passes_the_planners_numbers_through_unchanged():
    """Gemini only phrases the offer; every figure in the prompt is the
    planners' own, which is the one thing we can assert without a live call."""
    client = make_fake_client("plain narration text")
    offer = {"price_per_kg": 0.76, "district": "Bathinda", "kg": 14000.0, "payout_inr": 10640.0,
             "pickup_window": "2026-10-19 09:00-12:00"}
    assert explain_offer(client, offer, "Punjabi") == "plain narration text"
    prompt_sent = client.models.generate_content.call_args.kwargs["contents"]
    for figure in ("0.76", "14000.0", "10640.0", "2026-10-19 09:00-12:00", "Bathinda"):
        assert figure in prompt_sent


def test_price_explanation_uses_only_the_planners_reason():
    client = make_fake_client("plain words")
    facts = {"district": "Bathinda", "price_per_kg": 0.76, "reason": "Our orders need more straw from Bathinda this week."}
    assert explain_price(client, facts, "Hindi") == "plain words"
    prompt_sent = client.models.generate_content.call_args.kwargs["contents"]
    assert facts["reason"] in prompt_sent and "0.76" in prompt_sent and "no English words" in prompt_sent
