#!/bin/sh
# Role-switching entrypoint for the Donna container image.
#
# Railway (and anywhere else this image runs) selects the role via the
# DONNA_PROCESS_ROLE env var. This is what lets the same image power both
# the public API (webhook + dashboard backend) and the dedicated reminders
# worker that fires DonnaSchedule rows on time.
#
#   DONNA_PROCESS_ROLE=api        → uvicorn api.main:app  (default)
#   DONNA_PROCESS_ROLE=reminders  → python -m scripts.run_schedule_worker
#
# Reminders need only DB + WhatsApp + the BRAIN-free templated send path.
# They MUST NOT be co-located with the API any more — the API is busy with
# inbound webhooks and proactive turns and used to drop fires under load.

set -e

ROLE="${DONNA_PROCESS_ROLE:-api}"

case "$ROLE" in
    api)
        exec uvicorn api.main:app --host 0.0.0.0 --port "${PORT:-8000}"
        ;;
    reminders)
        exec python scripts/run_schedule_worker.py \
            --poll "${DONNA_REMINDERS_POLL_S:-5.0}" \
            --batch "${DONNA_REMINDERS_BATCH:-25}"
        ;;
    *)
        echo "bin/start.sh: unknown DONNA_PROCESS_ROLE='$ROLE' (expected 'api' or 'reminders')" >&2
        exit 64
        ;;
esac
