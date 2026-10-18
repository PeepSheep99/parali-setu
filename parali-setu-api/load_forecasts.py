"""Loads the committed forecast results (TimesFM season forecast and the two
backtests) into Firestore's `forecasts` collection, so a fresh project serves
them without running BigQuery or Earth Engine.

    GCP_PROJECT_ID=<project> python load_forecasts.py

Only writes three documents. Run reset_demo.py --yes after it to seed the demo
season.
"""
import json
from pathlib import Path

import firestore_store as store

RESULTS = Path(__file__).resolve().parent / "forecast" / "data" / "results"


def main() -> None:
    db = store.get_firestore_client()
    for path in sorted(RESULTS.glob("*.json")):
        db.collection("forecasts").document(path.stem).set(json.loads(path.read_text(encoding="utf-8")))
        print("loaded", path.stem, "into", store.PROJECT_ID)


if __name__ == "__main__":
    main()
