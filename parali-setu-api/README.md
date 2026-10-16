# Parali Setu: backend

A FastAPI service on Cloud Run. The design and diagrams are in
[../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

| Module | Layer | Does |
|---|---|---|
| `extraction.py`, `gemini_client.py` | Language | Gemini on Vertex AI: listing extraction, the single follow-up question, photo grading, narration. Quota errors start a 60-second cooldown. |
| `speech.py` | Language | Cloud Speech-to-Text (pa-IN, hi-IN) and Text-to-Speech |
| `phrases.py` | Language | Deterministic read-back of the listing in pa/hi/en |
| `solver.py`, `negotiation.py` | Market | OR-Tools transportation LP: buyer, kg and price, within the buyer's service radius and price ceiling; two-sided negotiation rounds |
| `scheduler.py`, `pickups.py` | Logistics | OR-Tools routing over crew-days: pickup slots before the sowing deadline, locked slots, waitlist with reasons; IST planning |
| `impact.py` | Impact | Sourced emission and cost factors; Punjab scenario |
| `geo.py` | | District coordinates and aliases (English, Devanagari, Gurmukhi), haversine |
| `firestore_store.py` | State | Firestore access; transactional quantity updates and match-status transitions |
| `main.py` | API | Endpoints, CORS (`ALLOWED_ORIGINS`), request bounds |

## Main endpoints

| Who | Endpoint |
|---|---|
| Farmer | `POST /listings/draft`, `POST /listings/{draft_id}/confirm`, `POST /matches/{id}/accept-slot`, `GET /farmers/{id}/pickups`, `POST /farmers/{id}/no-burn-proof`, `GET /matches/{id}/pricing-explanation`, `POST /negotiate/agents`, `POST /matches/{id}/confirm-price` |
| Buyer | `GET /companies`, `GET/POST /companies/{id}/demand`, `GET /companies/{id}/dashboard`, `GET /buyers/{id}/fleet`, `GET /buyers/{id}/schedule`, `POST /schedule/solve`, `POST /matches/{id}/status`, `POST /stops/{match_id}/collected`, `GET /buyers/{id}/impact` |
| Public | `GET /impact`, `GET /impact/scenario?share_pct=`, `GET /fire-detections`, `GET /health` |

The original one-shot `POST /listings` and `POST /listings/voice` still work.

## Configuration

| Variable | Default |
|---|---|
| `GCP_PROJECT_ID` | `ai-builder-cup-aidatlas` |
| `GEMINI_MODEL` | `gemini-3.8-flash` |
| `AGENT_PLATFORM_LOCATION` | `global` |
| `ALLOWED_ORIGINS` | the `parali-setu` Firebase Hosting origins and `localhost:8000` |

Authentication uses Application Default Credentials, with no API keys. Locally, run
`gcloud auth application-default login`. On Cloud Run, the service account is used.

## Run, test, seed, deploy

```bash
uvicorn main:app --port 8080
pytest                          # mocked; no credentials needed
python tests/live_smoke.py      # real Gemini / Firestore / Speech / TTS; needs ADC
python reset_demo.py --yes      # wipe Parali Setu's collections and seed the demo scenario
python fetch_fire_data.py       # Earth Engine FIRMS batch -> fire_detections
python forecast_pipeline.py     # BigQuery ML forecast -> forecasts
```

`live_smoke.py` is not named `test_*.py` on purpose, so `pytest` never runs it without
credentials. It creates its own smoke-test buyers and cleans them up afterwards.

To retrain the forecast after regenerating the synthetic corpus (`seed_data.py`), run
`bq query --use_legacy_sql=false < bigquery/forecast_model.sql` first.

Deploy:

```bash
gcloud run deploy parali-setu-api --source . \
  --project ai-builder-cup-aidatlas --region asia-southeast1 --allow-unauthenticated \
  --set-env-vars GCP_PROJECT_ID=ai-builder-cup-aidatlas,GEMINI_MODEL=gemini-3.8-flash,AGENT_PLATFORM_LOCATION=global \
  --memory 1Gi --timeout 120 --max-instances 3
```

## Known limitations

- `read_stubble_quality()` is noisy on ambiguous photos (see `seed/reference_photos/ATTRIBUTION.md`). It is only a soft matching signal and never sets a price.
- The baling rate and crew capacity in `scheduler.py` are working assumptions.
- Travel times are estimated from straight-line distance.
