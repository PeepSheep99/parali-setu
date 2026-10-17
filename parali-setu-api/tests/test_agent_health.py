"""The ops console's agent health is counted from stored guardrail reports."""
from fastapi.testclient import TestClient

import agent_health
import firestore_store as store
import main


def _turn(ms, model="primary", **report):
    return {"role": "model", "text": "...", "guardrails": {"model_calls": [{"ms": m, "model": model, "ok": True} for m in ms],
                                                           "regenerated": False, "fallback": False, **report}}


def test_summary_counts_speed_fallbacks_and_catches():
    convs = [
        {"booking_id": "b1", "turns": [{"role": "user", "text": "hi"}, _turn([900, 1100]),
                                       _turn([1200], blocked_numbers=[3.0], regenerated=True)]},
        {"turns": [_turn([4000], model="fallback", fallback=True),
                   {"role": "model", "text": "old", "guardrails": {"tool_calls": []}}]},   # recorded before timing
    ]
    s = agent_health.summarise(convs)
    assert s["conversations"] == 2 and s["bookings"] == 1 and s["turns"] == 4
    assert s["model_ms_per_turn"]["turns_timed"] == 3 and s["model_ms_per_turn"]["p50"] == 2000
    assert s["fallback_model_pct"] == 25.0
    assert s["rewritten_pct"] == 25.0 and s["template_pct"] == 25.0
    assert s["caught"]["unverified_numbers"] == 1


def test_empty_is_not_zero():
    s = agent_health.summarise([])
    assert s["turns"] == 0 and s["fallback_model_pct"] is None and s["rewritten_pct"] is None


def test_endpoint_skips_benchmark_conversations(fake_db):
    store.save_conversation(fake_db, {"farmer_id": "f1", "turns": [_turn([800])]})
    store.save_conversation(fake_db, {"farmer_id": "bench_live_0", "turns": [_turn([9000])]})
    body = TestClient(main.app).get("/ops/agent-health").json()
    assert body["live"]["conversations"] == 1 and body["live"]["model_call_ms"]["p50"] == 800
    assert body["benchmark"] is None or "bookings_completed" in body["benchmark"]
