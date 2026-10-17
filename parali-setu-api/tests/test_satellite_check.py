"""The Sentinel-2 field check after a pickup: verdicts, timing, and the daily
refresh writing them onto paid bookings (Earth Engine mocked)."""
from datetime import date, timedelta

import firestore_store as store
import satellite_check as sc
from test_api_flows import _offer, api, client  # noqa: F401


def test_verdicts():
    assert sc.verdict(0.58, -0.06) == "burn_scar"
    assert sc.verdict(0.35, 0.10) == "no_burn_scar", "a big drop on a still-green field is harvest, not fire"
    assert sc.verdict(0.05, -0.02) == "no_burn_scar"
    assert sc.verdict(None, None) == "no_clear_image"


def test_a_field_is_judged_only_after_the_after_window():
    d = date(2026, 10, 17)
    assert not sc.due(d, d + timedelta(days=sc.AFTER_END - 1))
    assert sc.due(d, d + timedelta(days=sc.AFTER_END))
    (b0, b1), (a0, a1) = sc.window(d)
    assert b1 == "2026-10-17" and a0 == "2026-10-20" and a1 == "2026-11-11"


def test_refresh_checks_paid_pickups_once_and_impact_counts_them(api):
    db = api["db"]
    booking = _offer(api)["booking"]
    client.post(f"/ops/bookings/{booking['id']}/accept")
    client.post(f"/ops/bookings/{booking['id']}/verify", json={})
    client.post(f"/stops/{booking['id']}/collected", json={})
    assert client.get("/impact").json()["field_checks"]["waiting_for_images"] == 1

    calls = []

    def fake_measure(fields):
        calls.append(fields)
        return [{"id": f["id"], "dnbr": 0.04, "nbr_after": 0.12, "verdict": "no_burn_scar"} for f in fields]

    assert sc.refresh(db, date(2026, 10, 20), fake_measure) == {}, "too early: no images after the pickup yet"
    later = date(2026, 10, 17) + timedelta(days=sc.AFTER_END)
    assert sc.refresh(db, later, fake_measure) == {"no_burn_scar": 1}
    assert store.get_booking(db, booking["id"])["field_check"]["verdict"] == "no_burn_scar"
    assert sc.refresh(db, later, fake_measure) == {}, "checked once"
    assert len(calls) == 1 and abs(calls[0][0]["lat"] - 30.2) < 1
    assert client.get("/impact").json()["field_checks"]["checked_clear"] == 1
