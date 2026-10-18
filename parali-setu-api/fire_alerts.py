"""A satellite fire near a farm we have booked: reach that farm first.

After the daily FIRMS refresh (fetch_fire_data.py), every farm with an open
booking (offered, booked or confirmed) is checked against this week's fire
detections. A fire within ALERT_RADIUS_KM means burning is happening around
that farm right now, so its straw is at risk.

Event-driven on Google Cloud: the daily job publishes each alert to the
Pub/Sub topic FIRE_ALERT_TOPIC; a push subscription delivers it to the API
(POST /pubsub/fire-alerts), which records it and flags the booking for the
ops dispatch board. Without a topic configured (tests, local runs) alerts are
recorded directly.
"""
from __future__ import annotations

import json
import os

from geo import haversine_km

ALERT_RADIUS_KM = 5.0
OPEN_STATUSES = ("offered", "booked", "verified")


def find(detections: list[dict], farms: list[dict], radius_km: float = ALERT_RADIUS_KM) -> list[dict]:
    """farms: [{"booking_id", "lat", "lon", ...}]. One alert per farm: the
    nearest detection within radius_km, or none."""
    alerts = []
    for farm in farms:
        best = None
        for d in detections:
            if d.get("lat") is None or d.get("lon") is None:
                continue
            km = haversine_km(farm["lat"], farm["lon"], d["lat"], d["lon"])
            if km <= radius_km and (best is None or km < best[0]):
                best = (km, d)
        if best:
            km, d = best
            alerts.append({"booking_id": farm["booking_id"], "depot_id": farm.get("depot_id"),
                           "distance_km": round(km, 1), "detected_at": d.get("detected_at"),
                           "fire_lat": round(d["lat"], 4), "fire_lon": round(d["lon"], 4)})
    return alerts


def open_farms(db) -> list[dict]:
    import firestore_store as store
    import pickups
    farms = []
    for b in store.get_bookings(db, OPEN_STATUSES):
        loc = pickups.listing_location(store.get_listing(db, b["listing_id"]) or {})
        if loc is not None:
            farms.append({"booking_id": b["id"], "depot_id": b.get("depot_id"), "lat": loc[0], "lon": loc[1]})
    return farms


def record(db, alert: dict) -> bool:
    """Saves an alert once (a re-delivered message is not counted twice) and
    flags the booking. Returns True if it was new."""
    import firestore_store as store
    doc_id = f"{alert['booking_id']}_{alert.get('detected_at') or 'unknown'}"
    ref = db.collection("fire_alerts").document(doc_id)
    if ref.get().exists:
        return False
    ref.set({**alert, "id": doc_id})
    if store.get_booking(db, alert["booking_id"]):
        store.update_booking_fields(db, alert["booking_id"], {"fire_nearby": alert})
    return True


def publish(alerts: list[dict], topic: str) -> int:
    from google.cloud import pubsub_v1
    publisher = pubsub_v1.PublisherClient()
    futures = [publisher.publish(topic, json.dumps(a).encode("utf-8")) for a in alerts]
    for f in futures:
        f.result(timeout=60)
    return len(futures)


def dispatch(db, detections: list[dict]) -> dict:
    """Finds alerts for open bookings and sends them through Pub/Sub when a
    topic is configured, else records them directly."""
    alerts = find(detections, open_farms(db))
    topic = os.environ.get("FIRE_ALERT_TOPIC")
    if alerts and topic:
        return {"alerts": len(alerts), "published": publish(alerts, topic)}
    return {"alerts": len(alerts), "recorded": sum(record(db, a) for a in alerts)}
