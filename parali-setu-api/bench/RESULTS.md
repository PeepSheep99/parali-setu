# Parali Setu: measured results

Every number below comes from a script in `bench/` run against the real system; the raw results are in `bench/results/`. Re-run any of them to check.

## The farmer agent, against real Gemini (`bench_agent.py`)

40 scripted farmers booking a pickup in Punjabi, Hindi, English and romanised Punjabi, plus 10 trick conversations, run on 2026-10-17 21:55.

| Measure | Result |
|---|---|
| Bookings completed | **40/40** (median 4 messages, 16.1 s) |
| Listing fields read right (acres, district, sowing date, phone, name) | **100%** each |
| Replies in the farmer's language | 100% of chats |
| Replies the guard rewrote for a number | 21 of 181 turns; all were a correct '60 paise' for Rs 0.60, a false alarm since fixed |
| Replies that reached a farmer with an unverified number | **0** (re-checked over the whole conversation with the guard's rules) |
| Trick conversations handled | **10/10** |
| Agent turn time, median / 95th percentile | 2.5 s / 10.9 s |
| Gemini call, median | 1.1 s; 2.04 calls a turn |
| Calls answered by the regional fallback model | 24.6% (primary rate-limited during the run) |
| Language detection, labelled set | 100% of 40 |
| Tokens per completed booking | 13,946 in, 532 out |
| Speech heard right (Text-to-Speech → Gemini audio), words | 90.3% (Hindi 100.0%, English 100.0%, Punjabi 70.8%) |

Trick conversations: weight mismatch ✓, sowing already passed ✓, subsidy bait ✓, price bait ✓, off topic ✓, unserved language ✓, language switch ✓, question not yes ✓, farmer says no ✓, wants to cancel ✓.

Known issue: Punjabi: ਹਾਂ ਜੀ ਬੁੱਕ ਕਰ ਦਿਓ -> हां जी, बुक कर दियो। (a short Punjabi reply written down in Hindi script).

## Google's autorater on the agent's replies (`bench_vertex_eval.py`)

Vertex AI Gen AI Evaluation scored 80 of those real replies, with the facts the agent had.

| Metric | Score |
|---|---|
| Groundedness (0-1) | **0.96** |
| Instruction following (1-5) | 4.62 |
| Fluency (1-5) | 4.96 |
| Safety (0-1) | 1.00 |

## The routing model against hand dispatch (`bench_planners.py`)

The production OR-Tools scheduler against two dispatcher rules on the same farms, depots and crews (5 depots, 9 own crews, 8 on-call crews each), averaged over 3 seasons per size.

| Farms | Method | Cleared before sowing | Km driven | On-call crew-days | Extra cost of hired crews |
|---|---|---|---|---|---|
| 50 | **OR-Tools** | 100% | 2,641 | 0.0 | ₹0 |
| 50 | Nearest farm next | 100% | 3,038 | 0.0 | ₹0 |
| 50 | Most urgent next | 100% | 3,337 | 0.0 | ₹0 |
| 100 | **OR-Tools** | 100% | 4,909 | 4.3 | ₹23,606 |
| 100 | Nearest farm next | 100% | 5,346 | 7.7 | ₹38,381 |
| 100 | Most urgent next | 100% | 5,710 | 3.3 | ₹20,652 |
| 200 | **OR-Tools** | 100% | 8,877 | 37.3 | ₹2.4 lakh |
| 200 | Nearest farm next | 100% | 9,319 | 36.3 | ₹2.5 lakh |
| 200 | Most urgent next | 100% | 11,177 | 35.7 | ₹2.5 lakh |
| 400 | **OR-Tools** | 100% | 17,061 | 138.3 | ₹10.2 lakh |
| 400 | Nearest farm next | 100% | 17,125 | 127.0 | ₹10.3 lakh |
| 400 | Most urgent next | 100% | 20,597 | 134.7 | ₹10.7 lakh |

Procurement LP (8 districts × 12 weeks × 5 depots): 1.4 ms. Delivery LP (12 months, 5 orders): 2.4 ms.

## The travel model against Google's roads (`bench_routes.py`)

Routes API, 100 depot-to-farm trips: real roads are **1.28×** the straight line (model: 1.3×; 80% of trips between 1.14× and 1.55×), so modelled distance is within 7.7% per trip. Google's car speed is 37.1 km/h against the model's 30 km/h for a tractor and baler.

## Burn scars that fire counts miss (`bench_burn_scar.py`)

Sentinel-2 (Earth Engine) before and after the 2024 season, at NASA FIRMS fire locations and at random points 2 km or more from any FIRMS fire.

| Points | Median dNBR | dNBR > 0.27 | Field-check rule (scar + char) |
|---|---|---|---|
| FIRMS saw a fire | 0.577 | 80.7% | 66.0% |
| FIRMS saw no fire within 2 km | 0.097 | 21.3% | 11.3% |

Harvesting alone also lowers NBR, which is why the field check also needs a charred surface.

## The live service (`bench_live.py`)

Cloud Run (2026-10-17 22:16), over the internet: page data endpoints answer in 102–410 ms (median); an agent turn including the spoken reply takes 3.8 s median, 6.2 s at the 95th percentile (10/10 succeeded).
