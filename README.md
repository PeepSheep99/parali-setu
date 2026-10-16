# Parali Setu

**A guaranteed stubble pickup before sowing, so the farmer gets paid instead of burning.**

Google Cloud AI Builder Cup 2026 · Sustainability & Social Impact · Team Ctrl Alt Conquer (Navneet Kumar, Sainath)

| | |
|---|---|
| Live site | https://parali-setu.web.app |
| Farmer app (mobile) | https://parali-setu.web.app/kisan/ |
| Buyer console (desktop) | https://parali-setu.web.app/buyer/ |
| API health | https://parali-setu-api-866617346749.asia-southeast1.run.app/health |
| Architecture | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |

*Parali* is Punjabi for paddy stubble; *setu* means bridge.

## The problem

Punjab's farm-fire **count** fell from 36,663 in 2023 to about 5,085 in 2025. The burnt
**area** did not: 19.14 lakh hectares in 2023 against 19.17 lakh hectares in 2024. That
points to burning timed to avoid satellite passes, rather than less burning. Meanwhile industry's use of paddy straw grew
from 0.92 Mt to about 7.06 Mt. The buyers exist.

So why does a farmer still burn? Per acre of paddy:

| | |
|---|---|
| Straw produced | 17–18 quintals |
| Its value delivered to a plant | ₹2,200–3,000 |
| Baling and transport, paid by the farmer | ₹2,500–4,000 |
| Burning | about ₹500 and one day |
| Time before wheat must be sown | 10–15 days |

Selling the straw nets the farmer roughly nothing, and a baler that arrives after the
sowing date is worthless to them. **The bottleneck is a guaranteed, free pickup inside
that window, coordinated across a scarce fleet of balers.** That is what Parali Setu
optimizes.

## What it does

1. **Speak once.** The farmer holds one button in the Kisan app and says, in Punjabi or
   Hindi, how many acres they have, which crop, the village and when the field must be clear.
2. **Confirm once.** The app reads the details back. If something is missing, it asks
   **one** question. An optional photo lets Gemini grade the stubble.
3. **Matched and scheduled.** A linear program picks the buyer whose crews can reach the
   farm. A routing model books a 3-hour pickup window before the sowing deadline, around
   slots already promised to other farmers. If no slot fits, the farmer is told why and
   waitlisted, not given a false promise.
4. **Collected and paid.** The buyer's crew marks the stop collected. The farmer's payout
   (kg × agreed price) is recorded, and the avoided emissions are counted.

The buyer console has four tabs:
- **Pickup Ops:** per-crew daily routes on Google Maps, a Re-plan button, and the waitlist with reasons.
- **Supply:** matched listings.
- **Demand:** standing demand with price and ceiling.
- **Impact:** tonnes collected, CO₂e avoided, farmer payouts.

## How Google Cloud is used

| Service | Role |
|---|---|
| **Gemini on Vertex AI** | Extracts acres, crop, district and sowing date from Punjabi/Hindi speech or text. Writes the single follow-up question. Grades stubble photos and no-burn proof photos. Narrates offers and the negotiation, each side stating its own number. It **never** produces a price, quantity, date or slot. |
| **Cloud Speech-to-Text / Text-to-Speech** | Voice in (pa-IN, hi-IN) and spoken replies (Chirp3-HD voices) |
| **Cloud Run** (`parali-setu-api`) | FastAPI service running both OR-Tools models, capped at 3 instances |
| **OR-Tools** | Market: a transportation LP (GLOP) for buyer, kg and price. Logistics: a capacitated vehicle routing model with time windows for crew, day and slot. |
| **Firestore** | Live state: listings, drafts, demand, matches, crews, pickup slots, payouts, negotiation sessions. Transactional quantity updates. |
| **BigQuery ML** (ARIMA_PLUS) | Seasonal demand forecast shown to buyers as background. Trained on a synthetic corpus and labelled as such. |
| **Earth Engine** (NASA FIRMS) | Fire detections for the landing-page map. Also cross-checks farmers' no-burn proofs, which feed a trust weight in matching. Batch refresh, not live. |
| **Firebase Hosting** | One site with three routes: `/`, `/kisan/`, `/buyer/` |
| **Maps JavaScript API** | Fire map and crew route maps, with a referrer-restricted key |
| **Cloud Billing budgets + Pub/Sub + a Cloud Run function** | Cost guard: emails both teammates; if real money is ever charged, the API's ingress is closed and the AI APIs are disabled (reversible) |

The design rule is **language from Gemini, numbers from optimizers**. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the deployment diagram, sequence
diagrams, match lifecycle, data model and the two optimization models.

## Impact methodology

Per tonne of straw collected instead of burned (`parali-setu-api/impact.py`):

- **≈ 0.184 t CO₂e avoided:** methane (5.82 kg × GWP 27) plus nitrous oxide (0.1 kg × GWP 273). Factors from Gadde et al. 2009; GWPs from IPCC AR6.
- **CO₂ from burning straw is biogenic and is not counted.**
- **Other figures:**
  - 8.3 kg of PM2.5 (range 4.7–20)
  - 102 kg of CO
  - ₹2,500–4,000 per acre of clearing cost avoided
- **Coal displacement** (about 1.33 t CO₂ per tonne, only when the buyer co-fires instead of coal) is shown separately and never added to the headline.

At 10% of Punjab's ~19.7 Mt of paddy straw, that is about 1.97 Mt collected and about
363 kt CO₂e avoided. The landing page has a slider for other shares.

## Honest limitations

- Buyers, crews and listings are **demo data** (marked "(demo)"). Payments are **simulated**.
- The baling rate (2 acres per crew-hour) and crew capacity (20 acres per day) are working assumptions, still to be checked against field data.
- Travel time is straight-line distance × 1.3 at 30 km/h, not a road-network matrix.
- The demand forecast is trained on synthetic data. Fire detections refresh in batch.
- There are no user accounts yet. A farmer is an anonymous id stored on the phone.
- Prices are farm-gate estimates of ₹0.5–1.5/kg. They sit below the delivered price (~₹169/quintal) because the buyer's crew does the baling and transport.

## Repository layout

```
parali-setu-api/        FastAPI backend on Cloud Run (README inside)
parali-setu-frontend/   Static site on Firebase Hosting: landing, kisan/, buyer/
ops/cost-guard/         Budget-triggered kill switch (Cloud Run function) + restore script
docs/ARCHITECTURE.md    Diagrams and design notes
docs/PARALI_SETU_PRD.md The original product spec (historical; see its status note)
```

## Run it locally

Requires Python 3.12 and Application Default Credentials
(`gcloud auth application-default login`) for a GCP project with Firestore, Vertex AI,
Speech-to-Text and Text-to-Speech enabled.

```bash
python -m venv .venv && .venv/Scripts/pip install -r parali-setu-api/requirements.txt   # bin/ on macOS/Linux
cd parali-setu-api
GCP_PROJECT_ID=<your-project> uvicorn main:app --port 8080
# in another shell: serve the frontend, then set API_BASE in config.js to http://127.0.0.1:8080
cd parali-setu-frontend && python -m http.server 8000
```

### Tests

```bash
.venv/Scripts/python -m pytest parali-setu-api ops/cost-guard   # 118 tests, all mocked, no credentials
python parali-setu-api/tests/live_smoke.py                      # against real GCP APIs; needs ADC
```

### Demo data

```bash
python parali-setu-api/reset_demo.py --yes                # wipe Parali Setu's collections, seed 5 buyers, 8 crews, 25 listings, then match and plan
python parali-setu-api/reset_demo.py --yes --no-listings  # buyers, crews and demand only
```

The seed overloads the Patiala buyer on purpose, so the waitlist is visible. The script
never touches `forecasts` or `fire_detections`.

## Deploy

```bash
gcloud run deploy parali-setu-api --source parali-setu-api \
  --project <project> --region asia-southeast1 --allow-unauthenticated \
  --set-env-vars GCP_PROJECT_ID=<project>,GEMINI_MODEL=gemini-3.8-flash,AGENT_PLATFORM_LOCATION=global \
  --memory 1Gi --timeout 120 --max-instances 3

firebase deploy --only hosting:parali-setu --project <project>
```

Batch jobs: `python parali-setu-api/fetch_fire_data.py` (Earth Engine FIRMS) and
`python parali-setu-api/forecast_pipeline.py` (BigQuery ML). The cost guard's setup is
in [ops/cost-guard/README.md](ops/cost-guard/README.md).

## Roadmap

- **A WhatsApp-style conversational channel.** A Gemini function-calling agent behind a channel-agnostic `/chat`, with tools wrapping the same listing, slot, negotiation, proof and payout endpoints, and a guardrail that every number comes from a tool. Adapters: WhatsApp Business, then IVR/missed-call for feature phones. The Kisan app is the first front end for the same "speak once, confirm once" idea.
- **Better models:** a joint matching and routing model, and Routes API travel times.
- **Real operations:** Firebase Auth (phone OTP for farmers), a UPI payout rail, onboarding of real balers, aggregators and CHCs.

## Credits

The original Parali Setu prototype (the PRD, the matching LP, Gemini extraction, voice
I/O and the forecast pipeline) was built by Sainath. Those commits are preserved in this
repository's history. The revamp adds:
- the pickup scheduler
- the Kisan app and buyer console
- the impact model
- the cost guard
