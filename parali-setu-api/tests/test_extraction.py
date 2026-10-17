"""Mocked tests for extraction.py's Gemini perception jobs: fast, no real API
calls. Each job returns structured data or None; it never invents a value
that the caller would then trust."""
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extraction import read_no_burn_proof, read_stubble_quality, to_english, understand_audio  # noqa: E402


def make_fake_client(response_text):
    client = MagicMock()
    client.models.generate_content.return_value = MagicMock(text=response_text)
    return client


def test_read_stubble_quality_parses_valid_grade():
    client = make_fake_client(json.dumps({"quality_grade": "dry", "note": "pale, no moisture"}))
    result = read_stubble_quality(client, b"fake-image-bytes", mime_type="image/jpeg")
    assert result["quality_grade"] == "dry"


def test_read_stubble_quality_rejects_invalid_grade_rather_than_trust_it():
    client = make_fake_client(json.dumps({"quality_grade": "excellent", "note": "..."}))  # not a real grade
    result = read_stubble_quality(client, b"fake-image-bytes")
    assert result["quality_grade"] is None


def test_read_stubble_quality_null_grade_passes_through():
    """Gemini returns a null grade for an unusable photo rather than guessing
    one; None must survive untouched, not get coerced."""
    client = make_fake_client(json.dumps({"quality_grade": None, "note": "not a usable photo"}))
    result = read_stubble_quality(client, b"fake-image-bytes")
    assert result["quality_grade"] is None
    assert result["note"] == "not a usable photo"


def test_read_stubble_quality_returns_none_on_malformed_json():
    assert read_stubble_quality(make_fake_client("not valid json"), b"fake-image-bytes") is None


def test_no_burn_proof_rejects_an_unknown_condition():
    client = make_fake_client(json.dumps({"field_condition": "probably fine", "note": "..."}))
    assert read_no_burn_proof(client, b"fake-image-bytes")["field_condition"] is None


def test_understand_audio_needs_a_transcript():
    heard = understand_audio(make_fake_client(json.dumps({"transcript": "ਦਸ ਕਿੱਲੇ", "english": "ten acres"})),
                             b"wav", "audio/wav", "Punjabi")
    assert heard == {"transcript": "ਦਸ ਕਿੱਲੇ", "english": "ten acres"}
    silent = understand_audio(make_fake_client(json.dumps({"transcript": None, "english": None})), b"wav", "audio/wav", "Punjabi")
    assert silent is None, "no speech means the caller falls back to Speech-to-Text"


def test_english_is_not_sent_for_translation():
    client = make_fake_client("unused")
    assert to_english(client, "ten acres in Sangrur", "English") == "ten acres in Sangrur"
    client.models.generate_content.assert_not_called()
