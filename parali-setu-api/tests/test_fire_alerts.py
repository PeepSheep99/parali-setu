"""Fire near a booked farm: found, sent once, verified when pushed, and shown
on the dispatch board. Pub/Sub and Google's token check are faked."""
import base64
import json

import pytest
from fastapi.testclient import TestClient

import fire_alerts
import firestore_store as store
import main
import reset_demo
from test_api_flows import _offer, api  # noqa: F401

client = TestClient(main.app)


def test_find_takes_the_nearest_fire_within_the_radius():
    farms = [{"booking_id": "b1", "lat": 30.25, "lon": 75.84}, {"booking_id": "b2", "lat": 29.69, "lon": 76.99}]
    fires = [{"lat": 30.27, "lon": 75.84, "detected_at": "2026-10-16"},     # ~2.2 km from b1
             {"lat": 30.26, "lon": 75.84, "detected_at": "2026-10-17"},     # ~1.1 km from b1
             {"lat": 30.90, "lon": 75.80, "detected_at": "2026-10-17"}]     # far from both
    alerts = fire_alerts.find(fires, farms)
    assert [a["booking_id"] for a in alerts] == ["b1"]
    assert alerts[0]["detected_at"] == "2026-10-17" and alerts[0]["distance_km"] == pytest.approx(1.1, abs=0.1)


def test_alerts_are_recorded_once_and_shown_on_the_dispatch_board(api, monkeypatch):
    db = api["db"]
    booking = _offer(api)["booking"]
    loc = fire_alerts.open_farms(db)[0]
    monkeypatch.delenv("FIRE_ALERT_TOPIC", raising=False)
    fire = [{"lat": loc["lat"] + 0.01, "lon": loc["lon"], "detected_at": "2026-10-17"}]
    assert fire_alerts.dispatch(db, fire) == {"alerts": 1, "recorded": 1}
    assert fire_alerts.dispatch(db, fire) == {"alerts": 1, "recorded": 0}, "a repeat is not counted twice"
    assert store.get_booking(db, booking["id"])["fire_nearby"]["distance_km"] == pytest.approx(1.1, abs=0.1)
    kinds = [x["kind"] for x in client.get("/ops/dispatch").json()["exceptions"]]
    assert "fire_nearby" in kinds


def test_with_a_topic_alerts_go_through_pubsub(api, monkeypatch):
    db = api["db"]
    _offer(api)
    loc = fire_alerts.open_farms(db)[0]
    sent = []
    monkeypatch.setenv("FIRE_ALERT_TOPIC", "projects/p/topics/fire-alerts")
    monkeypatch.setattr(fire_alerts, "publish", lambda alerts, topic: sent.extend(alerts) or len(alerts))
    out = fire_alerts.dispatch(db, [{"lat": loc["lat"], "lon": loc["lon"], "detected_at": "2026-10-17"}])
    assert out == {"alerts": 1, "published": 1} and sent[0]["booking_id"] == loc["booking_id"]
    assert db.docs("fire_alerts") == [], "recorded only when the push arrives"


def _push(alert, token="good"):
    data = base64.b64encode(json.dumps(alert).encode()).decode()
    return client.post("/pubsub/fire-alerts", json={"message": {"data": data}}, headers={"Authorization": f"Bearer {token}"})


def test_the_push_endpoint_accepts_only_our_signed_pubsub_sender(api, monkeypatch):
    from google.oauth2 import id_token
    monkeypatch.setenv("PUBSUB_PUSH_SA", "pubsub-push@p.iam.gserviceaccount.com")
    monkeypatch.setenv("PUSH_AUDIENCE", "https://api/pubsub/fire-alerts")

    def verify(token, request, audience):
        if token != "good" or audience != "https://api/pubsub/fire-alerts":
            raise ValueError("bad")
        return {"email": "pubsub-push@p.iam.gserviceaccount.com", "email_verified": True}
    monkeypatch.setattr(id_token, "verify_oauth2_token", verify)
    booking = _offer(api)["booking"]
    alert = {"booking_id": booking["id"], "distance_km": 2.0, "detected_at": "2026-10-17"}
    assert _push(alert, token="forged").status_code == 401
    assert client.post("/pubsub/fire-alerts", json={}).status_code == 401
    assert _push(alert).status_code == 204
    assert store.get_booking(api["db"], booking["id"])["fire_nearby"]["distance_km"] == 2.0
    assert _push({"no": "booking"}).status_code == 400


def test_push_endpoint_is_off_when_not_configured(monkeypatch):
    monkeypatch.delenv("PUBSUB_PUSH_SA", raising=False)
    assert client.post("/pubsub/fire-alerts", json={}).status_code == 404


def test_satellite_examples_are_checked_but_not_counted_as_impact(api):
    db = api["db"]
    before = client.get("/impact").json()
    assert reset_demo.seed_satellite_examples(db) == 2
    after = client.get("/impact").json()
    assert after["collected"]["tonnes_diverted"] == before["collected"]["tonnes_diverted"]
    assert after["field_checks"]["waiting_for_images"] == before["field_checks"]["waiting_for_images"] + 2
