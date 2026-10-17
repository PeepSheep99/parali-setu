# Parali Setu: frontend

Plain HTML, CSS and JavaScript with no build step, served by Firebase Hosting as one site.
All four apps share one design system, `shared/tokens.css` (the phulkari palette: madder,
silk gold, khaddar; Baloo Paaji 2 and Hind):

| Route | For |
|---|---|
| `/` | Landing page: the toll, the promise, how it works, the 25-season satellite record, who buys straw, the four apps, the Google Cloud build, the impact scenario |
| `/kisan/` | The pickup page: one conversation for every screen, with no language step. The farmer speaks (tap to record, or "Live words" for captions as they speak) or types in Punjabi, Hindi or English, and the page and the agent follow that language. Offer and booked cards with the savings nudge and booking ID. From 960 px a side rail shows my pickups (Booked, Confirmed, Collected, Paid), what you don't have to do, today's prices, how it works and the no-burn photo; on a phone it opens as a sheet. `?lang=pa\|hi\|en` sets the starting labels. |
| `/ops/` | Operations console: **Dispatch** (who goes out today or tomorrow on a 7 am to 6 pm ruler, the calls to make before dispatch, "Are we ready for the forecast?", exceptions), Routes (Google Maps, on-call crews dashed, confirm and mark collected), **Forecast** (this season against the last three, district heat strip, accuracy dot plot, buyers), Depots, Prices & plan, Orders, Impact |
| `/company/` | Customer portal: price an order in one sentence, the price built up against the in-season spot price, what we can commit month by month, orders as strips of months with cancel |

`/buyer/`, `/farmer.html` and `/company.html` redirect to the new routes (`firebase.json`).

`config.js` holds two values:
- `API_BASE`
- `MAPS_API_KEY`, a browser key restricted to the Maps JavaScript API and this site's referrers plus `localhost:8000`

Every number shown comes from the API. Text from the API is inserted with `textContent`.

## Run locally

```bash
python -m http.server 8000      # from this folder; open http://localhost:8000 (the Maps key allows localhost)
```

Point `API_BASE` at `http://127.0.0.1:8080` and run `python dev_server.py` in `parali-setu-api`.

## Deploy

```bash
firebase deploy --only hosting:parali-setu --project parali-setu-aibuildercup2026
```

## Testing

Each app is checked end to end with Playwright (Chromium) against the dev server, at 390×844 and 1366×900:
- **Kisan:** no language step; Punjabi, then Bengali (trilingual reply), then Hindi in one chat, each answered in that language; a booking that shows "awaiting our call", then "Confirmed" after ops verifies; the chat and language restored after a reload; Live words with Chromium's fake microphone.
- **Ops:** the dispatch board, verify and needs-change, every tab, no console errors.
- **Company:** a priced example on load, a commit-limited quote, order, cancel.
- **Landing:** the counters, chart and slider, at phone width.

Chart colours are checked with the dataviz palette validator (madder #a8304a and silk #d9821a pass colour-blind separation; silk marks always carry a label or a table view).
