"""Live mode for the farmer's agent: the phone streams microphone audio, Gemini's
live transcription model returns captions as the farmer speaks, and the final
transcript goes to the same guarded agent as a typed or recorded turn.

Why transcription and not a live voice model: a native-audio Live model speaks
its numbers straight to the farmer, before our code can check that each one
came from a tool. Here Gemini still does the listening in real time, but every
reply goes through agent.py's guardrails before it is spoken.

Tested on 17 Oct 2026: with the language fixed and a small farm vocabulary,
gemini-3.5-transcribe-live returned word-perfect Punjabi (Gurmukhi) and Hindi
transcripts about half a second after the farmer stopped speaking. Live models
are served from the global endpoint (not asia-south1 / asia-southeast1).
"""
from __future__ import annotations

import os

from google import genai
from google.genai import types

from gemini_client import PROJECT_ID

LIVE_MODEL = os.environ.get("LIVE_TRANSCRIBE_MODEL", "gemini-3.5-transcribe-live")
LIVE_LOCATION = os.environ.get("LIVE_LOCATION", "global")
SAMPLE_RATE = 16000
MAX_AUDIO_SECONDS = 60          # one utterance; the phone stops sooner
MAX_SESSION_SECONDS = 90

LANGUAGE_CODES = {"Punjabi": "pa-IN", "Hindi": "hi-IN", "English": "en-IN"}
# Words the recogniser should expect from a paddy farmer in Punjab or Haryana.
VOCABULARY = {
    "Punjabi": ["ਕਿੱਲੇ", "ਕਿੱਲਾ", "ਝੋਨਾ", "ਪਰਾਲੀ", "ਕਣਕ", "ਬਿਜਾਈ", "ਸੰਗਰੂਰ", "ਪਟਿਆਲਾ", "ਬਠਿੰਡਾ", "ਲੁਧਿਆਣਾ",
                "ਮੋਗਾ", "ਕਰਨਾਲ", "ਕੈਥਲ", "ਕੁਰੂਕਸ਼ੇਤਰ"],
    "Hindi": ["एकड़", "किल्ले", "धान", "पराली", "गेहूं", "बुवाई", "संगरूर", "पटियाला", "बठिंडा", "लुधियाना", "मोगा",
              "करनाल", "कैथल", "कुरुक्षेत्र"],
    "English": ["acres", "killa", "paddy", "stubble", "parali", "wheat", "Sangrur", "Patiala", "Bathinda",
                "Ludhiana", "Moga", "Karnal", "Kaithal", "Kurukshetra"],
}


def live_config(language: str | None = None) -> types.LiveConnectConfig:
    """With no language, the session listens for Punjabi, Hindi and English at
    once and writes each in its own script (tested 17 Oct 2026), so the farmer
    never has to pick one first."""
    if language in LANGUAGE_CODES:
        codes, vocabulary = [LANGUAGE_CODES[language]], VOCABULARY[language]
    else:
        codes = list(LANGUAGE_CODES.values())
        vocabulary = [w for words in VOCABULARY.values() for w in words]
    return types.LiveConnectConfig(
        response_modalities=["TEXT"],
        input_audio_transcription=types.AudioTranscriptionConfig(language_codes=codes, custom_vocabulary=vocabulary),
    )


def open_session(language: str | None = None):
    """An async context manager for one live transcription session. A seam
    tests replace with a scripted session."""
    client = genai.Client(vertexai=True, project=PROJECT_ID, location=LIVE_LOCATION)
    return client.aio.live.connect(model=LIVE_MODEL, config=live_config(language))


def audio_blob(pcm16: bytes) -> types.Blob:
    return types.Blob(data=pcm16, mime_type=f"audio/pcm;rate={SAMPLE_RATE}")


def caption_events(message) -> list[dict]:
    """What a server message means for the phone: interim words, the final
    transcript, and whether the utterance is finished."""
    sc = getattr(message, "server_content", None)
    if sc is None:
        return []
    events = []
    interim = getattr(sc, "interim_input_transcription", None)
    if interim is not None and interim.text:
        events.append({"type": "caption", "text": interim.text, "final": False})
    final = getattr(sc, "input_transcription", None)
    if final is not None and final.text:
        events.append({"type": "caption", "text": final.text, "final": True})
    if getattr(sc, "generation_complete", None) or getattr(sc, "turn_complete", None):
        events.append({"type": "done"})
    return events
