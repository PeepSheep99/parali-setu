"""Local development server: the real API (real Gemini, Speech and
Text-to-Speech) over an in-memory Firestore seeded like the demo, so the
apps can be tried end to end without touching the shared database.

    python dev_server.py            # http://127.0.0.1:8080
    python dev_server.py --port 8081

Serve the frontend separately (python -m http.server 8000 in
parali-setu-frontend) and point config.js's API_BASE at this server.
Data lives only for the life of the process.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def build_world():
    import pytest

    from fakes import use_fake_firestore

    patcher = pytest.MonkeyPatch()
    db = use_fake_firestore(patcher)

    import operations
    import pickups
    import reset_demo

    for path in sorted((ROOT / "forecast" / "data" / "results").glob("*.json")):
        db.collection("forecasts").document(path.stem).set(json.loads(path.read_text(encoding="utf-8")))
    today = pickups.now_ist().date()
    reset_demo.seed_depots(db)
    operations.run_procurement(db, today)
    reset_demo.seed_customers_and_orders(db, today)
    operations.run_procurement(db, today)
    listings = reset_demo.seed_listings(db, today)
    booked = [operations.book_listing(db, listing, today)[0] for listing in listings]
    pickups.plan_depots(db, {b["depot_id"] for b in booked if b})
    reset_demo.demo_run(db)
    operations.run_deliveries(db, today)
    return db, patcher


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    build_world()
    import uvicorn

    import main
    uvicorn.run(main.app, host="127.0.0.1", port=args.port, log_level="warning")
