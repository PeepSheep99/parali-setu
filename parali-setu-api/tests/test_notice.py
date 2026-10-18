"""At least 24 hours' notice: a new request is never offered a pickup that
starts sooner, counted from when the farmer asked and rounded to the hour."""
from datetime import datetime, timedelta

import firestore_store as store
import pickups
from test_api_flows import _offer, api  # noqa: F401


def test_a_new_request_gets_a_slot_at_least_24_hours_later(api):
    booking = _offer(api, sowing="2026-10-28")["booking"]
    asked = datetime.fromisoformat(store.get_booking(api["db"], booking["id"])["requested_at"])
    first = min(booking["slots"], key=lambda s: (s["date"], s["window_start_min"]))
    starts = datetime.fromisoformat(first["date"]).replace(tzinfo=pickups.IST) + timedelta(minutes=first["window_start_min"])
    assert starts >= asked + timedelta(hours=24), (asked, starts)


def test_notice_rolls_to_the_next_morning_after_five_pm():
    evening = {"requested_at": "2026-10-18T18:30:00+05:30"}
    assert pickups.notice_start(evening) == (datetime(2026, 10, 20).date(), 0)
    morning = {"requested_at": "2026-10-18T08:10:00+05:30"}
    assert pickups.notice_start(morning) == (datetime(2026, 10, 19).date(), 9 * 60)
