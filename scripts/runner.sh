#!/usr/bin/env bash
# Retrains when asked. The API writes state/retrain_request.json (from the web page or a drift
# alert); this loop picks it up, runs zoo_train and zoo_eval, and archives the request with its outcome.
# zoo_eval deploys the new champion only if its smoke test passes (optpred.zoo.promote).
set -u
# Scheduled retrain: RETRAIN_EVERY_S > 0 writes a request that often (0 = only on request or alert).
REQ=state/retrain_request.json
EVERY="${RETRAIN_EVERY_S:-0}"
mkdir -p state
echo "retrain runner waiting for $REQ (scheduled every ${EVERY}s; 0 = off)"
last=$(date +%s)
while true; do
  if [ "$EVERY" -gt 0 ] && [ $(( $(date +%s) - last )) -ge "$EVERY" ] && [ ! -f "$REQ" ]; then
    echo "{\"requested\": \"$(date +%Y-%m-%dT%H:%M:%S)\", \"reason\": \"schedule\", \"source\": \"schedule\"}" > "$REQ"
  fi
  if [ -f "$REQ" ]; then
    last=$(date +%s)
    echo "retrain requested: $(cat "$REQ")"
    mv "$REQ" state/retrain_running.json
    # through DVC, so dvc.lock records the new outputs (--force: retrain on the same data too)
    if dvc repro --force --single-item zoo_train && dvc repro --force --single-item zoo_eval; then result=ok; else result=FAILED; fi
    echo "retrain $result"
    mv state/retrain_running.json "state/retrain_$(date +%Y%m%dT%H%M%S)_$result.json"
  fi
  sleep "${POLL_SECONDS:-15}"
done
