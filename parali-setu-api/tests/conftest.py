"""Shared fixtures. `world` is an in-memory Parali Setu: the fake Firestore,
the clock fixed at 09:00 IST on 17 Oct 2026, the real TimesFM season
forecast, and the demo depots, crews, customers and orders seeded by the
same code reset_demo.py uses, with today's prices posted."""
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

NOW = (2026, 10, 17, 9, 0)


@pytest.fixture
def fake_db(monkeypatch):
    import pickups
    from fakes import use_fake_firestore

    db = use_fake_firestore(monkeypatch)
    monkeypatch.setattr(pickups, "now_ist", lambda: datetime(*NOW, tzinfo=pickups.IST))
    return db


@pytest.fixture
def world(fake_db):
    import operations
    import pickups
    import reset_demo

    forecast = json.loads((ROOT / "forecast" / "data" / "results" / "supply_live_2026.json").read_text(encoding="utf-8"))
    fake_db.collection("forecasts").document("supply_live_2026").set(forecast)
    today = pickups.now_ist().date()
    reset_demo.seed_depots(fake_db)
    operations.run_procurement(fake_db, today)
    reset_demo.seed_customers_and_orders(fake_db, today)
    operations.run_procurement(fake_db, today, repost_today=True)
    return fake_db
