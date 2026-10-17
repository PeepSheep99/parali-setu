# Parali Setu: API

A FastAPI service on Cloud Run. The design is in [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

| Module | Does |
|---|---|
| `agent.py` | The farmer's talking agent: Gemini function calling, tools, guardrails enforced in code |
| `extraction.py`, `gemini_client.py` | Gemini calls: listing extraction, the single follow-up question, audio understanding, photo grading, explanations. A quota error triggers a 60-second cooldown. |
| `speech.py`, `phrases.py` | Speech-to-Text and Text-to-Speech (pa/hi/en); deterministic read-backs, fallbacks and spoken pickup windows |
| `procurement.py` | LP: tonnes per district, depot and week; posted prices from shadow prices |
| `scheduler.py` | Routing over crew-days; partner crews in a second pass; reason codes |
| `deliveries.py` | LP: depot → customer orders by month, with stock carried over |
| `costs.py` | Cost constants (sourced or assumption) and customer quotes |
| `operations.py` | Runs the planners on Firestore data and the forecasts; `book_listing` |
| `pickups.py` | Locations, windows, offer expiry, depot planning, accept, `complete_pickup` |
| `impact.py`, `trust.py`, `geo.py` | Impact factors; no-burn trust score; districts |
| `firestore_store.py` | Firestore access; the booking lifecycle in a transaction |
| `forecast/` | FIRMS history (Earth Engine), crop statistics (Kaggle APY), BigQuery TimesFM/ARIMA pipeline, demand segments |

## Endpoints

| Who | Endpoint |
|---|---|
| Farmer, talking | `POST /agent/turn` (voice or text, optional photo) |
| Farmer, step by step | `POST /listings/draft`, `POST /listings/{draft_id}/confirm` |
| Farmer, either way | `POST /bookings/{id}/accept`, `POST /bookings/{id}/cancel`, `GET /farmers/{id}/bookings`, `GET /bookings/{id}/price-explanation`, `POST /farmers/{id}/no-burn-proof` |
| Ops | `GET /ops/summary`, `GET /depots`, `GET /depots/{id}/schedule`, `POST /depots/{id}/replan`, `POST /depots/{id}/crews`, `POST /ops/bookings/{id}/accept` (demo), `POST /stops/{id}/collected` |
| Ops | `GET /inventory`, `GET /purchases`, `GET\|POST /plan/procurement`, `GET /plan/deliveries`, `GET /forecast`, `GET /costs`, `GET /agent/conversations/{id}` |
| Customers | `GET /customers`, `POST /customers/{id}/quote`, `POST /customers/{id}/orders`, `GET /customers/{id}/orders` |
| Public | `GET /prices/today`, `GET /impact`, `GET /impact/scenario`, `GET /fires/history`, `GET /fire-detections`, `GET /health` |

## Configuration

| Variable | Default |
|---|---|
| `GCP_PROJECT_ID` | `ai-builder-cup-aidatlas` |
| `GEMINI_MODEL` | `gemini-3.8-flash` |
| `AGENT_PLATFORM_LOCATION` | `global` |
| `ALLOWED_ORIGINS` | the `parali-setu` Firebase Hosting origins and `localhost:8000` |

Authentication is via Application Default Credentials; there are no API keys.

## Run, test, seed

```bash
python dev_server.py            # real Gemini/voice over an in-memory demo world, :8080
uvicorn main:app --port 8080    # against the shared Firestore
pytest                          # 132 tests, in-memory Firestore fake, no credentials
python tests/live_smoke.py      # real services end to end; run reset_demo.py first
python reset_demo.py --yes      # wipe Parali Setu's collections and seed the demo season
```

`tests/fakes.py` is an in-memory stand-in for the slice of Firestore the store uses. With it,
whole flows run in tests: book → plan → accept → collect → pay → deliver.

## Deploy

```bash
gcloud run deploy parali-setu-api --source . --project ai-builder-cup-aidatlas --region asia-southeast1 \
  --allow-unauthenticated --memory 1Gi --timeout 120 --max-instances 3 \
  --set-env-vars GCP_PROJECT_ID=ai-builder-cup-aidatlas,GEMINI_MODEL=gemini-3.8-flash,AGENT_PLATFORM_LOCATION=global
```
