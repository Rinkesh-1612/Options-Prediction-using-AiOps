#!/usr/bin/env bash
# Serves the registry's champion with `mlflow models serve` and follows the alias (continuous deployment):
# when "champion" moves (a new model, or a rollback) it restarts on the new version within POLL_SECONDS.
#
# Automatic rollback: if a new version does not answer /ping within START_TIMEOUT seconds, the version is
# tagged deploy_check=failed_start and "champion" goes back to "previous". The loop then serves that.
set -u
NAME="${MODEL_NAME:-nifty-signal}"
PORT="${MODEL_PORT:-5001}"
POLL_S="${POLL_SECONDS:-10}"
START_TIMEOUT="${START_TIMEOUT:-180}"
export MLFLOW_TRACKING_URI="${MLFLOW_TRACKING_URI:-sqlite:////app/mlflow/mlflow.db}"

registry() {  # registry champion | registry rollback <failed version>
  python - "$@" 2>/dev/null <<PY
import sys, mlflow
c, name = mlflow.MlflowClient(), "$NAME"
try:
    if sys.argv[1] == "champion":
        print(c.get_model_version_by_alias(name, "champion").version)
    else:
        prev = c.get_model_version_by_alias(name, "previous").version
        c.set_model_version_tag(name, sys.argv[2], "deploy_check", "failed_start")
        c.set_registered_model_alias(name, "champion", prev)
        c.delete_registered_model_alias(name, "previous")
        print(prev)
except Exception:
    pass
PY
}

healthy() {
  python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:$PORT/ping', timeout=3)" 2>/dev/null
}

pid=""
current=""
stop_server() { [ -n "$pid" ] && kill "$pid" 2>/dev/null && wait "$pid" 2>/dev/null; pid=""; }
trap 'stop_server; exit 0' TERM INT

while true; do
  v="$(registry champion)"
  if [ -z "$v" ]; then
    echo "no champion registered yet; waiting"
  elif [ "$v" != "$current" ] || ! kill -0 "$pid" 2>/dev/null; then
    stop_server
    echo "deploying $NAME version $v"
    mlflow models serve -m "models:/$NAME/$v" -p "$PORT" --host 0.0.0.0 --env-manager local &
    pid=$!
    current="$v"
    waited=0
    until healthy; do
      sleep 3
      waited=$((waited + 3))
      if [ "$waited" -ge "$START_TIMEOUT" ] || ! kill -0 "$pid" 2>/dev/null; then
        stop_server
        prev="$(registry rollback "$v")"
        echo "version $v failed to start: rolled back to ${prev:-<none>}"
        current=""
        break
      fi
    done
    [ -n "$current" ] && echo "serving $NAME version $v"
  fi
  sleep "$POLL_S"
done
