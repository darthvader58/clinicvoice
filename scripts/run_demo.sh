#!/usr/bin/env bash
# clinicvoice demo runner — smoke-tests the API against a local server.
#
# Assumes:
#   * uvicorn server running on http://localhost:8000 (see README)
#   * scripts/generate_synthetic_audio.py has produced
#     tests/data/synthetic_consult.wav
#
# Usage:
#   bash scripts/run_demo.sh [path/to/audio.wav]

set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
AUDIO="${1:-tests/data/synthetic_consult.wav}"

say() { printf '\n=== %s ===\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

command -v curl >/dev/null 2>&1 || fail "curl is required"
command -v jq >/dev/null 2>&1 || echo "(note: jq not installed — raw JSON output will be shown)"

say "Health check"
if ! curl -fsS --max-time 5 "${BASE_URL}/api/health"; then
  fail "Cannot reach ${BASE_URL}/api/health — is the server running? Try: uvicorn src.main:app --reload"
fi
echo

[ -f "$AUDIO" ] || fail "Audio file not found: $AUDIO (run scripts/generate_synthetic_audio.py)"

say "Uploading $AUDIO"
UPLOAD_JSON="$(curl -fsS -X POST "${BASE_URL}/api/upload" \
  -F "file=@${AUDIO}" -F "scenario=consult")"
echo "$UPLOAD_JSON"

RECORDING_ID="$(printf '%s' "$UPLOAD_JSON" | sed -n 's/.*"recording_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
[ -n "${RECORDING_ID:-}" ] || fail "No recording_id returned from /api/upload"
echo "recording_id=${RECORDING_ID}"

say "Polling status (max ~60s)"
for i in $(seq 1 30); do
  STATUS_JSON="$(curl -fsS "${BASE_URL}/api/status/${RECORDING_ID}")"
  echo "[${i}] ${STATUS_JSON}"
  case "$STATUS_JSON" in
    *'"status":"done"'*|*'"status": "done"'*|*'"status":"complete"'*) break ;;
    *'"status":"error"'*|*'"status":"failed"'*) fail "pipeline failed" ;;
  esac
  sleep 2
done

say "Transcript"
curl -fsS "${BASE_URL}/api/transcript/${RECORDING_ID}" || true
echo

say "Metrics"
curl -fsS "${BASE_URL}/api/metrics/${RECORDING_ID}" || true
echo

say "Escalation"
curl -fsS "${BASE_URL}/api/escalation/${RECORDING_ID}" || true
echo

say "Demo complete"
