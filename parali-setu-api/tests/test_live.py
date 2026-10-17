"""Live mode over the WebSocket, with a scripted live transcription session:
captions are relayed as they arrive, the final transcript becomes one guarded
agent turn, and failures tell the phone to fall back to recording."""
import asyncio
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

import agent
import live
import main

client = TestClient(main.app)


def message(interim=None, final=None, done=False):
    return NS(server_content=NS(
        interim_input_transcription=NS(text=interim) if interim else None,
        input_transcription=NS(text=final) if final else None,
        generation_complete=done, turn_complete=False))


class FakeSession:
    def __init__(self, messages, fail=False):
        self.messages, self.fail, self.audio, self.ended = messages, fail, 0, False

    async def __aenter__(self):
        if self.fail:
            raise RuntimeError("live service down")
        return self

    async def __aexit__(self, *exc):
        return False

    async def send_realtime_input(self, audio=None, audio_stream_end=None):
        if audio is not None:
            self.audio += len(audio.data)
        if audio_stream_end:
            self.ended = True

    async def receive(self):
        # Like the real service: interim captions while audio arrives, the
        # final transcript only after the end of the audio.
        for m in self.messages:
            if m.server_content.input_transcription or m.server_content.generation_complete:
                while not self.ended:
                    await asyncio.sleep(0.01)
            yield m


@pytest.fixture
def live_world(world, monkeypatch):
    monkeypatch.setattr(main, "get_gemini_client", lambda: None)
    monkeypatch.setattr(main, "synthesize_speech", lambda text, lang: b"mp3")
    monkeypatch.setattr(agent, "to_english", lambda c, text, lang: f"(en) {text}")
    monkeypatch.setattr(agent, "_generate", lambda c, contents, config: ([], "ਸਤ ਸ੍ਰੀ ਅਕਾਲ ਜੀ, ਕਿੰਨੇ ਕਿੱਲੇ?", None))
    return world


def test_captions_stream_and_the_final_transcript_becomes_a_turn(live_world, monkeypatch):
    session = FakeSession([message(interim="ਮੇਰੇ ਕੋਲ"), message(interim="ਮੇਰੇ ਕੋਲ 10 ਕਿੱਲੇ"),
                           message(final="ਮੇਰੇ ਕੋਲ 10 ਕਿੱਲੇ ਝੋਨਾ ਹੈ।"), message(done=True)])
    monkeypatch.setattr(live, "open_session", lambda language: session)
    with client.websocket_connect("/agent/live") as ws:
        ws.send_text('{"farmer_id": "f_live", "language": "Punjabi"}')
        ws.send_bytes(b"\x00\x00" * 1600)
        ws.send_text('{"type": "end"}')
        events = []
        while True:
            event = ws.receive_json()
            events.append(event)
            if event["type"] in ("reply", "error"):
                break
    captions = [e for e in events if e["type"] == "caption"]
    assert [c["final"] for c in captions] == [False, False, True]
    reply = events[-1]
    assert reply["type"] == "reply" and reply["heard"]["text"] == "ਮੇਰੇ ਕੋਲ 10 ਕਿੱਲੇ ਝੋਨਾ ਹੈ।"
    assert reply["heard"]["english"].startswith("(en)") and reply["reply"]["audio_base64"]
    assert session.audio == 3200


def test_a_foreign_origin_is_refused(live_world):
    with pytest.raises(Exception):
        with client.websocket_connect("/agent/live", headers={"origin": "https://evil.example"}) as ws:
            ws.receive_json()


def test_when_live_listening_fails_the_phone_is_told_to_record_instead(live_world, monkeypatch):
    monkeypatch.setattr(live, "open_session", lambda language: FakeSession([], fail=True))
    with client.websocket_connect("/agent/live") as ws:
        ws.send_text('{"farmer_id": "f_live", "language": "Hindi"}')
        event = ws.receive_json()
    assert event["type"] == "error" and "record" in event["detail"]


def test_silence_gets_a_clear_message(live_world, monkeypatch):
    monkeypatch.setattr(live, "open_session", lambda language: FakeSession([message(done=True)]))
    with client.websocket_connect("/agent/live") as ws:
        ws.send_text('{"farmer_id": "f_live", "language": "Hindi"}')
        ws.send_text('{"type": "end"}')
        event = ws.receive_json()
    assert event["type"] == "error" and "hear" in event["detail"]


def test_live_config_locks_the_language_and_farm_vocabulary():
    cfg = live.live_config("Punjabi")
    assert cfg.input_audio_transcription.language_codes == ["pa-IN"]
    assert "ਕਿੱਲੇ" in cfg.input_audio_transcription.custom_vocabulary
    assert live.caption_events(NS(server_content=None)) == []


def test_without_a_language_live_listening_hears_all_three():
    cfg = live.live_config(None)
    assert cfg.input_audio_transcription.language_codes == ["pa-IN", "hi-IN", "en-IN"]
    vocab = cfg.input_audio_transcription.custom_vocabulary
    assert "ਕਿੱਲੇ" in vocab and "एकड़" in vocab and "acres" in vocab
