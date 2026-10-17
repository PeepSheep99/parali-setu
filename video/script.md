# Parali Setu: 3-minute demo video

Narration: English, Google Chirp 3 HD (Indian English voice), one audio clip per scene.
Sync rule: each scene lasts exactly as long as its clip plus a short pause. The video
is built from the measured clip lengths, so picture and sound cannot drift.
On-screen text: only labels and numbers that the voice does not read out word for word.
Footage: screen recordings of the live site once the new project is deployed.

Target: about 430 spoken words (2:55-3:00 at a calm pace).

| # | Scene (what is on screen) | Narration (spoken, not shown) |
|---|---|---|
| 1 | Night satellite fire map of Punjab, the 2024 season playing day by day | Every October, Punjab's paddy fields burn. Farmers have about two weeks between the rice harvest and sowing wheat, and clearing the straw by machine costs them two and a half to four thousand rupees an acre. Burning costs almost nothing. So the smoke rolls over North India. |
| 2 | Title card: Parali Setu, Punjabi tagline | Parali Setu takes that whole job off the farmer. We clear the field for free before sowing, pay for the straw the same day, and sell it to power and biogas plants all year. |
| 3 | Farmer page: a real voice booking in Punjabi, live captions, the offer card | A farmer just talks, in Punjabi, Hindi or English, with no language to choose. Our assistant, built on Gemini, asks only for what's missing: acres, village, sowing date, name and number. |
| 4 | Offer card close-up: price, payout, pickup window; farmer says yes | Then it makes an offer: today's price for the district, the payout, and a pickup slot before the sowing date. The farmer says yes, in their own words, and the booking is made. |
| 5 | Split screen: a reply with a number highlighted, next to the tool result it came from | Here is the rule that keeps it honest. Gemini only talks. Every price, weight and date comes from our optimizers, and code checks every number in every reply. In testing, across a hundred and eighty replies, it did not make up a single number. |
| 6 | Ops dispatch board: crews on a 7-to-6 timeline, the call queue | Before any crew leaves, a person calls the farmer to confirm. Our routing model, built with Google OR-Tools, fits every farm into a crew's day, and hires on-call crews only when ours are full. Against simple dispatching rules, it drove up to thirteen percent less. |
| 7 | Forecast tab: TimesFM curve and district heat strip | To be ready for the rush, we forecast when each district harvests. Twenty-five seasons of NASA fire data in BigQuery, forecast with Google's TimesFM, placed last year's peak within a week. |
| 8 | Ops Impact: "Did the fields stay unburned?"; a before/after Sentinel-2 field | And after we collect a field, Earth Engine compares satellite photos from before and after. A burn scar stays for weeks, so it can catch burning that fire alerts miss. |
| 9 | Company portal: one sentence order, month-by-month supply | Companies order a year of straw in one sentence, and see what we can supply each month. |
| 10 | Architecture diagram, Google Cloud logos animating in | It all runs on Google Cloud: Gemini on Vertex AI for the conversation, Text-to-Speech and Speech-to-Text for voice, Cloud Run for the app and optimizers, Firestore, BigQuery, Earth Engine, Maps and Firebase Hosting. |
| 11 | Benchmark numbers appearing one by one: 40/40, 0 invented numbers, 10/10, 0.96 | We measured it. Forty test farmers, forty bookings, every detail recorded correctly, ten out of ten trick conversations handled, and Google's own AI grader scored our answers point nine six for sticking to the facts. |
| 12 | Back to the fire map, fading as farm pins turn green; closing title | Every field we clear is straw that isn't burned. Parali Setu: don't burn it, book a pickup. |

Notes
- Scene 5 is the "innovation" moment; give it the most screen time.
- Scene 11's numbers must match bench/RESULTS.md at recording time (update if the simulated-farmer benchmark changes them).
- Music: soft, low under the voice (Lyria if available on the new project; otherwise none).
