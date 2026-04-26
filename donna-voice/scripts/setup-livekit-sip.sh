#!/usr/bin/env bash
# Idempotent LiveKit SIP setup for donna-voice.
#
# Reads LIVEKIT_URL/LIVEKIT_API_KEY/LIVEKIT_API_SECRET + TWILIO_SIP_PASSWORD
# from env. Creates inbound trunk, outbound trunk, and dispatch rule from
# the JSON files in donna-voice/trunks/. Skips creation when a resource
# with the same name already exists.
#
# Targets `lk` CLI 2.x (livekit-cli). Field names follow the proto schema
# (camelCase in --json output: sipTrunkId, sipDispatchRuleId).
#
# Usage:
#   set -a; source .env; set +a
#   ./donna-voice/scripts/setup-livekit-sip.sh

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TRUNKS="$ROOT/trunks"

# ─── prereqs ──────────────────────────────────────────────────────────

command -v lk >/dev/null 2>&1 || {
  echo "✗ lk (livekit-cli) not installed. brew install livekit-cli"; exit 1;
}
command -v jq >/dev/null 2>&1 || { echo "✗ jq not installed (brew install jq)"; exit 1; }

: "${LIVEKIT_URL:?LIVEKIT_URL must be set}"
: "${LIVEKIT_API_KEY:?LIVEKIT_API_KEY must be set}"
: "${LIVEKIT_API_SECRET:?LIVEKIT_API_SECRET must be set}"
: "${TWILIO_SIP_PASSWORD:?TWILIO_SIP_PASSWORD must be set (used in outbound trunk)}"

export LIVEKIT_URL LIVEKIT_API_KEY LIVEKIT_API_SECRET

INBOUND_NAME="donna-inbound-twilio"
OUTBOUND_NAME="donna-outbound-twilio"
DISPATCH_NAME="donna-inbound-dispatch"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# ─── helpers ──────────────────────────────────────────────────────────

# `lk sip ... list --json` returns {"items":[...]} on stdout (with a
# "Using url..." line on stderr — we drop that). For an unset/empty
# project, items can be missing or null; coalesce with `// []`.

find_inbound_id_by_name() {
  local name="$1"
  lk sip inbound list --json 2>/dev/null \
    | jq -r --arg n "$name" '(.items // []) | map(select(.name == $n)) | .[0].sipTrunkId // empty'
}

find_outbound_id_by_name() {
  local name="$1"
  lk sip outbound list --json 2>/dev/null \
    | jq -r --arg n "$name" '(.items // []) | map(select(.name == $n)) | .[0].sipTrunkId // empty'
}

find_dispatch_id_by_name() {
  local name="$1"
  lk sip dispatch list --json 2>/dev/null \
    | jq -r --arg n "$name" '(.items // []) | map(select(.name == $n)) | .[0].sipDispatchRuleId // empty'
}

# ─── 1. inbound trunk ─────────────────────────────────────────────────

echo "→ inbound trunk ($INBOUND_NAME)"
INBOUND_ID="$(find_inbound_id_by_name "$INBOUND_NAME" || true)"
if [[ -n "$INBOUND_ID" ]]; then
  echo "  ✓ exists: $INBOUND_ID"
else
  lk sip inbound create "$TRUNKS/inbound-trunk.json"
  INBOUND_ID="$(find_inbound_id_by_name "$INBOUND_NAME")"
  echo "  ✓ created: $INBOUND_ID"
fi

# ─── 2. outbound trunk ────────────────────────────────────────────────

echo "→ outbound trunk ($OUTBOUND_NAME)"
OUTBOUND_ID="$(find_outbound_id_by_name "$OUTBOUND_NAME" || true)"
if [[ -n "$OUTBOUND_ID" ]]; then
  echo "  ✓ exists: $OUTBOUND_ID"
else
  envsubst < "$TRUNKS/outbound-trunk.json" > "$WORK/outbound.json"
  lk sip outbound create "$WORK/outbound.json"
  OUTBOUND_ID="$(find_outbound_id_by_name "$OUTBOUND_NAME")"
  echo "  ✓ created: $OUTBOUND_ID"
fi

# ─── 3. dispatch rule ─────────────────────────────────────────────────

echo "→ dispatch rule ($DISPATCH_NAME)"
DISPATCH_ID="$(find_dispatch_id_by_name "$DISPATCH_NAME" || true)"
if [[ -n "$DISPATCH_ID" ]]; then
  echo "  ✓ exists: $DISPATCH_ID"
else
  DONNA_INBOUND_TRUNK_ID="$INBOUND_ID" envsubst \
    < "$TRUNKS/dispatch-rule.json" > "$WORK/dispatch.json"
  lk sip dispatch create "$WORK/dispatch.json"
  DISPATCH_ID="$(find_dispatch_id_by_name "$DISPATCH_NAME")"
  echo "  ✓ created: $DISPATCH_ID"
fi

# ─── 4. report ────────────────────────────────────────────────────────

PROJECT_HOST="$(echo "$LIVEKIT_URL" | sed -E 's,^wss?://,,; s,/.*,,')"
PROJECT_SLUG="$(echo "$PROJECT_HOST" | sed -E 's,\.livekit\.cloud$,,')"
SIP_URI="sip:${PROJECT_SLUG}.sip.livekit.cloud"

echo
echo "============================================================"
echo "✓ livekit sip setup complete"
echo "------------------------------------------------------------"
echo "  inbound  trunk:  $INBOUND_ID"
echo "  outbound trunk:  $OUTBOUND_ID"
echo "  dispatch rule:   $DISPATCH_ID"
echo "  sip uri:         $SIP_URI"
echo "============================================================"
echo
echo "next:"
echo "  1. paste this Origination URI into Twilio:"
echo "     console.twilio.com → Elastic SIP Trunking → Trunks →"
echo "     donna → Origination tab → Origination URI:"
echo
echo "       $SIP_URI;transport=tls"
echo
echo "  2. add this to your .env:"
echo "       DONNA_OUTBOUND_TRUNK_ID=$OUTBOUND_ID"
echo
