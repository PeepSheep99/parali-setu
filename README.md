# Parali Setu

**Google Cloud AI Builder Cup 2026 (JAPAC), Sustainability & Social Impact track.**
Team Ctrl Alt Conquer: Navneet Kumar, Sainath.

*Parali* is the Punjabi word for crop stubble, and *setu* means bridge. Parali Setu
connects farmers in Punjab and Haryana who have paddy or wheat stubble with companies
that buy it as feedstock for pellets, packaging, board or road material. The goal is
for the stubble to be collected before the farmer's sowing deadline, so it doesn't
get burned.

> **Status (Oct 2026): revamp in progress.** This repository was split out of the
> team's earlier `aidatlas` repo, with the Parali Setu commit history preserved.
> The revamp adds three things:
> - a guaranteed pickup slot, backed by an OR-Tools fleet-routing scheduler
> - a low-friction Hindi/Punjabi voice listing flow
> - a buyer console with pickup operations
>
> Until this README is replaced, see the sub-project READMEs for the current state.

## Repository layout

```
parali-setu-api/        FastAPI backend (Cloud Run), see parali-setu-api/README.md
parali-setu-frontend/   Static web frontend (Firebase Hosting), see parali-setu-frontend/README.md
docs/PARALI_SETU_PRD.md Original product requirements document
```

## Google Cloud services used today

| Service | Role |
|---|---|
| Gemini on Vertex AI | Extracts structured listings from Hindi/Punjabi text or speech, reads stubble photos, writes plain-language explanations. It never computes a price or a quantity. |
| Cloud Speech-to-Text / Text-to-Speech | Voice in and voice out, in Hindi (hi-IN) and Punjabi (pa-IN) |
| OR-Tools on Cloud Run | Matches listings to buyer demand. All price and quantity decisions come from this solver. |
| Firestore | Listings, demand, matches, forecasts, fire detections |
| BigQuery ML (ARIMA_PLUS) | Seasonal demand forecast. It is trained offline on a synthetic corpus and labelled as synthetic. |
| Earth Engine (NASA FIRMS) | Satellite fire detections for the fire map and the trust score. This is a batch refresh, not live. |
| Firebase Hosting | Frontend |

## Credits

The original Parali Setu prototype (its PRD, solver, Gemini extraction, voice I/O and
forecast pipeline) was built by Sainath. Those commits are preserved in this history.
