#!/usr/bin/env bash
# Runs what the API asks for, from request files in state/, and archives each request with its outcome:
#   retrain_request.json  -> zoo_train + zoo_eval (forced)      pipeline_request.json -> dvc repro gate
set -u
# Scheduled retrain: RETRAIN_EVERY_S > 0 writes a request that often (0 = only on request or alert).
REQ=state/retrain_request.json
PREQ=state/pipeline_request.json
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
  # Pipeline run from the console (POST /pipeline/run): the CI pipeline, stale stages only, then the gate.
  if [ -f "$PREQ" ]; then
    echo "pipeline run requested: $(cat "$PREQ")"
    mv "$PREQ" state/pipeline_running.json
    if dvc repro gate; then result=ok; else result=FAILED; fi
    echo "pipeline run $result"
    mv state/pipeline_running.json "state/pipeline_$(date +%Y%m%dT%H%M%S)_$result.json"
  fi
  touch state/runner_heartbeat   # the API turns its age into the gauge runner_heartbeat_age_seconds
  sleep "${POLL_SECONDS:-15}"
done
