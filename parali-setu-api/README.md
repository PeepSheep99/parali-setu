# Parali Setu: API

A FastAPI service on Cloud Run. The design is in [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

| Module | Does |
|---|---|
| `agent.py` | The farmer's talking agent: Gemini function calling, tools, guardrails enforced in code (numbers, claims, language, an explicit yes), regional fallback model |
| `language.py` | Which language the farmer speaks, from the script and romanised cue words; the trilingual reply for other languages |
| `live.py` | Live words: streaming transcription that hears Punjabi, Hindi and English at once |
| `extraction.py`, `gemini_client.py` | Gemini perception jobs: audio understanding, photo grading (straw and no-burn proof), English records. A quota error triggers a 60-second cooldown. |
| `speech.py`, `phrases.py` | Speech-to-Text and Text-to-Speech (pa/hi/en); the agent's deterministic fallbacks and spoken pickup windows |
| `procurement.py` | LP: tonnes per district, depot and week; posted prices from shadow prices |
| `scheduler.py` | Routing over crew-days; on-call crews in a second pass; reason codes |
| `deliveries.py` | LP: depot → customer orders by month, stock carried over, earliest signed order served first |
| `costs.py` | Cost constants (sourced or assumption) and customer quotes |
| `operations.py` | Runs the planners on Firestore data and the forecasts (today's price locked once posted); `book_listing`; `committable` for quotes; `readiness` (forecast acres vs crews) |
| `pickups.py` | Locations, windows, offer expiry, one open offer per farmer, depot planning, accept, `verify_booking`, `complete_pickup` (needs a verified booking) |
| `impact.py`, `trust.py`, `geo.py` | Impact factors; no-burn trust score; districts |
| `firestore_store.py` | Firestore access; the booking lifecycle in a transaction |
| `forecast/` | FIRMS history (Earth Engine), crop statistics (Kaggle APY), BigQuery TimesFM/ARIMA pipeline, demand segments |

## Endpoints

| Who | Endpoint |
|---|---|
| Farmer, talking | `POST /agent/turn` (voice or text, optional photo; the language is detected), `WS /agent/live`, `POST /speech`, `POST /demo/locate` |
| Farmer, pickups | `POST /bookings/{id}/accept`, `POST /bookings/{id}/cancel`, `GET /farmers/{id}/bookings`, `POST /farmers/{id}/no-burn-proof` |
| Ops | `GET /ops/dispatch?day=`, `POST /ops/bookings/{id}/verify`, `POST /ops/bookings/{id}/needs-change`, `POST /ops/verify-all` (demo), `GET /ops/summary`, `GET /depots`, `GET /depots/{id}/schedule`, `POST /depots/{id}/replan`, `POST /depots/{id}/crews`, `POST /ops/bookings/{id}/accept` (demo), `POST /stops/{id}/collected` |
| Ops | `GET /inventory`, `GET /purchases`, `GET\|POST /plan/procurement`, `GET /plan/deliveries`, `GET /forecast`, `GET /forecast/seasons`, `GET /costs`, `GET /agent/conversations/{id}` |
| Customers | `GET /customers`, `POST /customers/{id}/quote` (with what we can commit), `POST /customers/{id}/orders`, `GET /customers/{id}/orders`, `POST /customers/{id}/orders/{oid}/cancel` |
| Public | `GET /prices/today`, `GET /impact`, `GET /impact/scenario`, `GET /fires/history`, `GET /fire-detections`, `GET /health` |

## Configuration

| Variable | Default |
|---|---|
| `GCP_PROJECT_ID` | `parali-setu-aibuildercup-2026` |
| `GEMINI_MODEL` | `gemini-3.5-flash` |
| `AGENT_FALLBACK_MODEL`, `AGENT_FALLBACK_LOCATION` | `gemini-2.5-flash`, `asia-south1` |
| `LIVE_TRANSCRIBE_MODEL`, `LIVE_LOCATION` | `gemini-3.5-transcribe-live`, `global` |
| `AGENT_PLATFORM_LOCATION` | `global` |
| `ALLOWED_ORIGINS` | the `parali-setu` Firebase Hosting origins and `localhost:8000` |

Authentication is via Application Default Credentials; there are no API keys.

## Run, test, seed

```bash
python dev_server.py            # real Gemini/voice over an in-memory demo world, :8080
uvicorn main:app --port 8080    # against the shared Firestore
pytest                          # in-memory Firestore fake, no credentials
python tests/live_smoke.py      # real services end to end; run reset_demo.py first
python reset_demo.py --yes      # wipe Parali Setu's collections and seed the demo season
```

`tests/fakes.py` is an in-memory stand-in for the slice of Firestore the store uses. With it,
whole flows run in tests: book → plan → accept → verify → collect → pay → deliver.

## Deploy

```bash
gcloud run deploy parali-setu-api --source . --project parali-setu-aibuildercup-2026 --region asia-southeast1 \
  --allow-unauthenticated --memory 1Gi --timeout 300 --max-instances 3 \
  --set-env-vars GCP_PROJECT_ID=parali-setu-aibuildercup-2026,GEMINI_MODEL=gemini-3.5-flash,AGENT_PLATFORM_LOCATION=global
```
