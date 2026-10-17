# Parali Setu: frontend

Plain HTML, CSS and JavaScript with no build step, served by Firebase Hosting as one site:

| Route | For |
|---|---|
| `/` | Landing page: the toll, the promise, how it works, the 25-season satellite record, who buys straw, the four apps, the Google Cloud build, the impact scenario |
| `/kisan/` | Farmer app in Punjabi, Hindi and English. **Phone view:** talk to the Gemini agent (tap to speak, recorded as 16 kHz WAV), with cards for price, offer and booking. **Laptop view:** the same booking step by step, plus today's prices, my pickups and the no-burn proof. A header toggle switches views; `?view=phone\|laptop` and `?lang=pa\|hi\|en` help demos. |
| `/ops/` | Operations console: Today, Pickups (crew routes on Google Maps, partner crews dashed, mark collected), Depots & stock, Forecast (TimesFM chart and backtests), Prices & plan, Orders, Impact |
| `/company/` | Customer portal: quote built from costs, forward orders, monthly delivery plan |

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
firebase deploy --only hosting:parali-setu --project ai-builder-cup-aidatlas
```

## Testing

Each app is checked end to end with Playwright (Chromium) against the dev server, at 390×844 and 1366×900:
- **Kisan, phone view:** a Punjabi conversation that ends in a booked pickup.
- **Kisan, laptop view:** a Hindi listing that ends in a booked pickup.
- **Ops:** accept on the farmer's behalf, mark collected, add a crew, re-plan, every tab.
- **Company:** quote, then order.
- **Landing:** the counters, chart and slider.
