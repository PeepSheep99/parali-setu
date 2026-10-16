#!/usr/bin/env bash
# Undo a cost-guard throttle: re-open public ingress and re-enable the AI APIs.
# Run only after you've checked billing and decided it's safe to resume.
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-ai-builder-cup-aidatlas}"
REGION="${REGION:-asia-southeast1}"
SERVICES="${SERVICES:-parali-setu-api aidatlas-api}"

gcloud services enable aiplatform.googleapis.com speech.googleapis.com texttospeech.googleapis.com \
  --project "$PROJECT_ID"

for svc in $SERVICES; do
  gcloud run services update "$svc" --ingress=all --region "$REGION" --project "$PROJECT_ID"
done

echo "Restored: ingress=all on [$SERVICES]; Vertex AI, Speech-to-Text, Text-to-Speech re-enabled."
