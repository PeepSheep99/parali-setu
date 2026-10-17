# cost-guard: automatic throttle when real money is charged

The prototype runs on GCP free-trial credit. This function makes sure an overnight
runaway can't turn into a real bill for the account owner.

## How it fits together

| Piece | What it is |
|---|---|
| Budget A, "Parali Setu - credit burn (gross)" | ₹13,000 of usage **before** credits, which tracks how fast the credit drains. It emails at 25/50/75/90/100% of actual spend and at 100% of forecast. Email only. |
| Budget B, "Parali Setu - REAL money (net)" | ₹100 of spend **after** credits, i.e. real money. It emails at 100% **and** publishes to the Pub/Sub topic `billing-alerts`. |
| `cost-guard` (this folder) | A Cloud Run function (gen2) triggered by `billing-alerts`. If the message comes from Budget B and `costAmount >= budgetAmount`, it throttles. |

Alert emails go to `saichvms@gmail.com` and `navneet.kumar6266@gmail.com` (Cloud Monitoring email channels), as well as to the billing account's admins.

## What "throttle" does (reversible; nothing is deleted)

1. Sets `ingress=internal` on `parali-setu-api`, so public traffic stops and so does the cost it drives.
2. Disables `aiplatform`, `speech` and `texttospeech`.

To undo it, run `bash ops/cost-guard/restore.sh`.

`DRY_RUN=true` (the default) only logs what the function *would* do. Cloud Billing
data lags by a few hours, so this is a backstop. The first line of defence is the
`--max-instances` caps on the Cloud Run services.

## Deploy

```bash
gcloud functions deploy cost-guard --gen2 --runtime=python312 --region=asia-southeast1 \
  --source=ops/cost-guard --entry-point=handle_budget_alert --trigger-topic=billing-alerts \
  --service-account=cost-guard@parali-setu-aibuildercup-2026.iam.gserviceaccount.com \
  --set-env-vars=DRY_RUN=true --max-instances=1 --memory=256Mi --no-allow-unauthenticated \
  --project=parali-setu-aibuildercup-2026
```

The `cost-guard` service account needs `roles/run.admin` and
`roles/serviceusage.serviceUsageAdmin` on the project, plus `roles/iam.serviceAccountUser`
on the runtime service account of the throttled Cloud Run services.

## Test without spending anything

```bash
gcloud pubsub topics publish billing-alerts --project=parali-setu-aibuildercup-2026 \
  --message='{"budgetDisplayName":"Parali Setu - REAL money (net)","costAmount":150,"budgetAmount":100,"currencyCode":"INR"}'
gcloud functions logs read cost-guard --gen2 --region=asia-southeast1 --project=parali-setu-aibuildercup-2026 --limit=10
```

With `DRY_RUN=true`, the log reads "DRY RUN: would throttle Parali Setu". Unit tests:
`python -m pytest ops/cost-guard`.
