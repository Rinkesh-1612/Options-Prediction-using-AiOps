#!/usr/bin/env bash
# Retrains when asked. The API writes state/retrain_request.json (from the web page or a drift
# alert); this loop picks it up, runs the train and register stages, and archives the request with its outcome.
# The new model is registered as a candidate and becomes champion only if it validates better.
set -u
REQ=state/retrain_request.json
mkdir -p state
echo "retrain runner waiting for $REQ"
while true; do
  if [ -f "$REQ" ]; then
    echo "retrain requested: $(cat "$REQ")"
    mv "$REQ" state/retrain_running.json
    # through DVC, so dvc.lock records the new train/register outputs (--force: retrain on the same data too)
    if dvc repro --force --single-item train && dvc repro --single-item register; then result=ok; else result=FAILED; fi
    echo "retrain $result"
    mv state/retrain_running.json "state/retrain_$(date +%Y%m%dT%H%M%S)_$result.json"
  fi
  sleep "${POLL_SECONDS:-15}"
done
