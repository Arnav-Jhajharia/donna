#!/usr/bin/env bash
# Sync the four WhatsApp env vars from local .env to all four Railway services.
#
# Prereqs (one-time):
#   1. npx @railway/cli login    # opens browser, authenticates
#   2. npx @railway/cli link     # pick the 'abundant-vision' project
#
# Usage:
#   bash scripts/sync_railway_whatsapp_env.sh
#
# Vars synced (all four are required for WA to work end-to-end):
#   - WHATSAPP_TOKEN              (api access token)
#   - WHATSAPP_PHONE_NUMBER_ID    (the new Donna number's id)
#   - WHATSAPP_VERIFY_TOKEN       (webhook handshake)
#   - WHATSAPP_BUSINESS_ACCOUNT_ID (waba id)
#
# Services updated: donna, donna-attention, donna-synthesis, donna-reminders.
# (FalkorDB is the graph backend — no WA env needed.)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: $ENV_FILE not found" >&2
  exit 1
fi

# Source the four vars from local .env without dumping anything else.
# shellcheck disable=SC1090,SC2046
export $(grep -E '^(WHATSAPP_TOKEN|WHATSAPP_PHONE_NUMBER_ID|WHATSAPP_VERIFY_TOKEN|WHATSAPP_BUSINESS_ACCOUNT_ID)=' "$ENV_FILE")

for var in WHATSAPP_TOKEN WHATSAPP_PHONE_NUMBER_ID WHATSAPP_VERIFY_TOKEN WHATSAPP_BUSINESS_ACCOUNT_ID; do
  if [[ -z "${!var:-}" ]]; then
    echo "error: $var is empty in $ENV_FILE" >&2
    exit 1
  fi
done

# Confirm we're linked. If not, prompt to link.
if ! npx --no-install @railway/cli status >/dev/null 2>&1; then
  echo "error: Railway CLI not linked. Run 'npx @railway/cli link' and pick 'abundant-vision'." >&2
  exit 1
fi

SERVICES=(donna donna-attention donna-synthesis donna-reminders)

for svc in "${SERVICES[@]}"; do
  echo ">>> updating $svc"
  npx --no-install @railway/cli variables \
    --service "$svc" \
    --set "WHATSAPP_TOKEN=$WHATSAPP_TOKEN" \
    --set "WHATSAPP_PHONE_NUMBER_ID=$WHATSAPP_PHONE_NUMBER_ID" \
    --set "WHATSAPP_VERIFY_TOKEN=$WHATSAPP_VERIFY_TOKEN" \
    --set "WHATSAPP_BUSINESS_ACCOUNT_ID=$WHATSAPP_BUSINESS_ACCOUNT_ID" \
    --skip-deploys >/dev/null
  echo "    ok ($svc)"
done

echo
echo "all four services updated. trigger redeploy via:"
echo "  for svc in ${SERVICES[*]}; do npx @railway/cli redeploy --service \$svc --yes; done"
echo "or redeploy in the Railway dashboard for each service."
