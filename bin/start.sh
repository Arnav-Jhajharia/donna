#!/bin/sh
# Role-switching entrypoint for the Donna container image.
#
# Railway (and anywhere else this image runs) selects the role via the
# DONNA_PROCESS_ROLE env var. The same image powers four distinct services:
#
#   DONNA_PROCESS_ROLE=api         → uvicorn api.main:app  (default)
#   DONNA_PROCESS_ROLE=reminders   → scripts/run_schedule_worker.py
#   DONNA_PROCESS_ROLE=attention   → scripts/run_attention_worker.py
#   DONNA_PROCESS_ROLE=synthesis   → scripts/run_synthesis_worker.py
#   DONNA_PROCESS_ROLE=proactive   → scripts/run_proactive_worker.py
#
# Workers MUST NOT be co-located with the API. The API is busy with inbound
# webhooks and proactive turns; co-located workers used to drop fires and
# silently die when uvicorn hot-reloaded incompletely. api/main.py guards
# against double-spawn — when the role is anything but `api` (or unset),
# the API process refuses to start the in-process worker tasks.

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
    attention)
        exec python scripts/run_attention_worker.py \
            --poll "${DONNA_ATTENTION_POLL_S:-30.0}" \
            --propose-interval "${DONNA_ATTENTION_PROPOSE_S:-3600.0}" \
            --promote-interval "${DONNA_ATTENTION_PROMOTE_S:-300.0}"
        ;;
    synthesis)
        exec python scripts/run_synthesis_worker.py \
            --poll "${DONNA_LIVING_PROFILE_INTERVAL_S:-1800.0}"
        ;;
    proactive)
        exec python scripts/run_proactive_worker.py \
            --drain-interval "${DONNA_PROACTIVE_DRAIN_S:-600.0}" \
            --purge-interval "${DONNA_PROACTIVE_PURGE_S:-3600.0}"
        ;;
    *)
        echo "bin/start.sh: unknown DONNA_PROCESS_ROLE='$ROLE'" >&2
        echo "  expected one of: api, reminders, attention, synthesis, proactive" >&2
        exit 64
        ;;
esac
