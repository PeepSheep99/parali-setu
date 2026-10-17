# Parali Setu

**Every October, Punjab's paddy fields burn. Parali Setu buys the straw instead.**

A farmer books a pickup by talking in Punjabi, Hindi or English. We clear the field before
wheat sowing and pay the same day. We store the straw at our depots and supply industry all
year. No vendors to chase, no machines to rent.

Google Cloud AI Builder Cup 2026 · Sustainability & Social Impact · Team Ctrl Alt Conquer (Navneet Kumar, Sainath)

| | |
|---|---|
| Live site | https://parali-setu.web.app |
| Farmer app | https://parali-setu.web.app/kisan/ (`?view=phone` talks, `?view=laptop` step by step) |
| Operations console | https://parali-setu.web.app/ops/ |
| Customer portal | https://parali-setu.web.app/company/ |
| Architecture | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |

*Parali* is Punjabi for paddy straw; *setu* means bridge.

## The problem

**The toll:**
- Living in a district with intense crop burning triples the risk of acute respiratory infection, and children under five are most affected ([IFPRI](https://www.ifpri.org/news-release/new-study-air-pollution-indias-stubble-burning-leads-usd-15-billion-economic-losses)).
- Each tonne burned releases about 0.18 t CO₂e of methane and nitrous oxide and about 8 kg of PM2.5.

**Fewer fires counted, the same area burned:**
- Punjab's counted farm fires fell from 36,663 in 2023 to about 5,085 in 2025.
- The area burned was unchanged: 19.17 lakh ha in 2024 against 19.14 lakh ha in 2023.

**Industry already wants the straw:** ex-situ use reached 5.96 Mt in 2024, against a target of about 7 Mt in 2025.

So why does a farmer still burn? Per acre of paddy:

| | |
|---|---|
| Straw produced | 17–18 quintals |
| Its value delivered to a plant | ₹2,200–3,000 |
| Baling and transport, paid by the farmer | ₹2,500–4,000 |
| Burning | about ₹500 and one day |
| Time before wheat must be sown | 10–15 days |

Selling the straw nets the farmer roughly nothing, and a baler that arrives after sowing is
worthless. **Parali Setu takes the whole job off the farmer and makes money on the other
side:** collecting efficiently, storing, and selling year-round to plants that today buy in a
six-week rush.

## How it works

1. **Talk once.** The farmer speaks freely. A Gemini agent understands Punjabi, Hindi or English audio directly, asks only for what's missing, and cross-checks what doesn't fit, such as 10 acres with 3,000 kg of straw, or a harvest after the sowing date. It reads the details back.
2. **One fair price.** Each district gets one posted farm-gate price per day (₹0.5–1.5/kg), set by our procurement optimizer. There is no bargaining.
3. **A slot before sowing.** A routing model books the farm onto one of our crews. If our crews can't reach the farm before sowing, a hired partner crew does, at our cost. The farmer accepts with a yes or one tap, and the slot is locked.
4. **Paid the same day.** When the crew collects, the payout is recorded (simulated UPI) and the straw goes into depot stock.
5. **Supplied all year.** Companies sign forward orders. A delivery optimizer ships from depot stock month by month and reports any shortfall.

## Google Cloud, and what each part does

| Service | Role |
|---|---|
| **Vertex AI · Gemini** | The farmer's talking agent, using function calling. Hears audio directly, giving the farmer's words plus an English record. Grades stubble photos and no-burn proof photos. Explains prices in plain words. **Never produces a number.** |
| **Speech-to-Text / Text-to-Speech** | Speech-to-Text is the fallback when Gemini can't hear the audio. Spoken replies use Chirp 3 HD voices in pa-IN, hi-IN and en-IN. |
| **BigQuery** | Weekly series of 25 paddy seasons of fire detections per district. **TimesFM (`AI.FORECAST`)** forecasts this season's harvest timing; **ARIMA_PLUS** and a same-as-last-year baseline are backtested against it. |
| **Earth Engine** | NASA FIRMS fire detections, 2001–2026, counted per day within FAO GAUL 2025 district boundaries for Punjab and Haryana. |
| **Cloud Run** | The API, with three OR-Tools planners: the procurement LP, the routing model and the delivery LP. Also the daily fire-refresh job, triggered by **Cloud Scheduler**. |
| **Firestore** | Bookings, depots, crews, slots, posted prices, purchases, stock moves, customers, orders, deliveries, plans, forecasts, conversations. |
| **Firebase Hosting** | The landing page, farmer app, ops console and customer portal. |
| **Maps JavaScript API** | Crew routes in the ops console. |
| **Billing budgets + Pub/Sub + Cloud Run function** | Cost guard. Emails both teammates, and closes the API and turns off the AI APIs if real money is ever charged. |

The design rule: **language from Gemini, numbers from optimizers, timing from satellites.**
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for diagrams, the agent's guardrails, the
three models and the data model.

## Forecasting, honestly

- **Supply timing.** The weekly fire detections per district (2002–2026) are real data. Both models saw data up to 30 June of a season and forecast September to December. Scores on two held-out seasons (lower is better):

| Season | Model | Season-shape error | Peak off by | Volume error |
|---|---|---|---|---|
| 2024 | **TimesFM** | **0.51** | **0.7 wk** | 1.78 |
| 2024 | ARIMA_PLUS | 1.13 | 5.2 wk | 0.99 |
| 2024 | Same as last year | 0.63 | 0.9 wk | 1.40 |
| 2025 | **TimesFM** | **0.66** | **0.8 wk** | 1.58 |
| 2025 | ARIMA_PLUS | 1.15 | 4.1 wk | 0.99 |
| 2025 | Same as last year | 0.70 | 1.0 wk | 0.83 |

  TimesFM gets the **timing** right. No model gets the **volume** right, because enforcement cut fire counts while the burned area held. So we use fires only for timing.
- **Supply volume** comes from the Ministry of Agriculture's APY crop statistics (via Kaggle): district rice production × a straw-to-grain ratio of 1.5. For Punjab in 2019 that is 12.68 Mt × 1.5 = 19.0 Mt, against the state's estimate of about 19.7 Mt.
- **Demand** is derived from published consumption by segment (biomass power, CBG, boilers, pellets), not trained: no public time series exists. It is labelled that way everywhere.

## The money, honestly

- **Pricing.** Farmers get today's posted price: a base of ₹0.60/kg, plus a bounded share of the procurement LP's shadow price where we need more straw than we expect to be booked.
- **Quotes.** A customer's quote is built from costs: farm-gate + collection + storage + haulage + 10% margin, shown against the ₹1,690/t that plants pay at harvest.
- **Assumptions.** The collection, storage and freight costs are our working assumptions, labelled as such on the ops console (`GET /costs`).
- **The catch.** At today's prices the margin is thin. The business depends on collecting more cheaply than hired balers (₹1,430–2,290/t), which is the routing model's job, and on industry valuing year-round supply.

## What's real and what's simulated

**Real:**
- satellite fire history, the TimesFM forecast and its backtests
- crop statistics and published demand figures
- the Gemini agent and voice
- all three optimizers

**Simulated:**
- farms, customers, crews and partner crews (all demo data)
- payments
- the cost figures marked "assumption"

## Repository layout

```
parali-setu-api/        FastAPI on Cloud Run (README inside)
  agent.py              farmer talking agent: Gemini function calling + guardrails
  procurement.py        LP: what to buy where; posted prices from shadow prices
  scheduler.py          routing: crew slots before sowing, partner crews
  deliveries.py         LP: depot -> customer orders, month by month
  costs.py              cost model and quotes
  operations.py         runs the planners on live data
  pickups.py            bookings, slots, same-day payouts, stock
  forecast/             FIRMS history, crop statistics, BigQuery TimesFM/ARIMA pipeline
parali-setu-frontend/   Firebase Hosting: / (landing), kisan/, ops/, company/
ops/cost-guard/         budget-triggered kill switch + restore script
docs/                   ARCHITECTURE.md; the original PRD (historical)
```

## Run it locally

Requires Python 3.12 and Application Default Credentials (`gcloud auth application-default login`).

```bash
python -m venv .venv && .venv/Scripts/pip install -r parali-setu-api/requirements.txt
cd parali-setu-api && python dev_server.py      # real Gemini and voice, in-memory demo data, :8080
cd parali-setu-frontend && python -m http.server 8000
# set API_BASE in parali-setu-frontend/config.js to http://127.0.0.1:8080
```

```bash
.venv/Scripts/python -m pytest parali-setu-api ops/cost-guard   # 132 tests, no credentials needed
python parali-setu-api/tests/live_smoke.py                      # real services; run reset_demo first
```

**Forecast pipeline:**

```bash
cd parali-setu-api
python -m forecast.firms_history --from 2001 --to 2026 --out forecast/data/fires_daily.csv
python -m forecast.crop_production --raw "forecast/data/raw/pyatakov/India Agriculture Crop Production.csv"
python -m forecast.pipeline backtest --season 2024      # and 2025
python -m forecast.pipeline live                        # this season's timing forecast
```

**Demo data:**

```bash
python parali-setu-api/reset_demo.py --yes
```

This wipes Parali Setu's own collections and seeds:
- 5 depots with their crews and a partner pool
- 5 demo customers with orders
- 25 farm bookings
- a small collected-and-paid run

## Deploy

```bash
gcloud run deploy parali-setu-api --source parali-setu-api --project <project> --region asia-southeast1 \
  --allow-unauthenticated --memory 1Gi --timeout 120 --max-instances 3 \
  --set-env-vars GCP_PROJECT_ID=<project>,GEMINI_MODEL=gemini-3.8-flash,AGENT_PLATFORM_LOCATION=global
firebase deploy --only hosting:parali-setu --project <project>
```

The daily fire refresh is the Cloud Run job `parali-setu-firms`, triggered by the Cloud Scheduler job `parali-setu-firms-daily` at 06:30 IST.

## Roadmap

- **Live voice.** A streaming conversation with Gemini Live. A test in us-central1 understood and answered spoken Punjabi, but was not yet reliable. A design that keeps the numbers guardrail streams transcription live and lets the guarded agent answer.
- **WhatsApp and missed-call channels** in front of the same agent.
- **One joint model** for buying, routing and delivery. **Routes API** travel times.
- **Real operations:** onboarding real balers, CHCs and aggregators; UPI payouts; farmer phone sign-in.

## Credits

The original Parali Setu prototype (the PRD, a matching LP, Gemini extraction, voice I/O) was
built by Sainath. Those commits are preserved in this repository's history. Version 2.0
turns it into a buyer-of-record service:
- the agent
- the forecasting
- the three planners
- the ops console and customer portal
