"""cost-guard: auto-throttle Parali Setu when real money starts being charged.

Triggered by the Cloud Billing budget "Parali Setu - REAL money (net)"
(spend after credits) through the `billing-alerts` Pub/Sub topic. Budgets
publish to that topic several times a day regardless of thresholds, so this
function decides for itself whether to act: only when the message comes from
the trigger budget AND costAmount >= budgetAmount.

When it acts it is reversible by design -- nothing is deleted:
  1. sets ingress=internal on each Cloud Run service in SERVICES, so public
     traffic (and the cost it drives) stops;
  2. disables the paid AI APIs in APIS_TO_DISABLE (Gemini on Vertex AI,
     Speech-to-Text, Text-to-Speech).
Undo with ops/cost-guard/restore.sh.

DRY_RUN defaults to "true": it logs what it would do and touches nothing.
"""
from __future__ import annotations

import base64
import json
import os

import functions_framework

PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "parali-setu-aibuildercup2026")
REGION = os.environ.get("REGION", "asia-southeast1")
TRIGGER_BUDGET_NAME = os.environ.get("TRIGGER_BUDGET_NAME", "Parali Setu - REAL money (net)")
SERVICES = [s for s in os.environ.get("SERVICES", "parali-setu-api").split(",") if s]
APIS_TO_DISABLE = [
    a for a in os.environ.get(
        "APIS_TO_DISABLE",
        "aiplatform.googleapis.com,speech.googleapis.com,texttospeech.googleapis.com",
    ).split(",") if a
]


def _dry_run() -> bool:
    return os.environ.get("DRY_RUN", "true").strip().lower() != "false"


def _log(severity: str, message: str, **fields) -> None:
    # One JSON line per event -- Cloud Logging parses it into a structured entry.
    print(json.dumps({"severity": severity, "message": message, "component": "cost-guard", **fields}))


def parse_budget_message(data: bytes | str) -> dict:
    """Decode the budget notification payload (JSON, base64 inside Pub/Sub)."""
    if isinstance(data, str):
        data = base64.b64decode(data)
    return json.loads(data.decode("utf-8"))


def should_throttle(notification: dict) -> bool:
    if notification.get("budgetDisplayName") != TRIGGER_BUDGET_NAME:
        return False
    try:
        cost = float(notification.get("costAmount", 0))
        budget = float(notification.get("budgetAmount", 0))
    except (TypeError, ValueError):
        return False
    return budget > 0 and cost >= budget


def throttle(run_client, usage_client, dry_run: bool) -> dict:
    """Apply the reversible throttle. Clients are injected so tests can mock them."""
    from google.cloud import run_v2

    actions = {"ingress_internal": [], "apis_disabled": [], "dry_run": dry_run}

    for service in SERVICES:
        name = f"projects/{PROJECT_ID}/locations/{REGION}/services/{service}"
        if dry_run:
            actions["ingress_internal"].append(service)
            continue
        current = run_client.get_service(name=name)
        if current.ingress == run_v2.IngressTraffic.INGRESS_TRAFFIC_INTERNAL_ONLY:
            continue
        current.ingress = run_v2.IngressTraffic.INGRESS_TRAFFIC_INTERNAL_ONLY
        run_client.update_service(service=current).result()
        actions["ingress_internal"].append(service)

    for api in APIS_TO_DISABLE:
        if not dry_run:
            usage_client.disable_service(
                request={
                    "name": f"projects/{PROJECT_ID}/services/{api}",
                    "disable_dependent_services": False,
                    "check_if_service_has_usage": "SKIP",
                }
            ).result()
        actions["apis_disabled"].append(api)

    return actions


@functions_framework.cloud_event
def handle_budget_alert(cloud_event) -> None:
    notification = parse_budget_message(cloud_event.data["message"]["data"])
    summary = {
        "budget": notification.get("budgetDisplayName"),
        "cost": notification.get("costAmount"),
        "budget_amount": notification.get("budgetAmount"),
        "currency": notification.get("currencyCode"),
    }
    if not should_throttle(notification):
        _log("INFO", "budget notification received, no action", **summary)
        return

    from google.cloud import run_v2, service_usage_v1

    dry_run = _dry_run()
    actions = throttle(run_v2.ServicesClient(), service_usage_v1.ServiceUsageClient(), dry_run)
    _log(
        "WARNING" if dry_run else "CRITICAL",
        "DRY RUN: would throttle Parali Setu" if dry_run else "THROTTLED Parali Setu: real money being charged",
        actions=actions,
        **summary,
    )
