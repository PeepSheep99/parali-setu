# Parali Setu: demo video (v6, 3:56)

Narration: English, Google Chirp 3 HD (en-IN-Chirp3-HD-Charon, rate 0.78), one audio clip per scene.
Sync rule: each scene lasts exactly as long as its clip plus a short pause (build/make_timing_v6.py
writes remotion/src/timing.json, which also names each scene's component and audio file).
Music: none (removed in v7 so the narration stays clear).
Footage: screen recordings of the live site (read-only, except the one English booking, which was
cancelled afterwards).

| # | Scene (what is on screen) | Narration (spoken, not shown) |
|---|---|---|
| 1 | Night satellite fire map of Punjab, the 2024 season playing day by day | Every October, Punjab's paddy fields burn. Farmers have about two weeks between the rice harvest and sowing wheat, and clearing the straw by machine costs them two and a half to four thousand rupees an acre. Burning costs almost nothing. So the smoke rolls over North India. |
| 2 | Title card: Parali Setu, Punjabi tagline | Parali Setu takes that whole job off the farmer. We clear the field for free before sowing, pay for the straw the same day, and sell it to power and biogas plants all year. |
| 3 | Farmer page: a real typed booking in English; banner: farmers are free to speak or type in Punjabi, Hindi or English | A farmer just talks, in Punjabi, Hindi or English, with no language to choose. Our assistant, built on Gemini, asks only for what's missing: acres, village, sowing date, name and number. |
| 4 | Offer card close-up: price, payout, pickup window; farmer says yes | Then it makes an offer: today's price for the district, the payout, and a pickup slot before the sowing date. The farmer says yes, in their own words, and the booking is made. |
| 5 | A reply with its numbers highlighted, next to the offer card they came from | Here is the rule that keeps it honest. Gemini only talks. Every price, weight and date comes from our optimizers, and code checks every number in every reply. In testing, across a hundred and eighty replies, it did not make up a single number. |
| 6 | Ops Dispatch: crews on a 7-to-6 timeline, the call queue | Before any crew leaves, a person calls the farmer to confirm. Our routing model, built with Google OR-Tools, fits every farm into a crew's day, and hires on-call crews only when ours are full. Against simple dispatching rules, it drove up to thirteen percent less. |
| 7 | Ops Routes: a depot's crew sheets and route map | Every crew gets its day as a route sheet and a map: the stops in order, an arrival window for each farm, and the acres it can clear. Booked pickups stay fixed, and new offers are planned around them. |
| 8 | Ops Forecast: TimesFM curve, this week's fires around our farms | To be ready for the rush, we forecast when each district harvests. Twenty-five seasons of NASA fire data in BigQuery, forecast with Google's TimesFM, placed last year's peak within a week. |
| 9 | Ops Capacity: forecast acres a day against our crews; crews to sign up before the peak | The forecast then becomes a plan. Three weeks ahead, the capacity desk turns the expected harvest into crews: how many on-call crews to hire each day, and how many more to sign up before the peak arrives. |
| 10 | Ops Impact; before/after Sentinel-2 fields | And after we collect a field, Earth Engine compares satellite photos from before and after. A burn scar stays for weeks, so it can catch burning that fire alerts miss. |
| 11 | Company portal: one sentence order, month-by-month supply | Companies order a year of straw in one sentence, and see what we can supply each month. |
| 12 | The deck's architecture diagram (slide 8), Google Cloud services listed as named | It all runs on Google Cloud: Gemini on Vertex AI for the conversation, Text-to-Speech and Speech-to-Text for voice, Cloud Run for the app and optimizers, Firestore, BigQuery, Earth Engine, Maps and Firebase Hosting. |
| 13 | Agent benchmark: 40/40, 0 invented numbers, 12/12, 0.96 | We measured it. Forty test farmers, forty bookings, every detail recorded correctly, twelve out of twelve trick conversations handled, and Google's own AI grader scored our answers point nine six for sticking to the facts. |
| 14 | Performance (deck slide 13): −13% km, 1.28×, 66% vs 11%, 0.1–0.3 s, 3.7 s | Beyond the agent: our road distance estimate matches Google Maps, satellite photos found burn scars at sixty-six percent of NASA fire spots against eleven percent elsewhere, and the live site answers in a fraction of a second. |
| 15 | Fires give way to booked farms; closing title and credits | Every field we clear is straw that isn't burned. Parali Setu: don't burn it, book a pickup. |

Notes
- Scenes 13 and 14 must match bench/RESULTS.md (agent run 17 Oct 2026, trick re-run 18 Oct 2026).
