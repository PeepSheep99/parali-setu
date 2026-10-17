"""Limits on the endpoints that call Gemini or speech, so a script can't run up
AI usage on the project."""
import pytest
from fastapi.testclient import TestClient

import main
import ratelimit

client = TestClient(main.app)


@pytest.fixture(autouse=True)
def fresh_limits():
    ratelimit.reset()
    yield
    ratelimit.reset()


def test_which_paths_are_limited():
    assert ratelimit.is_limited("/agent/turn", "POST") and ratelimit.is_limited("/speech", "POST")
    assert ratelimit.is_limited("/farmers/f1/no-burn-proof", "POST")
    assert not ratelimit.is_limited("/prices/today", "GET") and not ratelimit.is_limited("/ops/dispatch", "GET")
    assert not ratelimit.is_limited("/farmers/f1/bookings", "GET"), "reading a farmer's bookings calls no AI"


def test_a_visitor_over_the_minute_limit_is_stopped(monkeypatch):
    monkeypatch.setattr(ratelimit, "PER_VISITOR_PER_MINUTE", 20)
    monkeypatch.setattr(ratelimit, "PER_VISITOR_PER_HOUR", 200)
    monkeypatch.setattr(ratelimit, "SERVICE_PER_HOUR", 1500)
    for i in range(ratelimit.PER_VISITOR_PER_MINUTE):
        assert ratelimit.check("1.2.3.4", now=100 + i * 0.1) is None
    assert "minute" in ratelimit.check("1.2.3.4", now=103)
    assert ratelimit.check("5.6.7.8", now=103) is None, "another visitor is not affected"
    assert ratelimit.check("1.2.3.4", now=170) is None, "and the minute passes"


def test_the_whole_service_has_an_hourly_ceiling(monkeypatch):
    monkeypatch.setattr(ratelimit, "SERVICE_PER_HOUR", 5)
    for i in range(5):
        assert ratelimit.check(f"10.0.0.{i}", now=10 + i) is None
    assert "busy" in ratelimit.check("10.0.0.99", now=20)
    assert ratelimit.check("10.0.0.99", now=3700) is None


def test_over_the_limit_gets_429_and_never_reaches_gemini(monkeypatch):
    reached = []
    monkeypatch.setattr(main, "get_gemini_client", lambda: reached.append(1) or object())
    monkeypatch.setattr(ratelimit, "PER_VISITOR_PER_MINUTE", 0)
    resp = client.post("/agent/turn", data={"farmer_id": "f1", "text": "hello"})
    assert resp.status_code == 429 and resp.headers["retry-after"] and reached == []


def test_ordinary_pages_are_never_limited(monkeypatch):
    monkeypatch.setattr(ratelimit, "PER_VISITOR_PER_MINUTE", 0)
    assert client.get("/health").status_code == 200
