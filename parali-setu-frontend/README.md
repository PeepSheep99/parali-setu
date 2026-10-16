# Parali Setu: frontend

Plain HTML, CSS and JavaScript with no build step, served by Firebase Hosting as one
site with three routes:

| Route | Files | For |
|---|---|---|
| `/` | `index.html`, `landing.css`, `landing.js` | Landing page: the problem, live impact from `GET /impact`, the Punjab scenario slider (`GET /impact/scenario`), the FIRMS fire map, architecture |
| `/kisan/` | `kisan/` (PWA with `manifest.json`) | Farmer app, mobile-first, in Punjabi, Hindi and English, each label with an English subtitle. Steps: hold to speak, confirm card with editable chips, offer card (buyer, slot, payout, "Why this price?", negotiate), my pickups, no-burn proof |
| `/buyer/` | `buyer/` | Buyer console, desktop. Tabs: Pickup Ops (crew routes on Google Maps, Re-plan, waitlist), Supply, Demand, Impact |

`config.js` holds what changes per environment:
- `API_BASE`, the backend URL
- `MAPS_API_KEY`, a browser key restricted to the Maps JavaScript API and to this site's referrers (plus `localhost:8000`)

The old `farmer.html` and `company.html` 301-redirect to `/kisan/` and `/buyer/` (`firebase.json`).

All text from the API is inserted with `textContent` or escaped. Dates are formatted
with explicit month and weekday names, because some browsers have no Punjabi locale data.

## Run locally

```bash
python -m http.server 8000      # from this folder
```

To use a local API, set `API_BASE` in `config.js` to `http://127.0.0.1:8080`. The API's
CORS settings allow `localhost:8000`.

## Deploy

```bash
firebase deploy --only hosting:parali-setu --project ai-builder-cup-aidatlas
```

JavaScript and CSS are served with `Cache-Control: no-cache`, so a deploy takes effect
on the next page load.

## Testing

There is no unit-test suite for the frontend. Each page was checked end to end with
Playwright (Chromium; 390×844 phone and 1366×900 desktop) against the API, as follows:
- **Kisan:** speak → confirm → offer → accept, with the booking shown
- **Buyer:** collected → payout → impact updated, plus the waitlist
- **Landing:** counters, slider and fire map, with no console errors
